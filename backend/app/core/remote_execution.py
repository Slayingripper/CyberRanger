import asyncio
from typing import Any, Dict


def run_ssh_command(
    *,
    host: str,
    username: str,
    password: str,
    command: str,
    port: int = 22,
    timeout_seconds: float = 120.0,
    connect_timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("Paramiko is not installed. Add it to backend requirements before using SSH runbook execution.") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=max(1.0, float(connect_timeout_seconds or 0.0)),
            auth_timeout=max(1.0, float(connect_timeout_seconds or 0.0)),
            banner_timeout=max(1.0, float(connect_timeout_seconds or 0.0)),
            look_for_keys=False,
            allow_agent=False,
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=max(1.0, float(timeout_seconds or 0.0)), get_pty=True)
        exit_status = int(stdout.channel.recv_exit_status())
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        return {
            "exit_status": exit_status,
            "stdout": stdout_text,
            "stderr": stderr_text,
        }
    finally:
        client.close()


async def run_ssh_command_async(**kwargs: Any) -> Dict[str, Any]:
    return await asyncio.to_thread(run_ssh_command, **kwargs)