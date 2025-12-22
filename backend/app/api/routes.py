from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.core.vm_manager import vm_manager, WORK_DIR
import os
import glob
from app.core.image_manager import ensure_image
import asyncio
import time
import hashlib

from app.core.deploy_jobs import new_job, get_job, update_job, update_progress, set_progress_path

router = APIRouter()


def _host_images_dir() -> str:
    host_work_dir = os.environ.get("HOST_WORK_DIR", WORK_DIR)
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
        patterns = ["kali-linux-*-qemu-amd64.qcow2", "kali*.qcow2"]
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
    else:
        patterns = [f"{image_key}.qcow2", f"{image_key}.img"]

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
    except Exception:
        return False
    return ("opnsense" in img) or ("opnsense" in lbl)

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

@router.get("/vms", response_model=List[VMResponse])
async def get_vms():
    try:
        return vm_manager.list_domains()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/vms")
async def create_vm(vm: VMCreateRequest):
    if not vm.image_path and not vm.iso_path:
        raise HTTPException(status_code=400, detail="Either image_path or iso_path must be provided")
        
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
    return result

@router.post("/vms/{name}/start")
async def start_vm(name: str):
    if vm_manager.start_vm(name):
        return {"status": "started"}
    raise HTTPException(status_code=404, detail="VM not found or could not be started")

@router.post("/vms/{name}/stop")
async def stop_vm(name: str):
    if vm_manager.stop_vm(name):
        return {"status": "stopped"}
    raise HTTPException(status_code=404, detail="VM not found or could not be stopped")

@router.delete("/vms/{name}")
async def delete_vm(name: str):
    if vm_manager.delete_vm(name):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="VM not found or could not be deleted")

class TopologyNodeConfig(BaseModel):
    image: str
    cpu: int
    ram: int
    assets: List[Dict[str, str]]
    # Optional automation hooks for ISO installs (e.g., send keys/text).
    automation: Optional[Dict[str, Any]] = None

class TopologyNode(BaseModel):
    id: str
    label: str
    config: TopologyNodeConfig

class TopologyEdge(BaseModel):
    source: str
    target: str

class ScenarioConfig(BaseModel):
    name: str
    team: str
    objective: str
    difficulty: str
    # Optional mapping of image keys/filenames -> download source
    # Example:
    #   sources: {
    #     "xubuntu-24.04.3-minimal-amd64.iso": "https://.../xubuntu.iso",
    #     "kali-linux": {"url": "https://.../kali.iso", "filename": "kali.iso"}
    #   }
    sources: Optional[Dict[str, object]] = None

class TopologyDeployRequest(BaseModel):
    scenario: Optional[ScenarioConfig] = None
    nodes: List[TopologyNode]
    edges: List[TopologyEdge]

@router.post("/topology/deploy")
async def deploy_topology(topology: TopologyDeployRequest):
    results = []
    
    # Log scenario deployment
    if topology.scenario:
        print(f"Deploying Scenario: {topology.scenario.name} ({topology.scenario.difficulty}) for {topology.scenario.team} team.")
    
    # Create/ensure networks so edge-connected components can talk.
    # If a component contains an OPNsense node, we create an isolated LAN network (no DHCP/NAT)
    # and attach OPNsense with WAN+LAN, while other nodes attach to LAN only.
    scenario_name = (topology.scenario.name if topology.scenario else "topology")
    slug = _slugify(scenario_name)
    node_ids = [n.id for n in topology.nodes]
    comp_map = _connected_components(node_ids, topology.edges)
    max_comp = max(comp_map.values()) if comp_map else 0

    opnsense_nodes = {n.id for n in topology.nodes if _is_opnsense_node(n)}

    for cid in range(0, max_comp + 1):
        members = [nid for nid, cc in comp_map.items() if cc == cid]
        has_opnsense = any(nid in opnsense_nodes for nid in members)

        if has_opnsense:
            lan_name = f"cyberange-{slug}-lan-c{cid}"
            h = hashlib.sha1(lan_name.encode("utf-8")).hexdigest()[:8]
            bridge = f"cr{h}{cid}"[:15]
            if not vm_manager.ensure_isolated_network(lan_name, bridge):
                raise HTTPException(status_code=500, detail=f"Failed to create LAN network {lan_name}")
        else:
            net_name = f"cyberange-{slug}-c{cid}"
            h = hashlib.sha1(net_name.encode("utf-8")).hexdigest()[:8]
            bridge = f"cr{h}{cid}"[:15]
            third = 100 + cid
            if third > 250:
                raise HTTPException(status_code=400, detail="Topology too large: too many network segments")
            gw = f"192.168.{third}.1"
            if not vm_manager.ensure_network(net_name, bridge, gw):
                raise HTTPException(status_code=500, detail=f"Failed to create network {net_name}")

    for node in topology.nodes:
        packages = []
        runcmds = []
        for asset in node.config.assets:
            if asset['type'] == 'package':
                packages.append(asset['value'])
            elif asset['type'] == 'command':
                runcmds.append(asset['value'])
        
        packages_str = "\n".join([f"  - {p}" for p in packages])
        
        cloud_init = {
            "username": "user",
            "password": "password",
            "packages": packages_str,
            "runcmd": runcmds
        }
        
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
            # Sanitize name
            safe_name = "".join(c for c in node.label if c.isalnum() or c in ('-', '_')).strip()
            if not safe_name:
                safe_name = f"vm_{node.id}"

            cid = comp_map.get(node.id, 0)

            members = [nid for nid, cc in comp_map.items() if cc == cid]
            has_opnsense = any(nid in opnsense_nodes for nid in members)
            if has_opnsense:
                lan_name = f"cyberange-{slug}-lan-c{cid}"
                nets = ["default", lan_name] if node.id in opnsense_nodes else [lan_name]
            else:
                net_name = f"cyberange-{slug}-c{cid}"
                nets = [net_name]
            
            res = vm_manager.create_vm(
                name=f"{safe_name}_{node.id}",
                memory_mb=node.config.ram,
                vcpus=node.config.cpu,
                image_path=None if image_path.lower().endswith(".iso") else image_path,
                iso_path=_host_path_for_container_image(image_path) if image_path.lower().endswith(".iso") else None,
                cloud_init=None if image_path.lower().endswith(".iso") else cloud_init,
                network_names=nets,
            )
            results.append(res)
        except Exception as e:
            results.append({"status": "error", "message": str(e), "node": node.label})
            
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


async def _run_deploy_job(job_id: str, topology: TopologyDeployRequest):
    await update_job(job_id, status="running", started_at=time.time(), message="Starting deployment")
    await update_progress(
        job_id,
        {
            "phase": "downloads",
            "downloads": {},
            "nodes": {n.id: {"label": n.label, "status": "pending"} for n in topology.nodes},
        },
    )

    results: List[Dict[str, Any]] = []

    try:
        # Create/ensure networks so edge-connected components can talk.
        # If a component contains an OPNsense node, we create an isolated LAN network (no DHCP/NAT)
        # and attach OPNsense with WAN+LAN, while other nodes attach to LAN only.
        scenario_name = (topology.scenario.name if topology.scenario else "topology")
        slug = _slugify(scenario_name)
        node_ids = [n.id for n in topology.nodes]
        comp_map = _connected_components(node_ids, topology.edges)
        max_comp = max(comp_map.values()) if comp_map else 0

        opnsense_nodes = {n.id for n in topology.nodes if _is_opnsense_node(n)}
        for cid in range(0, max_comp + 1):
            members = [nid for nid, cc in comp_map.items() if cc == cid]
            has_opnsense = any(nid in opnsense_nodes for nid in members)
            if has_opnsense:
                lan_name = f"cyberange-{slug}-lan-c{cid}"
                h = hashlib.sha1(lan_name.encode("utf-8")).hexdigest()[:8]
                bridge = f"cr{h}{cid}"[:15]
                ok = vm_manager.ensure_isolated_network(lan_name, bridge)
                if not ok:
                    raise RuntimeError(f"Failed to create LAN network {lan_name}")
            else:
                net_name = f"cyberange-{slug}-c{cid}"
                h = hashlib.sha1(net_name.encode("utf-8")).hexdigest()[:8]
                bridge = f"cr{h}{cid}"[:15]
                third = 100 + cid
                if third > 250:
                    raise RuntimeError("Topology too large: too many network segments")
                gw = f"192.168.{third}.1"
                ok = vm_manager.ensure_network(net_name, bridge, gw)
                if not ok:
                    raise RuntimeError(f"Failed to create network {net_name}")

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

        async def _schedule_send_text(vm_name: str, node_id: str, text: str, delay_seconds: float, retries: int, retry_delay_seconds: float):
            await set_progress_path(job_id, f"nodes.{node_id}.automation.status", "scheduled")
            await set_progress_path(job_id, f"nodes.{node_id}.automation.delay_seconds", delay_seconds)
            await asyncio.sleep(max(0.0, delay_seconds))
            for attempt in range(1, max(1, retries) + 1):
                await set_progress_path(job_id, f"nodes.{node_id}.automation.status", f"sending ({attempt}/{max(1, retries)})")
                ok = vm_manager.send_text(vm_name, text)
                await set_progress_path(job_id, f"nodes.{node_id}.automation.last_ok", bool(ok))
                if ok:
                    await set_progress_path(job_id, f"nodes.{node_id}.automation.status", "sent")
                    return
                if attempt < max(1, retries):
                    await asyncio.sleep(max(0.0, retry_delay_seconds))
            await set_progress_path(job_id, f"nodes.{node_id}.automation.status", "failed")

        for node in topology.nodes:
            await set_progress_path(job_id, f"nodes.{node.id}.status", "creating")

            # Build cloud-init from node assets (same as sync deploy)
            packages = []
            runcmds = []
            for asset in node.config.assets:
                if asset['type'] == 'package':
                    packages.append(asset['value'])
                elif asset['type'] == 'command':
                    runcmds.append(asset['value'])

            packages_str = "\n".join([f"  - {p}" for p in packages])
            cloud_init = {
                "username": "user",
                "password": "password",
                "packages": packages_str,
                "runcmd": runcmds
            }

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

            safe_name = "".join(c for c in node.label if c.isalnum() or c in ('-', '_')).strip()
            if not safe_name:
                safe_name = f"vm_{node.id}"

            cid = comp_map.get(node.id, 0)

            members = [nid for nid, cc in comp_map.items() if cc == cid]
            has_opnsense = any(nid in opnsense_nodes for nid in members)
            if has_opnsense:
                lan_name = f"cyberange-{slug}-lan-c{cid}"
                nets = ["default", lan_name] if node.id in opnsense_nodes else [lan_name]
            else:
                net_name = f"cyberange-{slug}-c{cid}"
                nets = [net_name]

            res = vm_manager.create_vm(
                name=f"{safe_name}_{node.id}",
                memory_mb=node.config.ram,
                vcpus=node.config.cpu,
                image_path=None if image_path.lower().endswith(".iso") else image_path,
                iso_path=_host_path_for_container_image(image_path) if image_path.lower().endswith(".iso") else None,
                cloud_init=None if image_path.lower().endswith(".iso") else cloud_init,
                network_names=nets,
            )
            results.append({**res, "node": node.label})
            if res.get("status") == "success":
                await set_progress_path(job_id, f"nodes.{node.id}.status", "running")

                # Optional automation for ISO installs (e.g., Security Onion prompt).
                automation = node.config.automation or {}
                if image_path.lower().endswith(".iso") and isinstance(automation, dict):
                    if automation.get("type") == "send_text":
                        text = str(automation.get("text") or "")
                        if text:
                            delay_seconds = float(automation.get("delay_seconds") or 45)
                            retries = int(automation.get("retries") or 3)
                            retry_delay_seconds = float(automation.get("retry_delay_seconds") or 15)
                            asyncio.create_task(
                                _schedule_send_text(
                                    vm_name=f"{safe_name}_{node.id}",
                                    node_id=node.id,
                                    text=text,
                                    delay_seconds=delay_seconds,
                                    retries=retries,
                                    retry_delay_seconds=retry_delay_seconds,
                                )
                            )
            else:
                await set_progress_path(job_id, f"nodes.{node.id}.status", "error")
                await set_progress_path(job_id, f"nodes.{node.id}.message", res.get("message") or "failed")

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
async def start_deploy_job(topology: TopologyDeployRequest):
    job = new_job(initial_progress={"phase": "queued"})
    # Start background task
    asyncio.create_task(_run_deploy_job(job.id, topology))
    return {"job_id": job.id}


@router.get("/topology/deploy-jobs/{job_id}", response_model=DeployJobStatusResponse)
async def get_deploy_job(job_id: str):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)

@router.get("/topology/deploy")
async def deploy_topology_get():
    return {"message": "You sent a GET request. Please use POST to deploy."}

