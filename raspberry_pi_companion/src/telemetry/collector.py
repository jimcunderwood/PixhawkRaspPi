"""
Telemetry System
Collects, streams, and stores vehicle telemetry data
Handles real-time data updates via WebSocket
"""

import logging
import time
import threading
import json
from datetime import datetime
from typing import Optional, Dict, List, Callable
from collections import deque

logger = logging.getLogger(__name__)


class TelemetryPoint:
    """Single telemetry data point"""

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
        """Convert to dictionary"""
        return json.loads(self._payload_json)

    def to_json(self) -> str:
        """Return a compact JSON payload for websocket broadcast."""
        return self._payload_json


class TelemetryCollector:
    """Collects and stores telemetry data"""

    def __init__(self, max_history: int = 3600, update_interval: float = 0.5):
        self.max_history = max_history
        self.update_interval = update_interval
        self.history: deque = deque(maxlen=max_history)
        self.current_state: Optional[Dict] = None
        self.last_update = 0
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []
        self._running = False

    def start(self, vehicle_getter: Callable):
        """
        Start telemetry collection
        
        Args:
            vehicle_getter: Callable that returns vehicle state dict
        """
        self._running = True
        self._collection_thread = threading.Thread(
            target=self._collect_loop,
            args=(vehicle_getter,),
            daemon=True
        )
        self._collection_thread.start()
        logger.info("Telemetry collection started")

    def stop(self):
        """Stop telemetry collection"""
        self._running = False
        logger.info("Telemetry collection stopped")

    def _collect_loop(self, vehicle_getter: Callable):
        """Collection loop running in background thread"""
        while self._running:
            try:
                vehicle_state = vehicle_getter()
                if vehicle_state:
                    self.add_point(vehicle_state)
                time.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"Error in telemetry collection: {str(e)}")
                time.sleep(1)

    def add_point(self, vehicle_state: dict):
        """Add telemetry point to history"""
        with self._lock:
            timestamp = time.time()
            point = TelemetryPoint(timestamp, vehicle_state)
            self.history.append(point)
            self.current_state = dict(vehicle_state)
            self.last_update = timestamp
            
            # Trigger callbacks
            for callback in list(self._callbacks):
                try:
                    callback(point)
                except Exception as e:
                    logger.error(f"Error in telemetry callback: {str(e)}")

    def get_current(self) -> Optional[Dict]:
        """Get most recent telemetry point"""
        with self._lock:
            return self.current_state

    def get_history(self, seconds: Optional[int] = None) -> List[Dict]:
        """
        Get telemetry history
        
        Args:
            seconds: Get last N seconds of data (None = all)
            
        Returns:
            List of telemetry points
        """
        with self._lock:
            if seconds is None:
                return [point.to_dict() for point in self.history]
            
            cutoff_time = time.time() - seconds
            return [
                point.to_dict() for point in self.history
                if point.timestamp >= cutoff_time
            ]

    def get_statistics(self, seconds: int = 60) -> Dict:
        """Get telemetry statistics over time window"""
        history = self.get_history(seconds)
        
        if not history:
            return {}
        
        stats = {
            'count': len(history),
            'duration': seconds,
            'start_time': history[0]['timestamp'],
            'end_time': history[-1]['timestamp'],
        }
        
        # Battery statistics
        battery_levels = [
            p['battery']['level_percent']
            for p in history
            if 'battery' in p and p['battery'].get('level_percent') is not None
        ]
        if battery_levels:
            stats['battery'] = {
                'min': min(battery_levels),
                'max': max(battery_levels),
                'avg': sum(battery_levels) / len(battery_levels),
                'current': battery_levels[-1],
            }
        
        # Altitude statistics
        altitudes = [
            p['location']['altitude']
            for p in history
            if 'location' in p and p['location'].get('altitude') is not None
        ]
        if altitudes:
            stats['altitude'] = {
                'min': min(altitudes),
                'max': max(altitudes),
                'avg': sum(altitudes) / len(altitudes),
                'current': altitudes[-1],
            }
        
        # Speed statistics
        speeds = [p.get('ground_speed', 0) for p in history]
        if speeds:
            stats['ground_speed'] = {
                'min': min(speeds),
                'max': max(speeds),
                'avg': sum(speeds) / len(speeds),
                'current': speeds[-1],
            }
        
        return stats

    def register_callback(self, callback: Callable):
        """Register callback for telemetry updates"""
        with self._lock:
            self._callbacks.append(callback)

    def clear_history(self):
        """Clear all stored telemetry data"""
        with self._lock:
            self.history.clear()
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

    def __init__(self, max_history: int = 3600, update_interval: float = 0.5):
        self.collector = TelemetryCollector(max_history, update_interval)
        self.stream = LiveTelemetryStream()
        self._vehicle_getter = None

    def initialize(self, vehicle_getter: Callable):
        """
        Initialize telemetry system
        
        Args:
            vehicle_getter: Callable that returns current vehicle state
        """
        self._vehicle_getter = vehicle_getter
        
        # Register stream callback
        self.collector.register_callback(self._on_telemetry_update)
        
        # Start collection
        self.collector.start(vehicle_getter)

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
