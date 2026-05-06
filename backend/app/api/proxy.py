from fastapi import APIRouter, HTTPException, WebSocket, status
import asyncio
import logging
from typing import Optional

from app.core.auth import get_current_user_from_websocket
from app.core.ownership import can_access_vm
from app.core.vm_manager import vm_manager

router = APIRouter()
logger = logging.getLogger(__name__)


def _find_vm_name_for_vnc_port(port: int) -> Optional[str]:
    for vm in vm_manager.list_domains():
        if str(vm.get("vnc_port") or "") == str(port):
            return str(vm.get("name") or "") or None
    return None

@router.websocket("/ws/vnc/{port}")
async def vnc_proxy(websocket: WebSocket, port: int):
    try:
        current_user = get_current_user_from_websocket(websocket)
        vm_name = _find_vm_name_for_vnc_port(port)
        if not vm_name:
            await websocket.close(code=4404)
            return
        if not can_access_vm(vm_name, current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this virtual machine console")
    except HTTPException as exc:
        await websocket.close(code=4403 if exc.status_code == status.HTTP_403_FORBIDDEN else 4401)
        return

    await websocket.accept()
    try:
        # VNC servers bound to localhost
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
    except Exception as e:
        logger.exception("Failed to connect to VNC on port %s", port)
        try:
            await websocket.close()
        except RuntimeError:
            # already closed
            pass
        return

    async def copy_from_ws():
        try:
            while True:
                message = await websocket.receive()
                payload = message.get("bytes")
                if payload is None:
                    if message.get("type") == "websocket.disconnect":
                        break
                    continue
                writer.write(payload)
                await writer.drain()
        except Exception:
            # remote closed or error reading from websocket/tcp
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def copy_from_tcp():
        try:
            while True:
                data = await reader.read(1024 * 64)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            # remote closed or error
            pass

    # Run both loops and stop when one completes, cancelling the other.
    ws_task = asyncio.create_task(copy_from_ws())
    tcp_task = asyncio.create_task(copy_from_tcp())

    done, pending = await asyncio.wait({ws_task, tcp_task}, return_when=asyncio.FIRST_COMPLETED)

    # Cancel any pending task and await cancellation
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    # Close resources once and guard against double-close errors
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass

    try:
        await websocket.close()
    except RuntimeError:
        # websocket already closed or response completed
        pass
    except Exception:
        pass
