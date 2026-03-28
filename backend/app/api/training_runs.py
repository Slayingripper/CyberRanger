from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
import json
import uuid
import time
from app.core.vm_manager import WORK_DIR
from app.core.event_bus import event_bus

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
    attempts: int = 0
    completed_tasks: List[str] = []


class RunEvent(BaseModel):
    type: str
    ts: float = Field(default_factory=lambda: time.time())
    level_idx: Optional[int] = None
    task_id: Optional[str] = None
    correct: Optional[bool] = None
    score: Optional[int] = None
    detail: Dict[str, Any] = Field(default_factory=dict)


class TrainingRun(BaseModel):
    id: Optional[str] = None
    definition_id: str
    participants: List[str] = []
    current_level: int = 0
    state: str = "running"  # 'running'|'completed'|'stopped'
    level_states: List[LevelState] = []
    created_at: float = Field(default_factory=lambda: time.time())
    finished_at: Optional[float] = None
    events: List[RunEvent] = []


class LevelEvaluationSummary(BaseModel):
    index: int
    title: Optional[str] = None
    description: Optional[str] = None
    status: str
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    attempts: int = 0
    score: int = 0
    hints_used: int = 0
    hints: List[str] = []
    completed_tasks: List[str] = []
    completed_task_count: int = 0
    total_tasks: int = 0
    completion_ratio: float = 0.0
    last_event_at: Optional[float] = None


class TrainingRunEvaluation(BaseModel):
    run_id: str
    definition_id: str
    training_title: Optional[str] = None
    participants: List[str] = []
    state: str
    created_at: float
    finished_at: Optional[float] = None
    total_duration_seconds: Optional[float] = None
    current_level: int
    completed_levels: int = 0
    total_levels: int = 0
    completion_ratio: float = 0.0
    total_score: int = 0
    total_attempts: int = 0
    total_hints_used: int = 0
    level_summaries: List[LevelEvaluationSummary] = []
    activity_log: List[RunEvent] = []


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


def load_training_definition(definition_id: str) -> Dict[str, Any]:
    def_path = os.path.join(WORK_DIR, "trainings", f"{definition_id}.json")
    if not os.path.exists(def_path):
        raise HTTPException(status_code=404, detail="Training definition not found")
    with open(def_path, "r") as f:
        return json.load(f)


def record_event(run: TrainingRun, event_type: str, **kwargs: Any) -> None:
    run.events.append(RunEvent(type=event_type, **kwargs))


def summarize_run(run: TrainingRun, definition: Dict[str, Any]) -> TrainingRunEvaluation:
    now = time.time()
    levels = definition.get("levels", [])
    level_summaries: List[LevelEvaluationSummary] = []

    for idx, level_state in enumerate(run.level_states):
        level_meta = levels[idx] if idx < len(levels) else {}
        tasks = level_meta.get("tasks", []) if isinstance(level_meta, dict) else []
        total_tasks = len(tasks)
        completed_task_ids = list(dict.fromkeys(level_state.completed_tasks or []))
        ended_at = level_state.ended_at
        if ended_at is None and level_state.status == "in_progress":
            ended_at = now
        duration_seconds = None
        if level_state.started_at is not None and ended_at is not None:
            duration_seconds = max(0.0, ended_at - level_state.started_at)

        last_event_at = None
        for event in reversed(run.events):
            if event.level_idx == idx:
                last_event_at = event.ts
                break

        completed_task_count = len(completed_task_ids)
        completion_ratio = 0.0
        if total_tasks > 0:
            completion_ratio = min(1.0, completed_task_count / total_tasks)
        elif level_state.status == "completed":
            completion_ratio = 1.0

        level_summaries.append(
            LevelEvaluationSummary(
                index=idx,
                title=level_meta.get("title") if isinstance(level_meta, dict) else None,
                description=level_meta.get("description") if isinstance(level_meta, dict) else None,
                status=level_state.status,
                started_at=level_state.started_at,
                ended_at=level_state.ended_at,
                duration_seconds=duration_seconds,
                attempts=level_state.attempts,
                score=level_state.score,
                hints_used=len(level_state.hints or []),
                hints=list(level_state.hints or []),
                completed_tasks=completed_task_ids,
                completed_task_count=completed_task_count,
                total_tasks=total_tasks,
                completion_ratio=completion_ratio,
                last_event_at=last_event_at,
            )
        )

    finished_at = run.finished_at
    effective_end = finished_at or now
    total_duration_seconds = max(0.0, effective_end - run.created_at) if run.created_at else None
    completed_levels = sum(1 for level in run.level_states if level.status == "completed")
    total_levels = len(run.level_states)
    completion_ratio = (completed_levels / total_levels) if total_levels else 0.0

    return TrainingRunEvaluation(
        run_id=run.id or "",
        definition_id=run.definition_id,
        training_title=definition.get("title"),
        participants=list(run.participants or []),
        state=run.state,
        created_at=run.created_at,
        finished_at=run.finished_at,
        total_duration_seconds=total_duration_seconds,
        current_level=run.current_level,
        completed_levels=completed_levels,
        total_levels=total_levels,
        completion_ratio=completion_ratio,
        total_score=sum(level.score for level in run.level_states),
        total_attempts=sum(level.attempts for level in run.level_states),
        total_hints_used=sum(len(level.hints or []) for level in run.level_states),
        level_summaries=level_summaries,
        activity_log=list(run.events),
    )


@router.post("/training-runs", response_model=TrainingRun)
async def create_run(definition_id: str, participants: Optional[List[str]] = None):
    # ensure definition exists
    definition = load_training_definition(definition_id)

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

    record_event(run, "run_started", detail={"participants": list(run.participants or [])})
    if run.level_states:
        record_event(run, "level_started", level_idx=0)

    save_run(run)
    return run


@router.get("/training-runs/{run_id}", response_model=TrainingRun)
async def get_run(run_id: str):
    return load_run(run_id)


@router.get("/training-runs/{run_id}/evaluation", response_model=TrainingRunEvaluation)
async def get_run_evaluation(run_id: str):
    run = load_run(run_id)
    definition = load_training_definition(run.definition_id)
    return summarize_run(run, definition)


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
    definition = load_training_definition(run.definition_id)

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
    ls.attempts += 1
    ls.score = max(ls.score, score)
    record_event(
        run,
        "task_submitted",
        level_idx=level_idx,
        task_id=payload.task_id,
        correct=correct,
        score=score,
        detail={"answer_provided": bool((payload.answer or "").strip())},
    )

    if correct:
        ls.ended_at = time.time()
        ls.status = "completed"
        if payload.task_id not in ls.completed_tasks:
            ls.completed_tasks.append(payload.task_id)
        record_event(run, "level_completed", level_idx=level_idx, task_id=payload.task_id, correct=True, score=score)
    else:
        ls.status = "in_progress"

    # advance to next level if correct
    next_idx = None
    if correct:
        next_idx = level_idx + 1
        # mark completed and set next in_progress if exists
        if next_idx < len(run.level_states):
            run.current_level = next_idx
            run.level_states[next_idx].status = "in_progress"
            run.level_states[next_idx].started_at = time.time()
            record_event(run, "level_started", level_idx=next_idx)
        else:
            run.state = "completed"
            run.current_level = level_idx
            run.finished_at = time.time()
            record_event(run, "run_completed", level_idx=level_idx)

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
    record_event(run, "hint_taken", level_idx=level_idx, detail={"hint_idx": hint_idx})
    save_run(run)
    return {"status": "hint_taken", "hints": ls.hints, "score": ls.score}


@router.post("/training-runs/{run_id}/stop")
async def stop_run(run_id: str):
    run = load_run(run_id)
    if run.state != "stopped":
        run.state = "stopped"
        run.finished_at = time.time()
        if 0 <= run.current_level < len(run.level_states):
            ls = run.level_states[run.current_level]
            if ls.status == "in_progress":
                ls.status = "pending"
            if ls.ended_at is None:
                ls.ended_at = run.finished_at
        record_event(run, "run_stopped", level_idx=run.current_level)
        save_run(run)

    try:
        await event_bus.publish(run.id, {"type": "stopped", "ts": time.time(), "payload": {"run_id": run_id}})
    except Exception:
        pass

    return {"status": "stopped", "run": run}
