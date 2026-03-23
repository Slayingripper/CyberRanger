import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


def normalize_automation_steps(automation: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not automation:
        return []
    if not isinstance(automation, dict):
        raise ValueError("automation must be an object")

    if automation.get("type") == "send_text":
        text = str(automation.get("text") or "")
        if not text:
            raise ValueError("automation.text is required for send_text automation")
        return [
            {
                "type": "wait",
                "delay_seconds": float(automation.get("delay_seconds") or 45),
            },
            {
                "type": "send_text",
                "text": text,
                "retries": int(automation.get("retries") or 3),
                "retry_delay_seconds": float(automation.get("retry_delay_seconds") or 15),
            },
        ]

    raw_steps = automation.get("steps") or []
    if not isinstance(raw_steps, list):
        raise ValueError("automation.steps must be a list")

    normalized: List[Dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise ValueError(f"automation step {index} must be an object")

        step_type = str(raw_step.get("type") or "").strip()
        if step_type == "wait":
            normalized.append(
                {
                    "type": "wait",
                    "delay_seconds": float(raw_step.get("delay_seconds") or 0),
                }
            )
            continue

        if step_type == "send_text":
            text = str(raw_step.get("text") or "")
            if not text:
                raise ValueError(f"automation step {index} requires text")
            normalized.append(
                {
                    "type": "send_text",
                    "text": text,
                    "delay_seconds": float(raw_step.get("delay_seconds") or 0),
                    "retries": max(1, int(raw_step.get("retries") or 1)),
                    "retry_delay_seconds": float(raw_step.get("retry_delay_seconds") or 5),
                }
            )
            continue

        if step_type == "send_key":
            key = str(raw_step.get("key") or "").strip().lower()
            if not key:
                raise ValueError(f"automation step {index} requires key")
            normalized.append(
                {
                    "type": "send_key",
                    "key": key,
                    "delay_seconds": float(raw_step.get("delay_seconds") or 0),
                    "repeat": max(1, int(raw_step.get("repeat") or 1)),
                }
            )
            continue

        raise ValueError(f"unsupported automation step type: {step_type or '<missing>'}")

    return normalized


async def execute_automation_steps(
    *,
    vm_name: str,
    node_id: str,
    steps: List[Dict[str, Any]],
    send_text: Callable[[str, str], bool],
    send_key: Callable[[str, str], bool],
    progress_cb: Optional[ProgressCallback] = None,
) -> bool:
    async def _emit(event: Dict[str, Any]) -> None:
        if progress_cb:
            await progress_cb({"vm_name": vm_name, "node_id": node_id, **event})

    if not steps:
        await _emit({"status": "skipped"})
        return True

    await _emit({"status": "scheduled", "steps": len(steps)})
    for index, step in enumerate(steps, start=1):
        step_type = step["type"]
        await _emit({"status": "running", "step": index, "step_type": step_type})

        if step_type == "wait":
            delay_seconds = max(0.0, float(step.get("delay_seconds") or 0.0))
            await _emit({"status": "waiting", "step": index, "delay_seconds": delay_seconds})
            await asyncio.sleep(delay_seconds)
            continue

        if step_type == "send_text":
            delay_seconds = max(0.0, float(step.get("delay_seconds") or 0.0))
            if delay_seconds:
                await asyncio.sleep(delay_seconds)

            text = str(step.get("text") or "")
            retries = max(1, int(step.get("retries") or 1))
            retry_delay_seconds = max(0.0, float(step.get("retry_delay_seconds") or 0.0))
            for attempt in range(1, retries + 1):
                ok = bool(send_text(vm_name, text))
                await _emit({"status": "send_text", "step": index, "attempt": attempt, "ok": ok})
                if ok:
                    break
                if attempt < retries:
                    await asyncio.sleep(retry_delay_seconds)
            else:
                await _emit({"status": "failed", "step": index, "message": f"send_text failed for step {index}"})
                return False
            continue

        if step_type == "send_key":
            delay_seconds = max(0.0, float(step.get("delay_seconds") or 0.0))
            if delay_seconds:
                await asyncio.sleep(delay_seconds)

            key = str(step.get("key") or "")
            repeat = max(1, int(step.get("repeat") or 1))
            for press in range(1, repeat + 1):
                ok = bool(send_key(vm_name, key))
                await _emit({"status": "send_key", "step": index, "press": press, "key": key, "ok": ok})
                if not ok:
                    await _emit({"status": "failed", "step": index, "message": f"send_key failed for step {index}"})
                    return False
            continue

    await _emit({"status": "completed"})
    return True