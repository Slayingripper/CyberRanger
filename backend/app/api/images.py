from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List
import uuid
import os
import aiofiles
import httpx

router = APIRouter()

IMAGES_DIR = "/app/images"
# We need to know the host path to pass to libvirt
HOST_WORK_DIR = os.environ.get("HOST_WORK_DIR", "/app")
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
    filename: str

class DownloadStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    total: int
    current: int
    filename: str

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
    file_path = os.path.join(IMAGES_DIR, file.filename)
    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):  # Read in 1MB chunks
                await out_file.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    return {"filename": file.filename, "status": "uploaded"}

async def download_file_task(url: str, filename: str, task_id: str):
    file_path = os.path.join(IMAGES_DIR, filename)
    download_tasks[task_id] = {
        "status": "downloading",
        "progress": 0,
        "total": 0,
        "current": 0,
        "filename": filename
    }
    
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with client.stream('GET', url) as response:
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                download_tasks[task_id]["total"] = total_size
                
                downloaded = 0
                async with aiofiles.open(file_path, 'wb') as out_file:
                    async for chunk in response.aiter_bytes():
                        await out_file.write(chunk)
                        downloaded += len(chunk)
                        download_tasks[task_id]["current"] = downloaded
                        if total_size > 0:
                            download_tasks[task_id]["progress"] = int((downloaded / total_size) * 100)
                            
        download_tasks[task_id]["status"] = "completed"
        download_tasks[task_id]["progress"] = 100
    except Exception as e:
        print(f"Download failed: {e}")
        download_tasks[task_id]["status"] = "failed"
        download_tasks[task_id]["error"] = str(e)

@router.post("/images/download")
async def download_image(request: DownloadRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    background_tasks.add_task(download_file_task, request.url, request.filename, task_id)
    return {"status": "download_started", "filename": request.filename, "task_id": task_id}

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
