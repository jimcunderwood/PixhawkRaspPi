"""Telemetry system with SQLite-backed history."""

import json
import logging
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .database import TelemetryDatabase, TelemetryDatabaseConfig

logger = logging.getLogger(__name__)


class TelemetryPoint:
    """Single telemetry data point."""

    __slots__ = ("timestamp", "_payload_json")

    def __init__(self, timestamp: float, vehicle_state: dict):
        self.timestamp = timestamp
        payload = {
            "timestamp": timestamp,
            "datetime": datetime.fromtimestamp(timestamp).isoformat(),
            **vehicle_state,
        }
        self._payload_json = json.dumps(payload, separators=(",", ":"))

    def to_dict(self) -> dict:
        return json.loads(self._payload_json)

    def to_json(self) -> str:
        return self._payload_json


class TelemetryCollector:
    """Collects telemetry and persists it to SQLite."""

    def __init__(
        self,
        max_history: int = 3600,
        update_interval: float = 0.5,
        database: Optional[TelemetryDatabase] = None,
    ):
        self.max_history = max_history
        self.update_interval = update_interval
        self.database = database or TelemetryDatabase(
            TelemetryDatabaseConfig(
                path=Path(tempfile.mkdtemp(prefix="telemetry-")) / "telemetry.sqlite3",
            )
        )
        self.current_state: Optional[Dict] = None
        self.last_update = 0.0
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []
        self._running = False
        self._collection_thread: Optional[threading.Thread] = None

    def attach_database(self, database: TelemetryDatabase):
        self.database = database

    def start(self, vehicle_getter: Callable, payload_getter: Optional[Callable] = None):
        """Start telemetry collection."""
        self._running = True
        self._collection_thread = threading.Thread(
            target=self._collect_loop,
            args=(vehicle_getter, payload_getter),
            daemon=True,
        )
        self._collection_thread.start()
        logger.info("Telemetry collection started")

    def stop(self):
        """Stop telemetry collection."""
        self._running = False
        if self._collection_thread and self._collection_thread.is_alive():
            self._collection_thread.join(timeout=2)
        if self.database:
            try:
                self.database.close()
            except Exception as e:
                logger.debug("Telemetry database close failed: %s", str(e))
        logger.info("Telemetry collection stopped")

    def _collect_loop(self, vehicle_getter: Callable, payload_getter: Optional[Callable]):
        """Collection loop running in background thread."""
        while self._running:
            try:
                vehicle_state = vehicle_getter()
                if vehicle_state:
                    payload_state = payload_getter() if payload_getter else None
                    self.add_point(vehicle_state, payload_state=payload_state)
                time.sleep(self.update_interval)
            except Exception as e:
                logger.error("Error in telemetry collection: %s", str(e))
                time.sleep(1)

    def add_point(self, vehicle_state: dict, payload_state: Optional[dict] = None):
        """Add telemetry point to history and SQLite."""
        with self._lock:
            timestamp = time.time()
            snapshot = {
                "timestamp": timestamp,
                "datetime": datetime.fromtimestamp(timestamp).isoformat(),
                **vehicle_state,
            }
            if payload_state is not None:
                snapshot["payload"] = payload_state

            point = TelemetryPoint(timestamp, snapshot)
            self.current_state = dict(snapshot)
            self.last_update = timestamp

            if self.database:
                self.database.record(snapshot)

            for callback in list(self._callbacks):
                try:
                    callback(point)
                except Exception as e:
                    logger.error("Error in telemetry callback: %s", str(e))

    def get_current(self) -> Optional[Dict]:
        """Get most recent telemetry point."""
        with self._lock:
            return self.current_state

    def get_history(self, seconds: Optional[int] = None) -> List[Dict]:
        """Get telemetry history from SQLite."""
        if not self.database:
            return []
        return self.database.query(seconds=seconds)

    def get_statistics(self, seconds: int = 60) -> Dict:
        """Get telemetry statistics over a time window."""
        if not self.database:
            return {}
        return self.database.statistics(seconds)

    def register_callback(self, callback: Callable):
        """Register callback for telemetry updates."""
        with self._lock:
            self._callbacks.append(callback)

    def clear_history(self):
        """Clear all stored telemetry data."""
        with self._lock:
            if self.database:
                self.database.clear()
            self.current_state = None
            logger.info("Telemetry history cleared")


class LiveTelemetryStream:
    """Manages live telemetry streaming to connected clients"""

    def __init__(self):
        self.subscribers: Dict[str, Callable] = {}

    def subscribe(self, client_id: str, send_callback: Callable):
        """Subscribe to telemetry updates"""
        self.subscribers[client_id] = send_callback
        logger.info(f"Client {client_id} subscribed to telemetry")

    def unsubscribe(self, client_id: str):
        """Unsubscribe from telemetry updates"""
        if client_id in self.subscribers:
            del self.subscribers[client_id]
            logger.info(f"Client {client_id} unsubscribed from telemetry")

    def broadcast(self, data: str):
        """Broadcast telemetry to all subscribers"""
        disconnected = []

        for client_id, send_callback in self.subscribers.items():
            try:
                send_callback(data)
            except Exception as e:
                logger.warning(f"Failed to send to {client_id}: {str(e)}")
                disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            self.unsubscribe(client_id)


class TelemetryManager:
    """High-level telemetry management"""

    def __init__(self, max_history: int = 3600, update_interval: float = 0.5, database: Optional[TelemetryDatabase] = None):
        self.collector = TelemetryCollector(max_history, update_interval, database=database)
        self.stream = LiveTelemetryStream()
        self._vehicle_getter = None

    def initialize(self, vehicle_getter: Callable, payload_getter: Optional[Callable] = None):
        """
        Initialize telemetry system
        
        Args:
            vehicle_getter: Callable that returns current vehicle state
        """
        self._vehicle_getter = vehicle_getter
        
        # Register stream callback
        self.collector.register_callback(self._on_telemetry_update)
        
        # Start collection
        self.collector.start(vehicle_getter, payload_getter=payload_getter)

    def _on_telemetry_update(self, point: TelemetryPoint):
        """Handle new telemetry point"""
        self.stream.broadcast(point.to_json())

    def get_current(self) -> Optional[Dict]:
        """Get current telemetry"""
        return self.collector.get_current()

    @property
    def last_update(self) -> float:
        """Timestamp of the most recent telemetry update."""
        return self.collector.last_update

    def get_history(self, seconds: Optional[int] = None) -> List[Dict]:
        """Get telemetry history"""
        return self.collector.get_history(seconds)

    def get_statistics(self, seconds: int = 60) -> Dict:
        """Get statistics"""
        return self.collector.get_statistics(seconds)

    def subscribe(self, client_id: str, send_callback: Callable):
        """Subscribe to live telemetry"""
        self.stream.subscribe(client_id, send_callback)

    def unsubscribe(self, client_id: str):
        """Unsubscribe from live telemetry"""
        self.stream.unsubscribe(client_id)

    def stop(self):
        """Stop telemetry collection"""
        self.collector.stop()
