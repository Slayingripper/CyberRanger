import os
import json
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


def test_run_evaluation_summary_includes_activity():
    training = make_sample_training(None)

    run_res = client.post(
        "/api/training-runs",
        params={"definition_id": training['id'], "participants": ["alice"]},
    )
    assert run_res.status_code == 200
    run_id = run_res.json()["id"]

    wrong_res = client.post(
        f"/api/training-runs/{run_id}/levels/0/submit",
        json={"task_id": "t1", "answer": "5"},
    )
    assert wrong_res.status_code == 200
    assert wrong_res.json()["correct"] is False

    hint_res = client.post(f"/api/training-runs/{run_id}/levels/0/hint", params={"hint_idx": 1})
    assert hint_res.status_code == 200

    correct_res = client.post(
        f"/api/training-runs/{run_id}/levels/0/submit",
        json={"task_id": "t1", "answer": "4"},
    )
    assert correct_res.status_code == 200
    assert correct_res.json()["correct"] is True

    evaluation_res = client.get(f"/api/training-runs/{run_id}/evaluation")
    assert evaluation_res.status_code == 200
    evaluation = evaluation_res.json()

    assert evaluation["run_id"] == run_id
    assert evaluation["training_title"] == training["title"]
    assert evaluation["participants"] == ["alice"]
    assert evaluation["state"] == "completed"
    assert evaluation["completed_levels"] == 1
    assert evaluation["total_levels"] == 1
    assert evaluation["completion_ratio"] == 1.0
    assert evaluation["total_attempts"] == 2
    assert evaluation["total_hints_used"] == 1
    assert evaluation["total_duration_seconds"] is not None
    assert len(evaluation["level_summaries"]) == 1
    assert len(evaluation["activity_log"]) >= 5

    level_summary = evaluation["level_summaries"][0]
    assert level_summary["title"] == "Level 1"
    assert level_summary["status"] == "completed"
    assert level_summary["attempts"] == 2
    assert level_summary["hints_used"] == 1
    assert level_summary["completed_tasks"] == ["t1"]
    assert level_summary["completed_task_count"] == 1
    assert level_summary["total_tasks"] == 1
    assert level_summary["completion_ratio"] == 1.0
    assert level_summary["duration_seconds"] is not None

    activity_types = [event["type"] for event in evaluation["activity_log"]]
    assert "run_started" in activity_types
    assert "level_started" in activity_types
    assert "task_submitted" in activity_types
    assert "hint_taken" in activity_types
    assert "level_completed" in activity_types
    assert "run_completed" in activity_types
