from __future__ import annotations

import ipaddress
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from functools import lru_cache
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class Port:
    port: int
    proto: str
    service: Optional[str] = None
    fingerprint: Optional[Dict[str, str]] = None


@dataclass
class Host:
    id: str
    ip: str
    mac: Optional[str] = None
    hostnames: Optional[List[str]] = None
    os_guess: Optional[str] = None
    roles: Optional[List[str]] = None
    open_ports: Optional[List[Port]] = None


def _require_binary(binary: str) -> None:
    from shutil import which

    if which(binary) is None:
        raise RuntimeError(f"Required binary '{binary}' not found in PATH")


def _ip_to_id(ip: str) -> str:
    return f"host-{ip.replace('.', '-') }"


def _sorted_ports(ports: List[Port]) -> List[Port]:
    return sorted(ports, key=lambda p: (p.proto, p.port))


def infer_roles(ports: List[Port]) -> List[str]:
    roles = set()
    for p in ports:
        s = (p.service or "").lower()
        if p.port in (80, 443) or s in ("http", "https"):
            roles.add("web")
        if p.port == 22 or s == "ssh":
            roles.add("ssh")
        if p.port in (445, 139) or s in ("microsoft-ds", "netbios-ssn"):
            roles.add("fileshare")
        if p.port == 53 or s in ("domain", "dns"):
            roles.add("dns")
        if p.port == 3389 or s in ("ms-wbt-server", "rdp"):
            roles.add("rdp")
        if p.port in (3306, 5432) or s in ("mysql", "postgresql"):
            roles.add("database")
        if p.port in (1900, 554, 8008, 8009) or s in ("ssdp", "rtsp"):
            roles.add("iot")
    return sorted(roles)


def parse_nmap_xml(xml_path: Path) -> List[Host]:
    tree = ET.parse(str(xml_path))
    root = tree.getroot()

    hosts: List[Host] = []

    for h in root.findall("host"):
        status = h.find("status")
        if status is not None and status.get("state") != "up":
            continue

        ipv4: Optional[str] = None
        mac: Optional[str] = None
        for addr in h.findall("address"):
            atype = addr.get("addrtype")
            if atype == "ipv4":
                ipv4 = addr.get("addr")
            elif atype == "mac":
                mac = addr.get("addr")

        if not ipv4:
            continue

        hostnames: List[str] = []
        hn = h.find("hostnames")
        if hn is not None:
            for name in hn.findall("hostname"):
                n = name.get("name")
                if n:
                    hostnames.append(n)

        os_guess: Optional[str] = None
        os_el = h.find("os")
        if os_el is not None:
            match = os_el.find("osmatch")
            if match is not None and match.get("name"):
                os_guess = match.get("name")

        ports: List[Port] = []
        ports_el = h.find("ports")
        if ports_el is not None:
            for p in ports_el.findall("port"):
                proto = p.get("protocol") or "tcp"
                portid = p.get("portid")
                if portid is None:
                    continue

                state_el = p.find("state")
                if state_el is None or state_el.get("state") != "open":
                    continue

                service_el = p.find("service")
                service = None
                product = None
                version = None
                extrainfo = None

                if service_el is not None:
                    service = service_el.get("name")
                    product = service_el.get("product")
                    version = service_el.get("version")
                    extrainfo = service_el.get("extrainfo")

                fingerprint = (
                    {
                        k: v
                        for k, v in {
                            "product": product,
                            "version": version,
                            "extrainfo": extrainfo,
                        }.items()
                        if v
                    }
                    or None
                )

                ports.append(
                    Port(
                        port=int(portid),
                        proto=proto,
                        service=service,
                        fingerprint=fingerprint,
                    )
                )

        ports = _sorted_ports(ports)
        roles = infer_roles(ports) if ports else []

        hosts.append(
            Host(
                id=_ip_to_id(ipv4),
                ip=ipv4,
                mac=mac,
                hostnames=hostnames or None,
                os_guess=os_guess,
                roles=roles or None,
                open_ports=ports or None,
            )
        )

    hosts.sort(key=lambda x: x.ip)
    return hosts


def hosts_to_yaml_model(hosts: List[Host]) -> Dict[str, Any]:
    out_hosts: List[Dict[str, Any]] = []
    for h in hosts:
        d = asdict(h)
        if h.open_ports:
            d["open_ports"] = [asdict(p) for p in h.open_ports]
        out_hosts.append(d)
    return {"hosts": out_hosts}


def _guess_image(host: Host) -> str:
    os_guess = (host.os_guess or "").lower()
    roles = set((host.roles or []))

    # NOTE: these are just keys; user can adjust in the builder.
    if "windows" in os_guess or "rdp" in roles:
        return "windows-10"
    if "android" in os_guess:
        return "android"
    if "apple" in os_guess or "ios" in os_guess or "mac os" in os_guess:
        return "macos"
    if "iot" in roles:
        return "ubuntu-20.04"
    if "web" in roles:
        return "ubuntu-20.04"
    return "ubuntu-20.04"


def _guess_resources(host: Host) -> Dict[str, int]:
    roles = set((host.roles or []))
    os_guess = (host.os_guess or "").lower()

    if "iot" in roles:
        return {"cpu": 1, "ram": 512}
    if "windows" in os_guess:
        return {"cpu": 2, "ram": 4096}
    return {"cpu": 2, "ram": 2048}


def hosts_to_builder_topology(
    hosts: List[Host],
    *,
    scenario_name: str = "Imported Network",
    network_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a NetworkBuilder-compatible topology.

    Limitation: Nmap doesn't provide L2 topology. We attach all nodes to a single gateway.
    """

    router_id = "router"
    nodes: List[Dict[str, Any]] = [
        {
            "id": router_id,
            "label": "Gateway",
            "position": {"x": 0, "y": 0},
            "config": {"image": "openwrt", "cpu": 1, "ram": 512, "assets": []},
        }
    ]

    edges: List[Dict[str, Any]] = []

    cols = 4
    spacing_x = 260
    spacing_y = 180

    profiles = load_device_profiles()

    for idx, h in enumerate(hosts):
        row = idx // cols
        col = idx % cols

        label_parts = [h.ip]
        if h.hostnames:
            label_parts.append(h.hostnames[0])
        if h.roles:
            label_parts.append("/".join(h.roles[:2]))
        label = " - ".join(label_parts)

        res = _guess_resources(h)
        image = _guess_image(h)

        profile = select_device_profile(h, profiles)
        profile_name = profile.get("name") if profile else None
        profile_cfg = (profile.get("config") if profile else None) or {}

        node_cpu = int(profile_cfg.get("cpu") or res["cpu"])
        node_ram = int(profile_cfg.get("ram") or res["ram"])
        node_image = str(profile_cfg.get("image") or image)
        node_assets = profile_cfg.get("assets")
        if not isinstance(node_assets, list):
            node_assets = []

        nodes.append(
            {
                "id": h.id,
                "label": label,
                "position": {"x": (col + 1) * spacing_x, "y": (row + 1) * spacing_y},
                "config": {
                    "image": node_image,
                    "cpu": node_cpu,
                    "ram": node_ram,
                    "assets": node_assets,
                },
                "meta": {
                    "ip": h.ip,
                    "mac": h.mac,
                    "os_guess": h.os_guess,
                    "roles": h.roles,
                    "open_ports": [asdict(p) for p in (h.open_ports or [])],
                    "profile": profile_name,
                },
            }
        )
        edges.append({"source": router_id, "target": h.id})

    scenario: Dict[str, Any] = {
        "name": scenario_name,
        "team": "blue",
        "objective": "Imported from Nmap scan",
        "difficulty": "easy",
        "network_prefix": network_prefix,
    }

    openwrt_url = os.getenv("OPENWRT_IMAGE_URL")
    if openwrt_url:
        openwrt_filename = os.getenv("OPENWRT_IMAGE_FILENAME") or "openwrt.img.gz"
        openwrt_output = os.getenv("OPENWRT_IMAGE_OUTPUT") or "openwrt.img"
        scenario["sources"] = {
            **(scenario.get("sources") or {}),
            "openwrt": {
                "url": openwrt_url,
                "filename": openwrt_filename,
                "extract": {
                    "type": "gz",
                    "output_filename": openwrt_output,
                },
            },
        }

    topology: Dict[str, Any] = {
        "scenario": scenario,
        "nodes": nodes,
        "edges": edges,
    }
    return topology


def validate_target(target: str, allow_public: bool = False) -> None:
    """Basic safety gate to avoid accidental public Internet scanning."""

    # Accept a single IP or CIDR
    try:
        if "/" in target:
            net = ipaddress.ip_network(target, strict=False)
            if not allow_public and not net.is_private:
                raise ValueError("Target is not private RFC1918")
        else:
            ip = ipaddress.ip_address(target)
            if not allow_public and not ip.is_private:
                raise ValueError("Target is not private RFC1918")
    except ValueError as e:
        raise ValueError(f"Invalid/unsafe target '{target}': {e}")


def nmap_scan(
    target: str,
    *,
    workdir: Path,
    top_ports: int = 200,
    nmap_extra: Optional[List[str]] = None,
) -> Dict[str, Path]:
    _require_binary("nmap")
    workdir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    discovery_xml = workdir / f"discovery_{ts}.xml"
    services_xml = workdir / f"services_{ts}.xml"

    discover_cmd = ["nmap", "-sn", target, "-oX", str(discovery_xml)]
    services_cmd = [
        "nmap",
        "-sS",
        "-sV",
        "-O",
        "--osscan-guess",
        "--top-ports",
        str(top_ports),
        "--open",
        target,
        "-oX",
        str(services_xml),
    ]

    if nmap_extra:
        discover_cmd[1:1] = nmap_extra
        services_cmd[1:1] = nmap_extra

    subprocess.run(discover_cmd, check=True)
    try:
        subprocess.run(services_cmd, check=True)
    except subprocess.CalledProcessError:
        # Common fallback when running unprivileged (no raw sockets) or OS detection fails.
        # Use TCP connect scan and skip OS detection.
        fallback_cmd = [
            "nmap",
            "-sT",
            "-sV",
            "--top-ports",
            str(top_ports),
            "--open",
            target,
            "-oX",
            str(services_xml),
        ]
        if nmap_extra:
            fallback_cmd[1:1] = nmap_extra
        subprocess.run(fallback_cmd, check=True)

    return {"discovery_xml": discovery_xml, "services_xml": services_xml}


def scanning_enabled() -> bool:
    return os.getenv("RANGE_MAPPER_ENABLE", "0") in ("1", "true", "yes", "on")


@lru_cache(maxsize=1)
def load_device_profiles() -> List[Dict[str, Any]]:
    """Load device profiles from YAML.

    Location precedence:
      1) RANGE_MAPPER_PROFILES (explicit file path)
      2) backend/data/device_profiles.yaml (repo default)
    """

    explicit = os.getenv("RANGE_MAPPER_PROFILES")
    if explicit:
        path = Path(explicit)
    else:
        # backend/app/core/range_mapper.py -> backend/data/device_profiles.yaml
        path = Path(__file__).resolve().parents[2] / "data" / "device_profiles.yaml"

    try:
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles = data.get("profiles") or []
        if not isinstance(profiles, list):
            return []

        def prio(p: Dict[str, Any]) -> int:
            try:
                return int(p.get("priority") or 0)
            except Exception:
                return 0

        return sorted(profiles, key=prio, reverse=True)
    except Exception:
        return []


def _any_contains(haystack: str, needles: List[str]) -> bool:
    haystack = (haystack or "").lower()
    for n in needles or []:
        if n and str(n).lower() in haystack:
            return True
    return False


def select_device_profile(host: Host, profiles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the highest priority profile that matches a host.

    Matching semantics:
      - AND across match keys
      - OR within each list key
    """

    roles = set((host.roles or []))
    services = set(((p.service or "").lower() for p in (host.open_ports or [])))
    ports = set((p.port for p in (host.open_ports or [])))
    hostnames = " ".join(host.hostnames or [])
    os_guess = host.os_guess or ""

    for prof in profiles or []:
        match = prof.get("match") or {}
        if not isinstance(match, dict):
            continue

        roles_any = match.get("roles_any") or []
        if roles_any and not any(r in roles for r in roles_any):
            continue

        roles_all = match.get("roles_all") or []
        if roles_all and not all(r in roles for r in roles_all):
            continue

        ports_any = match.get("ports_any") or []
        if ports_any and not any(int(p) in ports for p in ports_any):
            continue

        services_any = match.get("services_any") or []
        if services_any and not any(str(s).lower() in services for s in services_any):
            continue

        os_contains = match.get("os_contains") or []
        if os_contains and not _any_contains(os_guess, [str(x) for x in os_contains]):
            continue

        hostname_contains = match.get("hostname_contains") or []
        if hostname_contains and not _any_contains(hostnames, [str(x) for x in hostname_contains]):
            continue

        return prof

    return None
