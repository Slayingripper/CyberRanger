from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import json
import yaml
import os
import uuid
from app.core.vm_manager import WORK_DIR, vm_manager

router = APIRouter()

TRAININGS_DIR = os.path.join(WORK_DIR, "trainings")
os.makedirs(TRAININGS_DIR, exist_ok=True)

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
    vms = topology.get('vms', [])
    results = []
    
    for vm_conf in vms:
        # Sanitize name
        safe_name = "".join(c for c in vm_conf.get('name', 'vm') if c.isalnum())
        name = f"t{training_id[:8]}_l{level_idx}_{safe_name}"
        
        image = vm_conf.get('image')
        image_path = None
        if image:
             image_path = os.path.join(WORK_DIR, "images", image)
             
        try:
            res = vm_manager.create_vm(
                name=name,
                memory_mb=int(vm_conf.get('memory', 1024)),
                vcpus=int(vm_conf.get('vcpus', 1)),
                image_path=image_path,
                network_name="default"
            )
            results.append({"name": name, "status": "created", "details": res})
        except Exception as e:
            results.append({"name": name, "status": "error", "error": str(e)})
        
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
        except Exception:
            pass
            
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
