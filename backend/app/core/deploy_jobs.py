import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class DeployJob:
    id: str
    created_at: float = field(default_factory=lambda: time.time())
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    status: str = "queued"  # queued|running|completed|failed
    message: str = ""
    progress: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None


_jobs: Dict[str, DeployJob] = {}
_jobs_lock = asyncio.Lock()


def new_job(initial_progress: Optional[Dict[str, Any]] = None) -> DeployJob:
    job_id = str(uuid.uuid4())
    job = DeployJob(id=job_id)
    if initial_progress is not None:
        job.progress = initial_progress
    _jobs[job_id] = job
    return job


async def get_job(job_id: str) -> Optional[DeployJob]:
    async with _jobs_lock:
        return _jobs.get(job_id)


async def update_job(job_id: str, **kwargs: Any) -> Optional[DeployJob]:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        for k, v in kwargs.items():
            setattr(job, k, v)
        return job


async def update_progress(job_id: str, patch: Dict[str, Any]) -> Optional[DeployJob]:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        # shallow merge
        job.progress = {**(job.progress or {}), **patch}
        return job


async def set_progress_path(job_id: str, path: str, value: Any) -> Optional[DeployJob]:
    """Set nested progress key like 'downloads.file.iso.current'."""
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        cur = job.progress
        parts = [p for p in path.split(".") if p]
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
        return job
