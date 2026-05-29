from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from app.core.vm_manager import vm_manager, WORK_DIR
import os
import glob
import json
import logging
import ipaddress
import re
from app.core.image_manager import ensure_image
import asyncio
import time
import hashlib
import uuid
from app.core.deploy_automation import execute_automation_steps, normalize_automation_steps
from app.core.provisioning import build_cloud_init_from_assets, cloud_init_credentials
from app.core.remote_execution import run_ssh_command_async
from app.core.vm_agent import VM_AGENT_DEFAULT_PORT, build_vm_agent_bootstrap_command, call_vm_agent
from app.api.trainings import canonicalize_image_download_source, canonicalize_image_key, resolve_verified_image_download_source

from app.core.deploy_jobs import new_job, get_job, update_job, update_progress, set_progress_path
from app.core.auth import AuthenticatedUser, get_current_user_from_websocket, require_admin_user, require_authenticated_user
from app.core.event_bus import event_bus
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


def _deployment_prefix(identifier: Optional[str]) -> str:
    compact = "".join(ch for ch in str(identifier or "") if ch.isalnum())[:8]
    return f"dep{compact or uuid.uuid4().hex[:8]}"


def _get_deployment_for_user(deployment_id: str, current_user: AuthenticatedUser) -> Dict[str, Any]:
    deployment = _load_deployments().get(deployment_id)
    if not isinstance(deployment, dict):
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not _deployment_visible_to_user(deployment, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this deployment")
    return deployment


def _topology_from_deployment_record(deployment: Dict[str, Any]) -> "TopologyDeployRequest":
    payload = deployment.get("topology")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Deployment record is missing topology data")
    try:
        return TopologyDeployRequest(**payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Deployment record contains invalid topology data") from exc


def _deployment_vm_names_by_node_id(topology: "TopologyDeployRequest", deployment_id: str) -> Dict[str, str]:
    deployment_prefix = _deployment_prefix(deployment_id)
    return {
        node.id: _scoped_vm_name(node.label, node.id, deployment_prefix)
        for node in topology.nodes
    }


def _topology_node_images_by_id(topology: "TopologyDeployRequest") -> Dict[str, str]:
    return {
        node.id: str(node.config.image or "").strip()
        for node in topology.nodes
    }


def _persist_deployment_record(
    deployment_id: str,
    topology: "TopologyDeployRequest",
    current_user: AuthenticatedUser,
    vm_names_by_node_id: Dict[str, str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    deployments = _load_deployments()
    existing = deployments.get(deployment_id) if isinstance(deployments.get(deployment_id), dict) else {}
    record: Dict[str, Any] = {
        **existing,
        "id": deployment_id,
        "name": topology.scenario.name if topology.scenario and topology.scenario.name else "Custom Deployment",
        "owner_id": current_user.id,
        "owner_username": current_user.username,
        "timestamp": existing.get("timestamp") if isinstance(existing, dict) and existing.get("timestamp") else time.time(),
        "vms": list(vm_names_by_node_id.values()),
        "topology": topology.dict(),
    }
    if extra:
        for key, value in extra.items():
            if value is None:
                continue
            if key in {"node_hosts", "vm_agents"} and isinstance(value, dict):
                previous = record.get(key) if isinstance(record.get(key), dict) else {}
                record[key] = {**previous, **value}
            else:
                record[key] = value

    deployments[deployment_id] = record
    _save_deployments(deployments)
    return record


def _image_supports_guest_command_execution(image_key: str) -> bool:
    normalized = canonicalize_image_key(image_key).strip().lower()
    if not normalized:
        return True

    resolved_name = os.path.basename(_resolve_image_path(normalized)).strip().lower()
    combined = " ".join(part for part in (normalized, resolved_name) if part)
    unsupported_tokens = (
        "gateway",
        "vyos",
        "opnsense",
        "openwrt",
        "security-onion",
        "securityonion",
        "contiki",
        "windows-10",
        "windows10",
    )
    return not any(token in combined for token in unsupported_tokens)


def _normalize_runbook_phases(phases: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    for raw_phase in phases or ["simulation"]:
        phase = str(raw_phase or "").strip().lower()
        if phase not in {"setup", "simulation"} or phase in normalized:
            continue
        normalized.append(phase)
    return normalized or ["simulation"]

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
    image_key = canonicalize_image_key(image_key)
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
            if image_key == "kali-linux":
                return candidate
            candidates.append(candidate)

    # Fallbacks for common variants
    patterns = []
    if image_key == "kali-linux":
        patterns = ["kali-linux-*-cloud-genericcloud-amd64.qcow2", "kali-linux-*-cloud-genericcloud-amd64.tar.xz"]
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


def _agent_mesh_enabled(topology: "TopologyDeployRequest") -> bool:
    scenario = getattr(topology, "scenario", None)
    if not scenario or not getattr(scenario, "runbook", None):
        return False
    configured = getattr(scenario, "agent_mesh", None)
    if configured is None:
        return True
    return bool(configured)


def _agent_mesh_network_name(slug: str) -> str:
    return f"cyberange-{slug}-agent"


def _runbook_preferred_networks(topology: "TopologyDeployRequest", slug: str) -> List[str]:
    if not _agent_mesh_enabled(topology):
        return []
    return [_agent_mesh_network_name(slug)]


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

    def _apply_agent_mesh() -> None:
        if not _agent_mesh_enabled(topology):
            return
        mesh_name = _agent_mesh_network_name(slug)
        _ensure_planned_network(mesh_name, "nat", f"{slug}:agent-mesh", used_thirds)
        for planned_node in topology.nodes:
            _append_network_assignment(node_networks, planned_node.id, mesh_name)

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
        _apply_agent_mesh()
        return {node_id: nets for node_id, nets in node_networks.items() if nets}

    comp_map = _connected_components(component_node_ids, implicit_edges)
    if not comp_map:
        _apply_agent_mesh()
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

    _apply_agent_mesh()

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


class ScenarioRunbookStep(BaseModel):
    title: str
    action: str
    actor: Optional[str] = None
    target: Optional[str] = None
    expected_outcome: Optional[str] = None
    delay_seconds: Optional[float] = None
    automation: Optional[Dict[str, Any]] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    timeout_seconds: Optional[float] = None


class ScenarioVisualization(BaseModel):
    title: str
    kind: str = "dashboard"
    node_id: Optional[str] = None
    url_hint: Optional[str] = None
    description: Optional[str] = None


class ScenarioRunbook(BaseModel):
    provisioning_strategy: Optional[str] = None
    setup_order: List[str] = Field(default_factory=list)
    setup_steps: List[ScenarioRunbookStep] = Field(default_factory=list)
    simulation_steps: List[ScenarioRunbookStep] = Field(default_factory=list)
    visualizations: List[ScenarioVisualization] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)

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
    # Attach a shared orchestration mesh for runbook/agent-driven scenarios.
    agent_mesh: Optional[bool] = None
    runbook: Optional[ScenarioRunbook] = None


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
            raw_source = topology.scenario.sources.get(node.config.image) or topology.scenario.sources.get(os.path.basename(resolved_guess))
            if raw_source is not None:
                source = await resolve_verified_image_download_source(node.config.image, raw_source)

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


class RunbookJobRequest(BaseModel):
    phases: List[Literal["setup", "simulation"]] = Field(default_factory=lambda: ["simulation"])
    execution_mode: Literal["sequential", "actor_parallel"] = "actor_parallel"
    agent_mode: Literal["off", "prefer", "require"] = "prefer"


class VmAgentTaskRequest(BaseModel):
    command: str
    background: bool = False
    timeout_seconds: Optional[float] = 120.0
    cwd: Optional[str] = None
    environment: Optional[Dict[str, str]] = None


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


async def _publish_deploy_event(job_id: str, event_type: str, **detail: Any) -> None:
    await event_bus.publish(
        job_id,
        {
            "type": event_type,
            "ts": time.time(),
            "detail": detail,
        },
    )


def _runbook_step_progress(step: ScenarioRunbookStep, index: int) -> Dict[str, Any]:
    progress = {
        "index": index + 1,
        "title": step.title,
        "action": step.action,
        "status": "pending",
    }
    if step.actor:
        progress["actor"] = step.actor
    if step.target:
        progress["target"] = step.target
    if step.expected_outcome:
        progress["expected_outcome"] = step.expected_outcome
    if step.delay_seconds is not None:
        progress["delay_seconds"] = step.delay_seconds
    if step.automation:
        progress["automation"] = step.automation
    if step.transport:
        progress["transport"] = step.transport
    if step.command:
        progress["command"] = step.command
    if step.timeout_seconds is not None:
        progress["timeout_seconds"] = step.timeout_seconds
    return progress


def _build_runbook_progress(runbook: Optional[ScenarioRunbook]) -> Dict[str, Any]:
    if not runbook:
        return {}

    def _phase_progress(steps: List[ScenarioRunbookStep]) -> Dict[str, Any]:
        return {
            "status": "pending" if steps else "skipped",
            "steps": {str(index): _runbook_step_progress(step, index) for index, step in enumerate(steps)},
        }

    progress: Dict[str, Any] = {
        "status": "pending",
        "current_phase": None,
        "setup": _phase_progress(runbook.setup_steps),
        "simulation": _phase_progress(runbook.simulation_steps),
    }
    if runbook.provisioning_strategy:
        progress["provisioning_strategy"] = runbook.provisioning_strategy
    if runbook.success_criteria:
        progress["success_criteria"] = list(runbook.success_criteria)
    if runbook.visualizations:
        progress["visualizations"] = [item.dict(exclude_none=True) for item in runbook.visualizations]
    return progress


def _resolve_runbook_vm_name(step: ScenarioRunbookStep, vm_names_by_node_id: Dict[str, str]) -> Optional[tuple[str, str]]:
    for node_id in (step.actor, step.target):
        if node_id and node_id in vm_names_by_node_id:
            return node_id, vm_names_by_node_id[node_id]
    return None


def _normalize_runbook_transport(transport: Optional[str]) -> str:
    normalized = str(transport or "ssh").strip().lower()
    return normalized or "ssh"


def _step_uses_vm_agent(step: ScenarioRunbookStep) -> bool:
    return bool(step.command) and not step.automation and _normalize_runbook_transport(step.transport) != "console"


def _deployment_vm_agents(deployment: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw_agents = deployment.get("vm_agents")
    if not isinstance(raw_agents, dict):
        return {}
    return {
        str(node_id): dict(agent_state)
        for node_id, agent_state in raw_agents.items()
        if isinstance(agent_state, dict)
    }


def _deployment_node_hosts(deployment: Dict[str, Any]) -> Dict[str, str]:
    raw_hosts = deployment.get("node_hosts")
    if not isinstance(raw_hosts, dict):
        return {}
    normalized: Dict[str, str] = {}
    for node_id, value in raw_hosts.items():
        host = str(value or "").strip()
        if not host:
            continue
        try:
            normalized[str(node_id)] = str(ipaddress.ip_address(host))
        except ValueError:
            continue
    return normalized


def _load_saved_vm_agent_state(deployment_id: str, node_id: str) -> Dict[str, Any]:
    deployment = _load_deployments().get(deployment_id)
    if not isinstance(deployment, dict):
        return {}
    return dict(_deployment_vm_agents(deployment).get(node_id) or {})


def _load_saved_node_host(deployment_id: str, node_id: str) -> Optional[str]:
    deployment = _load_deployments().get(deployment_id)
    if not isinstance(deployment, dict):
        return None
    host = _deployment_node_hosts(deployment).get(node_id)
    return str(host).strip() if host else None


def _save_vm_agent_state(deployment_id: str, node_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    deployments = _load_deployments()
    deployment = deployments.get(deployment_id)
    if not isinstance(deployment, dict):
        return dict(state)

    vm_agents = deployment.setdefault("vm_agents", {})
    if not isinstance(vm_agents, dict):
        vm_agents = {}
        deployment["vm_agents"] = vm_agents
    existing = vm_agents.get(node_id) if isinstance(vm_agents.get(node_id), dict) else {}
    merged = {**existing, **state}
    vm_agents[node_id] = merged
    _save_deployments(deployments)
    return merged


def _save_node_host(deployment_id: str, node_id: str, host: str) -> Optional[str]:
    try:
        normalized_host = str(ipaddress.ip_address(str(host or "").strip()))
    except ValueError:
        return None

    deployments = _load_deployments()
    deployment = deployments.get(deployment_id)
    if not isinstance(deployment, dict):
        return normalized_host

    node_hosts = deployment.setdefault("node_hosts", {})
    if not isinstance(node_hosts, dict):
        node_hosts = {}
        deployment["node_hosts"] = node_hosts
    node_hosts[node_id] = normalized_host
    _save_deployments(deployments)
    return normalized_host


def _collect_runbook_vm_agent_targets(
    steps: List[ScenarioRunbookStep],
    vm_names_by_node_id: Dict[str, str],
) -> Dict[str, str]:
    targets: Dict[str, str] = {}
    for step in steps:
        if not _step_uses_vm_agent(step):
            continue
        resolved_target = _resolve_runbook_vm_name(step, vm_names_by_node_id)
        if not resolved_target:
            continue
        node_id, vm_name = resolved_target
        targets[node_id] = vm_name
    return targets


def _collect_runbook_phase_host_targets(
    steps: List[ScenarioRunbookStep],
    vm_names_by_node_id: Dict[str, str],
    node_images_by_id: Dict[str, str],
) -> Dict[str, str]:
    targets: Dict[str, str] = {}
    for step in steps:
        if not step.command or step.automation or _normalize_runbook_transport(step.transport) == "console":
            continue
        resolved_target = _resolve_runbook_vm_name(step, vm_names_by_node_id)
        if resolved_target:
            node_id, vm_name = resolved_target
            if not _image_supports_guest_command_execution(node_images_by_id.get(node_id, "")):
                continue
            targets[node_id] = vm_name
        if step.target and step.target in vm_names_by_node_id:
            targets[step.target] = vm_names_by_node_id[step.target]
    return targets


async def _vm_agent_healthcheck(agent_state: Dict[str, Any], timeout_seconds: float = 5.0) -> Dict[str, Any]:
    return await call_vm_agent(
        host=str(agent_state.get("host") or "").strip(),
        token=str(agent_state.get("token") or "").strip(),
        port=int(agent_state.get("port") or VM_AGENT_DEFAULT_PORT),
        path="/health",
        timeout_seconds=timeout_seconds,
    )


async def _execute_vm_agent_task(
    *,
    agent_state: Dict[str, Any],
    command: str,
    timeout_seconds: float = 120.0,
    background: bool = False,
    cwd: Optional[str] = None,
    environment: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "command": str(command),
        "background": bool(background),
        "timeout_seconds": max(1.0, float(timeout_seconds or 0.0)),
    }
    if cwd:
        payload["cwd"] = str(cwd)
    if environment:
        payload["environment"] = {str(key): str(value) for key, value in environment.items()}
    request_timeout = 10.0 if background else max(5.0, float(payload["timeout_seconds"]) + 5.0)
    return await call_vm_agent(
        host=str(agent_state.get("host") or "").strip(),
        token=str(agent_state.get("token") or "").strip(),
        port=int(agent_state.get("port") or VM_AGENT_DEFAULT_PORT),
        method="POST",
        path="/tasks",
        payload=payload,
        timeout_seconds=request_timeout,
    )


async def _get_vm_agent_task(agent_state: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    return await call_vm_agent(
        host=str(agent_state.get("host") or "").strip(),
        token=str(agent_state.get("token") or "").strip(),
        port=int(agent_state.get("port") or VM_AGENT_DEFAULT_PORT),
        method="GET",
        path=f"/tasks/{task_id}",
        timeout_seconds=10.0,
    )


async def _stop_vm_agent_task(agent_state: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    return await call_vm_agent(
        host=str(agent_state.get("host") or "").strip(),
        token=str(agent_state.get("token") or "").strip(),
        port=int(agent_state.get("port") or VM_AGENT_DEFAULT_PORT),
        method="DELETE",
        path=f"/tasks/{task_id}",
        timeout_seconds=10.0,
    )


async def _ensure_vm_agent_for_node(
    *,
    deployment_id: str,
    node_id: str,
    vm_name: str,
    node_credentials_by_id: Dict[str, Dict[str, str]],
    preferred_networks: Optional[List[str]],
    node_ip_cache: Dict[str, str],
    allow_bootstrap: bool,
) -> Dict[str, Any]:
    host = await _resolve_runbook_node_ip(
        step_title=f"VM agent for {node_id}",
        node_id=node_id,
        vm_name=vm_name,
        node_ip_cache=node_ip_cache,
        preferred_networks=preferred_networks,
        deployment_id=deployment_id,
        saved_host=_load_saved_node_host(deployment_id, node_id),
    )
    saved_state = _load_saved_vm_agent_state(deployment_id, node_id)
    token = str(saved_state.get("token") or uuid.uuid4().hex)
    port = int(saved_state.get("port") or VM_AGENT_DEFAULT_PORT)
    candidate_state = {
        **saved_state,
        "node_id": node_id,
        "vm_name": vm_name,
        "host": host,
        "port": port,
        "token": token,
    }

    try:
        health = await _vm_agent_healthcheck(candidate_state, timeout_seconds=3.0)
        candidate_state.update({
            "status": "ready",
            "last_seen_at": time.time(),
            "health": health,
        })
        return _save_vm_agent_state(deployment_id, node_id, candidate_state)
    except Exception as exc:
        if not allow_bootstrap:
            raise RuntimeError(f"VM agent for node '{node_id}' is unavailable: {exc}") from exc

    credentials = node_credentials_by_id.get(node_id) or {}
    username = str(credentials.get("username") or "").strip()
    password = str(credentials.get("password") or "").strip()
    if not username or not password:
        raise RuntimeError(f"VM agent for node '{node_id}' requires SSH credentials to bootstrap.")

    bootstrap_result = await run_ssh_command_async(
        host=host,
        username=username,
        password=password,
        command=build_vm_agent_bootstrap_command(token=token, port=port),
        timeout_seconds=45.0,
    )
    exit_status = int(bootstrap_result.get("exit_status") or 0)
    if exit_status != 0:
        stderr_text = str(bootstrap_result.get("stderr") or "").strip()
        raise RuntimeError(
            f"VM agent bootstrap failed for node '{node_id}' with exit status {exit_status}: {stderr_text or 'unknown error'}"
        )

    last_error: Optional[Exception] = None
    for _attempt in range(10):
        try:
            health = await _vm_agent_healthcheck(candidate_state, timeout_seconds=3.0)
            candidate_state.update({
                "status": "ready",
                "last_seen_at": time.time(),
                "health": health,
                "bootstrapped_at": time.time(),
            })
            return _save_vm_agent_state(deployment_id, node_id, candidate_state)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1.0)

    raise RuntimeError(f"VM agent for node '{node_id}' did not become healthy after bootstrap: {last_error}")


async def _ensure_runbook_vm_agents(
    *,
    job_id: str,
    deployment_id: str,
    phase_name: str,
    steps: List[ScenarioRunbookStep],
    vm_names_by_node_id: Dict[str, str],
    node_images_by_id: Dict[str, str],
    node_credentials_by_id: Dict[str, Dict[str, str]],
    preferred_networks: Optional[List[str]],
    agent_mode: Literal["off", "prefer", "require"],
) -> Dict[str, Dict[str, Any]]:
    if agent_mode == "off":
        return {}

    targets = _collect_runbook_vm_agent_targets(steps, vm_names_by_node_id)
    if not targets:
        return {}

    await set_progress_path(
        job_id,
        "runbook.vm_agents",
        {
            node_id: {
                "status": "pending",
                "vm_name": vm_name,
            }
            for node_id, vm_name in targets.items()
        },
    )

    agents: Dict[str, Dict[str, Any]] = {}
    node_ip_cache: Dict[str, str] = {}

    for node_id, vm_name in targets.items():
        image_key = str(node_images_by_id.get(node_id) or "").strip()
        if not _image_supports_guest_command_execution(image_key):
            message = (
                f"Node '{node_id}' uses image '{image_key or 'unknown'}', which does not support the current automatic agent/SSH control path. "
                "Use console automation or target a Linux cloud guest instead."
            )
            await set_progress_path(job_id, f"runbook.vm_agents.{node_id}.status", "unsupported")
            await set_progress_path(job_id, f"runbook.vm_agents.{node_id}.message", message)
            await _publish_deploy_event(
                job_id,
                "runbook_vm_agent",
                phase=phase_name,
                node_id=node_id,
                vm_name=vm_name,
                status="unsupported",
                message=message,
            )
            if agent_mode == "require":
                raise RuntimeError(message)
            continue

        await set_progress_path(job_id, f"runbook.vm_agents.{node_id}.status", "starting")
        await _publish_deploy_event(
            job_id,
            "runbook_vm_agent",
            phase=phase_name,
            node_id=node_id,
            vm_name=vm_name,
            status="starting",
            message=f"Starting VM agent for {node_id}.",
        )
        try:
            agent_state = await _ensure_vm_agent_for_node(
                deployment_id=deployment_id,
                node_id=node_id,
                vm_name=vm_name,
                node_credentials_by_id=node_credentials_by_id,
                preferred_networks=preferred_networks,
                node_ip_cache=node_ip_cache,
                allow_bootstrap=True,
            )
            agents[node_id] = agent_state
            await set_progress_path(job_id, f"runbook.vm_agents.{node_id}", {
                "status": "ready",
                "vm_name": vm_name,
                "host": agent_state.get("host"),
                "port": agent_state.get("port"),
                "last_seen_at": agent_state.get("last_seen_at"),
            })
            await _publish_deploy_event(
                job_id,
                "runbook_vm_agent",
                phase=phase_name,
                node_id=node_id,
                vm_name=vm_name,
                status="ready",
                host=agent_state.get("host"),
                port=agent_state.get("port"),
                message=f"VM agent ready for {node_id}.",
            )
        except Exception as exc:
            await set_progress_path(job_id, f"runbook.vm_agents.{node_id}.status", "failed")
            await set_progress_path(job_id, f"runbook.vm_agents.{node_id}.error", str(exc))
            await _publish_deploy_event(
                job_id,
                "runbook_vm_agent",
                phase=phase_name,
                node_id=node_id,
                vm_name=vm_name,
                status="failed",
                message=str(exc),
            )
            if agent_mode == "require":
                raise

    return agents


def _build_runbook_actor_lanes(
    steps: List[ScenarioRunbookStep],
    vm_names_by_node_id: Dict[str, str],
) -> List[Dict[str, Any]]:
    lanes_by_identifier: Dict[str, Dict[str, Any]] = {}
    ordered_lanes: List[Dict[str, Any]] = []

    for index, step in enumerate(steps):
        resolved_target = _resolve_runbook_vm_name(step, vm_names_by_node_id)
        lane_identifier = resolved_target[0] if resolved_target else str(step.actor or step.target or "shared")

        lane = lanes_by_identifier.get(lane_identifier)
        if lane is None:
            lane = {
                "key": str(len(ordered_lanes)),
                "label": lane_identifier,
                "status": "pending",
                "step_indexes": [],
                "steps": [],
            }
            if resolved_target:
                lane["node_id"] = resolved_target[0]
                lane["vm_name"] = resolved_target[1]
            if step.actor:
                lane["actor"] = step.actor
            if step.target:
                lane["target"] = step.target
            lanes_by_identifier[lane_identifier] = lane
            ordered_lanes.append(lane)

        if step.actor and "actor" not in lane:
            lane["actor"] = step.actor
        if step.target and "target" not in lane:
            lane["target"] = step.target

        lane["step_indexes"].append(index + 1)
        lane["steps"].append((index, step))

    return ordered_lanes


async def _resolve_runbook_node_ip(
    *,
    step_title: str,
    node_id: str,
    vm_name: str,
    node_ip_cache: Dict[str, str],
    preferred_networks: Optional[List[str]] = None,
    deployment_id: Optional[str] = None,
    saved_host: Optional[str] = None,
    timeout_seconds: float = 180.0,
) -> str:
    cached = node_ip_cache.get(node_id)
    if cached:
        return cached

    persisted_host = str(saved_host or "").strip()

    ip_address = None
    if preferred_networks:
        try:
            ip_address = await asyncio.to_thread(
                vm_manager.wait_for_preferred_ipv4,
                vm_name,
                preferred_networks,
                max(1.0, float(timeout_seconds or 0.0)),
                5.0,
            )
        except Exception:
            ip_address = None
    if not ip_address:
        ip_address = await asyncio.to_thread(
            vm_manager.wait_for_primary_ipv4,
            vm_name,
            max(1.0, float(timeout_seconds or 0.0)),
            5.0,
        )
    if not ip_address and persisted_host:
        ip_address = persisted_host
    if not ip_address:
        raise RuntimeError(f"Runbook step '{step_title}' could not resolve an IPv4 address for node '{node_id}'.")

    try:
        normalized_ip = str(ipaddress.ip_address(str(ip_address).strip()))
    except ValueError as exc:
        raise RuntimeError(f"Runbook step '{step_title}' resolved a non-IP host '{ip_address}' for node '{node_id}'.") from exc

    node_ip_cache[node_id] = normalized_ip
    if deployment_id:
        _save_node_host(deployment_id, node_id, normalized_ip)
    return normalized_ip


def _render_runbook_command(command: str, replacements: Dict[str, str]) -> str:
    rendered = str(command or "")
    for token in sorted(replacements, key=len, reverse=True):
        rendered = re.sub(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])", replacements[token], rendered)
    return rendered


async def _execute_runbook_phase(
    *,
    job_id: str,
    phase_name: str,
    deployment_id: Optional[str],
    steps: List[ScenarioRunbookStep],
    vm_names_by_node_id: Dict[str, str],
    node_images_by_id: Dict[str, str],
    node_credentials_by_id: Dict[str, Dict[str, str]],
    preferred_networks: Optional[List[str]] = None,
    execution_mode: Literal["sequential", "actor_parallel"] = "sequential",
    vm_agents_by_node_id: Optional[Dict[str, Dict[str, Any]]] = None,
    agent_mode: Literal["off", "prefer", "require"] = "off",
    saved_node_hosts_by_id: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    node_ip_cache: Dict[str, str] = {}
    vm_agents_by_node_id = vm_agents_by_node_id or {}
    saved_node_hosts_by_id = saved_node_hosts_by_id or {}

    if not steps:
        await set_progress_path(job_id, f"runbook.{phase_name}.execution_mode", execution_mode)
        await set_progress_path(job_id, f"runbook.{phase_name}.status", "skipped")
        await _publish_deploy_event(job_id, "runbook_phase", phase=phase_name, status="skipped", execution_mode=execution_mode)
        return []

    await set_progress_path(job_id, "runbook.status", "running")
    await set_progress_path(job_id, "runbook.current_phase", phase_name)
    await set_progress_path(job_id, f"runbook.{phase_name}.status", "running")
    await set_progress_path(job_id, f"runbook.{phase_name}.execution_mode", execution_mode)
    await _publish_deploy_event(job_id, "runbook_phase", phase=phase_name, status="running", execution_mode=execution_mode)

    preflight_targets = _collect_runbook_phase_host_targets(steps, vm_names_by_node_id, node_images_by_id)
    if preflight_targets:
        await set_progress_path(
            job_id,
            f"runbook.{phase_name}.node_hosts",
            {
                node_id: {"status": "pending", "vm_name": vm_name}
                for node_id, vm_name in preflight_targets.items()
            },
        )
        preflight_errors: List[str] = []
        for node_id, vm_name in preflight_targets.items():
            await set_progress_path(job_id, f"runbook.{phase_name}.node_hosts.{node_id}.status", "resolving")
            await _publish_deploy_event(
                job_id,
                "runbook_node_host",
                phase=phase_name,
                node_id=node_id,
                vm_name=vm_name,
                status="resolving",
            )
            try:
                resolved_host = await _resolve_runbook_node_ip(
                    step_title=f"{phase_name.title()} host preflight",
                    node_id=node_id,
                    vm_name=vm_name,
                    node_ip_cache=node_ip_cache,
                    preferred_networks=preferred_networks,
                    deployment_id=deployment_id,
                    saved_host=saved_node_hosts_by_id.get(node_id),
                    timeout_seconds=300.0,
                )
                await set_progress_path(job_id, f"runbook.{phase_name}.node_hosts.{node_id}.status", "ready")
                await set_progress_path(job_id, f"runbook.{phase_name}.node_hosts.{node_id}.host", resolved_host)
                await _publish_deploy_event(
                    job_id,
                    "runbook_node_host",
                    phase=phase_name,
                    node_id=node_id,
                    vm_name=vm_name,
                    status="ready",
                    host=resolved_host,
                )
            except RuntimeError as exc:
                message = str(exc)
                preflight_errors.append(f"{node_id}: {message}")
                await set_progress_path(job_id, f"runbook.{phase_name}.node_hosts.{node_id}.status", "failed")
                await set_progress_path(job_id, f"runbook.{phase_name}.node_hosts.{node_id}.message", message)
                await _publish_deploy_event(
                    job_id,
                    "runbook_node_host",
                    phase=phase_name,
                    node_id=node_id,
                    vm_name=vm_name,
                    status="failed",
                    message=message,
                )
        if preflight_errors:
            raise RuntimeError(
                f"Runbook phase '{phase_name}' preflight could not resolve required node hosts: {'; '.join(preflight_errors)}"
            )

    async def _execute_step(index: int, step: ScenarioRunbookStep) -> Dict[str, Any]:
        step_key = str(index)
        step_path = f"runbook.{phase_name}.steps.{step_key}"
        started_at = time.time()
        step_number = index + 1
        await set_progress_path(job_id, f"{step_path}.status", "running")
        await set_progress_path(job_id, f"{step_path}.started_at", started_at)
        await _publish_deploy_event(
            job_id,
            "runbook_step",
            phase=phase_name,
            step_index=step_number,
            title=step.title,
            status="running",
            actor=step.actor,
            target=step.target,
        )

        if step.delay_seconds:
            await set_progress_path(job_id, f"{step_path}.status", "waiting")
            await _publish_deploy_event(
                job_id,
                "runbook_step",
                phase=phase_name,
                step_index=step_number,
                title=step.title,
                status="waiting",
                delay_seconds=float(step.delay_seconds),
            )
            await asyncio.sleep(max(0.0, float(step.delay_seconds)))
            await set_progress_path(job_id, f"{step_path}.status", "running")

        if not step.automation:
            if step.command:
                target = _resolve_runbook_vm_name(step, vm_names_by_node_id)
                if not target:
                    msg = f"Runbook step '{step.title}' does not target a deployed node."
                    await set_progress_path(job_id, f"{step_path}.status", "failed")
                    await set_progress_path(job_id, f"{step_path}.message", msg)
                    await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
                    await _publish_deploy_event(
                        job_id,
                        "runbook_step",
                        phase=phase_name,
                        step_index=step_number,
                        title=step.title,
                        status="failed",
                        message=msg,
                    )
                    raise RuntimeError(msg)

                node_id, vm_name = target
                image_key = str(node_images_by_id.get(node_id) or "").strip()
                requested_transport = _normalize_runbook_transport(step.transport)
                if requested_transport != "console" and not _image_supports_guest_command_execution(image_key):
                    msg = (
                        f"Runbook step '{step.title}' targets node '{node_id}' with image '{image_key or 'unknown'}', "
                        "which does not support the current automatic agent/SSH execution path. "
                        "Use console automation or target a Linux cloud guest instead."
                    )
                    await set_progress_path(job_id, f"{step_path}.status", "failed")
                    await set_progress_path(job_id, f"{step_path}.message", msg)
                    await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
                    await _publish_deploy_event(
                        job_id,
                        "runbook_step",
                        phase=phase_name,
                        step_index=step_number,
                        title=step.title,
                        status="failed",
                        message=msg,
                        node_id=node_id,
                        vm_name=vm_name,
                        transport=requested_transport,
                    )
                    raise RuntimeError(msg)

                credentials = node_credentials_by_id.get(node_id) or {}
                username = str(credentials.get("username") or "").strip()
                password = str(credentials.get("password") or "").strip()
                if not username or not password:
                    msg = f"Runbook step '{step.title}' requires SSH credentials for node '{node_id}'."
                    await set_progress_path(job_id, f"{step_path}.status", "failed")
                    await set_progress_path(job_id, f"{step_path}.message", msg)
                    await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
                    await _publish_deploy_event(
                        job_id,
                        "runbook_step",
                        phase=phase_name,
                        step_index=step_number,
                        title=step.title,
                        status="failed",
                        message=msg,
                        node_id=node_id,
                    )
                    raise RuntimeError(msg)

                await set_progress_path(job_id, f"{step_path}.status", "waiting_for_ip")
                await _publish_deploy_event(
                    job_id,
                    "runbook_step",
                    phase=phase_name,
                    step_index=step_number,
                    title=step.title,
                    status="waiting_for_ip",
                    node_id=node_id,
                    vm_name=vm_name,
                )
                try:
                    ip_address = await _resolve_runbook_node_ip(
                        step_title=step.title,
                        node_id=node_id,
                        vm_name=vm_name,
                        node_ip_cache=node_ip_cache,
                        preferred_networks=preferred_networks,
                        deployment_id=deployment_id,
                        saved_host=saved_node_hosts_by_id.get(node_id),
                    )
                except RuntimeError as exc:
                    msg = str(exc)
                    await set_progress_path(job_id, f"{step_path}.status", "failed")
                    await set_progress_path(job_id, f"{step_path}.message", msg)
                    await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
                    await _publish_deploy_event(
                        job_id,
                        "runbook_step",
                        phase=phase_name,
                        step_index=step_number,
                        title=step.title,
                        status="failed",
                        message=msg,
                        node_id=node_id,
                    )
                    raise RuntimeError(msg) from exc

                command_text = str(step.command or "")
                command_replacements = {
                    "actor_ip": ip_address,
                    node_id: ip_address,
                    f"{node_id}_ip": ip_address,
                    f"{node_id.replace('-', '_')}_ip": ip_address,
                }
                if step.target and step.target != node_id:
                    target_vm_name = vm_names_by_node_id.get(step.target)
                    if target_vm_name:
                        target_ip = await _resolve_runbook_node_ip(
                            step_title=step.title,
                            node_id=step.target,
                            vm_name=target_vm_name,
                            node_ip_cache=node_ip_cache,
                            preferred_networks=preferred_networks,
                            deployment_id=deployment_id,
                            saved_host=saved_node_hosts_by_id.get(step.target),
                        )
                        command_replacements.update(
                            {
                                "target_ip": target_ip,
                                step.target: target_ip,
                                f"{step.target}_ip": target_ip,
                                f"{step.target.replace('-', '_')}_ip": target_ip,
                            }
                        )
                rendered_command = _render_runbook_command(command_text, command_replacements)

                actual_transport = requested_transport
                remote_host = ip_address
                command_result: Optional[Dict[str, Any]] = None
                agent_state = vm_agents_by_node_id.get(node_id)
                command_timeout = max(1.0, float(step.timeout_seconds or 120.0))

                if agent_state and requested_transport != "console" and (requested_transport == "agent" or agent_mode != "off"):
                    actual_transport = "agent"
                    remote_host = str(agent_state.get("host") or ip_address)

                if rendered_command != command_text:
                    await set_progress_path(job_id, f"{step_path}.resolved_command", rendered_command)
                await set_progress_path(job_id, f"{step_path}.transport", actual_transport)
                await set_progress_path(job_id, f"{step_path}.remote_host", remote_host)
                if actual_transport == "agent" and agent_state is not None:
                    await set_progress_path(job_id, f"{step_path}.agent_port", int(agent_state.get("port") or VM_AGENT_DEFAULT_PORT))

                await _publish_deploy_event(
                    job_id,
                    "runbook_command",
                    phase=phase_name,
                    step_index=step_number,
                    title=step.title,
                    status="running",
                    node_id=node_id,
                    vm_name=vm_name,
                    host=remote_host,
                    transport=actual_transport,
                    command=rendered_command,
                )

                if actual_transport == "agent" and agent_state is not None:
                    try:
                        command_result = await _execute_vm_agent_task(
                            agent_state=agent_state,
                            command=rendered_command,
                            timeout_seconds=command_timeout,
                            background=False,
                        )
                    except Exception as exc:
                        if requested_transport == "agent" or agent_mode == "require":
                            msg = f"VM agent execution failed for node '{node_id}' at '{remote_host}': {exc}"
                            await set_progress_path(job_id, f"{step_path}.status", "failed")
                            await set_progress_path(job_id, f"{step_path}.message", msg)
                            await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
                            await _publish_deploy_event(
                                job_id,
                                "runbook_command",
                                phase=phase_name,
                                step_index=step_number,
                                title=step.title,
                                status="failed",
                                node_id=node_id,
                                host=remote_host,
                                transport=actual_transport,
                                command=rendered_command,
                                message=msg,
                            )
                            raise RuntimeError(msg) from exc

                        actual_transport = "ssh"
                        remote_host = ip_address
                        await set_progress_path(job_id, f"{step_path}.transport", actual_transport)
                        await set_progress_path(job_id, f"{step_path}.remote_host", remote_host)
                        await _publish_deploy_event(
                            job_id,
                            "runbook_vm_agent",
                            phase=phase_name,
                            step_index=step_number,
                            node_id=node_id,
                            vm_name=vm_name,
                            status="fallback",
                            message=f"VM agent unavailable for {node_id}; falling back to SSH.",
                        )

                if command_result is None:
                    try:
                        command_result = await run_ssh_command_async(
                            host=ip_address,
                            username=username,
                            password=password,
                            command=rendered_command,
                            timeout_seconds=command_timeout,
                        )
                    except Exception as exc:
                        msg = f"SSH execution failed for node '{node_id}' at '{ip_address}': {exc}"
                        await set_progress_path(job_id, f"{step_path}.status", "failed")
                        await set_progress_path(job_id, f"{step_path}.message", msg)
                        await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
                        await _publish_deploy_event(
                            job_id,
                            "runbook_command",
                            phase=phase_name,
                            step_index=step_number,
                            title=step.title,
                            status="failed",
                            node_id=node_id,
                            host=ip_address,
                            transport=actual_transport,
                            command=rendered_command,
                            message=msg,
                        )
                        raise RuntimeError(msg) from exc
                stdout_text = str(command_result.get("stdout") or "")
                if not stdout_text:
                    stdout_text = str(command_result.get("stdout_tail") or "")
                stderr_text = str(command_result.get("stderr") or "")
                if not stderr_text:
                    stderr_text = str(command_result.get("stderr_tail") or "")
                exit_status = int(command_result.get("exit_status") or 0)
                await set_progress_path(job_id, f"{step_path}.command_exit_status", exit_status)
                if stdout_text:
                    await set_progress_path(job_id, f"{step_path}.stdout_tail", stdout_text[-500:])
                if stderr_text:
                    await set_progress_path(job_id, f"{step_path}.stderr_tail", stderr_text[-500:])
                await _publish_deploy_event(
                    job_id,
                    "runbook_command",
                    phase=phase_name,
                    step_index=step_number,
                    title=step.title,
                    status="completed" if exit_status == 0 else "failed",
                    node_id=node_id,
                    host=remote_host,
                    transport=actual_transport,
                    exit_status=exit_status,
                    stdout_tail=stdout_text[-200:],
                    stderr_tail=stderr_text[-200:],
                )
                if exit_status != 0:
                    msg = f"{actual_transport.upper()} command for runbook step '{step.title}' failed with exit status {exit_status}."
                    await set_progress_path(job_id, f"{step_path}.status", "failed")
                    await set_progress_path(job_id, f"{step_path}.message", msg)
                    await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
                    await _publish_deploy_event(
                        job_id,
                        "runbook_step",
                        phase=phase_name,
                        step_index=step_number,
                        title=step.title,
                        status="failed",
                        message=msg,
                        node_id=node_id,
                    )
                    raise RuntimeError(msg)

                finished_at = time.time()
                await set_progress_path(job_id, f"{step_path}.status", "completed")
                await set_progress_path(job_id, f"{step_path}.message", f"Executed over {actual_transport.upper()} on {node_id}.")
                await set_progress_path(job_id, f"{step_path}.finished_at", finished_at)
                await _publish_deploy_event(
                    job_id,
                    "runbook_step",
                    phase=phase_name,
                    step_index=step_number,
                    title=step.title,
                    status="completed",
                    node_id=node_id,
                    transport=actual_transport,
                )
                return {
                    "title": step.title,
                    "status": "completed",
                    "actor": step.actor,
                    "target": step.target,
                    "node_id": node_id,
                    "vm_name": vm_name,
                    "transport": actual_transport,
                    "host": remote_host,
                    "exit_status": exit_status,
                }

            finished_at = time.time()
            await set_progress_path(job_id, f"{step_path}.status", "manual")
            await set_progress_path(job_id, f"{step_path}.message", "No executable automation was provided for this step.")
            await set_progress_path(job_id, f"{step_path}.finished_at", finished_at)
            await _publish_deploy_event(
                job_id,
                "runbook_step",
                phase=phase_name,
                step_index=step_number,
                title=step.title,
                status="manual",
                message="No executable automation was provided for this step.",
            )
            return {
                "title": step.title,
                "status": "manual",
                "actor": step.actor,
                "target": step.target,
                "message": "No executable automation was provided for this step.",
            }

        target = _resolve_runbook_vm_name(step, vm_names_by_node_id)
        if not target:
            msg = f"Runbook step '{step.title}' does not target a deployed node."
            await set_progress_path(job_id, f"{step_path}.status", "failed")
            await set_progress_path(job_id, f"{step_path}.message", msg)
            await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
            await _publish_deploy_event(
                job_id,
                "runbook_step",
                phase=phase_name,
                step_index=step_number,
                title=step.title,
                status="failed",
                message=msg,
            )
            raise RuntimeError(msg)

        node_id, vm_name = target
        try:
            automation_steps = normalize_automation_steps(step.automation)
        except ValueError as exc:
            msg = f"Invalid runbook automation for '{step.title}': {exc}"
            await set_progress_path(job_id, f"{step_path}.status", "failed")
            await set_progress_path(job_id, f"{step_path}.message", msg)
            await set_progress_path(job_id, f"{step_path}.finished_at", time.time())
            await _publish_deploy_event(
                job_id,
                "runbook_step",
                phase=phase_name,
                step_index=step_number,
                title=step.title,
                status="failed",
                message=msg,
            )
            raise RuntimeError(msg) from exc

        async def _progress_cb(event: Dict[str, Any]):
            status = event.get("status")
            if status is not None:
                await set_progress_path(job_id, f"{step_path}.status", str(status))
            if "step" in event:
                await set_progress_path(job_id, f"{step_path}.automation_step", int(event["step"]))
            if "step_type" in event:
                await set_progress_path(job_id, f"{step_path}.automation_step_type", str(event["step_type"]))
            if "delay_seconds" in event:
                await set_progress_path(job_id, f"{step_path}.automation_delay_seconds", float(event["delay_seconds"]))
            if "ok" in event:
                await set_progress_path(job_id, f"{step_path}.last_ok", bool(event["ok"]))
            if "message" in event:
                await set_progress_path(job_id, f"{step_path}.message", str(event["message"]))
            if "key" in event:
                await set_progress_path(job_id, f"{step_path}.key", str(event["key"]))
            await _publish_deploy_event(
                job_id,
                "runbook_step",
                phase=phase_name,
                step_index=step_number,
                title=step.title,
                status=str(event.get("status") or "running"),
                node_id=node_id,
                step_type=event.get("step_type"),
                message=event.get("message"),
                key=event.get("key"),
            )

        ok = await execute_automation_steps(
            vm_name=vm_name,
            node_id=node_id,
            steps=automation_steps,
            send_text=vm_manager.send_text,
            send_key=vm_manager.send_key,
            progress_cb=_progress_cb,
        )
        finished_at = time.time()
        if not ok:
            msg = f"Runbook step '{step.title}' failed while executing automation."
            await set_progress_path(job_id, f"{step_path}.status", "failed")
            await set_progress_path(job_id, f"{step_path}.message", msg)
            await set_progress_path(job_id, f"{step_path}.finished_at", finished_at)
            await _publish_deploy_event(
                job_id,
                "runbook_step",
                phase=phase_name,
                step_index=step_number,
                title=step.title,
                status="failed",
                message=msg,
                node_id=node_id,
            )
            raise RuntimeError(msg)

        await set_progress_path(job_id, f"{step_path}.status", "completed")
        await set_progress_path(job_id, f"{step_path}.message", f"Executed on {node_id}.")
        await set_progress_path(job_id, f"{step_path}.finished_at", finished_at)
        await _publish_deploy_event(
            job_id,
            "runbook_step",
            phase=phase_name,
            step_index=step_number,
            title=step.title,
            status="completed",
            node_id=node_id,
            transport="console",
        )
        return {
            "title": step.title,
            "status": "completed",
            "actor": step.actor,
            "target": step.target,
            "node_id": node_id,
            "vm_name": vm_name,
            "transport": "console",
        }

    if execution_mode != "actor_parallel":
        phase_results: List[Dict[str, Any]] = []
        for index, step in enumerate(steps):
            phase_results.append(await _execute_step(index, step))

        await set_progress_path(job_id, f"runbook.{phase_name}.status", "completed")
        await _publish_deploy_event(job_id, "runbook_phase", phase=phase_name, status="completed", execution_mode=execution_mode)
        return phase_results

    actor_lanes = _build_runbook_actor_lanes(steps, vm_names_by_node_id)
    await set_progress_path(
        job_id,
        f"runbook.{phase_name}.lanes",
        {
            lane["key"]: {k: v for k, v in lane.items() if k != "steps"}
            for lane in actor_lanes
        },
    )
    await set_progress_path(job_id, f"runbook.{phase_name}.lane_count", len(actor_lanes))

    async def _execute_lane(lane: Dict[str, Any]) -> List[tuple[int, Dict[str, Any]]]:
        lane_path = f"runbook.{phase_name}.lanes.{lane['key']}"
        started_at = time.time()
        await set_progress_path(job_id, f"{lane_path}.status", "running")
        await set_progress_path(job_id, f"{lane_path}.started_at", started_at)
        await _publish_deploy_event(
            job_id,
            "runbook_lane",
            phase=phase_name,
            lane_key=lane["key"],
            lane_label=lane.get("label"),
            node_id=lane.get("node_id"),
            actor=lane.get("actor"),
            target=lane.get("target"),
            status="running",
            step_indexes=list(lane.get("step_indexes") or []),
        )

        lane_results: List[tuple[int, Dict[str, Any]]] = []
        try:
            for index, step in lane.get("steps") or []:
                lane_results.append((index, await _execute_step(index, step)))
        except Exception as exc:
            await set_progress_path(job_id, f"{lane_path}.status", "failed")
            await set_progress_path(job_id, f"{lane_path}.error", str(exc))
            await set_progress_path(job_id, f"{lane_path}.finished_at", time.time())
            await _publish_deploy_event(
                job_id,
                "runbook_lane",
                phase=phase_name,
                lane_key=lane["key"],
                lane_label=lane.get("label"),
                node_id=lane.get("node_id"),
                actor=lane.get("actor"),
                target=lane.get("target"),
                status="failed",
                message=str(exc),
            )
            raise

        await set_progress_path(job_id, f"{lane_path}.status", "completed")
        await set_progress_path(job_id, f"{lane_path}.finished_at", time.time())
        await _publish_deploy_event(
            job_id,
            "runbook_lane",
            phase=phase_name,
            lane_key=lane["key"],
            lane_label=lane.get("label"),
            node_id=lane.get("node_id"),
            actor=lane.get("actor"),
            target=lane.get("target"),
            status="completed",
        )
        return lane_results

    lane_outcomes = await asyncio.gather(*(_execute_lane(lane) for lane in actor_lanes), return_exceptions=True)
    lane_errors: List[str] = []
    phase_results_by_index: Dict[int, Dict[str, Any]] = {}

    for lane, outcome in zip(actor_lanes, lane_outcomes):
        if isinstance(outcome, Exception):
            lane_errors.append(f"{lane.get('label') or lane['key']}: {outcome}")
            continue
        for index, result in outcome:
            phase_results_by_index[index] = result

    if lane_errors:
        message = "; ".join(lane_errors)
        await set_progress_path(job_id, f"runbook.{phase_name}.status", "failed")
        await _publish_deploy_event(job_id, "runbook_phase", phase=phase_name, status="failed", execution_mode=execution_mode, message=message)
        raise RuntimeError(f"Runbook phase '{phase_name}' failed in actor lanes: {message}")

    phase_results = [phase_results_by_index[index] for index in sorted(phase_results_by_index)]

    await set_progress_path(job_id, f"runbook.{phase_name}.status", "completed")
    await _publish_deploy_event(job_id, "runbook_phase", phase=phase_name, status="completed", execution_mode=execution_mode)
    return phase_results


async def _run_runbook_job(
    job_id: str,
    deployment_id: str,
    topology: TopologyDeployRequest,
    current_user: AuthenticatedUser,
    phases: List[str],
    execution_mode: Literal["sequential", "actor_parallel"] = "actor_parallel",
    agent_mode: Literal["off", "prefer", "require"] = "off",
):
    runbook = topology.scenario.runbook if topology.scenario else None
    if not runbook:
        await update_job(
            job_id,
            status="failed",
            started_at=time.time(),
            finished_at=time.time(),
            message="Deployment does not include a runbook",
            result={"status": "error", "detail": "Deployment does not include a runbook"},
        )
        return

    await update_job(job_id, status="running", started_at=time.time(), message="Starting scenario run")
    await _publish_deploy_event(job_id, "deploy_status", status="running", phase="runbook", message="Starting scenario run")

    vm_names_by_node_id = _deployment_vm_names_by_node_id(topology, deployment_id)
    node_images_by_id = _topology_node_images_by_id(topology)
    deployment_record = _load_deployments().get(deployment_id)
    saved_node_hosts_by_id = _deployment_node_hosts(deployment_record) if isinstance(deployment_record, dict) else {}
    if isinstance(deployment_record, dict):
        for node_id, agent_state in _deployment_vm_agents(deployment_record).items():
            host = str(agent_state.get("host") or "").strip()
            if host and node_id not in saved_node_hosts_by_id:
                saved_node_hosts_by_id[node_id] = host
    creds_cache = _load_creds_cache()
    node_credentials_by_id = {
        node_id: creds_cache.get(vm_name) or {}
        for node_id, vm_name in vm_names_by_node_id.items()
    }
    slug = _network_slug(topology.scenario, suffix=(deployment_id.split("-")[0] if deployment_id else None))
    preferred_runbook_networks = _runbook_preferred_networks(topology, slug)
    requested_phases = _normalize_runbook_phases(phases)
    simulation_execution_mode = execution_mode if "simulation" in requested_phases else "sequential"
    simulation_vm_agents: Dict[str, Dict[str, Any]] = {}

    await update_progress(
        job_id,
        {
            "phase": "runbook",
            "job_kind": "runbook",
            "deployment_id": deployment_id,
            "owner_id": current_user.id,
            "owner_username": current_user.username,
            "nodes": {
                node.id: {
                    "label": node.label,
                    "status": "ready",
                    "vm_name": vm_names_by_node_id.get(node.id),
                }
                for node in topology.nodes
            },
            "runbook": _build_runbook_progress(runbook),
        },
    )
    await set_progress_path(job_id, "runbook.agent_mode", agent_mode)
    await set_progress_path(job_id, "runbook.simulation.execution_mode", simulation_execution_mode)

    if "setup" not in requested_phases:
        await set_progress_path(job_id, "runbook.setup.status", "skipped")
    if "simulation" not in requested_phases:
        await set_progress_path(job_id, "runbook.simulation.status", "skipped")

    setup_results: List[Dict[str, Any]] = []
    simulation_results: List[Dict[str, Any]] = []
    runbook_errors: List[Dict[str, Any]] = []

    try:
        if "setup" in requested_phases:
            try:
                setup_results = await _execute_runbook_phase(
                    job_id=job_id,
                    phase_name="setup",
                    deployment_id=deployment_id,
                    steps=list(runbook.setup_steps or []),
                    vm_names_by_node_id=vm_names_by_node_id,
                    node_images_by_id=node_images_by_id,
                    node_credentials_by_id=node_credentials_by_id,
                    preferred_networks=preferred_runbook_networks,
                    saved_node_hosts_by_id=saved_node_hosts_by_id,
                )
            except Exception as exc:
                runbook_errors.append({"phase": "setup", "message": str(exc)})
                await set_progress_path(job_id, "runbook.setup.error", str(exc))
                await set_progress_path(job_id, "runbook.setup.status", "failed")

        if "simulation" in requested_phases:
            if runbook_errors and "setup" in requested_phases:
                await set_progress_path(job_id, "runbook.simulation.status", "skipped")
            else:
                try:
                    simulation_vm_agents = await _ensure_runbook_vm_agents(
                        job_id=job_id,
                        deployment_id=deployment_id,
                        phase_name="simulation",
                        steps=list(runbook.simulation_steps or []),
                        vm_names_by_node_id=vm_names_by_node_id,
                        node_images_by_id=node_images_by_id,
                        node_credentials_by_id=node_credentials_by_id,
                        preferred_networks=preferred_runbook_networks,
                        agent_mode=agent_mode,
                    )
                    for node_id, agent_state in simulation_vm_agents.items():
                        host = str(agent_state.get("host") or "").strip()
                        if host:
                            saved_node_hosts_by_id[node_id] = host
                    simulation_results = await _execute_runbook_phase(
                        job_id=job_id,
                        phase_name="simulation",
                        deployment_id=deployment_id,
                        steps=list(runbook.simulation_steps or []),
                        vm_names_by_node_id=vm_names_by_node_id,
                        node_images_by_id=node_images_by_id,
                        node_credentials_by_id=node_credentials_by_id,
                        preferred_networks=preferred_runbook_networks,
                        execution_mode=simulation_execution_mode,
                        vm_agents_by_node_id=simulation_vm_agents,
                        agent_mode=agent_mode,
                        saved_node_hosts_by_id=saved_node_hosts_by_id,
                    )
                except Exception as exc:
                    runbook_errors.append({"phase": "simulation", "message": str(exc)})
                    await set_progress_path(job_id, "runbook.simulation.error", str(exc))
                    await set_progress_path(job_id, "runbook.simulation.status", "failed")

        runbook_status = "completed_with_errors" if runbook_errors else "completed"
        final_message = "Scenario run completed with warnings" if runbook_errors else "Scenario run completed"
        final_result_status = "scenario_run_processed_with_warnings" if runbook_errors else "scenario_run_processed"
        await set_progress_path(job_id, "runbook.status", runbook_status)
        await set_progress_path(job_id, "runbook.current_phase", None)
        await update_progress(job_id, {"phase": "done"})
        await update_job(
            job_id,
            status="completed",
            finished_at=time.time(),
            message=final_message,
            result={
                "status": final_result_status,
                "deployment_id": deployment_id,
                "runbook": {
                    "status": runbook_status,
                    "agent_mode": agent_mode,
                    "vm_agents": simulation_vm_agents,
                    "simulation_execution_mode": simulation_execution_mode,
                    "setup_results": setup_results,
                    "simulation_results": simulation_results,
                    "errors": runbook_errors,
                },
            },
        )
        await _publish_deploy_event(
            job_id,
            "deploy_status",
            status="completed_with_warnings" if runbook_errors else "completed",
            phase="done",
            message=final_message,
            deployment_id=deployment_id,
        )
    except Exception as exc:
        await update_job(
            job_id,
            status="failed",
            finished_at=time.time(),
            message=str(exc),
            result={"status": "error", "detail": str(exc), "deployment_id": deployment_id},
        )
        await _publish_deploy_event(job_id, "deploy_status", status="failed", phase="runbook", message=str(exc), deployment_id=deployment_id)


async def _run_deploy_job(job_id: str, topology: TopologyDeployRequest, current_user: AuthenticatedUser):
    await update_job(job_id, status="running", started_at=time.time(), message="Starting deployment")
    await _publish_deploy_event(job_id, "deploy_status", status="running", phase="downloads", message="Starting deployment")
    creds_cache = _load_creds_cache()
    deployment_prefix = _deployment_prefix(job_id)
    runbook = topology.scenario.runbook if topology.scenario else None
    await update_progress(
        job_id,
        {
            "phase": "downloads",
            "job_kind": "deploy",
            "deployment_id": job_id,
            "owner_id": current_user.id,
            "owner_username": current_user.username,
            "downloads": {},
            "nodes": {n.id: {"label": n.label, "status": "pending"} for n in topology.nodes},
            **({"runbook": _build_runbook_progress(runbook)} if runbook else {}),
        },
    )

    results: List[Dict[str, Any]] = []

    try:
        slug = _network_slug(topology.scenario, suffix=(job_id.split("-")[0] if job_id else None))
        node_networks = _plan_topology_network_assignments(topology, slug)
        preferred_runbook_networks = _runbook_preferred_networks(topology, slug)
        node_images_by_id = _topology_node_images_by_id(topology)

        # Pre-ensure any scenario sources referenced by nodes (cached; emits progress)
        sources = topology.scenario.sources if topology.scenario and topology.scenario.sources else {}

        # Determine which sources are relevant for this topology
        needed_sources: Dict[str, Any] = {}
        for node in topology.nodes:
            guess = _resolve_image_path(node.config.image)
            raw_src = sources.get(node.config.image) or sources.get(os.path.basename(guess))
            src = await resolve_verified_image_download_source(node.config.image, raw_src) if raw_src is not None else None
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
            await _publish_deploy_event(job_id, "deploy_status", status="running", phase="downloads", message="Downloading required images")
        for _name, src in needed_sources.items():
            await ensure_image(src, progress_cb=_progress_cb)

        # Create VMs
        await update_progress(job_id, {"phase": "vms"})
        await update_job(job_id, message="Creating virtual machines")
        await _publish_deploy_event(job_id, "deploy_status", status="running", phase="vms", message="Creating virtual machines")

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
            await _publish_deploy_event(
                job_id,
                "node_automation",
                node_id=node_id,
                status=event.get("status"),
                step=event.get("step"),
                step_type=event.get("step_type"),
                key=event.get("key"),
                message=event.get("message"),
            )

        vm_names_by_node_id: Dict[str, str] = {}
        node_credentials_by_id: Dict[str, Dict[str, str]] = {}
        node_automation_tasks: List[tuple[str, Any]] = []

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
                raw_src = topology.scenario.sources.get(node.config.image) or topology.scenario.sources.get(os.path.basename(guess))
                if raw_src is not None:
                    src = await resolve_verified_image_download_source(node.config.image, raw_src)

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
            vm_names_by_node_id[node.id] = vm_name

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
                    node_credentials_by_id[node.id] = creds
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
                    node_automation_tasks.append(
                        (
                            node.id,
                            execute_automation_steps(
                                vm_name=vm_name,
                                node_id=node.id,
                                steps=automation_steps,
                                send_text=vm_manager.send_text,
                                send_key=vm_manager.send_key,
                                progress_cb=_automation_progress,
                            ),
                        )
                    )
            else:
                await set_progress_path(job_id, f"nodes.{node.id}.status", "error")
                await set_progress_path(job_id, f"nodes.{node.id}.message", res.get("message") or "failed")

        try:
            _persist_deployment_record(job_id, topology, current_user, vm_names_by_node_id)
        except Exception as exc:
            logger.error("Failed to persist deployment record before runbook: %s", exc)

        if node_automation_tasks:
            await update_progress(job_id, {"phase": "node_automation"})
            await update_job(job_id, message="Waiting for installer automation")
            await _publish_deploy_event(job_id, "deploy_status", status="running", phase="node_automation", message="Waiting for installer automation")
            automation_results = await asyncio.gather(*(task for _node_id, task in node_automation_tasks), return_exceptions=True)
            for (node_id, _task), outcome in zip(node_automation_tasks, automation_results):
                if isinstance(outcome, Exception) or outcome is False:
                    msg = f"Installer automation failed for node '{node_id}'."
                    await set_progress_path(job_id, f"nodes.{node_id}.status", "error")
                    await set_progress_path(job_id, f"nodes.{node_id}.message", msg)
                    await _publish_deploy_event(job_id, "deploy_status", status="failed", phase="node_automation", message=msg, node_id=node_id)
                    raise RuntimeError(msg) if not isinstance(outcome, Exception) else outcome

        runbook_result: Optional[Dict[str, Any]] = None
        if runbook:
            await update_progress(job_id, {"phase": "runbook"})
            await update_job(job_id, message="Executing scenario runbook")
            await _publish_deploy_event(job_id, "deploy_status", status="running", phase="runbook", message="Executing scenario runbook")
            runbook_errors: List[Dict[str, Any]] = []
            setup_results: List[Dict[str, Any]] = []
            simulation_results: List[Dict[str, Any]] = []

            try:
                setup_results = await _execute_runbook_phase(
                    job_id=job_id,
                    phase_name="setup",
                    deployment_id=job_id,
                    steps=list(runbook.setup_steps or []),
                    vm_names_by_node_id=vm_names_by_node_id,
                    node_images_by_id=node_images_by_id,
                    node_credentials_by_id=node_credentials_by_id,
                    preferred_networks=preferred_runbook_networks,
                )
            except Exception as exc:
                runbook_errors.append({"phase": "setup", "message": str(exc)})
                await set_progress_path(job_id, "runbook.setup.error", str(exc))
                await set_progress_path(job_id, "runbook.setup.status", "failed")

            if not runbook_errors:
                try:
                    simulation_results = await _execute_runbook_phase(
                        job_id=job_id,
                        phase_name="simulation",
                        deployment_id=job_id,
                        steps=list(runbook.simulation_steps or []),
                        vm_names_by_node_id=vm_names_by_node_id,
                        node_images_by_id=node_images_by_id,
                        node_credentials_by_id=node_credentials_by_id,
                        preferred_networks=preferred_runbook_networks,
                    )
                except Exception as exc:
                    runbook_errors.append({"phase": "simulation", "message": str(exc)})
                    await set_progress_path(job_id, "runbook.simulation.error", str(exc))
                    await set_progress_path(job_id, "runbook.simulation.status", "failed")
            elif runbook.simulation_steps:
                await set_progress_path(job_id, "runbook.simulation.status", "skipped")

            runbook_status = "completed_with_errors" if runbook_errors else "completed"
            await set_progress_path(job_id, "runbook.status", runbook_status)
            await set_progress_path(job_id, "runbook.current_phase", None)
            runbook_result = {
                "status": runbook_status,
                "setup_results": setup_results,
                "simulation_results": simulation_results,
                "errors": runbook_errors,
            }

        os.makedirs(os.path.dirname(CREDS_CACHE_PATH), exist_ok=True)
        with open(CREDS_CACHE_PATH, "w") as f:
            json.dump(creds_cache, f)

        # Save deployment record
        try:
            extra: Dict[str, Any] = {}
            if runbook_result and isinstance(runbook_result, dict):
                vm_agents = runbook_result.get("vm_agents") if isinstance(runbook_result.get("vm_agents"), dict) else {}
                if vm_agents:
                    extra["vm_agents"] = vm_agents
                node_hosts = {
                    str(entry.get("node_id")): str(entry.get("host"))
                    for entry in list(runbook_result.get("setup_results") or []) + list(runbook_result.get("simulation_results") or [])
                    if isinstance(entry, dict) and entry.get("node_id") and entry.get("host")
                }
                if node_hosts:
                    extra["node_hosts"] = node_hosts
            _persist_deployment_record(job_id, topology, current_user, vm_names_by_node_id, extra)
        except Exception as e:
            logger.error("Failed to save deployment record: %s", e)

        final_message = "Deployment completed"
        final_result_status = "deployment_processed"
        if runbook_result and runbook_result.get("errors"):
            final_message = "Deployment completed with runbook warnings"
            final_result_status = "deployment_processed_with_warnings"

        await update_job(
            job_id,
            status="completed",
            finished_at=time.time(),
            message=final_message,
            result={"status": final_result_status, "results": results, **({"runbook": runbook_result} if runbook_result else {})},
        )
        await update_progress(job_id, {"phase": "done"})
        await _publish_deploy_event(
            job_id,
            "deploy_status",
            status="completed_with_warnings" if runbook_result and runbook_result.get("errors") else "completed",
            phase="done",
            message=final_message,
        )
    except Exception as e:
        await _publish_deploy_event(job_id, "deploy_status", status="failed", phase=(await get_job(job_id)).progress.get("phase") if await get_job(job_id) else None, message=str(e))
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


@router.post("/deployments/{deployment_id}/runbook-jobs", response_model=DeployJobStartResponse)
async def start_runbook_job(
    deployment_id: str,
    request: RunbookJobRequest,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
):
    deployment = _get_deployment_for_user(deployment_id, current_user)
    topology = _topology_from_deployment_record(deployment)
    if not topology.scenario or not topology.scenario.runbook:
        raise HTTPException(status_code=400, detail="Deployment does not include a runbook")

    job = new_job(
        initial_progress={
            "phase": "queued",
            "job_kind": "runbook",
            "deployment_id": deployment_id,
            "owner_id": current_user.id,
            "owner_username": current_user.username,
        }
    )
    asyncio.create_task(
        _run_runbook_job(
            job.id,
            deployment_id,
            topology,
            current_user,
            list(request.phases or ["simulation"]),
            request.execution_mode,
            request.agent_mode,
        )
    )
    return {"job_id": job.id}


async def _resolve_vm_agent_for_api(
    *,
    deployment_id: str,
    node_id: str,
    topology: TopologyDeployRequest,
    allow_bootstrap: bool,
) -> Dict[str, Any]:
    vm_names_by_node_id = _deployment_vm_names_by_node_id(topology, deployment_id)
    vm_name = vm_names_by_node_id.get(node_id)
    if not vm_name:
        raise HTTPException(status_code=404, detail="Node not found in deployment")

    creds_cache = _load_creds_cache()
    node_credentials_by_id = {
        candidate_node_id: creds_cache.get(candidate_vm_name) or {}
        for candidate_node_id, candidate_vm_name in vm_names_by_node_id.items()
    }
    slug = _network_slug(topology.scenario, suffix=(deployment_id.split("-")[0] if deployment_id else None))
    preferred_networks = _runbook_preferred_networks(topology, slug)

    try:
        return await _ensure_vm_agent_for_node(
            deployment_id=deployment_id,
            node_id=node_id,
            vm_name=vm_name,
            node_credentials_by_id=node_credentials_by_id,
            preferred_networks=preferred_networks,
            node_ip_cache={},
            allow_bootstrap=allow_bootstrap,
        )
    except RuntimeError as exc:
        status_code = 503 if not allow_bootstrap else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/deployments/{deployment_id}/vm-agents")
async def list_deployment_vm_agents(
    deployment_id: str,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
):
    deployment = _get_deployment_for_user(deployment_id, current_user)
    return {"agents": _deployment_vm_agents(deployment)}


@router.post("/deployments/{deployment_id}/vm-agents/{node_id}/tasks")
async def start_vm_agent_task(
    deployment_id: str,
    node_id: str,
    request: VmAgentTaskRequest,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
):
    deployment = _get_deployment_for_user(deployment_id, current_user)
    topology = _topology_from_deployment_record(deployment)
    agent_state = await _resolve_vm_agent_for_api(
        deployment_id=deployment_id,
        node_id=node_id,
        topology=topology,
        allow_bootstrap=True,
    )
    try:
        result = await _execute_vm_agent_task(
            agent_state=agent_state,
            command=request.command,
            timeout_seconds=max(1.0, float(request.timeout_seconds or 0.0)),
            background=request.background,
            cwd=request.cwd,
            environment=request.environment,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"VM agent task failed: {exc}") from exc

    return {
        "deployment_id": deployment_id,
        "node_id": node_id,
        "agent": {
            "host": agent_state.get("host"),
            "port": agent_state.get("port"),
        },
        "task": result,
    }


@router.get("/deployments/{deployment_id}/vm-agents/{node_id}/tasks/{task_id}")
async def get_vm_agent_task_status(
    deployment_id: str,
    node_id: str,
    task_id: str,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
):
    deployment = _get_deployment_for_user(deployment_id, current_user)
    topology = _topology_from_deployment_record(deployment)
    agent_state = await _resolve_vm_agent_for_api(
        deployment_id=deployment_id,
        node_id=node_id,
        topology=topology,
        allow_bootstrap=False,
    )
    try:
        task = await _get_vm_agent_task(agent_state, task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read VM agent task: {exc}") from exc

    return {
        "deployment_id": deployment_id,
        "node_id": node_id,
        "task": task,
    }


@router.delete("/deployments/{deployment_id}/vm-agents/{node_id}/tasks/{task_id}")
async def stop_vm_agent_task(
    deployment_id: str,
    node_id: str,
    task_id: str,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
):
    deployment = _get_deployment_for_user(deployment_id, current_user)
    topology = _topology_from_deployment_record(deployment)
    agent_state = await _resolve_vm_agent_for_api(
        deployment_id=deployment_id,
        node_id=node_id,
        topology=topology,
        allow_bootstrap=False,
    )
    try:
        task = await _stop_vm_agent_task(agent_state, task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop VM agent task: {exc}") from exc

    return {
        "deployment_id": deployment_id,
        "node_id": node_id,
        "task": task,
    }


@router.get("/topology/deploy-jobs/{job_id}", response_model=DeployJobStatusResponse)
async def get_deploy_job(job_id: str, current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and (job.progress or {}).get("owner_id") != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this deployment job")
    return _job_to_response(job)


@router.websocket("/ws/deploy-jobs/{job_id}")
async def deploy_job_events_ws(websocket: WebSocket, job_id: str):
    try:
        current_user = get_current_user_from_websocket(websocket)
        job = await get_job(job_id)
        if not job:
            await websocket.close(code=4404)
            return
        if current_user.role != "admin" and (job.progress or {}).get("owner_id") != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this deployment job")
    except HTTPException as exc:
        await websocket.close(code=4403 if exc.status_code == status.HTTP_403_FORBIDDEN else 4401)
        return

    await websocket.accept()
    await event_bus.connect(job_id, websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await event_bus.disconnect(job_id, websocket)
    except Exception:
        await event_bus.disconnect(job_id, websocket)

@router.get("/topology/deploy")
async def deploy_topology_get():
    return {"message": "You sent a GET request. Please use POST to deploy."}

