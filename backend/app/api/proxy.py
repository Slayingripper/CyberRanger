from fastapi import APIRouter, WebSocket
import asyncio
import logging
from typing import Set

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/ws/vnc/{port}")
async def vnc_proxy(websocket: WebSocket, port: int):
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
                message = await websocket.receive_bytes()
                writer.write(message)
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
