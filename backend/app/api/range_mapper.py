from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.range_mapper import (
    hosts_to_builder_topology,
    hosts_to_yaml_model,
    nmap_scan,
    parse_nmap_xml,
    load_device_profiles,
    scanning_enabled,
    validate_target,
)

router = APIRouter()


class RangeScanRequest(BaseModel):
    target: str = Field(..., description="CIDR or single IP, e.g. 192.168.1.0/24")
    top_ports: int = Field(200, ge=1, le=5000)
    nmap_extra: Optional[List[str]] = Field(
        default=None,
        description="Extra args inserted after 'nmap' (dangerous; use with care)",
    )
    allow_public: bool = Field(
        default=False,
        description="Allow scanning non-private targets (blocked by default)",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, validate and return the planned commands/paths without scanning",
    )
    scenario_name: str = Field(default="Imported Network")
    network_prefix: Optional[str] = None


class RangeParseRequest(BaseModel):
    xml_path: str = Field(..., description="Path to an existing Nmap XML file on the server")
    scenario_name: str = Field(default="Imported Network")
    network_prefix: Optional[str] = None


@router.post("/range-mapper/scan")
async def scan_and_convert(req: RangeScanRequest) -> Dict[str, Any]:
    try:
        validate_target(req.target, allow_public=req.allow_public)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    workdir = Path(os.getenv("RANGE_MAPPER_WORKDIR", "/tmp/range_mapper_out"))

    if req.dry_run:
        # Return a conservative approximation of what would run.
        discover_cmd = ["nmap", "-sn", req.target, "-oX", "<workdir>/discovery_<ts>.xml"]
        services_cmd = [
            "nmap",
            "-sS",
            "-sV",
            "-O",
            "--osscan-guess",
            "--top-ports",
            str(req.top_ports),
            "--open",
            req.target,
            "-oX",
            "<workdir>/services_<ts>.xml",
        ]
        if req.nmap_extra:
            discover_cmd[1:1] = req.nmap_extra
            services_cmd[1:1] = req.nmap_extra
        return {
            "dry_run": True,
            "target": req.target,
            "workdir": str(workdir),
            "commands": {"discovery": discover_cmd, "services": services_cmd},
        }

    if not scanning_enabled():
        raise HTTPException(
            status_code=403,
            detail="Range mapper scanning is disabled. Set RANGE_MAPPER_ENABLE=1 to enable.",
        )

    try:
        paths = nmap_scan(
            req.target,
            workdir=workdir,
            top_ports=req.top_ports,
            nmap_extra=req.nmap_extra,
        )
        hosts = parse_nmap_xml(paths["services_xml"])
        return {
            "hosts": hosts_to_yaml_model(hosts),
            "topology": hosts_to_builder_topology(
                hosts,
                scenario_name=req.scenario_name,
                network_prefix=req.network_prefix,
            ),
            "artifacts": {
                "discovery_xml": str(paths["discovery_xml"]),
                "services_xml": str(paths["services_xml"]),
            },
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {e}")


@router.post("/range-mapper/parse")
async def parse_and_convert(req: RangeParseRequest) -> Dict[str, Any]:
    xml_path = Path(req.xml_path)
    if not xml_path.exists():
        raise HTTPException(status_code=404, detail="XML file not found")

    try:
        hosts = parse_nmap_xml(xml_path)
        return {
            "hosts": hosts_to_yaml_model(hosts),
            "topology": hosts_to_builder_topology(
                hosts,
                scenario_name=req.scenario_name,
                network_prefix=req.network_prefix,
            ),
            "artifacts": {"services_xml": str(xml_path)},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {e}")


@router.post("/range-mapper/import-xml")
async def import_xml(file: UploadFile = File(...), scenario_name: str = "Imported Network", network_prefix: Optional[str] = None) -> Dict[str, Any]:
    """Upload an Nmap XML file and convert it into a builder topology."""

    filename = file.filename or "nmap.xml"
    if not filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Please upload an .xml file")

    workdir = Path(os.getenv("RANGE_MAPPER_WORKDIR", "/tmp/range_mapper_out"))
    workdir.mkdir(parents=True, exist_ok=True)
    dst = workdir / f"upload_{int(time.time())}_{Path(filename).name}"

    try:
        content = await file.read()
        dst.write_bytes(content)
        hosts = parse_nmap_xml(dst)
        return {
            "hosts": hosts_to_yaml_model(hosts),
            "topology": hosts_to_builder_topology(hosts, scenario_name=scenario_name, network_prefix=network_prefix),
            "artifacts": {"services_xml": str(dst)},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")


@router.get("/range-mapper/profiles")
async def list_profiles() -> Dict[str, Any]:
    return {"profiles": load_device_profiles()}
