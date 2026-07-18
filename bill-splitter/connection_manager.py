"""
Tracks which WebSocket clients are currently "watching" each group, and
lets the rest of the app broadcast an event to everyone watching a group
whenever something changes (a new expense, a new settlement, etc).

This is in-memory, single-process. If you later run multiple server
instances (see Day 6 -- Docker Compose), a broadcast from instance A won't
reach a client connected to instance B unless you add Redis Pub/Sub in
front of this. For a single local server, this is all you need.
"""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # group_id -> list of currently-open websocket connections
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, group_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(group_id, []).append(websocket)

    def disconnect(self, group_id: int, websocket: WebSocket):
        connections = self.active_connections.get(group_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if group_id in self.active_connections and not self.active_connections[group_id]:
            del self.active_connections[group_id]

    async def broadcast(self, group_id: int, message: dict):
        """Send `message` (as JSON) to every client currently watching this group."""
        connections = self.active_connections.get(group_id, [])
        dead_connections = []

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                # the client disconnected without us noticing yet -- clean it up
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(group_id, connection)


# A single shared instance, imported by main.py
manager = ConnectionManager()
