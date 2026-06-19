"""
Tests for swarm persistence and API wiring.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

from src.api.server import ServerAPI
from src.swarm.database import SwarmDatabase, SwarmDatabaseConfig
from src.swarm.manager import SwarmManager


class FakeConnectionManager:
    connected = True

    def get_vehicle_state(self):
        return {
            "armed": True,
            "mode": "GUIDED",
            "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 52.0},
            "battery": {"level_percent": 88},
            "ground_speed": 3.2,
            "heading": 91.0,
            "gps": {"fix_type": 6, "satellite_count": 15, "horizontal_accuracy": 0.35},
        }

    def get_prearm_status(self):
        return {"gps": {"fix_type": 6, "satellite_count": 15}, "ekf_ok": True, "is_armable": True}

    def get_navigation_status(self):
        return {}


class FakeMissionPlanner:
    def get_navigation_config(self):
        return {"obstacle_avoidance": {}, "terrain_following": {}}


class FakePayloadController:
    camera = None

    def get_payload_status(self):
        return {}


class FakeTelemetryManager:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get_current(self):
        return self._snapshot


def _swarm_config():
    return {
        "swarm_id": "field-alpha-swarm",
        "enabled": True,
        "self_drone_id": "drone-01",
        "role": "leader",
        "transport": {"type": "native", "endpoint": "local"},
        "peers": [
            {
                "drone_id": "drone-01",
                "callsign": "Companion",
                "role": "leader",
                "transport": {"type": "native", "endpoint": "local"},
                "trust": "primary",
                "max_age_seconds": 2.0,
                "requires_rtk": False,
            },
            {
                "drone_id": "drone-02",
                "callsign": "Wingman",
                "role": "follower",
                "transport": {"type": "udp", "endpoint": "udp://127.0.0.1:14550"},
                "trust": "trusted",
                "max_age_seconds": 2.0,
                "requires_rtk": False,
            },
        ],
        "broadcast": {
            "enabled": True,
            "rate_hz": 2.0,
            "include_location": True,
            "include_velocity": True,
            "include_quality": True,
            "include_vehicle_state": True,
            "include_alerts": True,
        },
        "fusion": {
            "mode": "weighted_gnss",
            "min_peer_count": 1,
            "max_peer_age_seconds": 2.0,
            "require_reference_node": True,
            "reference_node_id": "drone-01",
            "use_peer_velocity": True,
            "weights": {
                "self_position": 0.7,
                "peer_position": 0.2,
                "peer_velocity": 0.05,
                "heading": 0.03,
                "quality": 0.02,
            },
        },
        "safety": {
            "min_horizontal_separation_m": 8.0,
            "min_vertical_separation_m": 3.0,
            "warn_distance_m": 15.0,
            "critical_distance_m": 8.0,
            "hold_on_loss": True,
            "hold_timeout_seconds": 3.0,
        },
    }


def test_swarm_database_persists_telemetry_and_fusion(tmp_path):
    database = SwarmDatabase(
        SwarmDatabaseConfig(
            path=tmp_path / "swarm.sqlite3",
            max_bytes=1024 * 1024,
            backup_count=2,
            vacuum_interval_seconds=0,
        )
    )
    manager = SwarmManager(
        database,
        local_state_getter=lambda: {
            "timestamp": time.time(),
            "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 52.0},
            "armed": True,
            "mode": "GUIDED",
            "battery": {"level_percent": 88},
            "ground_speed": 3.2,
            "heading": 91.0,
            "gps": {"fix_type": 6, "satellite_count": 15, "horizontal_accuracy": 0.35},
        },
    )
    manager.update_config(_swarm_config())

    sample = manager.broadcast_local_snapshot()
    fusion = manager.get_fusion_state()
    telemetry = manager.get_telemetry()

    try:
        assert sample["swarm_id"] == "field-alpha-swarm"
        assert telemetry and telemetry[0]["sample_id"] == sample["sample_id"]
        assert fusion["swarm_id"] == "field-alpha-swarm"
        assert fusion["fused_location"]["latitude"] == sample["location"]["latitude"]
    finally:
        database.close()


def test_swarm_routes_expose_persisted_state(tmp_path, monkeypatch):
    snapshot = {
        "timestamp": time.time(),
        "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 52.0},
        "armed": True,
        "mode": "GUIDED",
        "battery": {"level_percent": 88},
        "ground_speed": 3.2,
        "heading": 91.0,
        "gps": {"fix_type": 6, "satellite_count": 15, "horizontal_accuracy": 0.35},
    }
    database = SwarmDatabase(
        SwarmDatabaseConfig(
            path=tmp_path / "swarm.sqlite3",
            max_bytes=1024 * 1024,
            backup_count=2,
            vacuum_interval_seconds=0,
        )
    )
    swarm_manager = SwarmManager(database, local_state_getter=lambda: snapshot)
    swarm_manager.update_config(_swarm_config())

    server = ServerAPI(
        FakeConnectionManager(),
        FakeMissionPlanner(),
        FakePayloadController(),
        FakeTelemetryManager(snapshot),
        swarm_manager=swarm_manager,
    )
    monkeypatch.setattr(server, "_require_command_authority", lambda *args, **kwargs: None)

    async def exercise_routes():
        config_endpoint = next(
            route.endpoint
            for route in server.get_app().routes
            if getattr(route, "path", None) == "/api/swarm/config" and "GET" in getattr(route, "methods", [])
        )
        broadcast_endpoint = next(
            route.endpoint
            for route in server.get_app().routes
            if getattr(route, "path", None) == "/api/swarm/broadcast" and "POST" in getattr(route, "methods", [])
        )
        status_endpoint = next(
            route.endpoint
            for route in server.get_app().routes
            if getattr(route, "path", None) == "/api/swarm/status" and "GET" in getattr(route, "methods", [])
        )

        config_response = await config_endpoint()
        broadcast_response = await broadcast_endpoint()
        status_response = await status_endpoint()
        return config_response, broadcast_response, status_response

    config_response, broadcast_response, status_response = asyncio.run(exercise_routes())

    try:
        assert config_response.data["swarm_id"] == "field-alpha-swarm"
        assert broadcast_response.data["sample"]["source_drone_id"] == "drone-01"
        assert broadcast_response.data["fusion"]["swarm_id"] == "field-alpha-swarm"
        assert status_response.data["enabled"] is True
        assert status_response.data["peer_count"] == 2
        assert status_response.data["healthy_peer_count"] >= 1
    finally:
        database.close()
