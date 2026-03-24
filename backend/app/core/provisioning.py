import base64
import json
import os
import secrets
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_VM_USERNAME = os.environ.get("CYBERANGE_DEFAULT_VM_USER", "trainee")


def build_cloud_init_assets(assets: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    packages: List[str] = []
    runcmds: List[str] = []

    for asset in assets or []:
        atype = asset.get("type")
        if atype == "package":
            val = asset.get("value")
            if val:
                packages.append(str(val))
        elif atype == "command":
            val = asset.get("value")
            if val:
                runcmds.append(str(val))
        elif atype == "ansible":
            playbook = asset.get("playbook")
            if not playbook:
                continue
            playbook_name = asset.get("playbook_name") or "playbook.yml"
            extra_vars = asset.get("extra_vars")
            install_ansible = asset.get("install", True)

            if install_ansible:
                packages.append("ansible")

            b64 = base64.b64encode(str(playbook).encode("utf-8")).decode("ascii")
            runcmds.append(f"printf '%s' '{b64}' | base64 -d > /tmp/{playbook_name}")

            cmd = f"ansible-playbook -c local -i localhost, /tmp/{playbook_name}"
            if isinstance(extra_vars, dict) and extra_vars:
                cmd += f" --extra-vars '{json.dumps(extra_vars)}'"
            runcmds.append(cmd)

    return packages, runcmds


def generate_guest_password() -> str:
    override = os.environ.get("CYBERANGE_DEFAULT_VM_PASSWORD")
    if override:
        return override
    return secrets.token_hex(4)


def ensure_cloud_init_defaults(cloud_init: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if cloud_init is None:
        return None

    normalized = dict(cloud_init)
    normalized["username"] = str(normalized.get("username") or DEFAULT_VM_USERNAME)
    normalized["password"] = str(normalized.get("password") or generate_guest_password())
    normalized["packages"] = str(normalized.get("packages") or "")
    normalized["runcmd"] = [str(cmd) for cmd in (normalized.get("runcmd") or []) if cmd]
    return normalized


def build_cloud_init_from_assets(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    packages, runcmds = build_cloud_init_assets(assets)
    packages_str = "\n".join([f"  - {pkg}" for pkg in packages])
    return ensure_cloud_init_defaults(
        {
            "username": DEFAULT_VM_USERNAME,
            "password": generate_guest_password(),
            "packages": packages_str,
            "runcmd": runcmds,
        }
    )


def cloud_init_credentials(cloud_init: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not cloud_init:
        return None
    username = str(cloud_init.get("username") or "").strip()
    password = str(cloud_init.get("password") or "").strip()
    if not username or not password:
        return None
    return {"username": username, "password": password}