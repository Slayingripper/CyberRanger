"""Simple demo script to exercise training run endpoints."""
import httpx
import time
import json

API = "http://localhost:8001/api"

def main():
    # List trainings
    r = httpx.get(f"{API}/trainings")
    trainings = r.json()
    if not trainings:
        print("No trainings found. Create one via /api/trainings or upload.")
        return
    training = trainings[0]
    print("Using training:", training.get('title'))

    # Create run
    r = httpx.post(f"{API}/training-runs", params={"definition_id": training.get('id')})
    run = r.json()
    print("Created run:", run['id'])

    # Find first quiz task
    levels = training.get('levels', [])
    if not levels:
        print("No levels")
        return
    level0 = levels[0]
    task = None
    for t in level0.get('tasks', []):
        if t.get('type') == 'quiz':
            task = t
            break
    if not task:
        print("No quiz task found in level 0")
        return

    payload = {"task_id": task['id'], "answer": task.get('answer')}
    print("Submitting correct answer payload:", payload)
    res = httpx.post(f"{API}/training-runs/{run['id']}/levels/0/submit", json=payload)
    print("Submit response:", res.json())

if __name__ == '__main__':
    main()
