import os
import json
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.core.event_bus import event_bus
from app.core.vm_manager import WORK_DIR

client = TestClient(app)


def make_example_training():
    trainings_dir = os.path.join(WORK_DIR, "trainings")
    os.makedirs(trainings_dir, exist_ok=True)
    path = os.path.join(trainings_dir, "example-scenario.json")
    if not os.path.exists(path):
        # Create sample training if missing (helps containerized tests)
        training = {
            "id": "example-scenario",
            "title": "Example: Echo VM Scenario",
            "description": "A simple example training with one VM and one quiz task to test deploys and console streaming.",
            "difficulty": "easy",
            "levels": [
                {
                    "id": "lvl-echo",
                    "title": "Echo Level",
                    "description": "Starts a VM that echoes a message to console.",
                    "topology": { "vms": [{"name": "echo-vm", "image": "ubuntu-20.04", "memory": 1024, "vcpus": 1}] },
                    "tasks": [{"id": "q1", "question": "What's the magic word?", "type": "quiz", "answer": "please"}]
                }
            ]
        }
        with open(path, "w") as f:
            json.dump(training, f, indent=2)
        return training
    with open(path, "r") as f:
        return json.load(f)


def test_console_debug_endpoint_delivered_to_ws():
    training = make_example_training()
    # Create run
    r = client.post("/api/training-runs", params={"definition_id": training['id']})
    assert r.status_code == 200
    run = r.json()
    run_id = run['id']

    with client.websocket_connect(f"/api/ws/training-runs/{run_id}") as ws:
        # Send debug console message
        msg = "hello from debug"
        res = client.post(f"/api/debug/trainings/{training['id']}/levels/0/console", json={"msg": msg})
        assert res.status_code == 200
        ev = ws.receive_json()
        assert ev['type'] == 'console'
        assert msg in ev['msg']
