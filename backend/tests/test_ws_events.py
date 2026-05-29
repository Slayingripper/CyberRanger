import os
import json
import asyncio
import sys
import types
import uuid
from fastapi.testclient import TestClient

libvirt_stub = types.SimpleNamespace(
    libvirtError=RuntimeError,
    open=lambda _uri: object(),
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE=0,
    VIR_KEYCODE_SET_LINUX=0,
)
sys.modules.pop("libvirt", None)
sys.modules["libvirt"] = libvirt_stub

from app.main import app
from app.core.auth import get_current_user_from_token
from app.core.deploy_jobs import new_job
from app.core.event_bus import event_bus
from app.core.vm_manager import WORK_DIR

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
    return {"Authorization": f"Bearer {token}"}, token


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
    headers, token = auth_headers("ws-user")

    # Create run
    r = client.post("/api/training-runs", params={"definition_id": training['id']}, headers=headers)
    assert r.status_code == 200
    run = r.json()
    run_id = run['id']

    with client.websocket_connect(f"/api/ws/training-runs/{run_id}?token={token}") as ws:
        # publish event for definition/level (async helper)
        asyncio.run(
            event_bus.publish_by_definition_level(training['id'], 0, {"type": "deploy", "ts": 1, "result": []})
        )
        msg = ws.receive_json()
        assert msg['type'] == 'deploy'


def test_deploy_job_ws_receives_runbook_events():
    _headers, token = auth_headers("deploy-ws-user")
    current_user = get_current_user_from_token(token)
    job = new_job(initial_progress={"owner_id": current_user.id, "owner_username": current_user.username})

    with client.websocket_connect(f"/api/ws/deploy-jobs/{job.id}?token={token}") as ws:
        asyncio.run(
            event_bus.publish(
                job.id,
                {"type": "runbook_step", "ts": 1, "detail": {"title": "Replay simulation", "status": "running"}},
            )
        )
        msg = ws.receive_json()
        assert msg["type"] == "runbook_step"
        assert msg["detail"]["title"] == "Replay simulation"
