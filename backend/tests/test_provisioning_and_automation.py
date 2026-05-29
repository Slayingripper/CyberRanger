import asyncio
import socket
import sys
import time
import types

from app.core.deploy_automation import execute_automation_steps, normalize_automation_steps
from app.core.provisioning import build_cloud_init_from_assets, cloud_init_credentials

libvirt_stub = types.SimpleNamespace(
    libvirtError=RuntimeError,
    open=lambda _uri: object(),
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE=0,
    VIR_KEYCODE_SET_LINUX=0,
)
sys.modules.pop("libvirt", None)
sys.modules["libvirt"] = libvirt_stub

from app.api import routes as routes_api
from app.api import trainings as trainings_api
from app.core.auth import AuthenticatedUser
from app.core.deploy_jobs import get_job, new_job


def test_build_cloud_init_from_assets_uses_non_default_password():
    cloud_init = build_cloud_init_from_assets([{"type": "package", "value": "nmap"}])

    creds = cloud_init_credentials(cloud_init)
    assert creds is not None
    assert creds["username"] == "trainee"
    assert creds["password"]
    assert creds["password"] != "password"
    assert "nmap" in cloud_init["packages"]


def test_normalize_automation_steps_supports_legacy_send_text():
    steps = normalize_automation_steps(
        {
            "type": "send_text",
            "text": "install\n",
            "delay_seconds": 10,
            "retries": 2,
            "retry_delay_seconds": 3,
        }
    )

    assert steps[0]["type"] == "wait"
    assert steps[1]["type"] == "send_text"
    assert steps[1]["text"] == "install\n"


def test_get_deployments_does_not_cleanup_networks(monkeypatch):
    cleanup_calls = []

    monkeypatch.setattr(routes_api, "_load_deployments", lambda: {})
    monkeypatch.setattr(routes_api.vm_manager, "cleanup_unused_networks", lambda: cleanup_calls.append(True) or [])
    monkeypatch.setattr(routes_api.vm_manager, "list_domains", lambda: [])

    current_user = AuthenticatedUser(
        id="user-deployments",
        username="deployments-tester",
        full_name="Deployments Tester",
        role="user",
        created_at=time.time(),
    )

    result = asyncio.run(routes_api.get_deployments(current_user))

    assert result == {}
    assert cleanup_calls == []


def test_resolve_verified_image_download_source_falls_back_from_stale_kali_url(monkeypatch):
    checked_urls = []

    async def fake_reachable(url):
        checked_urls.append(url)
        return url.endswith("kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz")

    monkeypatch.setattr(trainings_api, "_VERIFIED_SOURCE_URLS", {})
    monkeypatch.setattr(trainings_api, "_source_url_is_reachable", fake_reachable)

    resolved = asyncio.run(
        trainings_api.resolve_verified_image_download_source(
            "kali-linux",
            {
                "url": "https://cdimage.kali.org/kali-2025.1/kali-linux-2025.1-qemu-amd64.7z",
                "filename": "kali-linux-2025.1-qemu-amd64.7z",
                "extract": {"type": "7z", "output_filename": "kali-linux-2025.4-qemu-amd64.qcow2"},
            },
        )
    )

    assert resolved["url"] == "https://kali.download/cloud-images/kali-2026.1/kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz"
    assert resolved["filename"] == "kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz"
    assert resolved["extract"]["output_filename"] == "kali-linux-2026.1-cloud-genericcloud-amd64.qcow2"
    assert checked_urls == [
        "https://kali.download/cloud-images/kali-2026.1/kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz",
    ]


def test_resolve_verified_image_download_source_rewrites_legacy_kali_qemu_key(monkeypatch):
    checked_urls = []

    async def fake_reachable(url):
        checked_urls.append(url)
        return url.endswith("kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz")

    monkeypatch.setattr(trainings_api, "_VERIFIED_SOURCE_URLS", {})
    monkeypatch.setattr(trainings_api, "_source_url_is_reachable", fake_reachable)

    resolved = asyncio.run(
        trainings_api.resolve_verified_image_download_source(
            "kali-linux-2026.1-qemu-amd64.qcow2",
            {
                "url": "https://cdimage.kali.org/kali-2026.1/kali-linux-2026.1-qemu-amd64.7z",
                "filename": "kali-linux-2026.1-qemu-amd64.7z",
                "extract": {"type": "7z", "output_filename": "kali-linux-2026.1-qemu-amd64.qcow2"},
            },
        )
    )

    assert resolved["url"] == "https://kali.download/cloud-images/kali-2026.1/kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz"
    assert resolved["filename"] == "kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz"
    assert resolved["extract"]["output_filename"] == "kali-linux-2026.1-cloud-genericcloud-amd64.qcow2"
    assert checked_urls == [
        "https://kali.download/cloud-images/kali-2026.1/kali-linux-2026.1-cloud-genericcloud-amd64.tar.xz",
    ]


def test_execute_automation_steps_runs_text_and_key_sequence():
    sent = []

    async def progress_cb(event):
        sent.append(("progress", event["status"]))

    def send_text(vm_name, text):
        sent.append(("text", vm_name, text))
        return True

    def send_key(vm_name, key):
        sent.append(("key", vm_name, key))
        return True

    steps = normalize_automation_steps(
        {
            "steps": [
                {"type": "wait", "delay_seconds": 0},
                {"type": "send_text", "text": "auto install\n"},
                {"type": "send_key", "key": "enter", "repeat": 2},
            ]
        }
    )

    ok = asyncio.run(
        execute_automation_steps(
            vm_name="vm-1",
            node_id="node-1",
            steps=steps,
            send_text=send_text,
            send_key=send_key,
            progress_cb=progress_cb,
        )
    )

    assert ok is True
    assert ("text", "vm-1", "auto install\n") in sent
    assert sent.count(("key", "vm-1", "enter")) == 2


def test_plan_topology_network_assignments_adds_agent_mesh_for_runbook(monkeypatch):
    ensured = []

    monkeypatch.setattr(routes_api, "_active_nat_third_octets", lambda: set())
    monkeypatch.setattr(routes_api, "_ensure_planned_network", lambda name, mode, seed, used: ensured.append((name, mode, seed)))

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Agent Mesh",
            team="purple",
            objective="Give runbook-driven nodes a shared orchestration network.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Probe",
                        actor="attacker",
                        target="victim",
                        action="Probe the victim.",
                        transport="ssh",
                        command="ping -c 1 victim_ip",
                    )
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="attacker",
                label="Attacker",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="firewall",
                label="Firewall",
                config=routes_api.TopologyNodeConfig(image="opnsense", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="victim",
                label="Victim",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
        ],
        edges=[
            routes_api.TopologyEdge(id="a-f", source="attacker", target="firewall", config=routes_api.TopologyEdgeConfig(segment="it-dmz", mode="nat")),
            routes_api.TopologyEdge(id="v-f", source="victim", target="firewall", config=routes_api.TopologyEdgeConfig(segment="ot-core", mode="nat")),
        ],
    )

    node_networks = routes_api._plan_topology_network_assignments(topology, "agent-mesh-demo")

    assert "cyberange-agent-mesh-demo-agent" in node_networks["attacker"]
    assert "cyberange-agent-mesh-demo-agent" in node_networks["firewall"]
    assert "cyberange-agent-mesh-demo-agent" in node_networks["victim"]
    assert any(name == "cyberange-agent-mesh-demo-agent" and mode == "nat" for name, mode, _seed in ensured)


def test_run_deploy_job_prefers_agent_mesh_ip_for_runbook(tmp_path, monkeypatch):
    image_path = tmp_path / "ubuntu-20.04.qcow2"
    image_path.write_text("qcow2")

    ssh_calls = []
    preferred_calls = []

    monkeypatch.setattr(routes_api, "CREDS_CACHE_PATH", str(tmp_path / "vm_credentials.json"))
    monkeypatch.setattr(routes_api, "_load_creds_cache", lambda: {})
    monkeypatch.setattr(routes_api, "_load_deployments", lambda: {})
    monkeypatch.setattr(routes_api, "_save_deployments", lambda _deployments: None)
    monkeypatch.setattr(routes_api, "_resolve_image_path", lambda _image: str(image_path))
    monkeypatch.setattr(routes_api, "register_vm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        routes_api,
        "_plan_topology_network_assignments",
        lambda _topology, _slug: {
            "attacker": ["seg-a", "cyberange-test-agent"],
            "victim": ["seg-b", "cyberange-test-agent"],
        },
    )
    monkeypatch.setattr(routes_api, "_runbook_preferred_networks", lambda _topology, _slug: ["cyberange-test-agent"])

    async def fake_ensure_image(src, progress_cb=None):
        class Ensured:
            container_path = str(image_path)

        return Ensured()

    async def fake_ssh_command(**kwargs):
        ssh_calls.append(kwargs)
        return {"exit_status": 0, "stdout": "ok\n", "stderr": ""}

    def fake_wait_for_preferred_ipv4(vm_name, preferred_networks=None, timeout_seconds=180.0, poll_interval_seconds=5.0):
        preferred_calls.append((vm_name, list(preferred_networks or [])))
        return "10.10.10.5" if vm_name.endswith("_attacker") else "10.10.10.6"

    monkeypatch.setattr(routes_api, "ensure_image", fake_ensure_image)
    monkeypatch.setattr(routes_api, "run_ssh_command_async", fake_ssh_command)
    monkeypatch.setattr(routes_api.vm_manager, "wait_for_preferred_ipv4", fake_wait_for_preferred_ipv4)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "create_vm",
        lambda **kwargs: {"status": "success", "uuid": "vm-uuid", "vnc_port": 5901},
    )

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Agent Mesh SSH",
            team="purple",
            objective="Prefer the shared agent mesh when executing runbook commands.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Probe",
                        actor="attacker",
                        target="victim",
                        action="Probe the victim.",
                        transport="ssh",
                        command="ping -c 1 victim_ip",
                    )
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="attacker",
                label="Attacker",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="victim",
                label="Victim",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
        ],
        edges=[routes_api.TopologyEdge(id="edge-1", source="attacker", target="victim")],
    )
    current_user = AuthenticatedUser(
        id="user-agent-mesh",
        username="agent-mesh",
        full_name="Agent Mesh",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_deploy_job(job.id, topology, current_user))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert ssh_calls[0]["host"] == "10.10.10.5"
    assert ssh_calls[0]["command"] == "ping -c 1 10.10.10.6"
    assert preferred_calls
    assert all(call[1] == ["cyberange-test-agent"] for call in preferred_calls)


def test_runbook_job_replays_simulation_for_existing_deployment(monkeypatch):
    deployment_id = "12345678-1234-5678-9abc-def012345678"
    deployment_prefix = routes_api._deployment_prefix(deployment_id)
    ssh_calls = []

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Replay Existing Deployment",
            team="purple",
            objective="Replay the simulation runbook on an existing deployment.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Probe",
                        actor="attacker",
                        target="victim",
                        action="Probe the victim over the orchestration mesh.",
                        transport="ssh",
                        command="ping -c 1 victim_ip",
                    )
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="attacker",
                label="Attacker",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="victim",
                label="Victim",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
        ],
        edges=[routes_api.TopologyEdge(id="edge-1", source="attacker", target="victim")],
    )
    vm_names = {
        node.id: routes_api._scoped_vm_name(node.label, node.id, deployment_prefix)
        for node in topology.nodes
    }

    monkeypatch.setattr(
        routes_api,
        "_load_creds_cache",
        lambda: {
            vm_names["attacker"]: {"username": "trainee", "password": "pw-attacker"},
            vm_names["victim"]: {"username": "trainee", "password": "pw-victim"},
        },
    )
    monkeypatch.setattr(routes_api.vm_manager, "wait_for_primary_ipv4", lambda _vm_name, _timeout=180.0, _poll=5.0: None)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_preferred_ipv4",
        lambda vm_name, preferred_networks=None, timeout_seconds=180.0, poll_interval_seconds=5.0: (
            "10.20.0.10" if vm_name.endswith("_attacker") else "10.20.0.20"
        ),
    )

    async def fake_ssh_command(**kwargs):
        ssh_calls.append(kwargs)
        return {"exit_status": 0, "stdout": "replayed\n", "stderr": ""}

    monkeypatch.setattr(routes_api, "run_ssh_command_async", fake_ssh_command)

    current_user = AuthenticatedUser(
        id="user-runbook-job",
        username="runbook-job",
        full_name="Runbook Job",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_runbook_job(job.id, deployment_id, topology, current_user, ["simulation"]))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert stored_job.progress["job_kind"] == "runbook"
    assert stored_job.result["status"] == "scenario_run_processed"
    assert stored_job.result["deployment_id"] == deployment_id
    assert ssh_calls[0]["host"] == "10.20.0.10"
    assert ssh_calls[0]["command"] == "ping -c 1 10.20.0.20"


def test_runbook_job_executes_simulation_in_actor_parallel_lanes(monkeypatch):
    deployment_id = "22345678-1234-5678-9abc-def012345678"
    deployment_prefix = routes_api._deployment_prefix(deployment_id)
    call_order = []
    max_active_calls = 0
    active_calls = 0
    attacker_started = asyncio.Event()
    defender_started = asyncio.Event()

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Parallel Existing Deployment",
            team="purple",
            objective="Replay simulation steps with per-actor lanes.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Attacker Recon",
                        actor="attacker",
                        target="victim",
                        action="Attacker probes the victim.",
                        transport="ssh",
                        command="echo attacker-1 victim_ip",
                    ),
                    routes_api.ScenarioRunbookStep(
                        title="Defender Observe",
                        actor="defender",
                        target="victim",
                        action="Defender inspects the victim.",
                        transport="ssh",
                        command="echo defender-1 victim_ip",
                    ),
                    routes_api.ScenarioRunbookStep(
                        title="Attacker Follow-up",
                        actor="attacker",
                        target="victim",
                        action="Attacker continues after the first step finishes.",
                        transport="ssh",
                        command="echo attacker-2 victim_ip",
                    ),
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="attacker",
                label="Attacker",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="defender",
                label="Defender",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="victim",
                label="Victim",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
        ],
        edges=[
            routes_api.TopologyEdge(id="edge-1", source="attacker", target="victim"),
            routes_api.TopologyEdge(id="edge-2", source="defender", target="victim"),
        ],
    )
    vm_names = {
        node.id: routes_api._scoped_vm_name(node.label, node.id, deployment_prefix)
        for node in topology.nodes
    }

    monkeypatch.setattr(
        routes_api,
        "_load_creds_cache",
        lambda: {
            vm_names["attacker"]: {"username": "trainee", "password": "pw-attacker"},
            vm_names["defender"]: {"username": "trainee", "password": "pw-defender"},
            vm_names["victim"]: {"username": "trainee", "password": "pw-victim"},
        },
    )
    monkeypatch.setattr(routes_api.vm_manager, "wait_for_primary_ipv4", lambda _vm_name, _timeout=180.0, _poll=5.0: None)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_preferred_ipv4",
        lambda vm_name, preferred_networks=None, timeout_seconds=180.0, poll_interval_seconds=5.0: {
            vm_names["attacker"]: "10.30.0.10",
            vm_names["defender"]: "10.30.0.11",
            vm_names["victim"]: "10.30.0.20",
        }[vm_name],
    )

    async def fake_ssh_command(**kwargs):
        nonlocal active_calls, max_active_calls

        marker = str(kwargs["command"]).split()[1]
        call_order.append(f"start:{marker}")
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)

        if marker == "attacker-1":
            attacker_started.set()
            await defender_started.wait()
        elif marker == "defender-1":
            defender_started.set()
            await attacker_started.wait()

        await asyncio.sleep(0)

        active_calls -= 1
        call_order.append(f"end:{marker}")
        return {"exit_status": 0, "stdout": f"{marker}\n", "stderr": ""}

    monkeypatch.setattr(routes_api, "run_ssh_command_async", fake_ssh_command)

    current_user = AuthenticatedUser(
        id="user-runbook-parallel",
        username="runbook-parallel",
        full_name="Runbook Parallel",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_runbook_job(job.id, deployment_id, topology, current_user, ["simulation"], "actor_parallel"))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert stored_job.progress["runbook"]["simulation"]["execution_mode"] == "actor_parallel"
    assert stored_job.progress["runbook"]["simulation"]["lane_count"] == 2
    lane_indexes = sorted(
        lane.get("step_indexes")
        for lane in stored_job.progress["runbook"]["simulation"].get("lanes", {}).values()
    )
    assert lane_indexes == [[1, 3], [2]]
    assert stored_job.result["runbook"]["simulation_execution_mode"] == "actor_parallel"
    assert stored_job.result["runbook"]["simulation_results"][0]["node_id"] == "attacker"
    assert stored_job.result["runbook"]["simulation_results"][1]["node_id"] == "defender"
    assert stored_job.result["runbook"]["simulation_results"][2]["node_id"] == "attacker"
    assert max_active_calls >= 2

    first_end_index = min(call_order.index("end:attacker-1"), call_order.index("end:defender-1"))
    assert call_order.index("start:attacker-1") < first_end_index
    assert call_order.index("start:defender-1") < first_end_index
    assert call_order.index("start:attacker-2") > call_order.index("end:attacker-1")


def test_ensure_vm_agent_for_node_bootstraps_and_persists_state(monkeypatch):
    deployment_id = "32345678-1234-5678-9abc-def012345678"
    deployment_prefix = routes_api._deployment_prefix(deployment_id)
    vm_name = routes_api._scoped_vm_name("Attacker", "attacker", deployment_prefix)
    deployments = {deployment_id: {"id": deployment_id, "owner_id": "user-agent", "topology": {}}}
    bootstrap_commands = []
    health_calls = []

    monkeypatch.setattr(routes_api, "_load_deployments", lambda: deployments)
    monkeypatch.setattr(routes_api, "_save_deployments", lambda data: deployments.update(data))
    monkeypatch.setattr(routes_api.vm_manager, "wait_for_primary_ipv4", lambda _vm_name, _timeout=180.0, _poll=5.0: None)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_preferred_ipv4",
        lambda _vm_name, preferred_networks=None, timeout_seconds=180.0, poll_interval_seconds=5.0: "10.40.0.10",
    )

    async def fake_ssh_command(**kwargs):
        bootstrap_commands.append(kwargs["command"])
        return {"exit_status": 0, "stdout": "agent-started\n", "stderr": ""}

    async def fake_healthcheck(agent_state, timeout_seconds=5.0):
        health_calls.append(dict(agent_state))
        if len(health_calls) == 1:
            raise RuntimeError("agent unavailable")
        return {"status": "ok", "task_count": 0, "tasks": {}}

    monkeypatch.setattr(routes_api, "run_ssh_command_async", fake_ssh_command)
    monkeypatch.setattr(routes_api, "_vm_agent_healthcheck", fake_healthcheck)

    state = asyncio.run(
        routes_api._ensure_vm_agent_for_node(
            deployment_id=deployment_id,
            node_id="attacker",
            vm_name=vm_name,
            node_credentials_by_id={"attacker": {"username": "trainee", "password": "pw-attacker"}},
            preferred_networks=["cyberange-test-agent"],
            node_ip_cache={},
            allow_bootstrap=True,
        )
    )

    assert state["status"] == "ready"
    assert state["host"] == "10.40.0.10"
    assert state["port"] == 8765
    assert bootstrap_commands
    assert "cyberange_vm_agent.py" in bootstrap_commands[0]
    assert deployments[deployment_id]["vm_agents"]["attacker"]["token"] == state["token"]


def test_runbook_job_uses_vm_agent_daemon_when_requested(monkeypatch):
    deployment_id = "42345678-1234-5678-9abc-def012345678"
    deployment_prefix = routes_api._deployment_prefix(deployment_id)
    agent_calls = []

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Agent Backed Simulation",
            team="purple",
            objective="Use the per-VM agent for simulation commands.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Probe Through Agent",
                        actor="attacker",
                        target="victim",
                        action="Probe the victim over the agent-backed lane.",
                        transport="ssh",
                        command="ping -c 1 victim_ip",
                    )
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="attacker",
                label="Attacker",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="victim",
                label="Victim",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
        ],
        edges=[routes_api.TopologyEdge(id="edge-1", source="attacker", target="victim")],
    )
    vm_names = {
        node.id: routes_api._scoped_vm_name(node.label, node.id, deployment_prefix)
        for node in topology.nodes
    }

    monkeypatch.setattr(routes_api.vm_manager, "wait_for_primary_ipv4", lambda _vm_name, _timeout=180.0, _poll=5.0: None)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_preferred_ipv4",
        lambda vm_name, preferred_networks=None, timeout_seconds=180.0, poll_interval_seconds=5.0: {
            vm_names["attacker"]: "10.50.0.10",
            vm_names["victim"]: "10.50.0.20",
        }[vm_name],
    )

    async def fake_ensure_runbook_vm_agents(**kwargs):
        return {
            "attacker": {
                "node_id": "attacker",
                "vm_name": vm_names["attacker"],
                "host": "10.50.0.10",
                "port": 8765,
                "token": "agent-token",
                "status": "ready",
            }
        }

    async def fake_execute_vm_agent_task(**kwargs):
        agent_calls.append(kwargs)
        return {"exit_status": 0, "stdout": "agent-ok\n", "stderr": ""}

    async def fail_ssh(**kwargs):
        raise AssertionError("SSH should not be used when the VM agent is ready")

    monkeypatch.setattr(routes_api, "_ensure_runbook_vm_agents", fake_ensure_runbook_vm_agents)
    monkeypatch.setattr(routes_api, "_execute_vm_agent_task", fake_execute_vm_agent_task)
    monkeypatch.setattr(routes_api, "run_ssh_command_async", fail_ssh)
    monkeypatch.setattr(
        routes_api,
        "_load_creds_cache",
        lambda: {
            vm_names["attacker"]: {"username": "trainee", "password": "pw-attacker"},
            vm_names["victim"]: {"username": "trainee", "password": "pw-victim"},
        },
    )

    current_user = AuthenticatedUser(
        id="user-agent-runbook",
        username="agent-runbook",
        full_name="Agent Runbook",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_runbook_job(job.id, deployment_id, topology, current_user, ["simulation"], "actor_parallel", "prefer"))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert stored_job.progress["runbook"]["agent_mode"] == "prefer"
    assert stored_job.result["runbook"]["simulation_results"][0]["transport"] == "agent"
    assert agent_calls[0]["command"] == "ping -c 1 10.50.0.20"


def test_start_vm_agent_task_bootstraps_and_returns_background_task(monkeypatch):
    deployment_id = "52345678-1234-5678-9abc-def012345678"
    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Agent Task API",
            team="purple",
            objective="Launch a background task through the VM agent API.",
            difficulty="medium",
        ),
        nodes=[
            routes_api.TopologyNode(
                id="attacker",
                label="Attacker",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            )
        ],
        edges=[],
    )
    current_user = AuthenticatedUser(
        id="user-agent-api",
        username="agent-api",
        full_name="Agent API",
        role="user",
        created_at=time.time(),
    )

    async def fake_resolve_vm_agent_for_api(**kwargs):
        assert kwargs["allow_bootstrap"] is True
        return {"host": "10.60.0.10", "port": 8765, "token": "agent-token"}

    async def fake_execute_vm_agent_task(**kwargs):
        assert kwargs["background"] is True
        return {"task_id": "task-1", "status": "running", "background": True, "pid": 4242}

    monkeypatch.setattr(routes_api, "_get_deployment_for_user", lambda _deployment_id, _user: {"id": deployment_id, "topology": topology.dict()})
    monkeypatch.setattr(routes_api, "_topology_from_deployment_record", lambda _deployment: topology)
    monkeypatch.setattr(routes_api, "_resolve_vm_agent_for_api", fake_resolve_vm_agent_for_api)
    monkeypatch.setattr(routes_api, "_execute_vm_agent_task", fake_execute_vm_agent_task)

    response = asyncio.run(
        routes_api.start_vm_agent_task(
            deployment_id,
            "attacker",
            routes_api.VmAgentTaskRequest(command="python3 -m http.server 8080", background=True, timeout_seconds=5.0),
            current_user,
        )
    )

    assert response["deployment_id"] == deployment_id
    assert response["node_id"] == "attacker"
    assert response["agent"]["host"] == "10.60.0.10"
    assert response["task"]["task_id"] == "task-1"


def test_run_deploy_job_executes_node_automation_before_runbook(tmp_path, monkeypatch):
    iso_path = tmp_path / "ubuntu-22.04-server.iso"
    iso_path.write_text("iso")

    sent_texts = []

    monkeypatch.setattr(routes_api, "CREDS_CACHE_PATH", str(tmp_path / "vm_credentials.json"))
    monkeypatch.setattr(routes_api, "_load_creds_cache", lambda: {})
    monkeypatch.setattr(routes_api, "_load_deployments", lambda: {})
    monkeypatch.setattr(routes_api, "_save_deployments", lambda _deployments: None)
    monkeypatch.setattr(routes_api, "_resolve_image_path", lambda _image: str(iso_path))
    monkeypatch.setattr(routes_api, "_plan_topology_network_assignments", lambda _topology, _slug: {"installer": ["default"]})
    monkeypatch.setattr(routes_api, "register_vm", lambda *args, **kwargs: None)

    async def fake_ensure_image(src, progress_cb=None):
        class Ensured:
            container_path = str(iso_path)

        return Ensured()

    monkeypatch.setattr(routes_api, "ensure_image", fake_ensure_image)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "create_vm",
        lambda **kwargs: {"status": "success", "uuid": "vm-uuid", "vnc_port": 5901},
    )
    monkeypatch.setattr(
        routes_api.vm_manager,
        "send_text",
        lambda vm_name, text: sent_texts.append((vm_name, text)) or True,
    )
    monkeypatch.setattr(routes_api.vm_manager, "send_key", lambda _vm_name, _key: True)

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Automated Replay",
            team="blue",
            objective="Install the node and replay a benign simulation command.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                provisioning_strategy="Installer automation first, then replay the simulation via console.",
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Replay simulation",
                        actor="installer",
                        action="Run the replay script after the installer finishes.",
                        automation={"steps": [{"type": "send_text", "text": "python3 /opt/replay.py\n"}]},
                    )
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="installer",
                label="Installer",
                config=routes_api.TopologyNodeConfig(
                    image="ubuntu-22.04-server.iso",
                    cpu=2,
                    ram=2048,
                    assets=[],
                    automation={"steps": [{"type": "send_text", "text": "autoinstall\n"}]},
                ),
            )
        ],
        edges=[],
    )
    current_user = AuthenticatedUser(
        id="user-1",
        username="tester",
        full_name="Tester",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_deploy_job(job.id, topology, current_user))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert [text for _vm_name, text in sent_texts] == ["autoinstall\n", "python3 /opt/replay.py\n"]
    assert stored_job.progress["nodes"]["installer"]["automation"]["status"] == "completed"
    assert stored_job.progress["runbook"]["simulation"]["steps"]["0"]["status"] == "completed"
    assert stored_job.result["runbook"]["simulation_results"][0]["status"] == "completed"


def test_run_deploy_job_executes_ssh_runbook_command_and_publishes_events(tmp_path, monkeypatch):
    image_path = tmp_path / "ubuntu-20.04.qcow2"
    image_path.write_text("qcow2")

    ssh_calls = []
    published_events = []

    monkeypatch.setattr(routes_api, "CREDS_CACHE_PATH", str(tmp_path / "vm_credentials.json"))
    monkeypatch.setattr(routes_api, "_load_creds_cache", lambda: {})
    monkeypatch.setattr(routes_api, "_load_deployments", lambda: {})
    monkeypatch.setattr(routes_api, "_save_deployments", lambda _deployments: None)
    monkeypatch.setattr(routes_api, "_resolve_image_path", lambda _image: str(image_path))
    monkeypatch.setattr(routes_api, "_plan_topology_network_assignments", lambda _topology, _slug: {"telemetry": ["default"]})
    monkeypatch.setattr(routes_api, "register_vm", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes_api.vm_manager, "wait_for_primary_ipv4", lambda _vm_name, _timeout=180.0, _poll=5.0: "192.168.122.50")
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_preferred_ipv4",
        lambda _vm_name, _preferred_networks=None, _timeout=180.0, _poll=5.0: "192.168.122.50",
    )

    async def fake_publish(_job_id, event):
        published_events.append(event)

    async def fake_ssh_command(**kwargs):
        ssh_calls.append(kwargs)
        return {"exit_status": 0, "stdout": "replay complete\n", "stderr": ""}

    async def fake_ensure_image(src, progress_cb=None):
        class Ensured:
            container_path = str(image_path)

        return Ensured()

    monkeypatch.setattr(routes_api, "ensure_image", fake_ensure_image)
    monkeypatch.setattr(routes_api.event_bus, "publish", fake_publish)
    monkeypatch.setattr(routes_api, "run_ssh_command_async", fake_ssh_command)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "create_vm",
        lambda **kwargs: {"status": "success", "uuid": "vm-uuid", "vnc_port": 5901},
    )

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="SSH Replay",
            team="blue",
            objective="Provision a cloud image and execute a replay command over SSH.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                provisioning_strategy="Use cloud-init credentials for SSH execution.",
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Replay simulation",
                        actor="telemetry",
                        action="Run the replay script over SSH.",
                        transport="ssh",
                        command="python3 /opt/replay.py",
                        timeout_seconds=90,
                    )
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="telemetry",
                label="Telemetry",
                config=routes_api.TopologyNodeConfig(
                    image="ubuntu-20.04",
                    cpu=2,
                    ram=2048,
                    assets=[{"type": "package", "value": "python3"}],
                ),
            )
        ],
        edges=[],
    )
    current_user = AuthenticatedUser(
        id="user-2",
        username="ssh-tester",
        full_name="SSH Tester",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_deploy_job(job.id, topology, current_user))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert len(ssh_calls) == 1
    assert ssh_calls[0]["host"] == "192.168.122.50"
    assert ssh_calls[0]["username"] == "trainee"
    assert ssh_calls[0]["command"] == "python3 /opt/replay.py"
    assert stored_job.progress["runbook"]["simulation"]["steps"]["0"]["status"] == "completed"
    assert stored_job.progress["runbook"]["simulation"]["steps"]["0"]["transport"] == "ssh"
    assert stored_job.result["runbook"]["simulation_results"][0]["transport"] == "ssh"
    assert any(event["type"] == "runbook_command" for event in published_events)


def test_run_deploy_job_renders_runbook_target_placeholders_before_ssh(tmp_path, monkeypatch):
    image_path = tmp_path / "ubuntu-20.04.qcow2"
    image_path.write_text("qcow2")

    ssh_calls = []

    monkeypatch.setattr(routes_api, "CREDS_CACHE_PATH", str(tmp_path / "vm_credentials.json"))
    monkeypatch.setattr(routes_api, "_load_creds_cache", lambda: {})
    monkeypatch.setattr(routes_api, "_load_deployments", lambda: {})
    monkeypatch.setattr(routes_api, "_save_deployments", lambda _deployments: None)
    monkeypatch.setattr(routes_api, "_resolve_image_path", lambda _image: str(image_path))
    monkeypatch.setattr(
        routes_api,
        "_plan_topology_network_assignments",
        lambda _topology, _slug: {
            "attacker": ["default"],
            "hmi": ["default"],
            "scada-server": ["default"],
        },
    )
    monkeypatch.setattr(routes_api, "register_vm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_primary_ipv4",
        lambda vm_name, _timeout=180.0, _poll=5.0: (
            "192.168.122.50"
            if vm_name.endswith("_attacker")
            else "192.168.122.51"
            if vm_name.endswith("_hmi")
            else "192.168.122.52"
            if vm_name.endswith("_scada-server")
            else "192.168.122.99"
        ),
    )
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_preferred_ipv4",
        lambda vm_name, _preferred_networks=None, _timeout=180.0, _poll=5.0: (
            "192.168.122.50"
            if vm_name.endswith("_attacker")
            else "192.168.122.51"
            if vm_name.endswith("_hmi")
            else "192.168.122.52"
            if vm_name.endswith("_scada-server")
            else "192.168.122.99"
        ),
    )

    async def fake_ssh_command(**kwargs):
        ssh_calls.append(kwargs)
        return {"exit_status": 0, "stdout": "ok\n", "stderr": ""}

    async def fake_ensure_image(src, progress_cb=None):
        class Ensured:
            container_path = str(image_path)

        return Ensured()

    monkeypatch.setattr(routes_api, "ensure_image", fake_ensure_image)
    monkeypatch.setattr(routes_api, "run_ssh_command_async", fake_ssh_command)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "create_vm",
        lambda **kwargs: {"status": "success", "uuid": "vm-uuid", "vnc_port": 5901},
    )

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="Rendered SSH Targets",
            team="purple",
            objective="Resolve simple node-id placeholders before executing SSH runbook commands.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                provisioning_strategy="Use cloud-init credentials for SSH execution.",
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Recon",
                        actor="attacker",
                        target="hmi",
                        action="Scan the HMI IP.",
                        transport="ssh",
                        command="nmap -sV -p- hmi_ip",
                    ),
                    routes_api.ScenarioRunbookStep(
                        title="Inject",
                        actor="attacker",
                        target="scada-server",
                        action="Inject toward the SCADA server IP.",
                        transport="ssh",
                        command="python3 /opt/modbus_inject.py --target scada-server",
                    ),
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="attacker",
                label="Attacker",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="hmi",
                label="HMI",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
            routes_api.TopologyNode(
                id="scada-server",
                label="SCADA",
                config=routes_api.TopologyNodeConfig(image="ubuntu-20.04", cpu=2, ram=2048, assets=[]),
            ),
        ],
        edges=[],
    )
    current_user = AuthenticatedUser(
        id="user-ssh-render",
        username="ssh-render",
        full_name="SSH Render",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_deploy_job(job.id, topology, current_user))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert [call["command"] for call in ssh_calls] == [
        "nmap -sV -p- 192.168.122.51",
        "python3 /opt/modbus_inject.py --target 192.168.122.52",
    ]
    assert stored_job.progress["runbook"]["simulation"]["steps"]["0"]["resolved_command"] == "nmap -sV -p- 192.168.122.51"
    assert stored_job.progress["runbook"]["simulation"]["steps"]["1"]["resolved_command"] == "python3 /opt/modbus_inject.py --target 192.168.122.52"


def test_run_deploy_job_rewrites_stale_opnsense_source_before_download(tmp_path, monkeypatch):
    image_path = tmp_path / "opnsense.img"
    image_path.write_text("img")

    ensured_sources = []

    monkeypatch.setattr(routes_api, "CREDS_CACHE_PATH", str(tmp_path / "vm_credentials.json"))
    monkeypatch.setattr(routes_api, "_load_creds_cache", lambda: {})
    monkeypatch.setattr(routes_api, "_load_deployments", lambda: {})
    monkeypatch.setattr(routes_api, "_save_deployments", lambda _deployments: None)
    monkeypatch.setattr(routes_api, "_resolve_image_path", lambda _image: str(image_path))
    monkeypatch.setattr(routes_api, "_plan_topology_network_assignments", lambda _topology, _slug: {"firewall": ["default"]})
    monkeypatch.setattr(routes_api, "register_vm", lambda *args, **kwargs: None)
    monkeypatch.setattr(trainings_api, "_VERIFIED_SOURCE_URLS", {})

    async def fake_reachable(url):
        return url.startswith("https://pkg.opnsense.org/")

    monkeypatch.setattr(trainings_api, "_source_url_is_reachable", fake_reachable)

    async def fake_ensure_image(src, progress_cb=None):
        ensured_sources.append(src)

        class Ensured:
            container_path = str(image_path)

        return Ensured()

    monkeypatch.setattr(routes_api, "ensure_image", fake_ensure_image)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "create_vm",
        lambda **kwargs: {"status": "success", "uuid": "vm-uuid", "vnc_port": 5901},
    )

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="OPNsense Mirror Rewrite",
            team="blue",
            objective="Deploy a firewall VM from an auto-download source.",
            difficulty="medium",
            sources={
                "opnsense": {
                    "url": "https://mirror.us-phoenix-1.gnupgrade.net/opnsense/releases/24.1/OPNsense-24.1.1-OpenSSL-nano-amd64.img.bz2",
                    "filename": "OPNsense-24.1.1-OpenSSL-nano-amd64.img.bz2",
                    "extract": {"type": "bz2", "output_filename": "OPNsense.qcow2"},
                }
            },
        ),
        nodes=[
            routes_api.TopologyNode(
                id="firewall",
                label="Firewall",
                config=routes_api.TopologyNodeConfig(
                    image="opnsense",
                    cpu=2,
                    ram=2048,
                    assets=[],
                ),
            )
        ],
        edges=[],
    )
    current_user = AuthenticatedUser(
        id="user-opnsense",
        username="opnsense-tester",
        full_name="OPNsense Tester",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_deploy_job(job.id, topology, current_user))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert len(ensured_sources) == 2
    assert all(src["url"].startswith("https://pkg.opnsense.org/") for src in ensured_sources)
    assert all(src["extract"]["output_filename"] == "opnsense.img" for src in ensured_sources)


def test_run_deploy_job_completes_with_warnings_when_ssh_runbook_transport_fails(tmp_path, monkeypatch):
    image_path = tmp_path / "ubuntu-20.04.qcow2"
    image_path.write_text("qcow2")

    monkeypatch.setattr(routes_api, "CREDS_CACHE_PATH", str(tmp_path / "vm_credentials.json"))
    monkeypatch.setattr(routes_api, "_load_creds_cache", lambda: {})
    monkeypatch.setattr(routes_api, "_load_deployments", lambda: {})
    monkeypatch.setattr(routes_api, "_save_deployments", lambda _deployments: None)
    monkeypatch.setattr(routes_api, "_resolve_image_path", lambda _image: str(image_path))
    monkeypatch.setattr(routes_api, "_plan_topology_network_assignments", lambda _topology, _slug: {"telemetry": ["default"]})
    monkeypatch.setattr(routes_api, "register_vm", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes_api.vm_manager, "wait_for_primary_ipv4", lambda _vm_name, _timeout=180.0, _poll=5.0: "192.168.122.50")
    monkeypatch.setattr(
        routes_api.vm_manager,
        "wait_for_preferred_ipv4",
        lambda _vm_name, _preferred_networks=None, _timeout=180.0, _poll=5.0: "192.168.122.50",
    )

    async def fake_ensure_image(src, progress_cb=None):
        class Ensured:
            container_path = str(image_path)

        return Ensured()

    async def fake_ssh_command(**kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(routes_api, "ensure_image", fake_ensure_image)
    monkeypatch.setattr(routes_api, "run_ssh_command_async", fake_ssh_command)
    monkeypatch.setattr(
        routes_api.vm_manager,
        "create_vm",
        lambda **kwargs: {"status": "success", "uuid": "vm-uuid", "vnc_port": 5901},
    )

    topology = routes_api.TopologyDeployRequest(
        scenario=routes_api.ScenarioConfig(
            name="SSH Replay Warning",
            team="blue",
            objective="Provision a cloud image and attempt a replay command over SSH.",
            difficulty="medium",
            runbook=routes_api.ScenarioRunbook(
                provisioning_strategy="Use cloud-init credentials for SSH execution.",
                simulation_steps=[
                    routes_api.ScenarioRunbookStep(
                        title="Replay simulation",
                        actor="telemetry",
                        action="Run the replay script over SSH.",
                        transport="ssh",
                        command="python3 /opt/replay.py",
                        timeout_seconds=90,
                    )
                ],
            ),
        ),
        nodes=[
            routes_api.TopologyNode(
                id="telemetry",
                label="Telemetry",
                config=routes_api.TopologyNodeConfig(
                    image="ubuntu-20.04",
                    cpu=2,
                    ram=2048,
                    assets=[{"type": "package", "value": "python3"}],
                ),
            )
        ],
        edges=[],
    )
    current_user = AuthenticatedUser(
        id="user-3",
        username="ssh-warning-tester",
        full_name="SSH Warning Tester",
        role="user",
        created_at=time.time(),
    )
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    asyncio.run(routes_api._run_deploy_job(job.id, topology, current_user))
    stored_job = asyncio.run(get_job(job.id))

    assert stored_job is not None
    assert stored_job.status == "completed"
    assert stored_job.message == "Deployment completed with runbook warnings"
    assert stored_job.progress["runbook"]["status"] == "completed_with_errors"
    assert stored_job.progress["runbook"]["simulation"]["status"] == "failed"
    assert "SSH execution failed for node 'telemetry' at '192.168.122.50'" in stored_job.progress["runbook"]["simulation"]["error"]
    assert stored_job.result["status"] == "deployment_processed_with_warnings"
    assert stored_job.result["runbook"]["status"] == "completed_with_errors"
    assert stored_job.result["runbook"]["errors"][0]["phase"] == "simulation"