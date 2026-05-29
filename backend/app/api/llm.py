import asyncio
import copy
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.images import IMAGES_DIR
from app.api.routes import TopologyDeployRequest, _resolve_image_path, _run_deploy_job
from app.api.trainings import IMAGE_DOWNLOAD_SOURCES, canonicalize_image_download_source, canonicalize_image_key
from app.core.auth import AuthenticatedUser, require_authenticated_user
from app.core.deploy_automation import normalize_automation_steps
from app.core.deploy_jobs import new_job
from app.core.ownership import save_topology_cache_for_user

router = APIRouter()
logger = logging.getLogger(__name__)

KNOWN_IMAGE_KEYS = [
    "ubuntu-20.04",
    "ubuntu-22.04",
    "kali-linux",
    "debian-12",
    "windows-10",
    "gateway",
    "security-onion",
    "opnsense",
    "openwrt",
    "contiki-ng",
]

IMAGE_FILE_EXTENSIONS = (".img", ".iso", ".qcow2", ".qcow", ".7z", ".bz2", ".gz", ".xz")

DEFAULT_DOWNLOAD_SOURCES = {
    "ubuntu-20.04": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["focal-server-cloudimg-amd64.img"]),
    "focal-server-cloudimg-amd64.img": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["focal-server-cloudimg-amd64.img"]),
    "ubuntu-22.04": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["jammy-server-cloudimg-amd64.img"]),
    "jammy-server-cloudimg-amd64.img": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["jammy-server-cloudimg-amd64.img"]),
    "kali-linux": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["kali-linux-2026.1-cloud-genericcloud-amd64.qcow2"]),
    "kali-linux-2026.1-cloud-genericcloud-amd64.qcow2": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["kali-linux-2026.1-cloud-genericcloud-amd64.qcow2"]),
    "debian-12": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["debian-12-generic-amd64.qcow2"]),
    "debian-12-generic-amd64.qcow2": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["debian-12-generic-amd64.qcow2"]),
    "opnsense": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["opnsense.img"]),
    "opnsense.img": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["opnsense.img"]),
    "OPNsense.qcow2": copy.deepcopy(IMAGE_DOWNLOAD_SOURCES["opnsense.img"]),
}

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
MAX_TOPOLOGY_REPAIR_ATTEMPTS = 3

PLAN_RESPONSE_EXAMPLE = {
    "summary": "A compact phishing simulation with a mail gateway, victim workstation, and analyst box.",
    "scenario": {
        "name": "AI Generated Scenario",
        "team": "blue",
        "objective": "Investigate and contain a simulated phishing incident.",
        "difficulty": "medium",
        "runbook": {
            "provisioning_strategy": "Use cloud-init assets for Ubuntu nodes and console automation only for installer ISOs.",
            "setup_order": ["gateway", "victim", "analyst"],
            "setup_steps": [
                {
                    "title": "Provision mail gateway",
                    "actor": "gateway",
                    "action": "Install and start Postfix plus a small phishing mailbox simulation service.",
                    "expected_outcome": "The gateway accepts mail traffic for the lab.",
                }
            ],
            "simulation_steps": [
                {
                    "title": "Replay phishing email",
                    "actor": "gateway",
                    "target": "victim",
                    "action": "Send a benign phishing lure and wait for the victim-side telemetry service to log it.",
                    "expected_outcome": "The analyst host can review the event and the generated logs.",
                    "transport": "ssh",
                    "command": "python3 /opt/replay_phish.py",
                    "timeout_seconds": 120,
                }
            ],
            "visualizations": [
                {
                    "title": "Analyst dashboard",
                    "node_id": "analyst",
                    "kind": "dashboard",
                    "url_hint": "http://[analyst-ip]:5000",
                    "description": "Shows phishing alerts, host telemetry, and containment status.",
                }
            ],
            "success_criteria": ["The phishing event is visible on the analyst dashboard."]
        },
    },
    "nodes": [
        {
            "id": "gateway",
            "label": "Mail Gateway",
            "image": "ubuntu-20.04",
            "cpu": 2,
            "ram": 2048,
            "assets": [
                {"type": "package", "value": "postfix"},
                {"type": "command", "value": "systemctl enable postfix && systemctl start postfix"},
            ],
        }
    ],
    "edges": [
        {"source": "gateway", "target": "victim", "segment": "corp-net", "mode": "nat"}
    ],
    "warnings": ["Use locally available images whenever possible."],
}

TOPOLOGY_RESPONSE_EXAMPLE = {
    "summary": "A compact phishing simulation with three connected nodes.",
    "scenario": {
        "name": "AI Generated Scenario",
        "team": "blue",
        "objective": "Investigate and contain a simulated phishing incident.",
        "difficulty": "medium",
        "runbook": {
            "provisioning_strategy": "Prefer cloud-init assets and use console automation only for ISO nodes.",
            "setup_order": ["gateway", "victim", "analyst"],
            "setup_steps": [
                {
                    "title": "Provision mail gateway",
                    "actor": "gateway",
                    "action": "Install and start Postfix plus the alert forwarding service.",
                    "expected_outcome": "Mail flow and alert forwarding are ready.",
                }
            ],
            "simulation_steps": [
                {
                    "title": "Replay phishing lure",
                    "actor": "gateway",
                    "target": "victim",
                    "action": "Send a benign phishing lure and log the victim response.",
                    "expected_outcome": "The analyst host can review the event timeline.",
                    "transport": "ssh",
                    "command": "python3 /opt/replay_phish.py",
                    "timeout_seconds": 120,
                }
            ],
            "visualizations": [
                {
                    "title": "Analyst dashboard",
                    "node_id": "analyst",
                    "kind": "dashboard",
                    "url_hint": "http://[analyst-ip]:5000",
                    "description": "Displays host telemetry and attack replay results.",
                }
            ],
            "success_criteria": ["The phishing replay appears on the analyst dashboard."]
        },
    },
    "nodes": [
        {
            "id": "gateway",
            "label": "Mail Gateway",
            "config": {
                "image": "ubuntu-20.04",
                "cpu": 2,
                "ram": 2048,
                "assets": [
                    {"type": "package", "value": "postfix"},
                    {"type": "command", "value": "systemctl enable postfix && systemctl start postfix"},
                ],
            },
            "position": {"x": 240, "y": 60},
        }
    ],
    "edges": [
        {
            "id": "e-gateway-victim",
            "source": "gateway",
            "target": "victim",
            "config": {"segment": "corp-net", "mode": "nat"},
        }
    ],
    "warnings": ["Keep package installation commands short and idempotent."],
}


class LlmProviderConfig(BaseModel):
    provider: Literal["ollama", "openai", "openai-compatible"] = "ollama"
    model: str = Field(min_length=1, max_length=200)
    base_url: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=500)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)


class ScenarioWorkflowRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=12000)
    provider: LlmProviderConfig
    auto_deploy: bool = False
    max_nodes: int = Field(default=8, ge=1, le=20)


class WorkflowStep(BaseModel):
    stage: str
    status: str
    message: str
    duration_ms: int = 0


class ScenarioWorkflowResponse(BaseModel):
    summary: str
    topology: TopologyDeployRequest
    workflow: List[WorkflowStep]
    warnings: List[str] = Field(default_factory=list)
    deploy_job_id: Optional[str] = None


class ProviderInvalidJsonError(ValueError):
    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = str(raw_text or "")


def _collect_candidate_images() -> List[str]:
    image_names: List[str] = []
    if os.path.isdir(IMAGES_DIR):
        for entry in sorted(os.listdir(IMAGES_DIR)):
            full_path = os.path.join(IMAGES_DIR, entry)
            if os.path.isfile(full_path) and _looks_like_image_filename(entry):
                image_names.append(entry)
    candidates: List[str] = []
    for value in KNOWN_IMAGE_KEYS:
        if _image_exists(value) or _default_download_source_for_image(value):
            candidates.append(value)
    for value in image_names:
        if value not in candidates:
            candidates.append(value)
    return candidates[:48]


def _looks_like_image_filename(name: str) -> bool:
    lowered = str(name or "").strip().lower()
    return lowered.endswith(IMAGE_FILE_EXTENSIONS)


def _image_exists(image_key: str) -> bool:
    try:
        return os.path.exists(_resolve_image_path(str(image_key or "").strip()))
    except Exception:
        return False


def _default_download_source_for_image(image_key: Any) -> Optional[Dict[str, Any]]:
    key = canonicalize_image_key(image_key)
    if not key:
        return None

    direct = DEFAULT_DOWNLOAD_SOURCES.get(key)
    if direct:
        return copy.deepcopy(direct)

    basename = os.path.basename(key)
    direct = DEFAULT_DOWNLOAD_SOURCES.get(basename)
    if direct:
        return copy.deepcopy(direct)

    return None


def _dedupe_strings(values: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _format_stage(stage: str, started_at: float, message: str) -> WorkflowStep:
    return WorkflowStep(
        stage=stage,
        status="completed",
        message=message,
        duration_ms=max(1, int((time.perf_counter() - started_at) * 1000)),
    )


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("The provider returned an empty response")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("The provider returned JSON that was not an object")
    except json.JSONDecodeError:
        pass

    block_match = JSON_BLOCK_RE.search(text)
    if block_match:
        parsed = json.loads(block_match.group(1))
        if isinstance(parsed, dict):
            return parsed

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("The provider response did not contain a JSON object")

    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("The provider returned JSON that was not an object")
    return parsed


def _openai_chat_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _provider_base_url(provider: LlmProviderConfig) -> str:
    if provider.provider == "ollama":
        return (provider.base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    if provider.provider == "openai":
        return (provider.base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    if not provider.base_url:
        raise HTTPException(status_code=400, detail="A base URL is required for openai-compatible providers")
    return provider.base_url.rstrip("/")


def _provider_auth_headers(provider: LlmProviderConfig) -> Dict[str, str]:
    if provider.provider == "ollama":
        return {}
    if not provider.api_key:
        raise HTTPException(status_code=400, detail="An API key is required for non-Ollama providers")
    return {"Authorization": f"Bearer {provider.api_key}"}


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content or "")


def _provider_error_detail(exc: httpx.HTTPStatusError) -> str:
    response_text = exc.response.text.strip()
    if not response_text:
        return f"Provider request failed with HTTP {exc.response.status_code}"
    snippet = response_text[:400]
    return f"Provider request failed with HTTP {exc.response.status_code}: {snippet}"


def _provider_request_target(exc: httpx.HTTPError) -> Optional[str]:
    request = getattr(exc, "request", None)
    if request is None:
        return None

    url = getattr(request, "url", None)
    if url is None:
        return None

    host = getattr(url, "host", None)
    if not host:
        text = str(url).strip()
        return text or None

    scheme = getattr(url, "scheme", None) or "http"
    port = getattr(url, "port", None)
    path = getattr(url, "path", None) or "/"
    authority = f"{host}:{port}" if port else str(host)
    return f"{scheme}://{authority}{path}"


def _provider_transport_error_detail(exc: httpx.HTTPError) -> str:
    detail = str(exc).strip()
    if detail:
        return f"Provider request failed: {detail}"

    target = _provider_request_target(exc)
    if target:
        return f"Provider request failed due to {exc.__class__.__name__} while calling {target}"
    return f"Provider request failed due to {exc.__class__.__name__}"


async def _request_llm_json(provider: LlmProviderConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    base_url = _provider_base_url(provider)
    headers = {"Content-Type": "application/json", **_provider_auth_headers(provider)}

    timeout = httpx.Timeout(90.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if provider.provider == "ollama":
                response = await client.post(
                    f"{base_url}/api/chat",
                    headers=headers,
                    json={
                        "model": provider.model,
                        "stream": False,
                        "format": "json",
                        "messages": messages,
                        "options": {"temperature": provider.temperature},
                    },
                )
                response.raise_for_status()
                payload = response.json()
                raw_text = _message_text((payload.get("message") or {}).get("content"))
            else:
                response = await client.post(
                    _openai_chat_url(base_url),
                    headers=headers,
                    json={
                        "model": provider.model,
                        "temperature": provider.temperature,
                        "messages": messages,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                choices = payload.get("choices") or []
                if not choices:
                    raise ValueError("The provider response did not include any choices")
                raw_text = _message_text((choices[0].get("message") or {}).get("content"))
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_provider_error_detail(exc)) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(_provider_transport_error_detail(exc)) from exc

    try:
        return _extract_json_object(raw_text)
    except ValueError as exc:
        raise ProviderInvalidJsonError(str(exc), raw_text) from exc


def _truncate_text(value: str, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def _sanitize_id(value: Any, fallback: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return raw or fallback


def _normalize_assets(raw_assets: Any) -> List[Dict[str, Any]]:
    assets: List[Dict[str, Any]] = []
    if not isinstance(raw_assets, list):
        return assets

    for raw_asset in raw_assets[:24]:
        if isinstance(raw_asset, str):
            text = raw_asset.strip()
            if text:
                assets.append({"type": "command", "value": text})
            continue
        if not isinstance(raw_asset, dict):
            continue

        asset_type = str(raw_asset.get("type") or "").strip().lower()
        if asset_type == "package":
            value = str(raw_asset.get("value") or raw_asset.get("name") or "").strip()
            if value:
                assets.append({"type": "package", "value": value})
        elif asset_type == "command":
            value = str(raw_asset.get("value") or raw_asset.get("command") or "").strip()
            if value:
                assets.append({"type": "command", "value": value})
        elif asset_type == "ansible":
            playbook = str(raw_asset.get("playbook") or "").strip()
            if not playbook:
                continue
            normalized = {"type": "ansible", "playbook": playbook}
            playbook_name = str(raw_asset.get("playbook_name") or "").strip()
            if playbook_name:
                normalized["playbook_name"] = playbook_name
            extra_vars = raw_asset.get("extra_vars")
            if isinstance(extra_vars, dict) and extra_vars:
                normalized["extra_vars"] = extra_vars
            if "install" in raw_asset:
                normalized["install"] = bool(raw_asset.get("install"))
            assets.append(normalized)
    return assets


def _normalize_automation(raw_automation: Any, warnings: List[str], node_label: str) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_automation, dict):
        return None
    try:
        return {"steps": normalize_automation_steps(raw_automation)}
    except ValueError as exc:
        warnings.append(f"Ignored invalid automation for node '{node_label}': {exc}")
        return None


def _normalize_sources(raw_sources: Any) -> Dict[str, object]:
    if not isinstance(raw_sources, dict):
        return {}
    sources: Dict[str, object] = {}
    for raw_key, raw_value in raw_sources.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        canonical = canonicalize_image_download_source(key, raw_value)
        if canonical:
            sources[key] = canonical
    return sources


def _normalize_runbook_step(raw_step: Any, index: int, warnings: List[str], phase: str, node_ids: List[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_step, dict):
        warnings.append(f"Ignored invalid {phase} runbook step {index + 1} because it was not an object.")
        return None

    title = str(raw_step.get("title") or raw_step.get("name") or f"{phase.title()} step {index + 1}").strip()
    action = str(raw_step.get("action") or raw_step.get("description") or "").strip()
    if not action:
        warnings.append(f"Ignored invalid {phase} runbook step '{title}' because it had no action.")
        return None

    normalized = {
        "title": title,
        "action": action,
    }
    for key in ("actor", "target"):
        value = _sanitize_id(raw_step.get(key), "")
        if value:
            if value not in node_ids:
                warnings.append(f"Ignored unknown {key} '{value}' on {phase} runbook step '{title}'.")
                continue
            normalized[key] = value

    expected_outcome = str(raw_step.get("expected_outcome") or "").strip()
    if expected_outcome:
        normalized["expected_outcome"] = expected_outcome

    if raw_step.get("delay_seconds") not in (None, ""):
        try:
            normalized["delay_seconds"] = max(0.0, float(raw_step.get("delay_seconds") or 0.0))
        except (TypeError, ValueError):
            warnings.append(f"Ignored invalid delay_seconds on {phase} runbook step '{title}'.")

    transport = str(raw_step.get("transport") or "").strip().lower()
    command = str(raw_step.get("command") or raw_step.get("shell") or "").strip()
    if command:
        if transport and transport != "ssh":
            warnings.append(f"Ignored unsupported transport '{transport}' on {phase} runbook step '{title}'. Falling back to ssh.")
        normalized["transport"] = "ssh"
        normalized["command"] = command
    elif transport:
        warnings.append(f"Ignored transport '{transport}' on {phase} runbook step '{title}' because no command was provided.")

    if raw_step.get("timeout_seconds") not in (None, ""):
        try:
            normalized["timeout_seconds"] = max(1.0, float(raw_step.get("timeout_seconds") or 0.0))
        except (TypeError, ValueError):
            warnings.append(f"Ignored invalid timeout_seconds on {phase} runbook step '{title}'.")

    automation = _normalize_automation(raw_step.get("automation"), warnings, title)
    if automation:
        normalized["automation"] = automation

    return normalized


def _normalize_visualization(raw_visualization: Any, index: int, warnings: List[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_visualization, dict):
        warnings.append(f"Ignored invalid visualization {index + 1} because it was not an object.")
        return None

    title = str(raw_visualization.get("title") or raw_visualization.get("name") or f"Visualization {index + 1}").strip()
    normalized = {
        "title": title,
        "kind": str(raw_visualization.get("kind") or "dashboard").strip() or "dashboard",
    }

    for key in ("node_id", "url_hint", "description"):
        value = str(raw_visualization.get(key) or "").strip()
        if value:
            normalized[key] = value

    return normalized


def _normalize_runbook(raw_runbook: Any, node_ids: List[str], warnings: List[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_runbook, dict):
        return None

    runbook: Dict[str, Any] = {}

    provisioning_strategy = str(raw_runbook.get("provisioning_strategy") or "").strip()
    if provisioning_strategy:
        runbook["provisioning_strategy"] = provisioning_strategy

    setup_order = []
    for raw_node_id in raw_runbook.get("setup_order") or []:
        node_id = _sanitize_id(raw_node_id, "")
        if node_id and node_id in node_ids and node_id not in setup_order:
            setup_order.append(node_id)
    if setup_order:
        runbook["setup_order"] = setup_order

    setup_steps = []
    for index, raw_step in enumerate(raw_runbook.get("setup_steps") or []):
        step = _normalize_runbook_step(raw_step, index, warnings, "setup", node_ids)
        if step:
            setup_steps.append(step)
    if setup_steps:
        runbook["setup_steps"] = setup_steps

    simulation_steps = []
    for index, raw_step in enumerate(raw_runbook.get("simulation_steps") or []):
        step = _normalize_runbook_step(raw_step, index, warnings, "simulation", node_ids)
        if step:
            simulation_steps.append(step)
    if simulation_steps:
        runbook["simulation_steps"] = simulation_steps

    visualizations = []
    for index, raw_visualization in enumerate(raw_runbook.get("visualizations") or []):
        visualization = _normalize_visualization(raw_visualization, index, warnings)
        if visualization:
            visualizations.append(visualization)
    if visualizations:
        runbook["visualizations"] = visualizations

    success_criteria = _dedupe_strings([str(item) for item in raw_runbook.get("success_criteria") or []])
    if success_criteria:
        runbook["success_criteria"] = success_criteria

    return runbook or None


def _preferred_fallback_image(candidate_images: List[str]) -> str:
    if "ubuntu-20.04" in candidate_images:
        return "ubuntu-20.04"
    for candidate in candidate_images:
        lower = candidate.lower()
        if "ubuntu" in lower:
            return candidate
    return candidate_images[0] if candidate_images else "ubuntu-20.04"


def _normalize_image(
    requested_image: Any,
    candidate_images: List[str],
    sources: Dict[str, object],
    warnings: List[str],
) -> str:
    image = canonicalize_image_key(requested_image)
    fallback = _preferred_fallback_image(candidate_images)
    if not image:
        warnings.append(f"One node omitted an image; using {fallback}.")
        return fallback

    lowered = image.lower()
    exact_lookup = {candidate.lower(): candidate for candidate in candidate_images}
    if lowered in exact_lookup:
        return exact_lookup[lowered]

    if image in sources or os.path.basename(image) in sources:
        return image

    for candidate in candidate_images:
        candidate_lower = candidate.lower()
        if lowered == os.path.basename(candidate_lower):
            return candidate
        if lowered in candidate_lower or candidate_lower in lowered:
            return candidate

    warnings.append(f"Requested image '{image}' is not available; using {fallback} instead.")
    return fallback


def _backfill_download_sources(
    nodes: List[Dict[str, Any]],
    sources: Dict[str, object],
    warnings: List[str],
) -> Dict[str, object]:
    merged = dict(sources)
    for node in nodes:
        image = str((((node or {}).get("config") or {}).get("image") or "")).strip()
        if not image:
            continue
        if image in merged or os.path.basename(image) in merged:
            continue
        if _image_exists(image):
            continue

        default_source = _default_download_source_for_image(image)
        if not default_source:
            continue

        merged[image] = default_source
        warnings.append(f"Added an auto-download source for image '{image}'.")
    return merged


def _grid_positions(node_ids: List[str], prioritized_id: Optional[str]) -> Dict[str, Dict[str, float]]:
    positions: Dict[str, Dict[str, float]] = {}
    ordered_ids = list(node_ids)
    if prioritized_id and prioritized_id in ordered_ids:
        ordered_ids.remove(prioritized_id)
        ordered_ids.insert(0, prioritized_id)

    columns = 3
    top_x = 260.0
    top_y = 60.0
    spacing_x = 260.0
    spacing_y = 180.0

    for index, node_id in enumerate(ordered_ids):
        if index == 0 and prioritized_id == node_id and len(ordered_ids) > 1:
            positions[node_id] = {"x": top_x, "y": top_y}
            continue
        offset_index = index - 1 if prioritized_id == ordered_ids[0] and len(ordered_ids) > 1 else index
        row = offset_index // columns
        col = offset_index % columns
        positions[node_id] = {"x": 80.0 + (col * spacing_x), "y": 220.0 + (row * spacing_y)}
    return positions


def _normalize_edges(raw_edges: Any, node_ids: List[str], warnings: List[str], gateway_id: Optional[str]) -> List[Dict[str, Any]]:
    valid_ids = set(node_ids)
    edges: List[Dict[str, Any]] = []

    if isinstance(raw_edges, list):
        for index, raw_edge in enumerate(raw_edges[:48]):
            if not isinstance(raw_edge, dict):
                continue
            source = _sanitize_id(raw_edge.get("source"), "")
            target = _sanitize_id(raw_edge.get("target"), "")
            if source not in valid_ids or target not in valid_ids or source == target:
                warnings.append(f"Dropped an invalid link from '{source or '?'}' to '{target or '?'}'.")
                continue
            config: Dict[str, Any] = {}
            raw_config = raw_edge.get("config") if isinstance(raw_edge.get("config"), dict) else raw_edge
            segment = str(raw_config.get("segment") or "").strip()
            mode = str(raw_config.get("mode") or "nat").strip().lower() or "nat"
            if mode not in {"nat", "isolated"}:
                mode = "nat"
            vlan_value = raw_config.get("vlan_id")
            vlan_id = None
            if vlan_value not in (None, ""):
                try:
                    vlan_id = int(vlan_value)
                except (TypeError, ValueError):
                    vlan_id = None

            if segment:
                config["segment"] = segment
            if mode != "nat":
                config["mode"] = mode
            if vlan_id is not None:
                config["vlan_id"] = vlan_id

            edge = {
                "id": _sanitize_id(raw_edge.get("id"), f"e-{source}-{target}-{index + 1}"),
                "source": source,
                "target": target,
            }
            if config:
                edge["config"] = config
            edges.append(edge)

    if not edges and gateway_id and len(node_ids) > 1:
        for target_id in node_ids:
            if target_id == gateway_id:
                continue
            edges.append(
                {
                    "id": f"e-{gateway_id}-{target_id}",
                    "source": gateway_id,
                    "target": target_id,
                    "config": {"mode": "nat"},
                }
            )
        warnings.append("The provider did not return valid links, so a simple gateway star network was created.")

    return edges


def _normalize_topology_payload(
    payload: Dict[str, Any],
    prompt: str,
    candidate_images: List[str],
    max_nodes: int,
) -> tuple[TopologyDeployRequest, str, List[str]]:
    topology_payload = payload.get("topology") if isinstance(payload.get("topology"), dict) else payload
    if not isinstance(topology_payload, dict):
        raise ValueError("The provider did not return a topology object")

    warnings = _dedupe_strings([str(item) for item in topology_payload.get("warnings") or []])
    scenario_raw = topology_payload.get("scenario") if isinstance(topology_payload.get("scenario"), dict) else {}
    sources = _normalize_sources(scenario_raw.get("sources"))
    raw_nodes = topology_payload.get("nodes") if isinstance(topology_payload.get("nodes"), list) else []
    if not raw_nodes:
        raise ValueError("The provider did not return any nodes")

    if len(raw_nodes) > max_nodes:
        warnings.append(f"The provider returned {len(raw_nodes)} nodes; only the first {max_nodes} were kept.")
        raw_nodes = raw_nodes[:max_nodes]

    nodes: List[Dict[str, Any]] = []
    node_ids: List[str] = []
    gateway_id: Optional[str] = None
    for index, raw_node in enumerate(raw_nodes, start=1):
        if not isinstance(raw_node, dict):
            continue

        node_id = _sanitize_id(raw_node.get("id"), f"node-{index}")
        while node_id in node_ids:
            node_id = f"{node_id}-{index}"
        label = str(raw_node.get("label") or raw_node.get("name") or f"Node {index}").strip() or f"Node {index}"
        raw_config = raw_node.get("config") if isinstance(raw_node.get("config"), dict) else raw_node

        image = _normalize_image(raw_config.get("image"), candidate_images, sources, warnings)
        try:
            cpu = max(1, min(8, int(raw_config.get("cpu") or 2)))
        except (TypeError, ValueError):
            cpu = 2
        try:
            ram = int(raw_config.get("ram") or 2048)
        except (TypeError, ValueError):
            ram = 2048
        ram = max(512, min(16384, ram))
        assets = _normalize_assets(raw_config.get("assets"))
        automation = _normalize_automation(raw_config.get("automation"), warnings, label)
        username = str(raw_config.get("username") or "").strip() or None
        password = str(raw_config.get("password") or "").strip() or None

        position = raw_node.get("position") if isinstance(raw_node.get("position"), dict) else None
        normalized_node = {
            "id": node_id,
            "label": label,
            "config": {
                "image": image,
                "cpu": cpu,
                "ram": ram,
                "assets": assets,
            },
        }
        if automation:
            normalized_node["config"]["automation"] = automation
        if username:
            normalized_node["config"]["username"] = username
        if password:
            normalized_node["config"]["password"] = password
        if position and position.get("x") is not None and position.get("y") is not None:
            normalized_node["position"] = {"x": float(position.get("x")), "y": float(position.get("y"))}

        nodes.append(normalized_node)
        node_ids.append(node_id)

        label_lower = label.lower()
        if gateway_id is None and any(keyword in label_lower for keyword in ("gateway", "router", "firewall", "internet")):
            gateway_id = node_id

    if not nodes:
        raise ValueError("No valid nodes were returned")

    positions = _grid_positions(node_ids, gateway_id)
    for node in nodes:
        if "position" not in node:
            node["position"] = positions[node["id"]]

    edges = _normalize_edges(topology_payload.get("edges"), node_ids, warnings, gateway_id)
    sources = _backfill_download_sources(nodes, sources, warnings)
    runbook = _normalize_runbook(scenario_raw.get("runbook"), node_ids, warnings)

    scenario = {
        "name": str(scenario_raw.get("name") or "AI Generated Scenario").strip() or "AI Generated Scenario",
        "team": str(scenario_raw.get("team") or "blue").strip() or "blue",
        "objective": str(scenario_raw.get("objective") or prompt).strip() or prompt,
        "difficulty": str(scenario_raw.get("difficulty") or "medium").strip() or "medium",
    }
    network_prefix = str(scenario_raw.get("network_prefix") or "").strip()
    if network_prefix:
        scenario["network_prefix"] = network_prefix
    if sources:
        scenario["sources"] = sources
    if runbook:
        scenario["runbook"] = runbook

    summary = _truncate_text(
        str(topology_payload.get("summary") or payload.get("summary") or scenario["objective"] or prompt),
        limit=320,
    )
    topology = TopologyDeployRequest.model_validate({"scenario": scenario, "nodes": nodes, "edges": edges})
    return topology, summary, _dedupe_strings(warnings)


def _plan_messages(prompt: str, candidate_images: List[str], max_nodes: int) -> List[Dict[str, str]]:
    image_text = ", ".join(candidate_images) if candidate_images else "ubuntu-20.04"
    return [
        {
            "role": "system",
            "content": (
                "You are a cyber range planning agent for CyberRanger. Produce only valid JSON, with no markdown. "
                f"Design a deployable lab with at most {max_nodes} nodes. Prefer these image identifiers: {image_text}. "
                "Use only practical bootstrapping assets of type package, command, or ansible. "
                "For ISO or installer nodes, plan console automation as wait/send_text/send_key steps instead of vague manual setup. "
                "Include a scenario.runbook that explains setup order, attack or simulation steps, visualization targets, and success criteria. "
                "When a runbook step should execute automatically on a cloud image, add transport='ssh' plus a command and timeout_seconds. "
                "When a runbook step should execute automatically on an installer ISO, add step.automation using wait/send_text/send_key steps and set actor to the node receiving that console input. "
                "Favor benign simulation, detection, and administration tooling suitable for a lab. "
                "Return this JSON shape exactly: "
                f"{json.dumps(PLAN_RESPONSE_EXAMPLE, separators=(',', ':'))}"
            ),
        },
        {"role": "user", "content": prompt},
    ]


def _topology_messages(plan: Dict[str, Any], prompt: str, candidate_images: List[str], max_nodes: int) -> List[Dict[str, str]]:
    image_text = ", ".join(candidate_images) if candidate_images else "ubuntu-20.04"
    return [
        {
            "role": "system",
            "content": (
                "You are a deployment synthesis agent for CyberRanger. Convert the approved scenario plan into topology JSON. "
                "Produce only valid JSON, with no markdown. Keep the topology under the requested node limit. "
                f"Prefer these image identifiers: {image_text}. "
                "Compile setup into node.config.assets for cloud images and node.config.automation.steps for installer ISOs. "
                "Also include scenario.runbook with setup_steps, simulation_steps, visualizations, and success_criteria. "
                "For any runbook step that should run automatically after deploy on a cloud image, include transport='ssh', command, and timeout_seconds. "
                "For installer ISO nodes, include an automation object with wait/send_text/send_key steps and actor set to the node that should execute it. "
                "The exact required response shape is: "
                f"{json.dumps(TOPOLOGY_RESPONSE_EXAMPLE, separators=(',', ':'))}"
            ),
        },
        {
            "role": "user",
            "content": (
                "User request:\n"
                f"{prompt}\n\n"
                "Approved scenario plan:\n"
                f"{json.dumps(plan, indent=2)}\n\n"
                f"Do not exceed {max_nodes} nodes."
            ),
        },
    ]


def _repair_messages(
    draft: Any,
    error_text: str,
    prompt: str,
    candidate_images: List[str],
    max_nodes: int,
    attempt: int,
) -> List[Dict[str, str]]:
    image_text = ", ".join(candidate_images) if candidate_images else "ubuntu-20.04"
    if isinstance(draft, dict):
        draft_text = json.dumps(draft, indent=2)
    else:
        draft_text = _truncate_text(str(draft or ""), limit=12000)
    return [
        {
            "role": "system",
            "content": (
                "You are a topology repair agent for CyberRanger. Repair invalid JSON responses so they fit the exact topology schema. "
                "Return only valid JSON, with no markdown. Preserve the original intent while fixing missing or malformed fields. "
                "If the response is malformed JSON, fix the syntax before returning the corrected topology. "
                f"You must return at least 1 node and no more than {max_nodes} nodes. "
                f"Prefer these image identifiers: {image_text}. "
                "Every node must include id, label, image, cpu, ram, and assets or config.assets. "
                "If links are present, they must reference valid returned node ids. "
                f"This is repair attempt {attempt} of {MAX_TOPOLOGY_REPAIR_ATTEMPTS}."
            ),
        },
        {
            "role": "user",
            "content": (
                "Original user request:\n"
                f"{prompt}\n\n"
                "Validation error:\n"
                f"{error_text}\n\n"
                "Do not return an empty nodes array. If necessary, create a minimal single-node topology that still matches the request intent.\n\n"
                "Required response shape example:\n"
                f"{json.dumps(TOPOLOGY_RESPONSE_EXAMPLE, indent=2)}\n\n"
                "Provider response to repair:\n"
                f"{draft_text}"
            ),
        },
    ]


async def _start_generated_topology_deploy(topology: TopologyDeployRequest, current_user: AuthenticatedUser) -> str:
    job = new_job(
        initial_progress={
            "phase": "queued",
            "owner_id": current_user.id,
            "owner_username": current_user.username,
            "source": "llm-scenario-workflow",
        }
    )
    asyncio.create_task(_run_deploy_job(job.id, topology, current_user))
    return job.id


async def _execute_agentic_scenario_workflow(request: ScenarioWorkflowRequest) -> tuple[str, TopologyDeployRequest, List[WorkflowStep], List[str]]:
    candidate_images = _collect_candidate_images()
    workflow: List[WorkflowStep] = []

    plan_started = time.perf_counter()
    plan = await _request_llm_json(request.provider, _plan_messages(request.prompt, candidate_images, request.max_nodes))
    plan_nodes = plan.get("nodes") if isinstance(plan.get("nodes"), list) else []
    workflow.append(_format_stage("plan", plan_started, f"Planned {len(plan_nodes)} node(s) from the scenario brief."))

    topology_started = time.perf_counter()
    try:
        candidate_payload: Any = await _request_llm_json(
            request.provider,
            _topology_messages(plan, request.prompt, candidate_images, request.max_nodes),
        )
    except ProviderInvalidJsonError as exc:
        candidate_payload = exc.raw_text
    workflow.append(_format_stage("synthesize", topology_started, "Converted the plan into CyberRanger topology JSON."))

    validate_started = time.perf_counter()
    repair_started: Optional[float] = None
    repair_attempts = 0
    while True:
        try:
            if not isinstance(candidate_payload, dict):
                candidate_payload = _extract_json_object(candidate_payload)
            topology, summary, warnings = _normalize_topology_payload(
                candidate_payload,
                request.prompt,
                candidate_images,
                request.max_nodes,
            )
            break
        except ValueError as exc:
            if repair_attempts >= MAX_TOPOLOGY_REPAIR_ATTEMPTS:
                raise
            if repair_started is None:
                repair_started = time.perf_counter()
            repair_attempts += 1
            try:
                candidate_payload = await _request_llm_json(
                    request.provider,
                    _repair_messages(
                        candidate_payload,
                        str(exc),
                        request.prompt,
                        candidate_images,
                        request.max_nodes,
                        repair_attempts,
                    ),
                )
            except ProviderInvalidJsonError as repair_exc:
                candidate_payload = repair_exc.raw_text
    if repair_attempts and repair_started is not None:
        workflow.append(
            _format_stage(
                "repair",
                repair_started,
                f"Repaired an invalid topology response after {repair_attempts} attempt(s).",
            )
        )
    workflow.append(
        _format_stage(
            "validate",
            validate_started,
            f"Validated {len(topology.nodes)} node(s) and {len(topology.edges)} link(s) for deployment.",
        )
    )

    return summary, topology, workflow, warnings


@router.post("/llm/scenario-workflows", response_model=ScenarioWorkflowResponse)
async def create_llm_scenario_workflow(
    request: ScenarioWorkflowRequest,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
):
    try:
        summary, topology, workflow, warnings = await _execute_agentic_scenario_workflow(request)
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("LLM scenario workflow returned invalid JSON: %s", exc)
        raise HTTPException(status_code=502, detail=f"The provider returned invalid scenario JSON: {exc}") from exc
    except RuntimeError as exc:
        logger.warning("LLM scenario workflow failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    save_topology_cache_for_user(current_user, topology.model_dump())

    deploy_job_id = None
    if request.auto_deploy:
        deploy_job_id = await _start_generated_topology_deploy(topology, current_user)

    return ScenarioWorkflowResponse(
        summary=summary,
        topology=topology,
        workflow=workflow,
        warnings=warnings,
        deploy_job_id=deploy_job_id,
    )