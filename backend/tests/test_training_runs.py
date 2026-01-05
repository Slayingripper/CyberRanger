import os
import json
import tempfile
from fastapi.testclient import TestClient
from app.main import app
from app.core.vm_manager import WORK_DIR

client = TestClient(app)


def make_sample_training(tmpdir):
    trainings_dir = os.path.join(WORK_DIR, "trainings")
    os.makedirs(trainings_dir, exist_ok=True)
    training = {
        "id": "test-training",
        "title": "Test Training",
        "description": "A sample",
        "difficulty": "easy",
        "levels": [
            {
                "id": "lvl1",
                "title": "Level 1",
                "description": "Desc",
                "tasks": [
                    {"id": "t1", "question": "What is 2+2?", "type": "quiz", "answer": "4"}
                ]
            }
        ]
    }
    path = os.path.join(trainings_dir, "test-training.json")
    with open(path, "w") as f:
        json.dump(training, f)
    return training


def test_create_run_and_submit():
    training = make_sample_training(None)

    # Create run
    r = client.post("/api/training-runs", params={"definition_id": training['id']})
    assert r.status_code == 200
    run = r.json()
    assert run['definition_id'] == training['id']

    run_id = run['id']

    # Submit correct answer
    payload = {"task_id": "t1", "answer": "4"}
    res = client.post(f"/api/training-runs/{run_id}/levels/0/submit", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data['correct'] is True
    assert data['score'] == 100
