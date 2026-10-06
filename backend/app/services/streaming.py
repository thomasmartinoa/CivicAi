"""WebSocket fan-out, keyed by tracking id.

Process-local by design: one registry per worker. A multi-worker deployment
needs a broker, which is out of scope while the app runs as a single process.
"""

import logging
from collections import defaultdict
from typing import Protocol

logger = logging.getLogger(__name__)


class Sendable(Protocol):
    async def send_json(self, message: dict) -> None: ...


class ConnectionRegistry:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Sendable]] = defaultdict(list)

    def connect(self, tracking_id: str, socket: Sendable) -> None:
        self._subscribers[tracking_id].append(socket)

    def disconnect(self, tracking_id: str, socket: Sendable) -> None:
        subscribers = self._subscribers.get(tracking_id, [])
        if socket in subscribers:
            subscribers.remove(socket)
        if not subscribers:
            self._subscribers.pop(tracking_id, None)

    def subscriber_count(self, tracking_id: str) -> int:
        return len(self._subscribers.get(tracking_id, []))

    async def publish(self, tracking_id: str, message: dict) -> None:
        """Best effort. A closed tab must not stop the graph from streaming."""
        for socket in list(self._subscribers.get(tracking_id, [])):
            try:
                await socket.send_json(message)
            except Exception:
                logger.debug("dropping dead subscriber for %s", tracking_id)
                self.disconnect(tracking_id, socket)


registry = ConnectionRegistry()
