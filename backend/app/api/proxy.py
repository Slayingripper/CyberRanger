from fastapi import APIRouter, WebSocket
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/ws/vnc/{port}")
async def vnc_proxy(websocket: WebSocket, port: int):
    await websocket.accept()
    try:
        # VNC servers bound to localhost
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
    except Exception as e:
        print(f"Failed to connect to VNC on port {port}: {e}")
        await websocket.close()
        return

    async def copy_from_ws():
        try:
            while True:
                message = await websocket.receive_bytes()
                writer.write(message)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def copy_from_tcp():
        try:
            while True:
                data = await reader.read(1024 * 64)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass
        finally:
            await websocket.close()

    await asyncio.gather(copy_from_ws(), copy_from_tcp())
