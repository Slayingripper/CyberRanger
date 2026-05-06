from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.training_runs import RUNS_DIR, TrainingRun, load_training_definition, summarize_run
from app.core.auth import (
    AuthenticatedUser,
    create_user,
    list_users,
    require_admin_user,
    update_user,
)
from app.core.ownership import list_vm_records
from app.core.vm_manager import WORK_DIR

router = APIRouter()

DEPLOYMENTS_FILE = os.path.join(WORK_DIR, "deployments.json")


class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    role: str = "user"


class AdminUpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


def _load_deployments() -> Dict[str, Dict[str, Any]]:
    try:
        with open(DEPLOYMENTS_FILE, "r") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_runs() -> list[TrainingRun]:
    runs: list[TrainingRun] = []
    if not os.path.exists(RUNS_DIR):
        return runs

    for filename in os.listdir(RUNS_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(RUNS_DIR, filename), "r") as handle:
                runs.append(TrainingRun(**json.load(handle)))
        except Exception:
            continue
    return sorted(runs, key=lambda item: item.created_at, reverse=True)


def _load_evaluations(user_id: Optional[str] = None) -> list[Dict[str, Any]]:
    evaluations: list[Dict[str, Any]] = []
    for run in _load_runs():
        if user_id and run.owner_id != user_id:
            continue
        try:
            definition = load_training_definition(run.definition_id)
            evaluations.append(summarize_run(run, definition).model_dump())
        except Exception:
            continue
    return evaluations


def _count_active_admins() -> int:
    return sum(1 for user in list_users() if user.role == "admin" and user.is_active)


@router.get("/admin/users")
async def admin_list_users(_admin_user: AuthenticatedUser = Depends(require_admin_user)):
    return [user.model_dump() for user in list_users()]


@router.post("/admin/users")
async def admin_create_user(
    payload: AdminCreateUserRequest,
    _admin_user: AuthenticatedUser = Depends(require_admin_user),
):
    try:
        user = create_user(payload.username, payload.password, payload.full_name, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return user.model_dump()


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    payload: AdminUpdateUserRequest,
    current_admin: AuthenticatedUser = Depends(require_admin_user),
):
    users = {user.id: user for user in list_users()}
    target = users.get(user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    will_remove_admin = target.role == "admin" and (
        payload.role == "user" or payload.is_active is False
    )
    if will_remove_admin and _count_active_admins() <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one active admin user must remain")

    if current_admin.id == user_id and payload.is_active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")

    try:
        updated = update_user(
            user_id,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return updated.model_dump()


@router.get("/admin/training-evaluations")
async def admin_training_evaluations(
    user_id: Optional[str] = Query(default=None),
    _admin_user: AuthenticatedUser = Depends(require_admin_user),
):
    evaluations = _load_evaluations(user_id=user_id)
    return sorted(evaluations, key=lambda item: item.get("created_at") or 0, reverse=True)


@router.get("/admin/dashboard")
async def admin_dashboard(_admin_user: AuthenticatedUser = Depends(require_admin_user)):
    users = list_users()
    runs = _load_runs()
    evaluations = _load_evaluations()
    deployments = _load_deployments()
    vm_records = list_vm_records()
    evaluation_by_run_id = {evaluation.get("run_id"): evaluation for evaluation in evaluations}

    user_summaries = []
    for user in users:
        user_runs = [run for run in runs if run.owner_id == user.id]
        user_evaluations = [evaluation_by_run_id.get(run.id) for run in user_runs if evaluation_by_run_id.get(run.id)]
        last_activity_candidates = [user.last_login_at, user.created_at]
        for run in user_runs:
            last_activity_candidates.append(run.finished_at)
            if run.events:
                last_activity_candidates.extend(event.ts for event in run.events)

        user_summaries.append(
            {
                "user": user.model_dump(),
                "training": {
                    "total_runs": len(user_runs),
                    "running_runs": sum(1 for run in user_runs if run.state == "running"),
                    "completed_runs": sum(1 for run in user_runs if run.state == "completed"),
                    "average_completion_ratio": (
                        sum(float(item.get("completion_ratio") or 0.0) for item in user_evaluations) / len(user_evaluations)
                        if user_evaluations
                        else 0.0
                    ),
                    "average_score": (
                        sum(float(item.get("total_score") or 0.0) for item in user_evaluations) / len(user_evaluations)
                        if user_evaluations
                        else 0.0
                    ),
                },
                "resources": {
                    "deployment_count": sum(1 for dep in deployments.values() if dep.get("owner_id") == user.id),
                    "vm_count": sum(1 for record in vm_records.values() if record.get("owner_id") == user.id),
                },
                "last_activity_at": max(value for value in last_activity_candidates if value is not None),
            }
        )

    return {
        "totals": {
            "users": len(users),
            "active_users": sum(1 for user in users if user.is_active),
            "admins": sum(1 for user in users if user.role == "admin"),
            "training_runs": len(runs),
            "running_training_runs": sum(1 for run in runs if run.state == "running"),
            "deployments": len(deployments),
            "tracked_vms": len(vm_records),
        },
        "users": sorted(user_summaries, key=lambda item: item["user"]["username"]),
        "recent_run_evaluations": sorted(evaluations, key=lambda item: item.get("created_at") or 0, reverse=True)[:25],
    }