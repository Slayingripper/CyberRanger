from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Iterable, Optional

from app.core.auth import AuthenticatedUser, STATE_DIR

VM_OWNERSHIP_FILE = os.path.join(STATE_DIR, "vm_ownership.json")
TOPOLOGY_CACHES_FILE = os.path.join(STATE_DIR, "topology_caches.json")

_STATE_LOCK = threading.Lock()


def _ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
            return data if isinstance(data, type(default)) else default
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: str, data: Any) -> None:
    _ensure_state_dir()
    with open(path, "w") as handle:
        json.dump(data, handle, indent=2)


def get_vm_record(vm_name: str) -> Optional[Dict[str, Any]]:
    with _STATE_LOCK:
        owners = _load_json(VM_OWNERSHIP_FILE, {})
        record = owners.get(vm_name)
        return dict(record) if isinstance(record, dict) else None


def list_vm_records() -> Dict[str, Dict[str, Any]]:
    with _STATE_LOCK:
        owners = _load_json(VM_OWNERSHIP_FILE, {})
        return {name: value for name, value in owners.items() if isinstance(value, dict)}


def register_vm(
    vm_name: str,
    current_user: AuthenticatedUser,
    *,
    source: str,
    deployment_id: Optional[str] = None,
    run_id: Optional[str] = None,
    training_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = time.time()
    with _STATE_LOCK:
        owners = _load_json(VM_OWNERSHIP_FILE, {})
        record = owners.get(vm_name) if isinstance(owners.get(vm_name), dict) else {}
        record.update(
            {
                "vm_name": vm_name,
                "owner_id": current_user.id,
                "owner_username": current_user.username,
                "source": source,
                "deployment_id": deployment_id,
                "run_id": run_id,
                "training_id": training_id,
                "created_at": float(record.get("created_at") or now),
                "updated_at": now,
            }
        )
        if metadata:
            record["metadata"] = {**dict(record.get("metadata") or {}), **metadata}
        owners[vm_name] = record
        _save_json(VM_OWNERSHIP_FILE, owners)
        return dict(record)


def register_vm_batch(
    vm_names: Iterable[str],
    current_user: AuthenticatedUser,
    *,
    source: str,
    deployment_id: Optional[str] = None,
    run_id: Optional[str] = None,
    training_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    for vm_name in vm_names:
        register_vm(
            vm_name,
            current_user,
            source=source,
            deployment_id=deployment_id,
            run_id=run_id,
            training_id=training_id,
            metadata=metadata,
        )


def remove_vm(vm_name: str) -> Optional[Dict[str, Any]]:
    with _STATE_LOCK:
        owners = _load_json(VM_OWNERSHIP_FILE, {})
        record = owners.pop(vm_name, None)
        _save_json(VM_OWNERSHIP_FILE, owners)
        return dict(record) if isinstance(record, dict) else None


def can_access_vm(vm_name: str, current_user: AuthenticatedUser) -> bool:
    if current_user.role == "admin":
        return True
    record = get_vm_record(vm_name)
    if not record:
        return False
    return record.get("owner_id") == current_user.id


def filter_vms_for_user(vms: Iterable[Dict[str, Any]], current_user: AuthenticatedUser) -> list[Dict[str, Any]]:
    if current_user.role == "admin":
        return list(vms)

    visible = []
    owners = list_vm_records()
    for vm in vms:
        name = str(vm.get("name") or "")
        if owners.get(name, {}).get("owner_id") == current_user.id:
            visible.append(vm)
    return visible


def get_topology_cache_for_user(current_user: AuthenticatedUser) -> Optional[Dict[str, Any]]:
    with _STATE_LOCK:
        caches = _load_json(TOPOLOGY_CACHES_FILE, {})
        entry = caches.get(current_user.id)
        return dict(entry) if isinstance(entry, dict) else None


def save_topology_cache_for_user(current_user: AuthenticatedUser, topology: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "user_id": current_user.id,
        "username": current_user.username,
        "updated_at": time.time(),
        "topology": topology,
    }
    with _STATE_LOCK:
        caches = _load_json(TOPOLOGY_CACHES_FILE, {})
        caches[current_user.id] = payload
        _save_json(TOPOLOGY_CACHES_FILE, caches)
    return payload
