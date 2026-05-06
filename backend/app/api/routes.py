from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.core.vm_manager import vm_manager, WORK_DIR
import os
import glob
import json
import logging
from app.core.image_manager import ensure_image
import asyncio
import time
import hashlib
import uuid
from app.core.deploy_automation import execute_automation_steps, normalize_automation_steps
from app.core.provisioning import build_cloud_init_from_assets, cloud_init_credentials

from app.core.deploy_jobs import new_job, get_job, update_job, update_progress, set_progress_path
from app.core.auth import AuthenticatedUser, require_admin_user, require_authenticated_user
from app.core.ownership import (
    can_access_vm,
    filter_vms_for_user,
    get_topology_cache_for_user,
    get_vm_record,
    register_vm,
    remove_vm,
    save_topology_cache_for_user,
)
import xml.etree.ElementTree as ET

router = APIRouter()
logger = logging.getLogger(__name__)

TOPOLOGY_CACHE_FILE = os.path.join(WORK_DIR, "topology_cache.json")
DEPLOYMENTS_FILE = os.path.join(WORK_DIR, "deployments.json")
CREDS_CACHE_PATH = os.path.join(WORK_DIR, "data", "vm_credentials.json")

def _load_topology_cache():
    if os.path.exists(TOPOLOGY_CACHE_FILE):
        try:
            with open(TOPOLOGY_CACHE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning("Topology cache contains invalid JSON: %s", e)
            return None
        except OSError as e:
            logger.warning("Failed to read topology cache: %s", e)
            return None
    return None

def _save_topology_cache(data):
    with open(TOPOLOGY_CACHE_FILE, "w") as f:
        json.dump(data, f)


def _load_creds_cache():
    try:
        with open(CREDS_CACHE_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _load_deployments():
    if os.path.exists(DEPLOYMENTS_FILE):
        try:
            with open(DEPLOYMENTS_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning("Deployments file contains invalid JSON: %s", e)
            return {}
        except OSError as e:
            logger.warning("Failed to read deployments file: %s", e)
            return {}
    return {}

def _save_deployments(data):
    with open(DEPLOYMENTS_FILE, "w") as f:
        json.dump(data, f)


def _deployment_visible_to_user(deployment: Dict[str, Any], current_user: AuthenticatedUser) -> bool:
    if current_user.role == "admin":
        return True
    return deployment.get("owner_id") == current_user.id


def _filter_deployments_for_user(deployments: Dict[str, Any], current_user: AuthenticatedUser) -> Dict[str, Any]:
    if current_user.role == "admin":
        return deployments
    return {
        dep_id: dep
        for dep_id, dep in deployments.items()
        if isinstance(dep, dict) and _deployment_visible_to_user(dep, current_user)
    }


def _require_vm_access(name: str, current_user: AuthenticatedUser) -> None:
    if not can_access_vm(name, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this virtual machine")


def _sanitize_vm_label(label: str, fallback: str) -> str:
    safe_name = "".join(c for c in label if c.isalnum() or c in ("-", "_")).strip()
    return safe_name or fallback


def _scoped_vm_name(node_label: str, node_id: str, deployment_prefix: Optional[str]) -> str:
    safe_name = _sanitize_vm_label(node_label, f"vm_{node_id}")
    if deployment_prefix:
        return f"{deployment_prefix}_{safe_name}_{node_id}"
    return f"{safe_name}_{node_id}"

@router.get("/topology/cache")
async def get_topology_cache(current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    entry = get_topology_cache_for_user(current_user)
    return {"topology": (entry or {}).get("topology") or {}, "updated_at": (entry or {}).get("updated_at")}

@router.post("/topology/cache")
async def save_topology_cache(topology: Dict[str, Any], current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    saved = save_topology_cache_for_user(current_user, topology)
    return {"status": "cached", "updated_at": saved["updated_at"]}

@router.get("/deployments")
async def get_deployments(current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    deployments = _load_deployments()
    try:
        vm_manager.cleanup_unused_networks()
    except Exception as e:
        logger.warning("Failed to cleanup unused networks: %s", e)
    
    try:
        current_vms = {vm['name'] for vm in vm_manager.list_domains()}
    except Exception as e:
        logger.error("Failed to list domains: %s", e)
        return deployments

    ids_to_remove = []
    
    for dep_id, dep in deployments.items():
        # Check if any of the deployment's VMs still exist
        dep_vms = dep.get("vms", [])
        if not dep_vms:
             # Empty deployment record?
             ids_to_remove.append(dep_id)
             continue
             
        # Check if *any* of the VMs belonging to this deployment currently exist
        any_vm_exists = any(vm_name in current_vms for vm_name in dep_vms)
        
        if not any_vm_exists:
            ids_to_remove.append(dep_id)
    
    if ids_to_remove:
        for dep_id in ids_to_remove:
            del deployments[dep_id]
        _save_deployments(deployments)

    return _filter_deployments_for_user(deployments, current_user)


@router.post("/networks/cleanup")
async def cleanup_networks(_admin_user: AuthenticatedUser = Depends(require_admin_user)):
    try:
        removed = vm_manager.cleanup_unused_networks()
        return {"status": "cleaned", "removed": removed, "count": len(removed)}
    except Exception as e:
        logger.exception("Failed to cleanup networks")
        raise HTTPException(status_code=500, detail="Failed to cleanup networks")

# In-memory cache for last topology (best-effort; resets on restart)
_TOPOLOGY_CACHE: Dict[str, Any] = {}
_TOPOLOGY_CACHE_TS: Optional[float] = None


def _normalize_host_work_dir(host_work_dir: str) -> str:
    if not host_work_dir:
        return WORK_DIR
    if host_work_dir == WORK_DIR:
        return host_work_dir
    normalized = os.path.normpath(host_work_dir)
    base = os.path.basename(normalized)
    if base in {"frontend", "backend"}:
        parent = os.path.dirname(normalized)
        if os.path.isabs(parent):
            return parent
    return normalized


def _host_images_dir() -> str:
    host_work_dir = _normalize_host_work_dir(os.environ.get("HOST_WORK_DIR", WORK_DIR))
    return os.path.join(host_work_dir, "images")


def _host_path_for_container_image(container_image_path: str) -> str:
    return os.path.join(_host_images_dir(), os.path.basename(container_image_path))


def _resolve_image_path(image_key: str) -> str:
    images_dir = os.path.join(WORK_DIR, "images")

    image_map = {
        "ubuntu-20.04": "ubuntu-20.04-server-cloudimg-amd64.img",
        "windows-10": "windows10.qcow2",
        "gateway": "vyos.qcow2",
        "security-onion": "securityonion.iso",
        "opnsense": "opnsense.img",
        "openwrt": "openwrt.qcow2",
        "contiki-ng": "contiki-ng.qcow2",
    }

    def _pick_best_match(paths: List[str]) -> Optional[str]:
        if not paths:
            return None
        scored = []
        for p in paths:
            try:
                size = os.path.getsize(p)
                mtime = os.path.getmtime(p)
            except OSError:
                continue
            scored.append((size, mtime, p))
        if not scored:
            return None
        # Prefer the largest/newest file (helps avoid tiny placeholder images).
        scored.sort(reverse=True)
        return scored[0][2]

    # Prefer explicit filename
    if image_key.endswith(".qcow2") or image_key.endswith(".img") or image_key.endswith(".iso"):
        candidate = os.path.join(images_dir, image_key)
        return candidate

    candidates: List[str] = []

    # Prefer mapped filename (as a candidate, but don't hard-pin if other variants exist)
    mapped = image_map.get(image_key)
    if mapped:
        candidate = os.path.join(images_dir, mapped)
        if os.path.exists(candidate):
            candidates.append(candidate)

    # Fallbacks for common variants
    patterns = []
    if image_key == "kali-linux":
        patterns = ["kali-linux-*-qemu-amd64.7z", "kali-linux-*-qemu-amd64.qcow2", "kali*.qcow2", "kali*.7z"]
    elif image_key == "ubuntu-20.04":
        patterns = ["ubuntu-20.04-server-cloudimg-amd64.img", "focal-server-cloudimg-amd64*.img", "ubuntu*20.04*cloudimg*amd64*.img"]
    elif image_key == "windows-10":
        patterns = ["windows10.qcow2", "windows*.qcow2"]
    elif image_key == "gateway":
        patterns = ["vyos.qcow2", "vyos*.qcow2"]
    elif image_key in ("security-onion", "securityonion"):
        patterns = ["securityonion*.iso", "security-onion*.iso", "securityonion.iso"]
    elif image_key in ("opnsense", "opn-sense"):
        patterns = ["opnsense.img", "OPNsense-*-vga-amd64.img", "opnsense*.img", "OPNsense-*.img"]
    elif image_key in ("openwrt", "open-wrt"):
        patterns = ["openwrt*.qcow2", "openwrt*.img", "openwrt*.iso"]
    elif image_key in ("contiki-ng", "contiki"):
        patterns = ["contiki*.qcow2", "contiki*.img"]
    else:
        patterns = [f"{image_key}.qcow2", f"{image_key}.img", f"{image_key}.7z"]

    for pat in patterns:
        candidates.extend(glob.glob(os.path.join(images_dir, pat)))

    best = _pick_best_match(list(dict.fromkeys(candidates)))
    if best:
        return best

    # Default
    return os.path.join(images_dir, f"{image_key}.qcow2")


def _slugify(value: str) -> str:
    s = "".join((c.lower() if c.isalnum() else "-") for c in (value or ""))
    s = "-".join([p for p in s.split("-") if p])
    return s or "topology"


def _connected_components(node_ids: List[str], edges: List[Any]) -> Dict[str, int]:
    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for e in edges or []:
        if e.source in adj and e.target in adj:
            adj[e.source].append(e.target)
            adj[e.target].append(e.source)

    comp: Dict[str, int] = {}
    cid = 0
    for nid in node_ids:
        if nid in comp:
            continue
        stack = [nid]
        comp[nid] = cid
        while stack:
            cur = stack.pop()
            for nxt in adj.get(cur, []):
                if nxt not in comp:
                    comp[nxt] = cid
                    stack.append(nxt)
        cid += 1
    return comp


def _is_opnsense_node(node: Any) -> bool:
    try:
        img = (node.config.image or "").lower()
        lbl = (node.label or "").lower()
        return ("opnsense" in img) or ("opnsense" in lbl)
    except AttributeError:
        return False


def _normalize_network_mode(mode: Optional[str]) -> str:
    normalized = (mode or "nat").strip().lower()
    if normalized not in {"nat", "isolated"}:
        raise ValueError("Network mode must be either 'nat' or 'isolated'")
    return normalized


def _normalize_vlan_id(vlan_id: Optional[int]) -> Optional[int]:
    if vlan_id in (None, ""):
        return None
    try:
        normalized = int(vlan_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("VLAN ID must be an integer between 1 and 4094") from exc
    if normalized < 1 or normalized > 4094:
        raise ValueError("VLAN ID must be between 1 and 4094")
    return normalized


def _edge_has_custom_network(edge: Any) -> bool:
    config = getattr(edge, "config", None)
    if config is None:
        return False
    segment = (getattr(config, "segment", None) or "").strip()
    mode = (getattr(config, "mode", None) or "nat").strip().lower()
    vlan_id = getattr(config, "vlan_id", None)
    return bool(segment or vlan_id is not None or mode != "nat")


def _append_network_assignment(node_networks: Dict[str, List[str]], node_id: str, network_name: str) -> None:
    assigned = node_networks.setdefault(node_id, [])
    if network_name not in assigned:
        assigned.append(network_name)


def _ensure_planned_network(network_name: str, mode: str, seed: str, used_thirds: set[int]) -> None:
    bridge_hash = hashlib.sha1(network_name.encode("utf-8")).hexdigest()[:10]
    bridge = f"cr{bridge_hash}"[:15]
    if mode == "isolated":
        ok = vm_manager.ensure_isolated_network(network_name, bridge)
        if not ok and not _reuse_existing_network(network_name):
            raise RuntimeError(f"Failed to create isolated network {network_name}")
        return

    third = _pick_nat_third(seed, used_thirds)
    gateway = f"192.168.{third}.1"
    ok = vm_manager.ensure_network(network_name, bridge, gateway)
    if not ok and not _reuse_existing_network(network_name):
        raise RuntimeError(f"Failed to create network {network_name}")


def _plan_topology_network_assignments(topology: "TopologyDeployRequest", slug: str) -> Dict[str, List[str]]:
    node_networks: Dict[str, List[str]] = {node.id: [] for node in topology.nodes}
    used_thirds = _active_nat_third_octets()
    explicit_node_ids: set[str] = set()
    explicit_networks: Dict[str, str] = {}
    implicit_edges: List[TopologyEdge] = []

    for edge in topology.edges:
        if not _edge_has_custom_network(edge):
            implicit_edges.append(edge)
            continue

        config = edge.config or TopologyEdgeConfig()
        mode = _normalize_network_mode(config.mode)
        vlan_id = _normalize_vlan_id(config.vlan_id)
        segment_base = (config.segment or "").strip() or f"{edge.source}-{edge.target}"
        segment_slug = _slugify(segment_base)
        if vlan_id is not None:
            segment_slug = f"{segment_slug}-vlan{vlan_id}"

        explicit_key = f"{mode}:{segment_slug}"
        network_name = explicit_networks.get(explicit_key)
        if not network_name:
            network_name = f"cyberange-{slug}-seg-{segment_slug}"
            _ensure_planned_network(network_name, mode, f"{slug}:{explicit_key}", used_thirds)
            explicit_networks[explicit_key] = network_name

        for node_id in (edge.source, edge.target):
            if node_id in node_networks:
                _append_network_assignment(node_networks, node_id, network_name)
                explicit_node_ids.add(node_id)

    implicit_edge_node_ids = {
        node_id
        for edge in implicit_edges
        for node_id in (edge.source, edge.target)
        if node_id in node_networks
    }
    component_node_ids = [
        node.id
        for node in topology.nodes
        if node.id in implicit_edge_node_ids or node.id not in explicit_node_ids
    ]

    if not component_node_ids:
        return {node_id: nets for node_id, nets in node_networks.items() if nets}

    comp_map = _connected_components(component_node_ids, implicit_edges)
    if not comp_map:
        return {node_id: nets for node_id, nets in node_networks.items() if nets}

    opnsense_nodes = {node.id for node in topology.nodes if _is_opnsense_node(node)}
    max_comp = max(comp_map.values())
    for cid in range(0, max_comp + 1):
        members = [node_id for node_id, component_id in comp_map.items() if component_id == cid]
        has_opnsense = any(node_id in opnsense_nodes for node_id in members)
        if has_opnsense:
            lan_name = f"cyberange-{slug}-lan-c{cid}"
            _ensure_planned_network(lan_name, "isolated", f"{slug}:lan:{cid}", used_thirds)
            for node_id in members:
                if node_id in opnsense_nodes:
                    _append_network_assignment(node_networks, node_id, "default")
                _append_network_assignment(node_networks, node_id, lan_name)
            continue

        net_name = f"cyberange-{slug}-c{cid}"
        _ensure_planned_network(net_name, "nat", f"{slug}:c{cid}", used_thirds)
        for node_id in members:
            _append_network_assignment(node_networks, node_id, net_name)

    return {node_id: nets for node_id, nets in node_networks.items() if nets}


def _reuse_existing_network(net_name: str) -> bool:
    """Best-effort: if a network with `net_name` already exists, ensure it's active/autostart.

    Returns True if the existing network is found (and ensured active), else False.
    """
    try:
        vm_manager.connect()
        conn = vm_manager.conn
        if conn is None:
            return False
        net = conn.networkLookupByName(net_name)
        if net is not None:
            if net.isActive() != 1:
                net.create()
            net.setAutostart(True)
            return True
    except Exception as e:
        if "not found" in str(e).lower() or "does not exist" in str(e).lower():
            logger.debug("Network %s not found: %s", net_name, e)
        else:
            logger.warning("Error checking existing network %s: %s", net_name, e)
    return False


def _active_nat_third_octets() -> set[int]:
    """Return third octets (X) for active libvirt NAT networks using 192.168.X.0/24."""
    thirds: set[int] = set()
    try:
        vm_manager.connect()
        conn = vm_manager.conn
        if conn is None:
            return thirds
        for net_name in conn.listNetworks() or []:
            try:
                net = conn.networkLookupByName(net_name)
                xml = net.XMLDesc(0)
                root = ET.fromstring(xml)
                ip_el = root.find("./ip")
                if ip_el is None:
                    continue
                addr = (ip_el.get("address") or "").strip()
                parts = addr.split(".")
                if len(parts) == 4 and parts[0] == "192" and parts[1] == "168":
                    thirds.add(int(parts[2]))
            except ET.ParseError as e:
                logger.warning("Failed to parse network XML for %s: %s", net_name, e)
            except Exception as e:
                logger.debug("Skipping network %s: %s", net_name, e)
    except Exception as e:
        logger.warning("Failed to list active NAT networks: %s", e)
    return thirds


def _pick_nat_third(seed: str, used: set[int]) -> int:
    """Pick a free third octet in [10, 249] based on a stable seed."""
    # Avoid very small subnets and leave room for cid probing.
    start = 10 + (int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:4], 16) % 240)  # 10..249
    for off in range(0, 240):
        third = 10 + ((start - 10 + off) % 240)
        if third not in used:
            used.add(third)
            return third
    raise RuntimeError("No free NAT subnets available (192.168.10.0/24..192.168.249.0/24)")

class VMCreateRequest(BaseModel):
    name: str
    memory_mb: int
    vcpus: int
    image_path: Optional[str] = None
    iso_path: Optional[str] = None
    cloud_init: Optional[dict] = None # {username, password, packages}
    network_name: Optional[str] = None
    network_names: Optional[List[str]] = None

class VMResponse(BaseModel):
    id: int
    name: str
    uuid: str
    state: int
    memory: int
    vcpus: int
    vnc_port: Optional[str]
    websocket_port: Optional[int] = None
    credentials: Optional[Dict[str, str]] = None


class VMInterfaceInfo(BaseModel):
    name: Optional[str] = None
    mac: Optional[str] = None
    network: Optional[str] = None
    ips: List[str] = []


class VMRuntimeInfo(BaseModel):
    name: str
    interfaces: List[VMInterfaceInfo] = []

@router.get("/vms", response_model=List[VMResponse])
async def get_vms(current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    try:
        creds_cache = _load_creds_cache()
        vms = vm_manager.list_domains()
        for vm in vms:
            vm["credentials"] = creds_cache.get(vm.get("name"))
        return filter_vms_for_user(vms, current_user)
    except Exception as e:
        logger.exception("Failed to list VMs")
        raise HTTPException(status_code=500, detail="Failed to list VMs")


@router.get("/runtime/vms", response_model=List[VMRuntimeInfo])
async def get_runtime_vms(current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    try:
        vms = vm_manager.list_domains_with_interfaces()
        return filter_vms_for_user(vms, current_user)
    except Exception as e:
        logger.exception("Failed to list runtime VMs")
        raise HTTPException(status_code=500, detail="Failed to list runtime VMs")

@router.post("/vms")
async def create_vm(vm: VMCreateRequest, current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    if not vm.image_path and not vm.iso_path:
        raise HTTPException(status_code=400, detail="Either image_path or iso_path must be provided")

    existing_record = get_vm_record(vm.name)
    if existing_record and not can_access_vm(vm.name, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A virtual machine with this name belongs to another user")
    existing_domain_names = {existing_vm.get("name") for existing_vm in vm_manager.list_domains()}
    if vm.name in existing_domain_names and not can_access_vm(vm.name, current_user) and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A virtual machine with this name already exists")
        
    result = vm_manager.create_vm(
        vm.name, 
        vm.memory_mb, 
        vm.vcpus, 
        image_path=vm.image_path, 
        iso_path=vm.iso_path,
        cloud_init=vm.cloud_init,
        network_name=vm.network_name or "default",
        network_names=vm.network_names,
    )
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    creds = cloud_init_credentials(vm.cloud_init)
    if creds:
        creds_cache = _load_creds_cache()
        creds_cache[vm.name] = creds
        os.makedirs(os.path.dirname(CREDS_CACHE_PATH), exist_ok=True)
        with open(CREDS_CACHE_PATH, "w") as f:
            json.dump(creds_cache, f)
        result["credentials"] = creds
    register_vm(
        vm.name,
        current_user,
        source="manual",
        metadata={
            "network_name": vm.network_name or "default",
            "network_names": vm.network_names or [],
            "image_path": vm.image_path,
            "iso_path": vm.iso_path,
        },
    )
    return result

@router.post("/vms/{name}/start")
async def start_vm(name: str, current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    _require_vm_access(name, current_user)
    if vm_manager.start_vm(name):
        return {"status": "started"}
    raise HTTPException(status_code=404, detail="VM not found or could not be started")

@router.post("/vms/{name}/stop")
async def stop_vm(name: str, current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    _require_vm_access(name, current_user)
    if vm_manager.stop_vm(name):
        return {"status": "stopped"}
    raise HTTPException(status_code=404, detail="VM not found or could not be stopped")

@router.delete("/vms/{name}")
async def delete_vm(name: str, current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    _require_vm_access(name, current_user)
    if vm_manager.delete_vm(name):
        creds_cache = _load_creds_cache()
        if name in creds_cache:
            del creds_cache[name]
            os.makedirs(os.path.dirname(CREDS_CACHE_PATH), exist_ok=True)
            with open(CREDS_CACHE_PATH, "w") as f:
                json.dump(creds_cache, f)
            remove_vm(name)
        try:
            vm_manager.cleanup_unused_networks()
        except Exception as e:
            logger.warning("Failed to cleanup networks after VM deletion: %s", e)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="VM not found or could not be deleted")


@router.post("/topology/cache")
async def cache_topology(payload: Dict[str, Any], current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    global _TOPOLOGY_CACHE, _TOPOLOGY_CACHE_TS
    _TOPOLOGY_CACHE = payload or {}
    _TOPOLOGY_CACHE_TS = time.time()
    saved = save_topology_cache_for_user(current_user, payload or {})
    return {"status": "cached", "updated_at": saved["updated_at"]}


@router.get("/topology/cache")
async def get_cached_topology(current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    entry = get_topology_cache_for_user(current_user)
    return {"topology": (entry or {}).get("topology") or {}, "updated_at": (entry or {}).get("updated_at")}

class TopologyNodeConfig(BaseModel):
    image: str
    cpu: int
    ram: int
    assets: List[Dict[str, str]]
    # Optional automation hooks for ISO installs (e.g., send keys/text).
    automation: Optional[Dict[str, Any]] = None
    # Optional user-specified credentials (override auto-generated ones)
    username: Optional[str] = None
    password: Optional[str] = None

class Position(BaseModel):
    x: float
    y: float

class TopologyNode(BaseModel):
    id: str
    label: str
    config: TopologyNodeConfig
    # Optional position for visualization restoration
    position: Optional[Position] = None

class TopologyEdgeConfig(BaseModel):
    segment: Optional[str] = None
    mode: str = "nat"
    vlan_id: Optional[int] = None

class TopologyEdge(BaseModel):
    id: Optional[str] = None
    source: str
    target: str
    config: Optional[TopologyEdgeConfig] = None

class ScenarioConfig(BaseModel):
    name: str
    team: str
    objective: str
    difficulty: str
    # Optional stable prefix for libvirt network names. If omitted, we auto-randomize per deploy.
    network_prefix: Optional[str] = None
    # Optional mapping of image keys/filenames -> download source
    # Example:
    #   sources: {
    #     "xubuntu-24.04.3-minimal-amd64.iso": "https://.../xubuntu.iso",
    #     "kali-linux": {"url": "https://.../kali.iso", "filename": "kali.iso"}
    #   }
    sources: Optional[Dict[str, object]] = None


def _network_slug(scenario: Optional[ScenarioConfig], suffix: Optional[str]) -> str:
    """Generate a network namespace slug.

    - If `scenario.network_prefix` is set: use it as-is (slugified) for stable names.
    - Otherwise: append a short suffix so repeated deploys don't collide.
    """
    base = None
    if scenario is not None:
        base = (scenario.network_prefix or scenario.name or "").strip()
    if not base:
        base = "topology"

    slug_base = _slugify(base)
    if scenario is not None and (scenario.network_prefix or "").strip():
        return slug_base
    suf = (suffix or uuid.uuid4().hex[:8]).strip()
    suf = "".join([c for c in suf.lower() if c.isalnum()])[:8] or uuid.uuid4().hex[:8]
    return f"{slug_base}-{suf}"

class TopologyDeployRequest(BaseModel):
    scenario: Optional[ScenarioConfig] = None
    nodes: List[TopologyNode]
    edges: List[TopologyEdge]

@router.post("/topology/deploy")
async def deploy_topology(topology: TopologyDeployRequest, current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    results = []
    creds_cache = _load_creds_cache()
    deployment_prefix = f"dep{uuid.uuid4().hex[:8]}"
    
    if topology.scenario:
        logger.info(
            "Deploying Scenario: %s (%s) for %s team",
            topology.scenario.name,
            topology.scenario.difficulty,
            topology.scenario.team
        )
    
    slug = _network_slug(topology.scenario, suffix=uuid.uuid4().hex[:8])
    try:
        node_networks = _plan_topology_network_assignments(topology, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for node in topology.nodes:
        cloud_init = build_cloud_init_from_assets(node.config.assets)
        
        # If scenario provides a source for this image, always ensure it (cached) so we don't
        # accidentally boot from an older/incorrect local file.
        source = None
        image_path = None
        if topology.scenario and topology.scenario.sources:
            # Allow referencing either by the node image key (e.g. 'kali-linux') or by filename
            resolved_guess = _resolve_image_path(node.config.image)
            source = topology.scenario.sources.get(node.config.image) or topology.scenario.sources.get(os.path.basename(resolved_guess))

        if source:
            try:
                ensured = await ensure_image(source)
                image_path = ensured.container_path
            except Exception as e:
                results.append({"status": "error", "node": node.label, "message": f"Failed to ensure image: {e}"})
                continue
        else:
            image_path = _resolve_image_path(node.config.image)
            if not os.path.exists(image_path):
                results.append(
                    {
                        "status": "error",
                        "node": node.label,
                        "message": (
                            f"Missing base image: {os.path.basename(image_path)}. "
                            f"Add it to ./images or provide scenario.sources for auto-download."
                        ),
                    }
                )
                continue
        
        try:
            vm_name = _scoped_vm_name(node.label, node.id, deployment_prefix)
            nets = node_networks.get(node.id) or ["default"]
            
            res = vm_manager.create_vm(
                name=vm_name,
                memory_mb=node.config.ram,
                vcpus=node.config.cpu,
                image_path=None if image_path.lower().endswith(".iso") else image_path,
                iso_path=_host_path_for_container_image(image_path) if image_path.lower().endswith(".iso") else None,
                cloud_init=None if image_path.lower().endswith(".iso") else cloud_init,
                network_names=nets,
            )
            creds = None if image_path.lower().endswith(".iso") else cloud_init_credentials(cloud_init)
            if creds and res.get("status") == "success":
                creds_cache[vm_name] = creds
            if res.get("status") == "success":
                register_vm(
                    vm_name,
                    current_user,
                    source="topology",
                    metadata={"scenario_name": topology.scenario.name if topology.scenario else None},
                )
            results.append({**res, "node": node.label, "credentials": creds})
        except Exception as e:
            results.append({"status": "error", "message": str(e), "node": node.label})

    os.makedirs(os.path.dirname(CREDS_CACHE_PATH), exist_ok=True)
    with open(CREDS_CACHE_PATH, "w") as f:
        json.dump(creds_cache, f)
            
    return {"status": "deployment_processed", "results": results}


class DeployJobStartResponse(BaseModel):
    job_id: str


class DeployJobStatusResponse(BaseModel):
    job_id: str
    status: str
    message: str
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    progress: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None


def _job_to_response(job) -> Dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "message": job.message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "progress": job.progress or {},
        "result": job.result,
    }


async def _run_deploy_job(job_id: str, topology: TopologyDeployRequest, current_user: AuthenticatedUser):
    await update_job(job_id, status="running", started_at=time.time(), message="Starting deployment")
    creds_cache = _load_creds_cache()
    deployment_prefix = f"dep{''.join(ch for ch in (job_id or '') if ch.isalnum())[:8] or uuid.uuid4().hex[:8]}"
    await update_progress(
        job_id,
        {
            "phase": "downloads",
            "owner_id": current_user.id,
            "owner_username": current_user.username,
            "downloads": {},
            "nodes": {n.id: {"label": n.label, "status": "pending"} for n in topology.nodes},
        },
    )

    results: List[Dict[str, Any]] = []

    try:
        slug = _network_slug(topology.scenario, suffix=(job_id.split("-")[0] if job_id else None))
        node_networks = _plan_topology_network_assignments(topology, slug)

        # Pre-ensure any scenario sources referenced by nodes (cached; emits progress)
        sources = topology.scenario.sources if topology.scenario and topology.scenario.sources else {}

        # Determine which sources are relevant for this topology
        needed_sources: Dict[str, Any] = {}
        for node in topology.nodes:
            guess = _resolve_image_path(node.config.image)
            src = sources.get(node.config.image) or sources.get(os.path.basename(guess))
            if src:
                # stable key by intended output name
                if isinstance(src, dict):
                    url = str(src.get("url") or "")
                    key = (src.get("filename") or os.path.basename(url.split("?")[0]) or "").strip()
                    extract = src.get("extract") if isinstance(src, dict) else None
                    if extract and isinstance(extract, dict) and extract.get("output_filename"):
                        key = extract.get("output_filename")
                else:
                    key = os.path.basename(str(src).split("?")[0]).strip()
                if key:
                    needed_sources[str(key)] = src

        for display_name, src in needed_sources.items():
            await set_progress_path(job_id, f"downloads.{display_name}.status", "queued")

        # Track per-download stats so we can compute speed/ETA.
        _dl_state: Dict[str, Dict[str, Any]] = {}

        def _progress_cb(evt: Dict[str, Any]):
            # Called frequently; schedule async updates without blocking.
            final_name = evt.get("final_name") or evt.get("filename") or "unknown"
            now = time.time()
            if evt.get("type") in ("download_start",):
                st = _dl_state.setdefault(str(final_name), {})
                st["started_at"] = now
                st["last_t"] = now
                st["last_bytes"] = 0
                st["speed_bps_ema"] = None
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.status", "downloading"))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.current", 0))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.total", int(evt.get("total") or 0)))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.started_at", now))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.updated_at", now))
            elif evt.get("type") in ("download_progress", "download_complete"):
                cur = int(evt.get("current") or 0)
                total = int(evt.get("total") or 0)
                pct = int((cur / total) * 100) if total > 0 else 0

                st = _dl_state.setdefault(str(final_name), {})
                last_t = float(st.get("last_t") or now)
                last_bytes = int(st.get("last_bytes") or 0)
                dt = max(0.0001, now - last_t)
                dbytes = max(0, cur - last_bytes)
                inst_bps = dbytes / dt
                prev_ema = st.get("speed_bps_ema")
                ema = inst_bps if prev_ema is None else (0.2 * inst_bps + 0.8 * float(prev_ema))
                st["last_t"] = now
                st["last_bytes"] = cur
                st["speed_bps_ema"] = ema

                eta = None
                if total > 0 and ema and ema > 1:
                    remaining = max(0, total - cur)
                    eta = remaining / ema

                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.current", cur))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.total", total))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.percent", pct))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.speed_bps", float(ema)))
                if eta is not None:
                    asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.eta_seconds", float(eta)))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.updated_at", now))
                if evt.get("type") == "download_complete":
                    asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.status", "downloaded"))
                    asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.finished_at", now))
            elif evt.get("type") == "extract_start":
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.status", "extracting"))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.extract_started_at", now))
            elif evt.get("type") == "extract_complete":
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.status", "ready"))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.percent", 100))
                asyncio.create_task(set_progress_path(job_id, f"downloads.{final_name}.extract_finished_at", now))

        # Ensure sources (sequential to keep progress clean)
        if needed_sources:
            await update_job(job_id, message="Downloading required images")
        for _name, src in needed_sources.items():
            await ensure_image(src, progress_cb=_progress_cb)

        # Create VMs
        await update_progress(job_id, {"phase": "vms"})
        await update_job(job_id, message="Creating virtual machines")

        async def _automation_progress(event: Dict[str, Any]):
            node_id = event.get("node_id")
            if not node_id:
                return
            status = event.get("status")
            if status is not None:
                await set_progress_path(job_id, f"nodes.{node_id}.automation.status", status)
            if "step" in event:
                await set_progress_path(job_id, f"nodes.{node_id}.automation.step", int(event["step"]))
            if "step_type" in event:
                await set_progress_path(job_id, f"nodes.{node_id}.automation.step_type", event["step_type"])
            if "delay_seconds" in event:
                await set_progress_path(job_id, f"nodes.{node_id}.automation.delay_seconds", float(event["delay_seconds"]))
            if "ok" in event:
                await set_progress_path(job_id, f"nodes.{node_id}.automation.last_ok", bool(event["ok"]))
            if "message" in event:
                await set_progress_path(job_id, f"nodes.{node_id}.automation.message", str(event["message"]))
            if "key" in event:
                await set_progress_path(job_id, f"nodes.{node_id}.automation.key", str(event["key"]))

        for node in topology.nodes:
            await set_progress_path(job_id, f"nodes.{node.id}.status", "creating")

            cloud_init = build_cloud_init_from_assets(node.config.assets)
            # Apply user-specified credentials if provided
            if node.config.username:
                cloud_init["username"] = node.config.username
            if node.config.password:
                cloud_init["password"] = node.config.password

            # Resolve/ensure image path
            image_path: Optional[str] = None
            src = None
            if topology.scenario and topology.scenario.sources:
                guess = _resolve_image_path(node.config.image)
                src = topology.scenario.sources.get(node.config.image) or topology.scenario.sources.get(os.path.basename(guess))

            if src:
                ensured = await ensure_image(src, progress_cb=_progress_cb)
                image_path = ensured.container_path
            else:
                image_path = _resolve_image_path(node.config.image)

            if not image_path or not os.path.exists(image_path):
                msg = f"Missing base image: {os.path.basename(image_path or node.config.image)}"
                await set_progress_path(job_id, f"nodes.{node.id}.status", "error")
                await set_progress_path(job_id, f"nodes.{node.id}.message", msg)
                results.append({"status": "error", "node": node.label, "message": msg})
                continue

            automation_steps = []
            if isinstance(node.config.automation, dict):
                try:
                    automation_steps = normalize_automation_steps(node.config.automation)
                except ValueError as e:
                    msg = f"Invalid automation: {e}"
                    await set_progress_path(job_id, f"nodes.{node.id}.status", "error")
                    await set_progress_path(job_id, f"nodes.{node.id}.message", msg)
                    results.append({"status": "error", "node": node.label, "message": msg})
                    continue

            vm_name = _scoped_vm_name(node.label, node.id, deployment_prefix)
            nets = node_networks.get(node.id) or ["default"]

            res = vm_manager.create_vm(
                name=vm_name,
                memory_mb=node.config.ram,
                vcpus=node.config.cpu,
                image_path=None if image_path.lower().endswith(".iso") else image_path,
                iso_path=_host_path_for_container_image(image_path) if image_path.lower().endswith(".iso") else None,
                cloud_init=None if image_path.lower().endswith(".iso") else cloud_init,
                network_names=nets,
            )
            results.append({**res, "node": node.label, "credentials": None if image_path.lower().endswith(".iso") else cloud_init_credentials(cloud_init)})
            if res.get("status") == "success":
                await set_progress_path(job_id, f"nodes.{node.id}.status", "running")
                if res.get("vnc_port"):
                    await set_progress_path(job_id, f"nodes.{node.id}.vnc_port", res["vnc_port"])
                creds = cloud_init_credentials(cloud_init)
                if creds:
                    creds_cache[vm_name] = creds
                    await set_progress_path(job_id, f"nodes.{node.id}.credentials.username", creds["username"])
                    await set_progress_path(job_id, f"nodes.{node.id}.credentials.password", creds["password"])

                register_vm(
                    vm_name,
                    current_user,
                    source="topology",
                    deployment_id=job_id,
                    metadata={"scenario_name": topology.scenario.name if topology.scenario else None},
                )

                if image_path.lower().endswith(".iso") and automation_steps:
                    asyncio.create_task(
                        execute_automation_steps(
                            vm_name=vm_name,
                            node_id=node.id,
                            steps=automation_steps,
                            send_text=vm_manager.send_text,
                            send_key=vm_manager.send_key,
                            progress_cb=_automation_progress,
                        )
                    )
            else:
                await set_progress_path(job_id, f"nodes.{node.id}.status", "error")
                await set_progress_path(job_id, f"nodes.{node.id}.message", res.get("message") or "failed")

        os.makedirs(os.path.dirname(CREDS_CACHE_PATH), exist_ok=True)
        with open(CREDS_CACHE_PATH, "w") as f:
            json.dump(creds_cache, f)

        # Save deployment record
        try:
            deployments = _load_deployments()
            vm_names = []
            for node in topology.nodes:
                 vm_names.append(_scoped_vm_name(node.label, node.id, deployment_prefix))
            
            deployments[job_id] = {
                "id": job_id,
                "name": topology.scenario.name if topology.scenario and topology.scenario.name else "Custom Deployment",
                "owner_id": current_user.id,
                "owner_username": current_user.username,
                "timestamp": time.time(),
                "vms": vm_names,
                "topology": topology.dict()
            }
            _save_deployments(deployments)
        except Exception as e:
            logger.error("Failed to save deployment record: %s", e)

        await update_job(
            job_id,
            status="completed",
            finished_at=time.time(),
            message="Deployment completed",
            result={"status": "deployment_processed", "results": results},
        )
        await update_progress(job_id, {"phase": "done"})
    except Exception as e:
        await update_job(job_id, status="failed", finished_at=time.time(), message=str(e), result={"status": "error", "detail": str(e), "results": results})


@router.post("/topology/deploy-jobs", response_model=DeployJobStartResponse)
async def start_deploy_job(
    topology: TopologyDeployRequest,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
):
    job = new_job(initial_progress={"phase": "queued", "owner_id": current_user.id, "owner_username": current_user.username})
    # Start background task
    asyncio.create_task(_run_deploy_job(job.id, topology, current_user))
    return {"job_id": job.id}


@router.get("/topology/deploy-jobs/{job_id}", response_model=DeployJobStatusResponse)
async def get_deploy_job(job_id: str, current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and (job.progress or {}).get("owner_id") != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this deployment job")
    return _job_to_response(job)

@router.get("/topology/deploy")
async def deploy_topology_get():
    return {"message": "You sent a GET request. Please use POST to deploy."}

