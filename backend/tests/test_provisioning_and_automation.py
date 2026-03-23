import asyncio

from app.core.deploy_automation import execute_automation_steps, normalize_automation_steps
from app.core.provisioning import build_cloud_init_from_assets, cloud_init_credentials


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