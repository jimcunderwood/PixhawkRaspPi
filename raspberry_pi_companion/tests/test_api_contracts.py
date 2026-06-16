"""
API contract tests for normalized public models and auth metadata.
"""

import os
import sys

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api import server as server_module
from src.api.server import (
    ArmRequest,
    ControlAuthority,
    GoToRequest,
    NavigationConfigRequest,
    ServerAPI,
    WaypointRequest,
)


class FakeConnectionManager:
    connected = True

    def get_vehicle_state(self):
        return {
            "armed": False,
            "mode": "GUIDED",
            "location": {"latitude": 1.0, "longitude": 2.0, "altitude": 10.0},
            "battery": {"voltage": 12.0, "current": 1.0, "level_percent": 90},
            "ground_speed": 1.0,
            "air_speed": 1.0,
            "velocity": {"north": 0.0, "east": 0.0, "down": 0.0},
        }

    def get_prearm_status(self):
        return {
            "connected": True,
            "is_armable": True,
            "ekf_ok": True,
            "gps": {"fix_type": 3, "satellite_count": 10},
        }

    def upload_mission(self, mission_items):
        return {"success": True, "uploaded_count": len(mission_items)}

    def download_mission(self):
        return {"success": True, "count": 0, "items": [], "checksum": "empty"}

    def verify_mission(self, expected_items):
        return {"success": True, "matches": True}

    def clear_pixhawk_mission(self):
        return {"success": True, "pixhawk_count": 0}


class FakeMissionPlanner:
    pass


class FakeCamera:
    def __init__(self, photo_directory):
        self.photo_directory = photo_directory

    def is_available(self):
        return True

    def get_photo_path(self, filename, session=None):
        photo_path = self.photo_directory / filename
        return photo_path if photo_path.is_file() else None


class FakePayloadController:
    def __init__(self, tmp_path):
        self.camera = FakeCamera(tmp_path)
        self.camera_trigger = None
        self.flow_sensor = object()
        self.pressure_sensor = None
        self.tank_level_sensor = None

    def get_payload_status(self):
        return {
            "spray_pump": {"status": "off"},
            "camera": {"available": True},
        }

    def list_spray_sessions(self):
        return []

    def list_application_records(self):
        return []


class FakeTelemetryManager:
    last_update = 9999999999

    def get_current(self):
        return None


@pytest.fixture()
def server_api(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module.config.api, "auth_enabled", True)
    monkeypatch.setattr(server_module.config.api, "api_key", "test-key")
    monkeypatch.setattr(server_module.config.api, "audit_log_file", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(server_module.config.api, "safety_gates_enabled", True)
    return ServerAPI(
        FakeConnectionManager(),
        FakeMissionPlanner(),
        FakePayloadController(tmp_path),
        FakeTelemetryManager(),
    )


def test_strict_normalized_request_models():
    assert ArmRequest.model_validate({"armed": True}).armed is True
    assert WaypointRequest.model_validate(
        {
            "location": {"latitude": 1, "longitude": 2, "altitude": 10},
            "altitude_frame": "terrain",
        }
    ).location.altitude == 10
    assert GoToRequest.model_validate(
        {"location": {"latitude": 1, "longitude": 2, "altitude": 10}}
    ).location.longitude == 2

    with pytest.raises(ValidationError):
        ArmRequest.model_validate({"arm": True})

    with pytest.raises(ValidationError):
        WaypointRequest.model_validate({"latitude": 1, "longitude": 2, "altitude": 10})

    with pytest.raises(ValidationError):
        WaypointRequest.model_validate(
            {
                "location": {"latitude": 1, "longitude": 2, "altitude": 10},
                "altitude_frame": "moon",
            }
        )


def test_navigation_config_request_model():
    request = NavigationConfigRequest.model_validate(
        {
            "obstacle_avoidance": {
                "enabled": True,
                "mode": "bendy_ruler",
                "margin_meters": 2.5,
                "lookahead_meters": 6,
                "behavior": "slide",
            },
            "terrain_following": {
                "enabled": True,
                "source": "rangefinder",
                "min_agl_meters": 2,
                "max_agl_meters": 50,
            },
            "apply_to_pixhawk": True,
        }
    )

    assert request.obstacle_avoidance.mode == "bendy_ruler"
    assert request.terrain_following.source == "rangefinder"
    assert request.apply_to_pixhawk is True


class FakeRequest:
    def __init__(self, query_params):
        self.query_params = query_params


def test_media_routes_advertise_api_key_and_accept_query_key(server_api):
    schema = server_api.get_app().openapi()
    session_photo_schema = schema["paths"][
        "/api/payload/camera/sessions/{session}/photos/{filename}"
    ]["get"]
    legacy_photo_schema = schema["paths"]["/api/payload/camera/photos/{filename}"]["get"]
    stream_schema = schema["paths"]["/api/payload/camera/stream"]["get"]

    assert session_photo_schema["security"] == [{"APIKeyHeader": []}]
    assert legacy_photo_schema["security"] == [{"APIKeyHeader": []}]
    assert stream_schema["security"] == [{"APIKeyHeader": []}]

    server_api._require_api_key_header_or_query(
        FakeRequest({"api_key": "test-key"}),
        api_key=None,
    )

    with pytest.raises(HTTPException) as error:
        server_api._require_api_key_header_or_query(FakeRequest({}), api_key=None)
    assert error.value.status_code == 401


def test_client_bootstrap_and_mission_edit_routes_are_documented(server_api):
    paths = server_api.get_app().openapi()["paths"]

    assert "/api/system/info" in paths
    assert "/api/v1/system/info" in paths
    assert "/api/system/audit" in paths
    assert "/api/v1/system/audit" in paths
    assert "/api/mission/state" in paths
    assert "/api/v1/mission/state" in paths
    assert "/api/navigation/config" in paths
    assert "/api/v1/navigation/config" in paths
    assert "/api/navigation/apply" in paths
    assert "/api/v1/navigation/apply" in paths
    assert paths["/api/navigation/config"]["post"]["security"] == [
        {"APIKeyHeader": []}
    ]
    assert "/api/mission/waypoints/{index}" in paths
    assert "/api/v1/mission/waypoints/{index}" in paths
    assert paths["/api/mission/waypoints/{index}"]["delete"]["security"] == [
        {"APIKeyHeader": []}
    ]
    assert "/api/field-boundaries/{name}" in paths
    assert paths["/api/field-boundaries/{name}"]["delete"]["security"] == [
        {"APIKeyHeader": []}
    ]


def test_safety_gate_blocks_unhealthy_flight_command(server_api):
    server_api.connection_manager.get_prearm_status = lambda: {
        "connected": True,
        "is_armable": False,
        "ekf_ok": False,
        "gps": {"fix_type": 1, "satellite_count": 3},
    }

    with pytest.raises(HTTPException) as error:
        server_api._enforce_safety_gate("vehicle.arm")

    assert error.value.status_code == 409
    assert "Vehicle is not armable." in error.value.detail["blocking_reasons"]
    assert "EKF is not healthy." in error.value.detail["blocking_reasons"]


def test_audit_logger_records_and_filters_events(server_api):
    server_api._audit_command(
        "vehicle.arm",
        "success",
        parameters={"armed": True},
        details={"source": "test"},
    )
    server_api._audit_command(
        "vehicle.takeoff",
        "blocked",
        parameters={"altitude": 10},
        details={"reason": "test"},
    )

    events = server_api.audit_logger.recent(limit=10)
    assert len(events) == 2
    assert events[0]["action"] == "vehicle.takeoff"
    assert events[1]["action"] == "vehicle.arm"

    filtered = server_api.audit_logger.recent(limit=10, outcome="blocked")
    assert len(filtered) == 1
    assert filtered[0]["action"] == "vehicle.takeoff"


def test_control_authority_lease():
    authority = ControlAuthority(default_lease_seconds=30)
    acquired = authority.acquire("client-a", operator="pilot")
    token = acquired["authority"]["token"]

    assert acquired["active"] is True
    authority.require(token)

    with pytest.raises(HTTPException) as error:
        authority.require("bad-token")
    assert error.value.status_code == 403

    renewed = authority.renew(token)
    assert renewed["authority"]["token"] == token

    released = authority.release(token)
    assert released["active"] is True
    assert authority.status()["active"] is False


def test_operational_routes_are_documented(server_api):
    paths = server_api.get_app().openapi()["paths"]

    expected_paths = [
        "/api/control/authority",
        "/api/v1/control/authority",
        "/api/emergency/land",
        "/api/emergency/rtl",
        "/api/emergency/stop-spray",
        "/api/emergency/hold",
        "/api/mission/pixhawk/upload",
        "/api/mission/pixhawk/download",
        "/api/mission/pixhawk/verify",
        "/api/mission/pixhawk",
        "/api/payload/spray/application-records",
        "/api/payload/spray/sessions/{session}/application-record",
    ]

    for path in expected_paths:
        assert path in paths
