from typing import Dict, List
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, tracking_id: str, websocket: WebSocket):
        await websocket.accept()
        if tracking_id not in self.connections:
            self.connections[tracking_id] = []
        self.connections[tracking_id].append(websocket)

    def disconnect(self, tracking_id: str, websocket: WebSocket):
        if tracking_id in self.connections:
            self.connections[tracking_id].remove(websocket)
            if not self.connections[tracking_id]:
                del self.connections[tracking_id]

    async def send_update(self, tracking_id: str, message: dict):
        if tracking_id in self.connections:
            for ws in self.connections[tracking_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(tracking_id, ws)


ws_manager = WebSocketManager()
