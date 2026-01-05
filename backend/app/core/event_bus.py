import asyncio
import json
import os
from typing import Dict, Set
from fastapi import WebSocket
# Avoid circular import: compute WORK_DIR relative to project root instead of importing vm_manager
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WORK_DIR = ROOT_DIR


class EventBus:
    def __init__(self):
        # run_id -> set of WebSocket
        self._subs: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, run_id: str, ws: WebSocket):
        async with self._lock:
            if run_id not in self._subs:
                self._subs[run_id] = set()
            self._subs[run_id].add(ws)

    async def disconnect(self, run_id: str, ws: WebSocket):
        async with self._lock:
            if run_id in self._subs and ws in self._subs[run_id]:
                self._subs[run_id].remove(ws)
                if not self._subs[run_id]:
                    del self._subs[run_id]

    async def publish(self, run_id: str, event: dict):
        async with self._lock:
            conns = list(self._subs.get(run_id, []))
        for ws in conns:
            try:
                await ws.send_json(event)
            except Exception:
                # ignore send errors; disconnect will clean up
                pass

    async def publish_by_definition_level(self, definition_id: str, level_idx: int, event: dict):
        # Look for runs that match definition and current_level
        runs_dir = os.path.join(WORK_DIR, "training_runs")
        if not os.path.exists(runs_dir):
            return
        for fn in os.listdir(runs_dir):
            if not fn.endswith('.json'):
                continue
            try:
                with open(os.path.join(runs_dir, fn), 'r') as f:
                    data = json.load(f)
                    if data.get('definition_id') == definition_id and data.get('current_level') == level_idx and data.get('state') == 'running':
                        run_id = data.get('id')
                        await self.publish(run_id, event)
            except Exception:
                continue


event_bus = EventBus()
