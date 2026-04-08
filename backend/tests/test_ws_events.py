import os
import json
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.core.event_bus import event_bus
from app.core.vm_manager import WORK_DIR

client = TestClient(app)


def make_sample_training():
    trainings_dir = os.path.join(WORK_DIR, "trainings")
    os.makedirs(trainings_dir, exist_ok=True)
    training = {
        "id": "ws-training",
        "title": "WS Training",
        "description": "For WS tests",
        "difficulty": "easy",
        "levels": [
            {
                "id": "lvl1",
                "title": "Level 1",
                "description": "Desc",
                "tasks": []
            }
        ]
    }
    path = os.path.join(trainings_dir, "ws-training.json")
    with open(path, "w") as f:
        json.dump(training, f)
    return training


def test_ws_receives_publish_by_definition_level():
    training = make_sample_training()

    # Create run
    r = client.post("/api/training-runs", params={"definition_id": training['id']})
    assert r.status_code == 200
    run = r.json()
    run_id = run['id']

    with client.websocket_connect(f"/api/ws/training-runs/{run_id}") as ws:
        # publish event for definition/level (async helper)
        asyncio.get_event_loop().run_until_complete(
            event_bus.publish_by_definition_level(training['id'], 0, {"type": "deploy", "ts": 1, "result": []})
        )
        msg = ws.receive_json()
        assert msg['type'] == 'deploy'
