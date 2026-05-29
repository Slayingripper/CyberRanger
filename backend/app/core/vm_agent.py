import base64
import os
import shlex
from typing import Any, Dict, Optional

import httpx


VM_AGENT_DEFAULT_PORT = 8765
VM_AGENT_BOOTSTRAP_PATH = "/tmp/cyberange_vm_agent.py"
VM_AGENT_BOOTSTRAP_LOG = "/tmp/cyberange_vm_agent.log"


VM_AGENT_SCRIPT = r'''#!/usr/bin/env python3
import argparse
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


TASKS = {}
TASKS_LOCK = threading.Lock()
LOG_DIR = Path("/tmp/cyberange-vm-agent")
LOG_DIR.mkdir(parents=True, exist_ok=True)
AUTH_TOKEN = ""


def _tail_text(path_value, limit=2000):
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        try:
            handle.seek(-limit, os.SEEK_END)
        except OSError:
            handle.seek(0)
        return handle.read().decode("utf-8", errors="replace")


def _task_status(task):
    process = task.get("process")
    if process is None:
        return task.get("status") or "completed"
    exit_status = process.poll()
    if exit_status is None:
        return "running"
    if task.get("status") == "stopped":
        return "stopped"
    return "completed" if int(exit_status) == 0 else "failed"


def _task_snapshot(task_id, task):
    process = task.get("process")
    exit_status = process.poll() if process is not None else task.get("exit_status")
    status = _task_status(task)
    if exit_status is not None and not task.get("finished_at"):
        task["finished_at"] = time.time()
        task["exit_status"] = int(exit_status)

    return {
        "task_id": task_id,
        "status": status,
        "command": task.get("command"),
        "background": bool(task.get("background")),
        "pid": task.get("pid"),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "exit_status": task.get("exit_status") if task.get("exit_status") is not None else exit_status,
        "stdout_tail": _tail_text(task.get("stdout_path")),
        "stderr_tail": _tail_text(task.get("stderr_path")),
    }


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "CyberangeVmAgent/1.0"

    def log_message(self, format, *args):
        return

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(int(status_code))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorize(self):
        token = self.headers.get("X-Cyberange-Token")
        if token != AUTH_TOKEN:
            self._send_json(401, {"detail": "Unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self._authorize():
            return
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parts == ["health"]:
            with TASKS_LOCK:
                snapshot = {
                    task_id: _task_snapshot(task_id, task)
                    for task_id, task in TASKS.items()
                }
            self._send_json(200, {"status": "ok", "task_count": len(snapshot), "tasks": snapshot})
            return
        if parts == ["tasks"]:
            with TASKS_LOCK:
                snapshot = {
                    task_id: _task_snapshot(task_id, task)
                    for task_id, task in TASKS.items()
                }
            self._send_json(200, {"tasks": snapshot})
            return
        if len(parts) == 2 and parts[0] == "tasks":
            task_id = parts[1]
            with TASKS_LOCK:
                task = TASKS.get(task_id)
                if task is None:
                    self._send_json(404, {"detail": "Task not found"})
                    return
                snapshot = _task_snapshot(task_id, task)
            self._send_json(200, snapshot)
            return
        self._send_json(404, {"detail": "Not found"})

    def do_POST(self):
        if not self._authorize():
            return
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parts != ["tasks"]:
            self._send_json(404, {"detail": "Not found"})
            return

        payload = self._read_json()
        command = str(payload.get("command") or "").strip()
        if not command:
            self._send_json(400, {"detail": "Task command is required"})
            return

        background = bool(payload.get("background"))
        timeout_seconds = payload.get("timeout_seconds")
        cwd = str(payload.get("cwd") or "").strip() or None
        env = payload.get("environment") if isinstance(payload.get("environment"), dict) else None
        shell = str(payload.get("shell") or "/bin/bash").strip() or "/bin/bash"
        task_id = str(payload.get("task_id") or uuid.uuid4().hex)
        started_at = time.time()

        if background:
            stdout_path = LOG_DIR / f"{task_id}.stdout.log"
            stderr_path = LOG_DIR / f"{task_id}.stderr.log"
            merged_env = os.environ.copy()
            if env:
                merged_env.update({str(k): str(v) for k, v in env.items()})
            stdout_handle = stdout_path.open("ab")
            stderr_handle = stderr_path.open("ab")
            try:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    executable=shell,
                    cwd=cwd,
                    env=merged_env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    start_new_session=True,
                )
            finally:
                stdout_handle.close()
                stderr_handle.close()

            task = {
                "command": command,
                "background": True,
                "created_at": started_at,
                "started_at": started_at,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "pid": int(process.pid),
                "process": process,
            }
            with TASKS_LOCK:
                TASKS[task_id] = task
            self._send_json(202, _task_snapshot(task_id, task))
            return

        try:
            completed = subprocess.run(
                command,
                shell=True,
                executable=shell,
                cwd=cwd,
                env={**os.environ, **({str(k): str(v) for k, v in (env or {}).items()})},
                capture_output=True,
                text=True,
                timeout=float(timeout_seconds) if timeout_seconds is not None else None,
            )
        except subprocess.TimeoutExpired as exc:
            self._send_json(
                408,
                {
                    "task_id": task_id,
                    "status": "timed_out",
                    "command": command,
                    "background": False,
                    "created_at": started_at,
                    "started_at": started_at,
                    "finished_at": time.time(),
                    "exit_status": None,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                },
            )
            return

        finished_at = time.time()
        self._send_json(
            200,
            {
                "task_id": task_id,
                "status": "completed" if completed.returncode == 0 else "failed",
                "command": command,
                "background": False,
                "created_at": started_at,
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_status": int(completed.returncode),
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "stdout_tail": (completed.stdout or "")[-2000:],
                "stderr_tail": (completed.stderr or "")[-2000:],
            },
        )

    def do_DELETE(self):
        if not self._authorize():
            return
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0] != "tasks":
            self._send_json(404, {"detail": "Not found"})
            return

        task_id = parts[1]
        with TASKS_LOCK:
            task = TASKS.get(task_id)
            if task is None:
                self._send_json(404, {"detail": "Task not found"})
                return
            process = task.get("process")
            if process is None:
                self._send_json(409, {"detail": "Task is not a background process"})
                return
            if process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                task["status"] = "stopped"
            task["finished_at"] = time.time()
            task["exit_status"] = process.poll()
            snapshot = _task_snapshot(task_id, task)
        self._send_json(200, snapshot)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    global AUTH_TOKEN
    AUTH_TOKEN = args.token
    server = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
'''


def build_vm_agent_bootstrap_command(*, token: str, port: int = VM_AGENT_DEFAULT_PORT) -> str:
    script_b64 = base64.b64encode(VM_AGENT_SCRIPT.encode("utf-8")).decode("ascii")
    path_literal = repr(VM_AGENT_BOOTSTRAP_PATH)
    return "\n".join(
        [
            "set -e",
            "if ! command -v python3 >/dev/null 2>&1; then echo 'python3 is required for the VM agent' >&2; exit 127; fi",
            "python3 - <<'PY'",
            "import base64",
            "from pathlib import Path",
            f"path = Path({path_literal})",
            f"path.write_bytes(base64.b64decode({script_b64!r}))",
            "path.chmod(0o700)",
            "PY",
            f"nohup python3 {shlex.quote(VM_AGENT_BOOTSTRAP_PATH)} --host 0.0.0.0 --port {int(port)} --token {shlex.quote(str(token))} > {shlex.quote(VM_AGENT_BOOTSTRAP_LOG)} 2>&1 < /dev/null &",
            "echo 'agent-started'",
        ]
    )


async def call_vm_agent(
    *,
    host: str,
    token: str,
    method: str = "GET",
    path: str = "/health",
    payload: Optional[Dict[str, Any]] = None,
    port: int = VM_AGENT_DEFAULT_PORT,
    timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    normalized_path = path if str(path).startswith("/") else f"/{path}"
    connect_timeout = min(max(1.0, float(timeout_seconds or 0.0)), 10.0)
    timeout = httpx.Timeout(max(1.0, float(timeout_seconds or 0.0)), connect=connect_timeout)
    url = f"http://{host}:{int(port)}{normalized_path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method.upper(),
            url,
            json=payload if payload is not None else None,
            headers={"X-Cyberange-Token": str(token)},
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        if isinstance(data, dict):
            return data
        return {"data": data, "status_code": response.status_code, "url": url}