from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import json
import yaml
import os
import uuid
from app.core.vm_manager import WORK_DIR, vm_manager
from app.core.image_manager import ensure_image
from app.core.event_bus import event_bus
from app.core.provisioning import build_cloud_init_assets, build_cloud_init_from_assets, cloud_init_credentials, ensure_cloud_init_defaults
import time

router = APIRouter()

TRAININGS_DIR = os.path.join(WORK_DIR, "trainings")
os.makedirs(TRAININGS_DIR, exist_ok=True)


def _resolve_training_image_path(image_key: str) -> str:
    images_dir = os.path.join(WORK_DIR, "images")
    image_map = {
        "ubuntu-20.04": "focal-server-cloudimg-amd64.img",
        "kali-linux": "kali-linux-2025.4-qemu-amd64.qcow2",
    }

    if image_key.endswith(".qcow2") or image_key.endswith(".img") or image_key.endswith(".iso"):
        return os.path.join(images_dir, image_key)

    mapped = image_map.get(image_key)
    if mapped:
        return os.path.join(images_dir, mapped)

    return os.path.join(images_dir, f"{image_key}.qcow2")

class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question: str
    type: str  # 'quiz', 'action'
    answer: Optional[str] = None
    verification_script: Optional[str] = None
    hints: Optional[List[str]] = []

class Level(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    topology: Optional[Dict[str, Any]] = None # Full topology object or reference
    tasks: List[Task]

class Training(BaseModel):
    id: Optional[str] = None
    title: str
    description: str
    difficulty: str # 'easy', 'medium', 'hard'
    levels: List[Level]

@router.get("/trainings", response_model=List[Training])
async def list_trainings():
    trainings = []
    if not os.path.exists(TRAININGS_DIR):
        return []
    
    for f in os.listdir(TRAININGS_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(TRAININGS_DIR, f), "r") as file:
                    data = json.load(file)
                    trainings.append(data)
            except Exception as e:
                print(f"Error loading training {f}: {e}")
    return trainings

@router.get("/trainings/{training_id}", response_model=Training)
async def get_training(training_id: str):
    file_path = os.path.join(TRAININGS_DIR, f"{training_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Training not found")
    
    with open(file_path, "r") as file:
        return json.load(file)

@router.post("/trainings", response_model=Training)
async def create_training(training: Training):
    if not training.id:
        training.id = str(uuid.uuid4())
    
    file_path = os.path.join(TRAININGS_DIR, f"{training.id}.json")
    with open(file_path, "w") as file:
        json.dump(training.dict(), file, indent=2)
    
    return training

@router.put("/trainings/{training_id}", response_model=Training)
async def update_training(training_id: str, training: Training):
    file_path = os.path.join(TRAININGS_DIR, f"{training_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Training not found")
    
    training.id = training_id # Ensure ID matches
    with open(file_path, "w") as file:
        json.dump(training.dict(), file, indent=2)
    
    return training

@router.delete("/trainings/{training_id}")
async def delete_training(training_id: str):
    file_path = os.path.join(TRAININGS_DIR, f"{training_id}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
    return {"status": "success"}

@router.post("/trainings/{training_id}/levels/{level_idx}/deploy")
async def deploy_level(training_id: str, level_idx: int):
    # Load training manually since we need dict access
    file_path = os.path.join(TRAININGS_DIR, f"{training_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Training not found")
    
    with open(file_path, "r") as file:
        training = json.load(file)

    if level_idx >= len(training['levels']):
        raise HTTPException(status_code=404, detail="Level not found")
    
    level = training['levels'][level_idx]
    if not level.get('topology'):
        raise HTTPException(status_code=400, detail="No topology defined for this level")
    
    topology = level['topology']
    sources = training.get("sources") or {}
    vms = topology.get('vms', [])
    results = []
    
    for vm_conf in vms:
        # Sanitize name
        safe_name = "".join(c for c in vm_conf.get('name', 'vm') if c.isalnum())
        name = f"t{training_id[:8]}_l{level_idx}_{safe_name}"
        
        image = vm_conf.get('image')
        image_path: Optional[str] = None
        if image:
            src = sources.get(image) or sources.get(os.path.basename(str(image)))
            if src:
                ensured = await ensure_image(src)
                image_path = ensured.container_path
            else:
                image_path = _resolve_training_image_path(str(image))

        cloud_init = None
        if isinstance(vm_conf.get("cloud_init"), dict):
            cloud_init = ensure_cloud_init_defaults(vm_conf.get("cloud_init"))
        else:
            packages, runcmds = build_cloud_init_assets(vm_conf.get("assets") or [])
            if packages or runcmds:
                cloud_init = build_cloud_init_from_assets(vm_conf.get("assets") or [])
             
        try:
            res = vm_manager.create_vm(
                name=name,
                memory_mb=int(vm_conf.get('memory', 1024)),
                vcpus=int(vm_conf.get('vcpus', 1)),
                image_path=image_path,
                cloud_init=cloud_init,
                network_name="default"
            )
            results.append({"name": name, "status": "created", "details": res, "credentials": cloud_init_credentials(cloud_init)})
            try:
                # Start console streaming to EventBus for runs associated with this training/level
                vm_manager.start_console_stream(name, training_id, level_idx)
            except Exception:
                pass
        except Exception as e:
            results.append({"name": name, "status": "error", "error": str(e)})
    # publish event to any matching runs
    await event_bus.publish_by_definition_level(training_id, level_idx, {"type": "deploy", "ts": time.time(), "result": results})

    return {"status": "deployed", "vms": results}

@router.post("/trainings/{training_id}/levels/{level_idx}/destroy")
async def destroy_level(training_id: str, level_idx: int):
    file_path = os.path.join(TRAININGS_DIR, f"{training_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Training not found")
    
    with open(file_path, "r") as file:
        training = json.load(file)

    if level_idx >= len(training['levels']):
        raise HTTPException(status_code=404, detail="Level not found")
    
    level = training['levels'][level_idx]
    if not level.get('topology'):
        return {"status": "no_topology"}
        
    topology = level['topology']
    vms = topology.get('vms', [])
    
    if not vm_manager.conn:
        vm_manager.connect()

    results = []
    for vm_conf in vms:
        safe_name = "".join(c for c in vm_conf.get('name', 'vm') if c.isalnum())
        name = f"t{training_id[:8]}_l{level_idx}_{safe_name}"
        try:
            if vm_manager.conn:
                dom = vm_manager.conn.lookupByName(name)
                if dom.isActive():
                    dom.destroy()
                dom.undefine()
                results.append(name)
                try:
                    vm_manager.stop_console_stream(name)
                except Exception:
                    pass
        except Exception:
            pass
    await event_bus.publish_by_definition_level(training_id, level_idx, {"type": "destroy", "ts": time.time(), "result": results})
    return {"status": "destroyed", "vms": results}

@router.get("/trainings/{training_id}/levels/{level_idx}/status")
async def level_status(training_id: str, level_idx: int):
    file_path = os.path.join(TRAININGS_DIR, f"{training_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Training not found")
    
    with open(file_path, "r") as file:
        training = json.load(file)

    if level_idx >= len(training['levels']):
        raise HTTPException(status_code=404, detail="Level not found")
    
    level = training['levels'][level_idx]
    if not level.get('topology'):
        return {"vms": []}
        
    topology = level['topology']
    vms = topology.get('vms', [])
    vm_statuses = []
    
    domains = vm_manager.list_domains()
    
    for vm_conf in vms:
        safe_name = "".join(c for c in vm_conf.get('name', 'vm') if c.isalnum())
        name = f"t{training_id[:8]}_l{level_idx}_{safe_name}"
        
        found = False
        for d in domains:
            if d['name'] == name:
                vm_statuses.append(d)
                found = True
                break
        if not found:
            vm_statuses.append({"name": name, "state": 0, "state_desc": "shut off"})
            
    return {"vms": vm_statuses}

@router.post("/trainings/upload", response_model=Training)
async def upload_training(file: UploadFile = File(...)):
    try:
        content = await file.read()
        # Support both JSON and YAML
        filename = file.filename or ""
        if filename.endswith('.json'):
            data = json.loads(content)
        else:
            data = yaml.safe_load(content)
        
        # Validate with Pydantic (IDs will be generated if missing)
        training = Training(**data)
        
        if not training.id:
            training.id = str(uuid.uuid4())
            
        file_path = os.path.join(TRAININGS_DIR, f"{training.id}.json")
        with open(file_path, "w") as f:
            json.dump(training.dict(), f, indent=2)
            
        return training
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file format or schema: {str(e)}")


@router.post("/debug/trainings/{training_id}/levels/{level_idx}/console")
async def debug_console_event(training_id: str, level_idx: int, payload: Dict[str, Any]):
    """Debug helper: inject a console event for a training/level to exercise the event bus."""
    msg = payload.get("msg") if isinstance(payload, dict) else None
    if not msg:
        raise HTTPException(status_code=400, detail="msg required")
    try:
        await event_bus.publish_by_definition_level(training_id, level_idx, {"type": "console", "vm": "debug", "msg": msg, "ts": time.time()})
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
