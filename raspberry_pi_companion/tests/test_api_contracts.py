"""
API contract tests for normalized public models and auth metadata.
"""

import os
import sys
import asyncio
import io
from pathlib import Path

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("pydantic")

from fastapi import HTTPException, WebSocketDisconnect
from fastapi.routing import APIRoute
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api import server as server_module
from src.api.server import (
    ArmRequest,
    ApiRole,
    BaseStationWizardRequest,
    CalibrationConfigRequest,
    ConfigProfileApplyRequest,
    ConfigProfileSaveRequest,
    ControlAuthority,
    ControlAuthorityRequest,
    ExifGeotagRequest,
    GoToRequest,
    GeofenceZoneRequest,
    GeotagExportRequest,
    GeotagRecordRequest,
    GeoTiffBoundsRequest,
    MappingCameraSpecRequest,
    NavigationConfigRequest,
    OrthomosaicPreviewRequest,
    FarmExportRequest,
    PpkProcessRequest,
    PointCloudScanRequest,
    RemoteIDRequest,
    SwarmConfig,
    SurveyGridPlanRequest,
    NdviPreviewRequest,
    SprayApplicationRecordRequest,
    ServerAPI,
    WaiverRequest,
    WaypointRequest,
    api_auth_context,
)


class FakeConnectionManager:
    connected = True

    def get_connection_status(self):
        return {
            "state": "connected",
            "connected": True,
            "monitoring": True,
            "reconnecting": False,
            "retry_backoff_seconds": 0.0,
            "max_retry_backoff_seconds": 30.0,
            "last_changed_at": 1234567890.0,
            "last_error": None,
        }

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

    def get_navigation_status(self):
        return {
            "obstacle_avoidance": {
                "parameters": {
                    "AVOID_ENABLE": 7,
                },
                "proximity": {
                    "available": True,
                    "source": "mavlink.distance_sensor",
                    "sensor_id": 1,
                    "coverage_mode": "forward",
                    "distance_meters": 12.3,
                },
                "sensor": {
                    "available": True,
                    "source": "mavlink.distance_sensor",
                    "sensor_id": 1,
                    "coverage_mode": "forward",
                    "distance_meters": 12.3,
                    "mavlink_sensor_id": 1,
                },
            },
            "terrain_following": {
                "parameters": {
                    "TERRAIN_ENABLE": 1,
                },
                "terrain": {
                    "available": True,
                    "source": "mavlink.distance_sensor",
                    "sensor_id": 0,
                    "rangefinder_distance_meters": 6.7,
                },
                "hooks": {
                    "ros_bridge_enabled": True,
                    "ros_backend": "mavros",
                    "ros_topic": "/terrain/range",
                    "mavros_topic": "/mavros/distance_sensor/hrlv_ez4_pub",
                    "ros_frame_id": "base_link",
                },
            },
            "distance_sensors": [
                {
                    "sensor_id": 0,
                    "orientation": 25,
                    "distance_meters": 6.7,
                    "source": "mavlink.distance_sensor",
                },
                {
                    "sensor_id": 1,
                    "orientation": 0,
                    "distance_meters": 12.3,
                    "source": "mavlink.distance_sensor",
                },
            ],
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
    def __init__(self):
        self.mission_items = []
        self.navigation_config = {
            "obstacle_avoidance": {
                "enabled": False,
                "mode": "simple",
                "margin_meters": 2.0,
                "lookahead_meters": 5.0,
                "backup_speed_mps": 0.0,
                "min_altitude_meters": 0.0,
                "proximity_type": 4,
                "behavior": "slide",
                "bendy_ruler_type": "horizontal",
                "obstacle_database_size": None,
                "sensor": {
                    "source": "mavlink",
                    "coverage_mode": "forward",
                    "mavlink_sensor_id": 1,
                    "gpio_pin": None,
                    "gpio_active_low": True,
                    "ros_enabled": True,
                    "ros_backend": "mavros",
                    "ros_topic": "/obstacle/distance",
                    "ros_frame_id": "base_link",
                    "ros_message_type": "std_msgs/Float32",
                },
            },
            "terrain_following": {
                "enabled": False,
                "source": "rangefinder",
                "min_agl_meters": 2.0,
                "max_agl_meters": 120.0,
                "target_agl_meters": None,
                "use_rangefinder_for_waypoints": True,
                "rtl_terrain_enabled": False,
                "terrain_spacing_meters": None,
                "ros_bridge_enabled": True,
                "ros_backend": "mavros",
                "ros_topic": "/terrain/range",
                "mavros_topic": "/mavros/distance_sensor/hrlv_ez4_pub",
                "ros_frame_id": "base_link",
            },
        }

    def pause_mission(self):
        return None

    def resume_mission(self):
        return None

    def abort_mission(self):
        return None

    def get_navigation_config(self):
        return {
            "obstacle_avoidance": self.navigation_config["obstacle_avoidance"].copy(),
            "terrain_following": self.navigation_config["terrain_following"].copy(),
        }

    def update_navigation_config(self, obstacle_avoidance=None, terrain_following=None):
        if obstacle_avoidance is not None:
            self.navigation_config["obstacle_avoidance"].update(obstacle_avoidance)
        if terrain_following is not None:
            self.navigation_config["terrain_following"].update(terrain_following)
        return self.get_navigation_config()


class FakeCamera:
    def __init__(self, photo_directory):
        self.photo_directory = photo_directory

    def is_available(self):
        return True

    def get_photo_path(self, filename, session=None):
        photo_path = self.photo_directory / filename
        return photo_path if photo_path.is_file() else None


class FakeMappingCamera(FakeCamera):
    def get_session_manifest(self, session):
        return {
            "session": session,
            "photos": [
                {
                    "filename": "red.jpg",
                    "captured_at": 1_700_000_000.0,
                    "session": session,
                    "geotag": {
                        "location": {
                            "latitude": 40.1,
                            "longitude": -74.2,
                            "altitude": 55.0,
                        },
                        "heading": 90.0,
                        "captured_at": 1_700_000_000.0,
                    },
                    "camera_trigger": {"triggered_at": 1_700_000_000.1},
                }
            ],
        }


class FakePayloadController:
    def __init__(self, tmp_path):
        self.camera = FakeCamera(tmp_path)
        self.camera_trigger = None
        self.flow_sensor = object()
        self.pressure_sensor = None
        self.tank_level_sensor = None
        self.calibration = {
            "flow_sensor": {"pulses_per_liter": 450.0},
            "pressure_sensor": {
                "min_voltage": 0.5,
                "max_voltage": 4.5,
                "min_psi": 0.0,
                "max_psi": 150.0,
            },
            "tank_level_sensor": {
                "min_voltage": 0.5,
                "max_voltage": 4.5,
                "capacity_liters": 10.0,
                "minimum_level_percent": 10.0,
            },
            "terrain_sensor": {
                "min_agl_meters": 2.0,
                "max_agl_meters": 120.0,
            },
        }

    def get_payload_status(self):
        return {
            "spray_pump": {"status": "off"},
            "camera": {"available": True},
        }

    def list_spray_sessions(self):
        return []

    def list_application_records(self):
        return []

    def get_application_record(self, session):
        return None

    def get_calibration_config(self):
        return {
            group: values.copy()
            for group, values in self.calibration.items()
        }

    def update_calibration_config(self, calibration):
        before = self.get_calibration_config()
        for group, values in calibration.items():
            self.calibration[group].update(values)
        return {
            "before": before,
            "after": self.get_calibration_config(),
            "applied": calibration,
            "persistent": False,
        }

    def create_application_record(self, session, metadata=None):
        return {
            "session": session,
            "metadata": metadata or {},
            "record_file": f"{session}.json",
        }


class FakeTelemetryManager:
    last_update = 9999999999

    def get_current(self):
        return {
            "timestamp": 1_700_000_120.0,
            "location": {"latitude": 40.101, "longitude": -74.199, "altitude": 51.0},
            "ground_speed": 3.4,
            "heading": 91.0,
            "gps": {"fix_type": 6, "satellite_count": 16},
        }

    def get_history(self, seconds=None):
        return [
            {
                "timestamp": 1_700_000_000.0,
                "location": {"latitude": 40.1000, "longitude": -74.2000, "altitude": 50.0},
                "ground_speed": 3.0,
            },
            {
                "timestamp": 1_700_000_060.0,
                "location": {"latitude": 40.1005, "longitude": -74.1995, "altitude": 50.5},
                "ground_speed": 3.5,
            },
            {
                "timestamp": 1_700_000_120.0,
                "location": {"latitude": 40.1010, "longitude": -74.1990, "altitude": 51.0},
                "ground_speed": 3.9,
            },
        ]


@pytest.fixture()
def server_api(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module.config.api, "auth_enabled", True)
    monkeypatch.setattr(server_module.config.api, "api_key", "test-key")
    monkeypatch.setattr(server_module.config.api, "api_key_role", "admin")
    monkeypatch.setattr(server_module.config.api, "api_key_roles", {"test-key": "admin"})
    monkeypatch.setattr(server_module.config.api, "audit_log_file", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(
        server_module.config.api,
        "config_database_file",
        str(tmp_path / "config" / "profiles.sqlite3"),
    )
    monkeypatch.setattr(
        server_module.config.storage,
        "geotiff_database_file",
        str(tmp_path / "geotiff" / "geotiff.sqlite3"),
    )
    monkeypatch.setattr(
        server_module.config.storage,
        "geotiff_asset_directory",
        str(tmp_path / "geotiff" / "assets"),
    )
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


def test_mapping_request_models():
    assert MappingCameraSpecRequest.model_validate(
        {
            "sensor_width_mm": 13.2,
            "sensor_height_mm": 8.8,
            "image_width_px": 4000,
            "image_height_px": 3000,
            "focal_length_mm": 8.8,
        }
    ).image_width_px == 4000

    assert SurveyGridPlanRequest.model_validate(
        {
            "field_boundary": {
                "name": "Field A",
                "vertices": [
                    {"latitude": 40.0, "longitude": -74.0},
                    {"latitude": 40.0, "longitude": -73.9},
                    {"latitude": 40.1, "longitude": -73.9},
                ],
            },
            "camera_spec": {
                "sensor_width_mm": 13.2,
                "sensor_height_mm": 8.8,
                "image_width_px": 4000,
                "image_height_px": 3000,
                "focal_length_mm": 8.8,
            },
        }
    ).field_boundary.name == "Field A"

    assert GeotagRecordRequest.model_validate(
        {
            "filename": "img_0001.jpg",
            "latitude": 40.0,
            "longitude": -74.0,
            "altitude_m": 50.0,
            "captured_at": 1_700_000_000.0,
        }
    ).filename == "img_0001.jpg"

    assert GeotagExportRequest.model_validate(
        {"records": [{"filename": "img_0001.jpg", "latitude": 40.0, "longitude": -74.0, "altitude_m": 50.0, "captured_at": 1_700_000_000.0}]}
    ).records[0].filename == "img_0001.jpg"

    assert NdviPreviewRequest.model_validate(
        {"red_filename": "red.jpg", "nir_filename": "nir.jpg"}
    ).red_band_index == server_module.config.mapping.ndvi_red_band_index

    assert OrthomosaicPreviewRequest.model_validate(
        {"filenames": ["a.jpg", "b.jpg"]}
    ).columns == server_module.config.mapping.orthomosaic_preview_max_columns

    assert PointCloudScanRequest.model_validate(
        {
            "field_boundary": {
                "name": "Field B",
                "vertices": [
                    {"latitude": 40.0, "longitude": -74.0},
                    {"latitude": 40.0, "longitude": -73.9},
                    {"latitude": 40.1, "longitude": -73.9},
                ],
            }
        }
    ).field_boundary.name == "Field B"

    assert GeofenceZoneRequest.model_validate(
        {
            "name": "Airport NFZ",
            "zone_type": "no_fly",
            "polygon": [
                {"latitude": 40.0, "longitude": -74.0},
                {"latitude": 40.0, "longitude": -73.9},
                {"latitude": 40.1, "longitude": -73.9},
            ],
        }
    ).name == "Airport NFZ"

    assert RemoteIDRequest.model_validate(
        {"enabled": True, "operator_id": "pilot-1", "broadcast_method": "mavlink"}
    ).operator_id == "pilot-1"

    assert WaiverRequest.model_validate(
        {"night_flight_authorized": True, "notes": "Night waiver"}
    ).night_flight_authorized is True


def test_geotiff_preview_support_generates_metadata_and_preview(server_api):
    image = Image.new("RGB", (64, 32), color=(40, 180, 120))
    geotiff_bytes = io.BytesIO()
    image.save(geotiff_bytes, format="TIFF")

    preview_bytes, preview_meta = server_api._preview_image_from_geotiff(geotiff_bytes.getvalue(), 48)
    metadata = server_api.geotiff_assets.save_asset(
        name="Field North",
        source_filename="field-north.tif",
        bounds=GeoTiffBoundsRequest(north=40.2, south=40.1, east=-74.1, west=-74.2).model_dump(),
        source_bytes=geotiff_bytes.getvalue(),
        preview_bytes=preview_bytes,
        preview_meta=preview_meta,
    )

    assert metadata["asset_id"].startswith("geotiff-")
    assert metadata["bounds"]["north"] == 40.2
    assert Path(metadata["preview_path"]).is_file()
    assert Path(metadata["source_path"]).is_file()
    assert metadata["preview_width_px"] > 0
    assert metadata["preview_height_px"] > 0

    assert preview_bytes[:4] == b"\x89PNG"
    assert preview_meta["source_width_px"] == 64
    assert preview_meta["source_height_px"] == 32


def test_safety_and_compliance_routes_expose_state(server_api):
    app = server_api.get_app()
    geofences_endpoint = get_route_endpoint(app, "/api/safety/geofences", "GET")
    safety_status_endpoint = get_route_endpoint(app, "/api/safety/status", "GET")
    remote_id_endpoint = get_route_endpoint(app, "/api/compliance/remote-id", "GET")
    waivers_endpoint = get_route_endpoint(app, "/api/compliance/waivers", "GET")
    arming_checks_endpoint = get_route_endpoint(app, "/api/arming/checks", "GET")

    geofence_response = asyncio.run(geofences_endpoint())
    safety_response = asyncio.run(safety_status_endpoint())
    remote_id_response = asyncio.run(remote_id_endpoint())
    waivers_response = asyncio.run(waivers_endpoint())
    arming_response = asyncio.run(arming_checks_endpoint())

    assert geofence_response.data["zones"] == []
    assert "remote_id" in safety_response.data
    assert "waivers" in safety_response.data
    assert isinstance(remote_id_response.data, dict)
    assert isinstance(waivers_response.data, dict)
    assert "prearm" in arming_response.data


def test_navigation_config_serialization_exposes_sensor_hooks(server_api, monkeypatch):
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_enabled", True)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_mode", "bendy_ruler")
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_margin_meters", 3.0)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_lookahead_meters", 8.0)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_backup_speed_mps", 1.5)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_min_altitude_meters", 2.5)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_proximity_type", 4)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_behavior", "slide")
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_bendy_ruler_type", "horizontal")
    monkeypatch.setattr(server_module.config.mission, "obstacle_database_size", 250)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_source", "gpio")
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_coverage_mode", "360")
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_mavlink_id", 1)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_gpio_pin", 23)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_gpio_active_low", False)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_ros_enabled", True)
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_ros_backend", "mavros")
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_ros_topic", "/obstacle/distance")
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_ros_frame_id", "base_link")
    monkeypatch.setattr(server_module.config.mission, "obstacle_avoidance_sensor_ros_message_type", "std_msgs/Float32")
    monkeypatch.setattr(server_module.config.mission, "terrain_target_agl_meters", 9.5)
    monkeypatch.setattr(server_module.config.mission, "terrain_use_rangefinder_for_waypoints", True)
    monkeypatch.setattr(server_module.config.mission, "terrain_rtl_enabled", False)
    monkeypatch.setattr(server_module.config.mission, "terrain_spacing_meters", 15.0)
    monkeypatch.setattr(server_module.config.mission, "terrain_ros_bridge_enabled", True)
    monkeypatch.setattr(server_module.config.mission, "terrain_ros_backend", "mavros")
    monkeypatch.setattr(server_module.config.mission, "terrain_ros_topic", "/terrain/range")
    monkeypatch.setattr(server_module.config.mission, "terrain_mavros_topic", "/mavros/distance_sensor/hrlv_ez4_pub")
    monkeypatch.setattr(server_module.config.mission, "terrain_ros_frame_id", "base_link")

    async def exercise_routes():
        endpoint = get_route_endpoint(
            server_api.get_app(),
            "/info",
            "GET",
        )
        response = await endpoint()
        return response

    response = asyncio.run(exercise_routes())
    system_info = response.data

    obstacle_defaults = system_info["mission"]["obstacle_avoidance_defaults"]
    terrain_defaults = system_info["mission"]["terrain_following_defaults"]
    obstacle_sensor = obstacle_defaults["sensor"]
    navigation_config = system_info["navigation"]["config"]
    navigation_pixhawk = system_info["navigation"]["pixhawk"]
    mavlink_status = system_info["mavlink"]["connection_status"]

    assert obstacle_defaults["enabled"] is True
    assert obstacle_defaults["mode"] == "bendy_ruler"
    assert obstacle_sensor["source"] == "gpio"
    assert obstacle_sensor["coverage_mode"] == "360"
    assert obstacle_sensor["mavlink_sensor_id"] == 1
    assert obstacle_sensor["gpio_pin"] == 23
    assert obstacle_sensor["gpio_active_low"] is False
    assert obstacle_sensor["ros_enabled"] is True
    assert obstacle_sensor["ros_backend"] == "mavros"
    assert obstacle_sensor["ros_topic"] == "/obstacle/distance"
    assert obstacle_sensor["ros_frame_id"] == "base_link"
    assert obstacle_sensor["ros_message_type"] == "std_msgs/Float32"
    assert terrain_defaults["ros_bridge_enabled"] is True
    assert terrain_defaults["ros_backend"] == "mavros"
    assert terrain_defaults["ros_topic"] == "/terrain/range"
    assert terrain_defaults["mavros_topic"] == "/mavros/distance_sensor/hrlv_ez4_pub"
    assert terrain_defaults["ros_frame_id"] == "base_link"
    assert mavlink_status["state"] == "connected"
    assert mavlink_status["connected"] is True
    assert navigation_config["obstacle_avoidance"]["sensor"]["coverage_mode"] == "forward"
    assert navigation_config["obstacle_avoidance"]["sensor"]["ros_topic"] == "/obstacle/distance"
    assert navigation_config["terrain_following"]["ros_bridge_enabled"] is True
    assert navigation_config["terrain_following"]["mavros_topic"] == "/mavros/distance_sensor/hrlv_ez4_pub"
    assert navigation_pixhawk["obstacle_avoidance"]["sensor"]["available"] is True
    assert navigation_pixhawk["terrain_following"]["hooks"]["ros_bridge_enabled"] is True
    assert navigation_pixhawk["distance_sensors"][0]["sensor_id"] == 0

    snapshot = server_api._current_config_snapshot()
    assert snapshot["navigation"]["obstacle_avoidance"]["sensor"]["source"] == "mavlink"
    assert snapshot["navigation"]["obstacle_avoidance"]["sensor"]["ros_topic"] == "/obstacle/distance"
    assert snapshot["navigation"]["terrain_following"]["ros_bridge_enabled"] is True
    assert snapshot["navigation"]["terrain_following"]["mavros_topic"] == "/mavros/distance_sensor/hrlv_ez4_pub"


def test_navigation_sensors_endpoint_exposes_live_status(server_api):
    async def exercise_routes():
        endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/navigation/sensors",
            "GET",
        )
        response = await endpoint()
        return response

    response = asyncio.run(exercise_routes())
    data = response.data

    assert data["obstacle_avoidance"]["available"] is True
    assert data["obstacle_avoidance"]["source"] == "mavlink.distance_sensor"
    assert data["obstacle_avoidance"]["sensor_id"] == 1
    assert data["terrain_following"]["available"] is True
    assert data["terrain_following"]["source"] == "mavlink.distance_sensor"
    assert data["terrain_following"]["sensor_id"] == 0
    assert data["distance_sensors"][0]["sensor_id"] == 0
    assert data["distance_sensors"][1]["sensor_id"] == 1


def test_mapping_endpoints_expose_planning_and_artifacts(server_api, tmp_path, monkeypatch):
    server_api.payload_controller.camera = FakeMappingCamera(tmp_path)
    monkeypatch.setattr(server_api, "_require_command_authority", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_api, "_require_success", lambda *args, **kwargs: None)

    Image.new("RGB", (32, 32), color="red").save(tmp_path / "red.jpg")
    Image.new("RGB", (32, 32), color="green").save(tmp_path / "nir.jpg")
    Image.new("RGB", (32, 32), color="white").save(tmp_path / "photo1.jpg")
    Image.new("RGB", (32, 32), color="white").save(tmp_path / "photo2.jpg")

    async def exercise_routes():
        survey_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/mapping/survey-grid",
            "POST",
        )
        export_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/mapping/geotag/export",
            "POST",
        )
        ndvi_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/mapping/ndvi/preview",
            "POST",
        )
        mosaic_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/mapping/orthomosaic/preview",
            "POST",
        )
        scan_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/mapping/point-cloud/scan",
            "POST",
        )
        geotag_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/mapping/geotag/exif",
            "POST",
        )

        survey_response = await survey_endpoint(
            SurveyGridPlanRequest(
                field_boundary={
                    "name": "Field A",
                    "vertices": [
                        {"latitude": 40.0, "longitude": -74.0},
                        {"latitude": 40.0, "longitude": -73.999},
                        {"latitude": 40.001, "longitude": -73.999},
                    ],
                    "altitude": 12.0,
                },
                camera_spec={
                    "sensor_width_mm": 13.2,
                    "sensor_height_mm": 8.8,
                    "image_width_px": 4000,
                    "image_height_px": 3000,
                    "focal_length_mm": 8.8,
                },
            ),
            x_control_token=None,
        )
        export_response = await export_endpoint(
            GeotagExportRequest(
                records=[
                    GeotagRecordRequest(
                        filename="img_0001.jpg",
                        latitude=40.1,
                        longitude=-74.2,
                        altitude_m=55.0,
                        captured_at=1_700_000_000.0,
                    )
                ]
            ),
            x_control_token=None,
        )
        ndvi_response = await ndvi_endpoint(
            NdviPreviewRequest(red_filename="red.jpg", nir_filename="nir.jpg"),
            x_control_token=None,
        )
        mosaic_response = await mosaic_endpoint(
            OrthomosaicPreviewRequest(filenames=["photo1.jpg", "photo2.jpg"]),
            x_control_token=None,
        )
        scan_response = await scan_endpoint(
            PointCloudScanRequest(
                field_boundary={
                    "name": "Scan Field",
                    "vertices": [
                        {"latitude": 40.0, "longitude": -74.0},
                        {"latitude": 40.0, "longitude": -73.999},
                        {"latitude": 40.001, "longitude": -73.999},
                    ],
                }
            ),
            x_control_token=None,
        )
        geotag_response = await geotag_endpoint(
            ExifGeotagRequest(session="field-1"),
            x_control_token=None,
        )
        return survey_response, export_response, ndvi_response, mosaic_response, scan_response, geotag_response

    survey_response, export_response, ndvi_response, mosaic_response, scan_response, geotag_response = asyncio.run(exercise_routes())

    assert survey_response.data["waypoints"]
    assert export_response.media_type == "text/csv"
    assert "img_0001.jpg" in export_response.body.decode()
    assert ndvi_response.media_type == "image/png"
    assert mosaic_response.media_type == "image/png"
    assert scan_response.data["points"]
    assert geotag_response.data["tagged_count"] >= 0


def test_calibration_farm_swarm_and_geotiff_flows_round_trip(server_api, tmp_path):
    server_api.payload_controller.camera = FakeMappingCamera(tmp_path)

    async def exercise_routes():
        api_headers = {"x-api-key": "test-key"}
        authority_endpoint = get_route_endpoint(server_api.get_app(), "/api/control/authority", "POST")
        calibration_status_endpoint = get_route_endpoint(server_api.get_app(), "/api/calibration/status", "GET")
        save_base_station_endpoint = get_route_endpoint(server_api.get_app(), "/api/calibration/rtk/base-stations", "POST")
        ppk_endpoint = get_route_endpoint(server_api.get_app(), "/api/calibration/ppk/process", "POST")
        farm_status_endpoint = get_route_endpoint(server_api.get_app(), "/api/farm/status", "GET")
        isoxml_endpoint = get_route_endpoint(server_api.get_app(), "/api/farm/integrations/isoxml/export", "POST")
        agleader_endpoint = get_route_endpoint(server_api.get_app(), "/api/farm/integrations/agleader/sync", "POST")
        report_endpoint = get_route_endpoint(server_api.get_app(), "/api/farm/reports/automated", "POST")
        swarm_config_endpoint = get_route_endpoint(server_api.get_app(), "/api/swarm/config", "GET")
        validate_swarm_endpoint = get_route_endpoint(server_api.get_app(), "/api/swarm/config/validate", "POST")
        update_swarm_endpoint = get_route_endpoint(server_api.get_app(), "/api/swarm/config", "PUT")
        broadcast_swarm_endpoint = get_route_endpoint(server_api.get_app(), "/api/swarm/broadcast", "POST")
        swarm_coordination_endpoint = get_route_endpoint(server_api.get_app(), "/api/swarm/coordination", "GET")
        swarm_history_endpoint = get_route_endpoint(server_api.get_app(), "/api/swarm/telemetry/history", "GET")

        authority_response = await authority_endpoint(ControlAuthorityRequest(client_id="test-suite", operator="qa"))
        control_token = authority_response.data["authority"]["token"]
        command_token = control_token

        calibration_response = await calibration_status_endpoint()
        assert calibration_response.data["base_station_count"] >= 0

        save_base_station_response = await save_base_station_endpoint(
            BaseStationWizardRequest(
                station_id="base-01",
                name="Field base station",
                latitude=40.1,
                longitude=-74.2,
                altitude_m=50.0,
                antenna_height_m=1.5,
                correction_port="/dev/ttyUSB0",
                correction_baudrate=115200,
                mount_type="tripod",
                activate=True,
            ),
            x_control_token=command_token,
        )
        assert save_base_station_response.data["active"] is True

        ppk_response = await ppk_endpoint(
            PpkProcessRequest(
                session="spray-001",
                base_station_id="base-01",
                telemetry_window_seconds=120,
                source_label="telemetry-history",
            ),
            x_control_token=command_token,
        )
        ppk_job = ppk_response.data
        assert ppk_job["request"]["base_station_id"] == "base-01"
        assert ppk_job["summary"]["sample_count"] == 3

        calibration_status = (await calibration_status_endpoint()).data
        assert calibration_status["active_base_station"]["station_id"] == "base-01"
        assert calibration_status["recent_jobs"][0]["job_id"] == ppk_job["job_id"]

        telemetry_history = server_api.telemetry_manager.get_history(120)
        assert len(telemetry_history) == 3

        farm_status_before = (await farm_status_endpoint()).data
        assert farm_status_before["configured"] in {True, False}

        isoxml_response = await isoxml_endpoint(FarmExportRequest(session="spray-001"), x_control_token=command_token)
        assert isoxml_response.data["archive_path"].endswith(".zip")

        agleader_response = await agleader_endpoint(FarmExportRequest(session="spray-001"), x_control_token=command_token)
        assert agleader_response.data["payload"]["telemetry_samples"] == 3

        report_response = await report_endpoint(FarmExportRequest(session="spray-001"), x_control_token=command_token)
        assert report_response.data["summary"]["telemetry_samples"] == 3

        farm_status_after = (await farm_status_endpoint()).data
        assert farm_status_after["recent_isoxml_exports"]
        assert farm_status_after["recent_reports"]
        assert farm_status_after["latest_report"]["name"].startswith("report-")

        swarm_config = (await swarm_config_endpoint()).data
        swarm_config["enabled"] = True
        swarm_config["role"] = "leader"
        swarm_config["fusion"]["mode"] = "relative_pose"
        swarm_config["fusion"]["reference_node_id"] = "drone-01"
        swarm_config["peers"] = [
            {
                **swarm_config["peers"][0],
                "callsign": "Companion",
                "role": "leader",
            },
            {
                "drone_id": "drone-02",
                "callsign": "Wing",
                "role": "follower",
                "transport": {"type": "udp", "endpoint": "udp://127.0.0.1:14550"},
                "trust": "trusted",
                "max_age_seconds": 2.0,
                "requires_rtk": False,
            },
        ]

        validate_swarm_response = await validate_swarm_endpoint(SwarmConfig.model_validate(swarm_config))
        assert validate_swarm_response.data["role"] == "leader"

        update_swarm_response = await update_swarm_endpoint(SwarmConfig.model_validate(swarm_config), x_control_token=command_token)
        updated_swarm = update_swarm_response.data
        assert updated_swarm["role"] == "leader"
        assert len(updated_swarm["peers"]) == 2

        broadcast_swarm_response = await broadcast_swarm_endpoint()
        assert broadcast_swarm_response.data["fusion"]["peer_count"] >= 0

        swarm_coordination_response = await swarm_coordination_endpoint()
        assert swarm_coordination_response.data["formation_mode"] == "leader_follower"

        swarm_history_response = await swarm_history_endpoint(seconds=120, limit=2)
        assert len(swarm_history_response.data["samples"]) >= 0

        image = Image.new("RGB", (64, 32), color=(40, 180, 120))
        geotiff_bytes = io.BytesIO()
        image.save(geotiff_bytes, format="TIFF")
        preview_bytes, preview_meta = server_api._preview_image_from_geotiff(geotiff_bytes.getvalue(), 48)
        geotiff_asset = server_api.geotiff_assets.save_asset(
            name="Field North",
            source_filename="field-north.tif",
            bounds=GeoTiffBoundsRequest(north=40.2, south=40.1, east=-74.1, west=-74.2).model_dump(),
            source_bytes=geotiff_bytes.getvalue(),
            preview_bytes=preview_bytes,
            preview_meta=preview_meta,
        )
        assert geotiff_asset["asset_id"].startswith("geotiff-")

        geotiff_detail = server_api.geotiff_assets.get_asset(geotiff_asset["asset_id"])
        assert geotiff_detail["source_filename"] == "field-north.tif"
        assert Path(geotiff_detail["preview_path"]).is_file()
        assert Path(geotiff_detail["source_path"]).is_file()

    asyncio.run(exercise_routes())


def test_health_and_readiness_expose_pixhawk_connection_state(server_api, monkeypatch):
    monkeypatch.setattr(
        server_api.connection_manager,
        "get_connection_status",
        lambda: {
            "state": "reconnecting",
            "connected": False,
            "monitoring": True,
            "reconnecting": True,
            "retry_backoff_seconds": 4.0,
            "max_retry_backoff_seconds": 30.0,
            "last_changed_at": 1234567890.0,
            "last_error": "heartbeat timeout",
        },
    )
    server_api.connection_manager.connected = False

    async def exercise_routes():
        health_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/health",
            "GET",
        )
        readiness_endpoint = get_route_endpoint(
            server_api.get_app(),
            "/readiness",
            "GET",
        )
        health_response = await health_endpoint()
        readiness_response = await readiness_endpoint()
        return health_response, readiness_response

    health_response, readiness_response = asyncio.run(exercise_routes())

    assert health_response["status"] == "degraded"
    assert health_response["message"] == "Pi is running, but Pixhawk is not connected."
    assert health_response["pixhawk_connection"]["state"] == "reconnecting"
    assert health_response["pixhawk_connection_state"] == "reconnecting"
    assert readiness_response.data["checks"]["pixhawk_connection"]["state"] == "reconnecting"
    assert "Pixhawk is reconnecting." in readiness_response.data["checks"]["blocking_reasons"]


def test_payload_record_start_uses_session_video_path(server_api, monkeypatch, tmp_path):
    class FakeVideoCamera:
        def __init__(self):
            self.recorded_paths = []

        def build_video_recording_path(self, session=None):
            session_name = session or "default"
            return tmp_path / session_name / "videos" / f"video_{session_name}.mp4"

        def start_video_recording(self, filename):
            self.recorded_paths.append(filename)
            return True

        def stop_video_recording(self):
            return True

    server_api.payload_controller.camera = FakeVideoCamera()
    monkeypatch.setattr(server_api, "_require_command_authority", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_api, "_require_success", lambda *args, **kwargs: None)

    async def exercise_routes():
        endpoint = get_route_endpoint(
            server_api.get_app(),
            "/api/payload/control",
            "POST",
        )
        response = await endpoint(
            server_module.PayloadControlRequest(action=server_module.PayloadAction.RECORD_START, session="field-7"),
            x_control_token=None,
        )
        return response

    response = asyncio.run(exercise_routes())

    assert response.status == "success"
    assert response.data["session"] == "field-7"
    assert response.data["path"].endswith("field-7/videos/video_field-7.mp4")
    assert server_api.payload_controller.camera.recorded_paths == [
        response.data["path"]
    ]


class FakeRequest:
    def __init__(self, query_params):
        self.query_params = query_params


class FakeURL:
    def __init__(self, path, query=""):
        self.path = path
        self.query = query


class FakeIdempotencyRequest:
    def __init__(
        self,
        method="POST",
        path="/api/vehicle/arm",
        query="",
        headers=None,
    ):
        self.method = method
        self.url = FakeURL(path, query=query)
        self.headers = headers or {}
        self.query_params = {}


class FakeEventWebSocket:
    def __init__(self, api_key="test-key", expected_messages=2):
        self.headers = {}
        self.query_params = {"api_key": api_key}
        self.expected_messages = expected_messages
        self.accepted = False
        self.closed = False
        self.sent = []
        self.disconnect = asyncio.Event()

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=None):
        self.closed = True

    async def send_json(self, data):
        self.sent.append(data)
        if len(self.sent) >= self.expected_messages:
            self.disconnect.set()

    async def receive_text(self):
        await self.disconnect.wait()
        raise WebSocketDisconnect()


def get_route_endpoint(app, path, method):
    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in (route.methods or [])
        ):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


def get_websocket_endpoint(app, path):
    for route in app.routes:
        if not isinstance(route, APIRoute) and getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"WebSocket route not found: {path}")


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


def test_api_key_roles_gate_command_and_audit_access(server_api, monkeypatch):
    token = api_auth_context.set(None)
    monkeypatch.setattr(server_module.config.api, "api_key", "")
    monkeypatch.setattr(
        server_module.config.api,
        "api_key_roles",
        {
            "viewer-key": "viewer",
            "operator-key": "operator",
            "maintenance-key": "maintenance",
            "admin-key": "admin",
        },
    )

    try:
        viewer = server_api._require_api_key_value("viewer-key")
        assert viewer.role == ApiRole.VIEWER
        with pytest.raises(HTTPException) as viewer_command_error:
            server_api._require_command_role()
        assert viewer_command_error.value.status_code == 403
        with pytest.raises(HTTPException) as viewer_audit_error:
            server_api._require_roles(server_module.AUDIT_ROLES)
        assert viewer_audit_error.value.status_code == 403

        operator = server_api._require_api_key_value("operator-key")
        assert operator.role == ApiRole.OPERATOR
        server_api._require_command_role()

        maintenance = server_api._require_api_key_value("maintenance-key")
        assert maintenance.role == ApiRole.MAINTENANCE
        server_api._require_roles(server_module.MAINTENANCE_ROLES)
        server_api._require_roles(server_module.AUDIT_ROLES)
        with pytest.raises(HTTPException) as maintenance_command_error:
            server_api._require_command_role()
        assert maintenance_command_error.value.status_code == 403

        admin = server_api._require_api_key_value("admin-key")
        assert admin.role == ApiRole.ADMIN
        server_api._require_command_role()
        server_api._require_roles(server_module.AUDIT_ROLES)
    finally:
        api_auth_context.reset(token)


def test_idempotency_cache_replays_same_request_and_detects_conflict(server_api):
    request = FakeIdempotencyRequest(
        headers={"idempotency-key": "retry-1", "x-api-key": "test-key"}
    )
    idempotency_key = server_api._get_idempotency_key(request)
    cache_id = server_api._idempotency_cache_id(request, idempotency_key)
    fingerprint = server_api._idempotency_fingerprint(request, b'{"armed":true}')
    response = Response(
        content=b'{"status":"success"}',
        status_code=200,
        media_type="application/json",
    )

    server_api._store_idempotency_record(cache_id, fingerprint, response, response.body)
    record = server_api._get_idempotency_record(cache_id)
    replay = server_api._build_idempotency_replay_response(record)
    conflicting_fingerprint = server_api._idempotency_fingerprint(
        request,
        b'{"armed":false}',
    )

    assert record["fingerprint"] == fingerprint
    assert replay.status_code == 200
    assert replay.headers["x-idempotency-status"] == "replayed"
    assert replay.body == b'{"status":"success"}'
    assert conflicting_fingerprint != record["fingerprint"]


def test_calibration_config_update_endpoint_updates_values_and_audits(server_api):
    async def exercise_routes():
        server_api._require_api_key_value("test-key")
        acquire_authority = get_route_endpoint(
            server_api.get_app(),
            "/api/control/authority",
            "POST",
        )
        get_calibration = get_route_endpoint(
            server_api.get_app(),
            "/api/config/calibration",
            "GET",
        )
        update_calibration = get_route_endpoint(
            server_api.get_app(),
            "/api/config/calibration",
            "PATCH",
        )

        authority_response = await acquire_authority(
            ControlAuthorityRequest(client_id="maintenance-ui")
        )
        token = authority_response.data["authority"]["token"]
        update_response = await update_calibration(
            CalibrationConfigRequest(
                flow_sensor={"pulses_per_liter": 500.0},
                pressure_sensor={"min_voltage": 0.4, "max_voltage": 4.6},
                tank_level_sensor={
                    "capacity_liters": 12.0,
                    "minimum_level_percent": 15.0,
                },
                terrain_sensor={"min_agl_meters": 3.0, "max_agl_meters": 100.0},
            ),
            x_control_token=token,
        )
        get_response = await get_calibration()
        return update_response, get_response

    token = api_auth_context.set(None)
    try:
        update_response, get_response = asyncio.run(exercise_routes())
    finally:
        api_auth_context.reset(token)

    assert update_response.status == "success"
    calibration = update_response.data["calibration"]
    assert calibration["flow_sensor"]["pulses_per_liter"] == 500.0
    assert calibration["pressure_sensor"]["min_voltage"] == 0.4
    assert calibration["pressure_sensor"]["max_voltage"] == 4.6
    assert calibration["tank_level_sensor"]["capacity_liters"] == 12.0
    assert calibration["tank_level_sensor"]["minimum_level_percent"] == 15.0
    assert calibration["terrain_sensor"]["min_agl_meters"] == 3.0
    assert calibration["terrain_sensor"]["max_agl_meters"] == 100.0
    assert get_response.data["calibration"] == calibration

    events = server_api.audit_logger.recent(limit=10, action="config.calibration_update")
    assert len(events) == 1
    assert events[0]["outcome"] == "success"
    assert events[0]["parameters"]["flow_sensor"]["pulses_per_liter"] == 500.0
    assert events[0]["details"]["before"]["flow_sensor"]["pulses_per_liter"] == 450.0
    assert events[0]["details"]["after"]["flow_sensor"]["pulses_per_liter"] == 500.0


def test_config_profiles_store_retrieve_and_reapply_runtime_values(server_api):
    async def exercise_routes():
        server_api._require_api_key_value("test-key")
        acquire_authority = get_route_endpoint(
            server_api.get_app(),
            "/api/control/authority",
            "POST",
        )
        save_profile = get_route_endpoint(
            server_api.get_app(),
            "/api/config/profiles",
            "POST",
        )
        list_profiles = get_route_endpoint(
            server_api.get_app(),
            "/api/config/profiles",
            "GET",
        )
        get_profile = get_route_endpoint(
            server_api.get_app(),
            "/api/config/profiles/{name}",
            "GET",
        )
        apply_profile = get_route_endpoint(
            server_api.get_app(),
            "/api/config/profiles/{name}/apply",
            "POST",
        )

        authority_response = await acquire_authority(
            ControlAuthorityRequest(client_id="maintenance-ui")
        )
        token = authority_response.data["authority"]["token"]
        saved = await save_profile(
            ConfigProfileSaveRequest(
                name="field-baseline",
                description="Known-good runtime config",
            ),
            x_control_token=token,
        )
        listed = await list_profiles()
        retrieved = await get_profile("field-baseline")

        server_api.payload_controller.update_calibration_config(
            {"flow_sensor": {"pulses_per_liter": 600.0}}
        )
        applied = await apply_profile(
            "field-baseline",
            ConfigProfileApplyRequest(),
            x_control_token=token,
        )
        return saved, listed, retrieved, applied

    token = api_auth_context.set(None)
    try:
        saved, listed, retrieved, applied = asyncio.run(exercise_routes())
    finally:
        api_auth_context.reset(token)

    profile = saved.data["profile"]
    assert profile["name"] == "field-baseline"
    assert profile["description"] == "Known-good runtime config"
    assert {
        "runtime",
        "mavlink",
        "api",
        "payload",
        "mission",
        "telemetry",
        "navigation",
        "calibration",
    }.issubset(profile["configuration"].keys())
    assert listed.data["profiles"][0]["name"] == "field-baseline"
    assert retrieved.data["profile"]["configuration"] == profile["configuration"]
    assert (
        server_api.payload_controller.calibration["flow_sensor"]["pulses_per_liter"]
        == 450.0
    )
    assert applied.data["result"]["applied"]["calibration"] == [
        "flow_sensor",
        "pressure_sensor",
        "tank_level_sensor",
        "terrain_sensor",
    ]

    stored_events = server_api.audit_logger.recent(limit=10, action="config.profile_store")
    retrieve_events = server_api.audit_logger.recent(limit=10, action="config.profile_retrieve")
    apply_events = server_api.audit_logger.recent(limit=10, action="config.profile_apply")
    assert stored_events[0]["outcome"] == "success"
    assert retrieve_events[0]["outcome"] == "success"
    assert apply_events[0]["outcome"] == "success"


def test_client_bootstrap_and_mission_edit_routes_are_documented(server_api):
    paths = server_api.get_app().openapi()["paths"]

    assert "/info" in paths
    assert "/v1/info" in paths
    assert "/readiness" in paths
    assert "/v1/readiness" in paths
    assert "/api/system/audit" in paths
    assert "/api/v1/system/audit" in paths
    assert "/api/config/calibration" in paths
    assert "/api/v1/config/calibration" in paths
    assert "/api/config/profiles" in paths
    assert "/api/v1/config/profiles" in paths
    assert "/api/config/profiles/{name}" in paths
    assert "/api/v1/config/profiles/{name}" in paths
    assert "/api/config/profiles/{name}/apply" in paths
    assert "/api/v1/config/profiles/{name}/apply" in paths
    assert "/api/mission/state" in paths
    assert "/api/v1/mission/state" in paths
    assert "/api/navigation/config" in paths
    assert "/api/v1/navigation/config" in paths
    assert "/api/navigation/apply" in paths
    assert "/api/v1/navigation/apply" in paths
    assert "/api/mapping/geotiff" in paths
    assert "/api/v1/mapping/geotiff" in paths
    assert "/api/mapping/geotiff/upload" in paths
    assert "/api/v1/mapping/geotiff/upload" in paths
    assert "/api/mapping/geotiff/{asset_id}" in paths
    assert "/api/v1/mapping/geotiff/{asset_id}" in paths
    assert "/api/mapping/geotiff/{asset_id}/preview" in paths
    assert "/api/v1/mapping/geotiff/{asset_id}/preview" in paths
    assert paths["/api/mapping/geotiff/{asset_id}"]["delete"]["security"] == [
        {"APIKeyHeader": []}
    ]
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
    assert paths["/api/config/calibration"]["patch"]["security"] == [
        {"APIKeyHeader": []}
    ]


def test_openapi_operation_ids_are_clean_and_v1_aliases_preserve_methods(server_api):
    paths = server_api.get_app().openapi()["paths"]
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    operation_ids = [
        operation["operationId"]
        for methods in paths.values()
        for method, operation in methods.items()
        if method in http_methods
    ]

    assert len(operation_ids) == len(set(operation_ids))
    assert paths["/info"]["get"]["operationId"] == "getInfo"
    assert paths["/v1/info"]["get"]["operationId"] == "v1GetInfo"
    assert paths["/readiness"]["get"]["operationId"] == "getReadiness"
    assert paths["/v1/readiness"]["get"]["operationId"] == "v1GetReadiness"
    assert (
        paths["/api/payload/camera/sessions/{session}/photos/{filename}"]["get"][
            "operationId"
        ]
        == "getPayloadCameraSessionsBySessionPhotosByFilename"
    )
    assert (
        paths["/api/v1/control/authority"]["post"]["operationId"]
        == "v1PostControlAuthority"
    )
    assert (
        paths["/api/v1/control/authority"]["delete"]["operationId"]
        == "v1DeleteControlAuthority"
    )

    for path, methods in paths.items():
        if not path.startswith("/api/") or path.startswith("/api/v1/"):
            continue

        v1_path = path.replace("/api/", "/api/v1/", 1)
        assert v1_path in paths
        for method in methods:
            if method in http_methods:
                assert method in paths[v1_path]


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


def test_command_event_stream_maps_audit_outcomes_and_domain_events(server_api):
    events = []
    server_api._subscribe_command_events("test-client", events.append)

    try:
        server_api._audit_command(
            "vehicle.arm",
            "success",
            parameters={"armed": True},
        )
        server_api._audit_http_error(
            "vehicle.takeoff",
            {"altitude": 10},
            HTTPException(status_code=409, detail="blocked"),
        )
        server_api._audit_http_error(
            "vehicle.goto",
            {"location": "bad"},
            HTTPException(status_code=500, detail="failed"),
        )
        server_api._audit_command("control.authority_acquire", "success")
        server_api._audit_command("control.authority_release", "success")
        server_api._audit_command("emergency.land", "success")
        server_api._audit_command("mission.pixhawk_upload", "success")
        server_api._audit_command("mission.pixhawk_verify", "success")
        server_api._audit_command("payload.application_record_create", "success")
    finally:
        server_api._unsubscribe_command_events("test-client")

    event_types = [event["type"] for event in events]

    assert "command.accepted" in event_types
    assert "command.blocked" in event_types
    assert "command.failed" in event_types
    assert "authority.acquired" in event_types
    assert "authority.released" in event_types
    assert "emergency.triggered" in event_types
    assert "mission.uploaded" in event_types
    assert "mission.verified" in event_types
    assert "spray_record.created" in event_types
    assert events[0]["action"] == "vehicle.arm"
    assert events[1]["outcome"] == "blocked"
    assert events[2]["outcome"] == "failed"


def test_command_event_websocket_receives_authority_events(server_api):
    async def exercise_websocket():
        websocket = FakeEventWebSocket(expected_messages=2)
        endpoint = get_websocket_endpoint(server_api.get_app(), "/ws/events")
        task = asyncio.create_task(endpoint(websocket))

        for _ in range(100):
            if websocket.accepted and server_api.command_event_subscribers:
                break
            await asyncio.sleep(0.01)
        else:
            task.cancel()
            raise AssertionError("Command event WebSocket did not subscribe.")

        server_api._audit_command(
            "control.authority_acquire",
            "success",
            parameters={
                "client_id": "ground-station",
                "operator": "pilot",
                "lease_seconds": None,
            },
        )
        await asyncio.wait_for(task, timeout=1)
        return websocket.sent

    command_event, authority_event = asyncio.run(exercise_websocket())

    assert command_event["type"] == "command.accepted"
    assert command_event["action"] == "control.authority_acquire"
    assert authority_event["type"] == "authority.acquired"
    assert authority_event["parameters"] == {
        "client_id": "ground-station",
        "operator": "pilot",
        "lease_seconds": None,
    }


def test_operational_routes_emit_specific_command_events(server_api):
    events = []
    server_api._subscribe_command_events("test-client", events.append)

    async def exercise_routes():
        acquire_authority = get_route_endpoint(
            server_api.get_app(),
            "/api/control/authority",
            "POST",
        )
        upload_mission = get_route_endpoint(
            server_api.get_app(),
            "/api/mission/pixhawk/upload",
            "POST",
        )
        verify_mission = get_route_endpoint(
            server_api.get_app(),
            "/api/mission/pixhawk/verify",
            "GET",
        )
        create_spray_record = get_route_endpoint(
            server_api.get_app(),
            "/api/payload/spray/sessions/{session}/application-record",
            "POST",
        )

        authority_response = await acquire_authority(
            ControlAuthorityRequest(client_id="ground-station")
        )
        token = authority_response.data["authority"]["token"]
        upload_response = await upload_mission(x_control_token=token)
        verify_response = await verify_mission()
        spray_record_response = await create_spray_record(
            "session-a",
            SprayApplicationRecordRequest(product_name="water"),
            x_control_token=token,
        )
        return authority_response, upload_response, verify_response, spray_record_response

    try:
        (
            authority_response,
            upload_response,
            verify_response,
            spray_record_response,
        ) = asyncio.run(exercise_routes())
    finally:
        server_api._unsubscribe_command_events("test-client")

    assert authority_response.status == "success"
    assert upload_response.status == "success"
    assert verify_response.status == "success"
    assert spray_record_response.status == "success"

    event_types = [event["type"] for event in events]
    assert "mission.uploaded" in event_types
    assert "mission.verified" in event_types
    assert "spray_record.created" in event_types


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
