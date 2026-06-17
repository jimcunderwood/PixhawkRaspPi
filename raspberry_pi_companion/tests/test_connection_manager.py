"""
Tests for MAVLink connection resiliency.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config.settings import ConnectionType, MAVLinkConfig
from src.mavlink.connection_manager import ConnectionManager


class FakeEvent:
    def __init__(self):
        self._is_set = False
        self.wait_calls = []

    def set(self):
        self._is_set = True

    def clear(self):
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return self._is_set


class FakeVehicle:
    def __init__(self, last_heartbeat=None):
        self.last_heartbeat = last_heartbeat
        self.listeners = []
        self.closed = False

    def add_message_listener(self, name, callback):
        self.listeners.append(("add", name))

    def remove_message_listener(self, name, callback):
        self.listeners.append(("remove", name))

    def close(self):
        self.closed = True


def _build_manager():
    config = MAVLinkConfig(
        connection_type=ConnectionType.SERIAL,
        port="/dev/null",
        baudrate=57600,
        timeout=30,
    )
    manager = ConnectionManager(config)
    manager._monitor_stop_event = FakeEvent()
    manager._monitor_active = True
    manager._reconnect_backoff_seconds = 1.0
    return manager


def test_monitor_thread_reconnects_without_spawning_a_new_monitor(monkeypatch):
    manager = _build_manager()
    initial_vehicle = FakeVehicle(last_heartbeat=999.0)
    reconnected_vehicle = FakeVehicle(last_heartbeat=0.1)
    manager.vehicle = initial_vehicle
    manager.connected = True

    callback_events = []
    cleanup_calls = []

    monkeypatch.setattr(
        ConnectionManager,
        "_vehicle_connection_healthy",
        lambda self: False,
    )
    monkeypatch.setattr(
        ConnectionManager,
        "_cleanup_obstacle_gpio",
        lambda self: cleanup_calls.append("gpio"),
    )
    monkeypatch.setattr(
        ConnectionManager,
        "_cleanup_obstacle_ros_bridge",
        lambda self: cleanup_calls.append("ros"),
    )
    monkeypatch.setattr(
        ConnectionManager,
        "_trigger_callback",
        lambda self, event, data=None: callback_events.append(event),
    )

    def fake_connect(self, start_monitor=True):
        assert start_monitor is False
        self.vehicle = reconnected_vehicle
        self.connected = True
        self._trigger_callback("connected")
        self._monitor_stop_event.set()
        return True

    monkeypatch.setattr(ConnectionManager, "connect", fake_connect)

    manager._monitor_connection()

    assert manager.connected is True
    assert manager.vehicle is reconnected_vehicle
    assert manager._reconnect_backoff_seconds == 1.0
    assert manager._monitor_stop_event.wait_calls == [1.0]
    assert callback_events == ["disconnected", "connected"]
    assert cleanup_calls == []


def test_monitor_thread_doubles_backoff_after_failed_reconnect(monkeypatch):
    manager = _build_manager()
    manager.vehicle = FakeVehicle(last_heartbeat=999.0)
    manager.connected = True

    reconnect_attempts = []
    cleanup_calls = []

    monkeypatch.setattr(
        ConnectionManager,
        "_vehicle_connection_healthy",
        lambda self: False,
    )
    monkeypatch.setattr(
        ConnectionManager,
        "_cleanup_obstacle_gpio",
        lambda self: cleanup_calls.append("gpio"),
    )
    monkeypatch.setattr(
        ConnectionManager,
        "_cleanup_obstacle_ros_bridge",
        lambda self: cleanup_calls.append("ros"),
    )
    monkeypatch.setattr(ConnectionManager, "_trigger_callback", lambda self, event, data=None: None)

    def fake_connect(self, start_monitor=True):
        assert start_monitor is False
        reconnect_attempts.append(self._reconnect_backoff_seconds)
        if len(reconnect_attempts) == 1:
            return False
        self.vehicle = FakeVehicle(last_heartbeat=0.1)
        self.connected = True
        self._monitor_stop_event.set()
        return True

    monkeypatch.setattr(ConnectionManager, "connect", fake_connect)

    manager._monitor_connection()

    assert reconnect_attempts == [1.0, 2.0]
    assert manager._reconnect_backoff_seconds == 1.0
    assert manager._monitor_stop_event.wait_calls == [1.0, 2.0]
    assert cleanup_calls == []
