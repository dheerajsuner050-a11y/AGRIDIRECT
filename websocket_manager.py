import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("agridirect.websocket")

class DeliveryConnectionManager:
    """Manages real-time WebSocket connections for live GPS tracking and delivery updates."""
    def __init__(self):
        # order_id -> Set of active WebSockets
        self.active_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, order_id: int, websocket: WebSocket):
        await websocket.accept()
        if order_id not in self.active_connections:
            self.active_connections[order_id] = set()
        self.active_connections[order_id].add(websocket)
        logger.info(f"WebSocket client connected to order #{order_id}. Total listeners: {len(self.active_connections[order_id])}")

    def disconnect(self, order_id: int, websocket: WebSocket):
        if order_id in self.active_connections:
            self.active_connections[order_id].discard(websocket)
            if not self.active_connections[order_id]:
                del self.active_connections[order_id]
        logger.info(f"WebSocket client disconnected from order #{order_id}.")

    async def broadcast_to_order(self, order_id: int, message: dict):
        if order_id not in self.active_connections:
            return

        dead_connections = set()
        payload = json.dumps(message)

        for connection in self.active_connections[order_id]:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket on order #{order_id}: {e}")
                dead_connections.add(connection)

        for dead in dead_connections:
            self.active_connections[order_id].discard(dead)

    async def broadcast_location(
        self,
        order_id: int,
        partner_id: int,
        latitude: float,
        longitude: float,
        speed: float = 0.0,
        heading: float = 0.0,
        distance_km: float = 0.0,
        eta_mins: int = 0
    ):
        """Broadcasts real-time vehicle GPS coordinates to all listeners."""
        await self.broadcast_to_order(order_id, {
            "type": "LOCATION_UPDATE",
            "order_id": order_id,
            "partner_id": partner_id,
            "latitude": latitude,
            "longitude": longitude,
            "speed": speed,
            "heading": heading,
            "distance_km": distance_km,
            "eta_mins": eta_mins
        })

    async def broadcast_status(self, order_id: int, status: str, metadata: dict = None):
        """Broadcasts delivery state machine transitions."""
        payload = {
            "type": "STATUS_UPDATE",
            "order_id": order_id,
            "status": status,
            "metadata": metadata or {}
        }
        await self.broadcast_to_order(order_id, payload)

delivery_ws_manager = DeliveryConnectionManager()
