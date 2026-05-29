import asyncio
import sys
import types
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

libvirt_stub = types.SimpleNamespace(
    libvirtError=RuntimeError,
    open=lambda _uri: object(),
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE=0,
    VIR_KEYCODE_SET_LINUX=0,
)
sys.modules.pop("libvirt", None)
sys.modules["libvirt"] = libvirt_stub

from app.api import llm as llm_api
from app.main import app

client = TestClient(app)


def auth_headers(username_prefix: str):
    username = f"{username_prefix}-{uuid.uuid4().hex[:8]}"
    password = "password123"
    register_res = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "full_name": username_prefix.title()},
    )
    assert register_res.status_code == 200
    token = register_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_request_llm_json_reports_transport_error_with_target(monkeypatch):
    request = httpx.Request("POST", "http://localhost:11434/api/chat")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("", request=request)

    monkeypatch.setattr(llm_api.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(
            llm_api._request_llm_json(
                llm_api.LlmProviderConfig(provider="ollama", model="qwen3:8b"),
                [{"role": "user", "content": "Generate a topology."}],
            )
        )

    assert str(exc_info.value) == "Provider request failed due to ConnectError while calling http://localhost:11434/api/chat"


def test_llm_workflow_returns_normalized_topology(monkeypatch):
    responses = [
        {
            "summary": "A phishing investigation lab with a gateway, victim, and analyst.",
            "scenario": {
                "name": "Phishing Investigation Lab",
                "team": "blue",
                "objective": "Investigate a phishing incident and isolate the compromised endpoint.",
                "difficulty": "medium",
            },
            "nodes": [
                {"id": "gateway", "label": "Mail Gateway", "image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                {"id": "victim", "label": "Victim Workstation", "image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                {"id": "analyst", "label": "Analyst Box", "image": "ubuntu-20.04", "cpu": 1, "ram": 1024, "assets": []},
            ],
            "edges": [
                {"source": "gateway", "target": "victim", "segment": "corp-net", "mode": "nat"},
                {"source": "gateway", "target": "missing-node", "segment": "invalid-net", "mode": "nat"},
            ],
        },
        {
            "summary": "A phishing investigation lab with a gateway, victim, and analyst.",
            "scenario": {
                "name": "Phishing Investigation Lab",
                "team": "blue",
                "objective": "Investigate a phishing incident and isolate the compromised endpoint.",
                "difficulty": "medium",
            },
            "nodes": [
                {
                    "id": "gateway",
                    "label": "Mail Gateway",
                    "config": {"image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                },
                {
                    "id": "victim",
                    "label": "Victim Workstation",
                    "config": {"image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                },
                {
                    "id": "analyst",
                    "label": "Analyst Box",
                    "config": {"image": "ubuntu-20.04", "cpu": 1, "ram": 1024, "assets": []},
                },
            ],
            "edges": [
                {"source": "gateway", "target": "victim", "segment": "corp-net", "mode": "nat"},
                {"source": "gateway", "target": "missing-node", "segment": "invalid-net", "mode": "nat"},
            ],
        },
    ]

    async def fake_request_llm_json(_provider, _messages):
        return responses.pop(0)

    async def unexpected_deploy(_topology, _current_user):
        raise AssertionError("auto_deploy should not be called")

    monkeypatch.setattr(llm_api, "_request_llm_json", fake_request_llm_json)
    monkeypatch.setattr(llm_api, "_start_generated_topology_deploy", unexpected_deploy)

    res = client.post(
        "/api/llm/scenario-workflows",
        headers=auth_headers("llm-user"),
        json={
            "prompt": "Create a phishing investigation lab with a gateway, victim, and analyst workstation.",
            "provider": {"provider": "ollama", "model": "qwen3:8b"},
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert data["summary"].startswith("A phishing investigation lab")
    assert data["deploy_job_id"] is None
    assert [step["stage"] for step in data["workflow"]] == ["plan", "synthesize", "validate"]
    assert len(data["topology"]["nodes"]) == 3
    assert all(node.get("position") for node in data["topology"]["nodes"])
    assert len(data["topology"]["edges"]) == 1
    assert data["topology"]["edges"][0]["source"] == "gateway"
    assert any("Dropped an invalid link" in warning for warning in data["warnings"])


def test_llm_workflow_backfills_sources_and_replaces_missing_unsupported_images(monkeypatch):
    responses = [
        {
            "summary": "An OT simulation with a firewall and operator console.",
            "scenario": {
                "name": "OT Firewall Simulation",
                "team": "blue",
                "objective": "Observe and contain suspicious traffic crossing the plant firewall.",
                "difficulty": "medium",
            },
            "nodes": [
                {"id": "gateway", "label": "Perimeter Router/Firewall", "image": "opnsense", "cpu": 2, "ram": 2048, "assets": []},
                {"id": "hmi", "label": "HMI Workstation (Victim)", "image": "windows-10", "cpu": 2, "ram": 4096, "assets": []},
            ],
            "edges": [{"source": "gateway", "target": "hmi", "segment": "ot-lan", "mode": "nat"}],
        },
        {
            "summary": "An OT simulation with a firewall and operator console.",
            "scenario": {
                "name": "OT Firewall Simulation",
                "team": "blue",
                "objective": "Observe and contain suspicious traffic crossing the plant firewall.",
                "difficulty": "medium",
            },
            "nodes": [
                {
                    "id": "gateway",
                    "label": "Perimeter Router/Firewall",
                    "config": {"image": "opnsense", "cpu": 2, "ram": 2048, "assets": []},
                },
                {
                    "id": "hmi",
                    "label": "HMI Workstation (Victim)",
                    "config": {"image": "windows-10", "cpu": 2, "ram": 4096, "assets": []},
                },
            ],
            "edges": [{"source": "gateway", "target": "hmi", "segment": "ot-lan", "mode": "nat"}],
        },
    ]

    async def fake_request_llm_json(_provider, _messages):
        return responses.pop(0)

    monkeypatch.setattr(llm_api, "_request_llm_json", fake_request_llm_json)
    monkeypatch.setattr(llm_api, "_collect_candidate_images", lambda: ["ubuntu-20.04", "opnsense"])

    res = client.post(
        "/api/llm/scenario-workflows",
        headers=auth_headers("llm-image-user"),
        json={
            "prompt": "Create an OT environment with a perimeter firewall and an operator workstation.",
            "provider": {"provider": "ollama", "model": "qwen3:8b"},
        },
    )

    assert res.status_code == 200
    data = res.json()
    nodes = {node["id"]: node for node in data["topology"]["nodes"]}
    assert nodes["gateway"]["config"]["image"] == "opnsense"
    assert nodes["hmi"]["config"]["image"] == "ubuntu-20.04"
    assert data["topology"]["scenario"]["sources"]["opnsense"]["url"].startswith("https://pkg.opnsense.org/")
    assert "windows-10" not in (data["topology"]["scenario"].get("sources") or {})
    assert any("Requested image 'windows-10' is not available" in warning for warning in data["warnings"])
    assert any("Added an auto-download source for image 'opnsense'" in warning for warning in data["warnings"])


def test_llm_workflow_preserves_automation_and_runbook(monkeypatch):
    responses = [
        {
            "summary": "An end-to-end OT simulation with automated installation and a replayable attack path.",
            "scenario": {
                "name": "OT Breach Simulation",
                "team": "blue",
                "objective": "Deploy the lab, replay a benign OT attack sequence, and watch the telemetry dashboard.",
                "difficulty": "hard",
                "runbook": {
                    "provisioning_strategy": "Use console automation for the ISO installer and cloud-init assets for the Linux nodes.",
                    "setup_order": ["hmi-installer", "telemetry"],
                    "setup_steps": [
                        {
                            "title": "Install HMI node",
                            "actor": "hmi-installer",
                            "action": "Drive the unattended installer through the console and wait for first boot.",
                            "expected_outcome": "The HMI node boots into the configured desktop.",
                        }
                    ],
                    "simulation_steps": [
                        {
                            "title": "Replay OT attack",
                            "actor": "telemetry",
                            "target": "hmi-installer",
                            "action": "Run the generated replay script and publish the resulting alerts to the dashboard.",
                            "expected_outcome": "The dashboard shows the attack timeline and detection verdict.",
                            "delay_seconds": 20,
                            "transport": "ssh",
                            "command": "python3 /opt/replay_ot_attack.py",
                            "timeout_seconds": 90,
                        }
                    ],
                    "visualizations": [
                        {
                            "title": "Telemetry dashboard",
                            "kind": "dashboard",
                            "node_id": "telemetry",
                            "url_hint": "http://[telemetry-ip]:5000",
                            "description": "Shows the OT attack timeline and alerts.",
                        }
                    ],
                    "success_criteria": [
                        "The dashboard shows the replayed OT attack and the detection alert.",
                    ],
                },
            },
            "nodes": [
                {
                    "id": "hmi-installer",
                    "label": "HMI Installer",
                    "image": "ubuntu-22.04-server.iso",
                    "cpu": 2,
                    "ram": 2048,
                    "assets": [],
                    "automation": {
                        "steps": [
                            {"type": "wait", "delay_seconds": 45},
                            {"type": "send_text", "text": "autoinstall\n", "retries": 2, "retry_delay_seconds": 10},
                            {"type": "send_key", "key": "enter", "repeat": 1},
                        ]
                    },
                },
                {
                    "id": "telemetry",
                    "label": "Telemetry Dashboard",
                    "image": "ubuntu-20.04",
                    "cpu": 2,
                    "ram": 2048,
                    "assets": [
                        {"type": "package", "value": "python3-pip"},
                        {"type": "command", "value": "echo ready >/opt/status.txt"},
                    ],
                },
            ],
            "edges": [{"source": "hmi-installer", "target": "telemetry", "segment": "ot-lan", "mode": "nat"}],
        },
        {
            "summary": "An end-to-end OT simulation with automated installation and a replayable attack path.",
            "scenario": {
                "name": "OT Breach Simulation",
                "team": "blue",
                "objective": "Deploy the lab, replay a benign OT attack sequence, and watch the telemetry dashboard.",
                "difficulty": "hard",
                "runbook": {
                    "provisioning_strategy": "Use console automation for the ISO installer and cloud-init assets for the Linux nodes.",
                    "setup_order": ["hmi-installer", "telemetry"],
                    "setup_steps": [
                        {
                            "title": "Install HMI node",
                            "actor": "hmi-installer",
                            "action": "Drive the unattended installer through the console and wait for first boot.",
                            "expected_outcome": "The HMI node boots into the configured desktop.",
                        }
                    ],
                    "simulation_steps": [
                        {
                            "title": "Replay OT attack",
                            "actor": "telemetry",
                            "target": "hmi-installer",
                            "action": "Run the generated replay script and publish the resulting alerts to the dashboard.",
                            "expected_outcome": "The dashboard shows the attack timeline and detection verdict.",
                            "delay_seconds": 20,
                            "transport": "ssh",
                            "command": "python3 /opt/replay_ot_attack.py",
                            "timeout_seconds": 90,
                        }
                    ],
                    "visualizations": [
                        {
                            "title": "Telemetry dashboard",
                            "kind": "dashboard",
                            "node_id": "telemetry",
                            "url_hint": "http://[telemetry-ip]:5000",
                            "description": "Shows the OT attack timeline and alerts.",
                        }
                    ],
                    "success_criteria": [
                        "The dashboard shows the replayed OT attack and the detection alert.",
                    ],
                },
            },
            "nodes": [
                {
                    "id": "hmi-installer",
                    "label": "HMI Installer",
                    "config": {
                        "image": "ubuntu-22.04-server.iso",
                        "cpu": 2,
                        "ram": 2048,
                        "assets": [],
                        "automation": {
                            "steps": [
                                {"type": "wait", "delay_seconds": 45},
                                {"type": "send_text", "text": "autoinstall\n", "retries": 2, "retry_delay_seconds": 10},
                                {"type": "send_key", "key": "enter", "repeat": 1},
                            ]
                        },
                    },
                },
                {
                    "id": "telemetry",
                    "label": "Telemetry Dashboard",
                    "config": {
                        "image": "ubuntu-20.04",
                        "cpu": 2,
                        "ram": 2048,
                        "assets": [
                            {"type": "package", "value": "python3-pip"},
                            {"type": "command", "value": "echo ready >/opt/status.txt"},
                        ],
                    },
                },
            ],
            "edges": [{"source": "hmi-installer", "target": "telemetry", "segment": "ot-lan", "mode": "nat"}],
        },
    ]

    async def fake_request_llm_json(_provider, _messages):
        return responses.pop(0)

    monkeypatch.setattr(llm_api, "_request_llm_json", fake_request_llm_json)
    monkeypatch.setattr(llm_api, "_collect_candidate_images", lambda: ["ubuntu-20.04", "ubuntu-22.04-server.iso"])

    res = client.post(
        "/api/llm/scenario-workflows",
        headers=auth_headers("llm-runbook-user"),
        json={
            "prompt": "Create an OT environment that installs an HMI from ISO, provisions a telemetry dashboard, replays a benign attack, and visualizes the result.",
            "provider": {"provider": "ollama", "model": "qwen3:8b"},
        },
    )

    assert res.status_code == 200
    data = res.json()
    nodes = {node["id"]: node for node in data["topology"]["nodes"]}
    automation = nodes["hmi-installer"]["config"]["automation"]
    assert automation["steps"][0]["type"] == "wait"
    assert automation["steps"][1]["type"] == "send_text"
    assert automation["steps"][2]["type"] == "send_key"

    runbook = data["topology"]["scenario"]["runbook"]
    assert runbook["setup_order"] == ["hmi-installer", "telemetry"]
    assert runbook["setup_steps"][0]["actor"] == "hmi-installer"
    assert runbook["simulation_steps"][0]["target"] == "hmi-installer"
    assert runbook["simulation_steps"][0]["delay_seconds"] == 20.0
    assert runbook["simulation_steps"][0]["transport"] == "ssh"
    assert runbook["simulation_steps"][0]["command"] == "python3 /opt/replay_ot_attack.py"
    assert runbook["simulation_steps"][0]["timeout_seconds"] == 90.0
    assert runbook["visualizations"][0]["node_id"] == "telemetry"
    assert runbook["success_criteria"] == ["The dashboard shows the replayed OT attack and the detection alert."]


def test_llm_workflow_retries_invalid_topology_until_it_returns_nodes(monkeypatch):
    responses = [
        {
            "summary": "A simple containment exercise.",
            "scenario": {
                "name": "Containment Exercise",
                "team": "blue",
                "objective": "Deploy a minimal containment lab.",
                "difficulty": "easy",
            },
            "nodes": [{"id": "gateway", "label": "Gateway"}],
        },
        {
            "summary": "Broken topology response.",
            "scenario": {
                "name": "Containment Exercise",
                "team": "blue",
                "objective": "Deploy a minimal containment lab.",
                "difficulty": "easy",
            },
            "nodes": [],
            "edges": [],
        },
        {
            "summary": "Still broken topology response.",
            "scenario": {
                "name": "Containment Exercise",
                "team": "blue",
                "objective": "Deploy a minimal containment lab.",
                "difficulty": "easy",
            },
            "nodes": [],
            "edges": [],
        },
        {
            "summary": "A repaired minimal containment topology.",
            "scenario": {
                "name": "Containment Exercise",
                "team": "blue",
                "objective": "Deploy a minimal containment lab.",
                "difficulty": "easy",
            },
            "nodes": [
                {
                    "id": "gateway",
                    "label": "Gateway",
                    "config": {"image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                }
            ],
            "edges": [],
        },
    ]

    async def fake_request_llm_json(_provider, _messages):
        return responses.pop(0)

    monkeypatch.setattr(llm_api, "_request_llm_json", fake_request_llm_json)
    monkeypatch.setattr(llm_api, "_collect_candidate_images", lambda: ["ubuntu-20.04"])

    res = client.post(
        "/api/llm/scenario-workflows",
        headers=auth_headers("llm-repair-user"),
        json={
            "prompt": "Create a minimal containment lab with one gateway node.",
            "provider": {"provider": "ollama", "model": "qwen3:8b"},
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert len(data["topology"]["nodes"]) == 1
    assert [step["stage"] for step in data["workflow"]] == ["plan", "synthesize", "repair", "validate"]
    assert "after 2 attempt(s)" in data["workflow"][2]["message"]


def test_llm_workflow_repairs_malformed_topology_json(monkeypatch):
    responses = [
        {
            "summary": "A compact web lab.",
            "scenario": {
                "name": "Web Lab",
                "team": "blue",
                "objective": "Deploy a minimal web monitoring lab.",
                "difficulty": "easy",
            },
            "nodes": [{"id": "web", "label": "Web"}],
        },
        llm_api.ProviderInvalidJsonError(
            "Expecting ',' delimiter: line 1 column 4613 (char 4612)",
            '{"summary":"Broken topology","scenario":{"name":"Web Lab","team":"blue","objective":"Deploy a minimal web monitoring lab.","difficulty":"easy"},"nodes":[{"id":"web","label":"Web","config":{"image":"ubuntu-20.04","cpu":2,"ram":2048,"assets":[]}}] "edges":[]}',
        ),
        {
            "summary": "A repaired compact web lab.",
            "scenario": {
                "name": "Web Lab",
                "team": "blue",
                "objective": "Deploy a minimal web monitoring lab.",
                "difficulty": "easy",
            },
            "nodes": [
                {
                    "id": "web",
                    "label": "Web",
                    "config": {"image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                }
            ],
            "edges": [],
        },
    ]

    async def fake_request_llm_json(_provider, _messages):
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(llm_api, "_request_llm_json", fake_request_llm_json)
    monkeypatch.setattr(llm_api, "_collect_candidate_images", lambda: ["ubuntu-20.04"])

    res = client.post(
        "/api/llm/scenario-workflows",
        headers=auth_headers("llm-malformed-user"),
        json={
            "prompt": "Create a minimal web monitoring lab with one Ubuntu web node.",
            "provider": {"provider": "ollama", "model": "qwen3:8b"},
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert len(data["topology"]["nodes"]) == 1
    assert [step["stage"] for step in data["workflow"]] == ["plan", "synthesize", "repair", "validate"]
    assert "after 1 attempt(s)" in data["workflow"][2]["message"]


def test_llm_workflow_can_start_deploy(monkeypatch):
    responses = [
        {
            "summary": "A compact SOC lab with a gateway and analyst host.",
            "scenario": {
                "name": "SOC Lab",
                "team": "blue",
                "objective": "Review simulated alerts from a central gateway.",
                "difficulty": "easy",
            },
            "nodes": [
                {"id": "gateway", "label": "Gateway", "image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                {"id": "analyst", "label": "Analyst", "image": "ubuntu-20.04", "cpu": 1, "ram": 1024, "assets": []},
            ],
            "edges": [{"source": "gateway", "target": "analyst", "segment": "corp-net", "mode": "nat"}],
        },
        {
            "summary": "A compact SOC lab with a gateway and analyst host.",
            "scenario": {
                "name": "SOC Lab",
                "team": "blue",
                "objective": "Review simulated alerts from a central gateway.",
                "difficulty": "easy",
            },
            "nodes": [
                {
                    "id": "gateway",
                    "label": "Gateway",
                    "config": {"image": "ubuntu-20.04", "cpu": 2, "ram": 2048, "assets": []},
                },
                {
                    "id": "analyst",
                    "label": "Analyst",
                    "config": {"image": "ubuntu-20.04", "cpu": 1, "ram": 1024, "assets": []},
                },
            ],
            "edges": [{"source": "gateway", "target": "analyst", "segment": "corp-net", "mode": "nat"}],
        },
    ]

    async def fake_request_llm_json(_provider, _messages):
        return responses.pop(0)

    async def fake_start_generated_topology_deploy(topology, _current_user):
        assert topology.scenario is not None
        assert topology.scenario.name == "SOC Lab"
        return "job-123"

    monkeypatch.setattr(llm_api, "_request_llm_json", fake_request_llm_json)
    monkeypatch.setattr(llm_api, "_start_generated_topology_deploy", fake_start_generated_topology_deploy)

    res = client.post(
        "/api/llm/scenario-workflows",
        headers=auth_headers("llm-deploy-user"),
        json={
            "prompt": "Create a small SOC lab with one gateway and one analyst workstation.",
            "provider": {"provider": "ollama", "model": "qwen3:8b"},
            "auto_deploy": True,
        },
    )

    assert res.status_code == 200
    assert res.json()["deploy_job_id"] == "job-123"