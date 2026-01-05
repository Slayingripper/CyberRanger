from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
import json
import uuid
import time
from app.core.vm_manager import WORK_DIR
from app.core.event_bus import event_bus
import time

router = APIRouter()

RUNS_DIR = os.path.join(WORK_DIR, "training_runs")
os.makedirs(RUNS_DIR, exist_ok=True)


class LevelState(BaseModel):
    index: int
    status: str = "pending"  # 'pending'|'in_progress'|'completed'
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    score: int = 0
    hints: List[str] = []
    sandbox: Optional[Dict[str, Any]] = None


class TrainingRun(BaseModel):
    id: Optional[str] = None
    definition_id: str
    participants: List[str] = []
    current_level: int = 0
    state: str = "running"  # 'running'|'completed'
    level_states: List[LevelState] = []
    created_at: float = Field(default_factory=lambda: time.time())


def _run_path(run_id: str) -> str:
    return os.path.join(RUNS_DIR, f"{run_id}.json")


def save_run(run: TrainingRun):
    if not run.id:
        raise ValueError("run.id required")
    with open(_run_path(run.id), "w") as f:
        json.dump(run.dict(), f, indent=2)


def load_run(run_id: str) -> TrainingRun:
    p = _run_path(run_id)
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Run not found")
    with open(p, "r") as f:
        data = json.load(f)
        return TrainingRun(**data)


@router.post("/training-runs", response_model=TrainingRun)
async def create_run(definition_id: str, participants: Optional[List[str]] = None):
    # ensure definition exists
    def_path = os.path.join(WORK_DIR, "trainings", f"{definition_id}.json")
    if not os.path.exists(def_path):
        raise HTTPException(status_code=404, detail="Training definition not found")

    with open(def_path, "r") as f:
        definition = json.load(f)

    run = TrainingRun(
        id=str(uuid.uuid4()),
        definition_id=definition_id,
        participants=participants or [],
        current_level=0,
        state="running",
        level_states=[LevelState(index=i) for i, _ in enumerate(definition.get("levels", []))],
    )
    # mark first level as in_progress
    if run.level_states:
        run.level_states[0].status = "in_progress"
        run.level_states[0].started_at = time.time()

    save_run(run)
    return run


@router.get("/training-runs/{run_id}", response_model=TrainingRun)
async def get_run(run_id: str):
    return load_run(run_id)


class SubmitPayload(BaseModel):
    task_id: str
    answer: Optional[str] = None


@router.post("/training-runs/{run_id}/levels/{level_idx}/submit")
async def submit_level(run_id: str, level_idx: int, payload: SubmitPayload):
    run = load_run(run_id)
    if run.state != "running":
        raise HTTPException(status_code=400, detail="Run is not active")

    if level_idx != run.current_level:
        raise HTTPException(status_code=400, detail="Submission must target the current level")

    # load training definition
    def_path = os.path.join(WORK_DIR, "trainings", f"{run.definition_id}.json")
    if not os.path.exists(def_path):
        raise HTTPException(status_code=404, detail="Training definition not found")

    with open(def_path, "r") as f:
        definition = json.load(f)

    levels = definition.get("levels", [])
    if level_idx >= len(levels):
        raise HTTPException(status_code=404, detail="Level not found")

    level = levels[level_idx]
    # find task
    task = None
    for t in level.get("tasks", []):
        if t.get("id") == payload.task_id:
            task = t
            break
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    correct = False
    score = 0
    if task.get("type") == "quiz":
        expected = (task.get("answer") or "").strip().lower()
        given = (payload.answer or "").strip().lower()
        if expected and given and expected == given:
            correct = True
            score = 100
    else:
        # For non-quiz tasks, perform basic presence check (MVP)
        if payload.answer and payload.answer.strip():
            correct = True
            score = 100

    ls = run.level_states[level_idx]
    ls.ended_at = time.time()
    ls.status = "completed" if correct else "pending"
    ls.score = score

    # advance to next level if correct
    next_idx = None
    if correct:
        next_idx = level_idx + 1
        # mark completed and set next in_progress if exists
        if next_idx < len(run.level_states):
            run.current_level = next_idx
            run.level_states[next_idx].status = "in_progress"
            run.level_states[next_idx].started_at = time.time()
        else:
            run.state = "completed"
            run.current_level = level_idx

    save_run(run)

    # Notify websocket subscribers about evaluation
    try:
        await event_bus.publish(run.id, {"type": "evaluation", "ts": time.time(), "payload": {"correct": correct, "score": score, "next_level": next_idx}})
    except Exception:
        pass

    return {"correct": correct, "score": score, "next_level": next_idx}


@router.websocket("/ws/training-runs/{run_id}")
async def run_events_ws(websocket: WebSocket, run_id: str):
    await websocket.accept()
    await event_bus.connect(run_id, websocket)
    try:
        while True:
            # Keep connection alive; client can send pings or simple messages
            msg = await websocket.receive_text()
            # echo ping
            if msg == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        await event_bus.disconnect(run_id, websocket)
    except Exception:
        await event_bus.disconnect(run_id, websocket)


@router.post("/training-runs/{run_id}/levels/{level_idx}/hint")
async def take_hint(run_id: str, level_idx: int, hint_idx: int = 0):
    run = load_run(run_id)
    if level_idx >= len(run.level_states):
        raise HTTPException(status_code=404, detail="Level not found")
    ls = run.level_states[level_idx]
    ls.hints.append(f"hint-{hint_idx}")
    # Apply simple penalty (subtract 10 points)
    ls.score = max(0, ls.score - 10)
    save_run(run)
    return {"status": "hint_taken", "hints": ls.hints, "score": ls.score}
