from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import uuid
import os
import aiofiles

from app.core.image_manager import ensure_image, normalize_source_spec

router = APIRouter()


def _normalize_host_work_dir(host_work_dir: str) -> str:
    if not host_work_dir:
        return "/app"
    if host_work_dir == "/app":
        return host_work_dir
    normalized = os.path.normpath(host_work_dir)
    base = os.path.basename(normalized)
    if base in {"frontend", "backend"}:
        parent = os.path.dirname(normalized)
        if os.path.isabs(parent):
            return parent
    return normalized

IMAGES_DIR = "/app/images"
# We need to know the host path to pass to libvirt
HOST_WORK_DIR = _normalize_host_work_dir(os.environ.get("HOST_WORK_DIR", "/app"))
HOST_IMAGES_DIR = os.path.join(HOST_WORK_DIR, "images")

# Global dictionary to track download progress
download_tasks = {}

class ImageResponse(BaseModel):
    name: str
    size: int
    path: str
    host_path: str

class DownloadRequest(BaseModel):
    url: str
    filename: Optional[str] = None
    min_bytes: Optional[int] = None
    sha256: Optional[str] = None
    archive_sha256: Optional[str] = None
    extract: Optional[Dict[str, Any]] = None

class DownloadStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    total: int
    current: int
    filename: str
    error: Optional[str] = None

@router.get("/images", response_model=List[ImageResponse])
async def list_images():
    images = []
    if not os.path.exists(IMAGES_DIR):
        return []
    
    for f in os.listdir(IMAGES_DIR):
        full_path = os.path.join(IMAGES_DIR, f)
        if os.path.isfile(full_path):
            images.append({
                "name": f,
                "size": os.path.getsize(full_path),
                "path": full_path,
                "host_path": os.path.join(HOST_IMAGES_DIR, f)
            })
    return images

@router.post("/images/upload")
async def upload_image(file: UploadFile = File(...)):
    safe_name = os.path.basename(file.filename or "")
    if not safe_name:
        raise HTTPException(status_code=400, detail="A filename is required")
    file_path = os.path.join(IMAGES_DIR, safe_name)
    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):  # Read in 1MB chunks
                await out_file.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    return {"filename": safe_name, "status": "uploaded"}

async def download_file_task(request_data: Dict[str, Any], task_id: str):
    download_tasks[task_id] = {
        "status": "downloading",
        "progress": 0,
        "total": 0,
        "current": 0,
        "filename": request_data.get("filename") or ""
    }

    try:
        source = normalize_source_spec(request_data)
        final_name = source.get("extract", {}).get("output_filename") if source.get("extract") else None
        download_tasks[task_id]["filename"] = final_name or source["filename"]

        def _progress_cb(event: Dict[str, Any]):
            total = int(event.get("total") or download_tasks[task_id].get("total") or 0)
            current = int(event.get("current") or download_tasks[task_id].get("current") or 0)
            final_display_name = event.get("final_name") or event.get("filename") or download_tasks[task_id].get("filename") or ""
            download_tasks[task_id]["filename"] = final_display_name
            download_tasks[task_id]["total"] = total
            download_tasks[task_id]["current"] = current
            download_tasks[task_id]["progress"] = int((current / total) * 100) if total > 0 else download_tasks[task_id].get("progress", 0)
            if event.get("type") == "extract_start":
                download_tasks[task_id]["status"] = "extracting"
            elif event.get("type") == "extract_complete":
                download_tasks[task_id]["status"] = "completed"
                download_tasks[task_id]["progress"] = 100
            elif event.get("type") == "download_complete":
                download_tasks[task_id]["status"] = "downloaded"

        await ensure_image(source, progress_cb=_progress_cb)
        download_tasks[task_id]["status"] = "completed"
        download_tasks[task_id]["progress"] = 100
    except Exception as e:
        download_tasks[task_id]["status"] = "failed"
        download_tasks[task_id]["error"] = str(e)

@router.post("/images/download")
async def download_image(request: DownloadRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    payload = request.model_dump(exclude_none=True)
    background_tasks.add_task(download_file_task, payload, task_id)
    return {"status": "download_started", "filename": request.filename or os.path.basename(request.url), "task_id": task_id}

@router.delete("/images/{image_name}")
async def delete_image(image_name: str):
    safe_name = os.path.basename(image_name)
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid image name")
    file_path = os.path.join(IMAGES_DIR, safe_name)
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    os.remove(file_path)
    return {"status": "deleted", "name": safe_name}

@router.get("/images/download/{task_id}", response_model=DownloadStatus)
async def get_download_status(task_id: str):
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = download_tasks[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task.get("progress", 0),
        "total": task.get("total", 0),
        "current": task.get("current", 0),
        "filename": task.get("filename", "")
    }
