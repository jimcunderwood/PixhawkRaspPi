import sys
import time
import importlib.util
import subprocess
from pathlib import Path
import site

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_MAVLINK_REQUIREMENTS = (
    "dronekit>=2.9.2",
    "pymavlink>=2.4.49",
    "future>=0.18.2",
    "pyserial>=3.5",
)

_VENV_SITE_PACKAGES = sorted(
    REPO_ROOT.joinpath("venv", "lib").glob("python*/site-packages")
)
for site_packages in _VENV_SITE_PACKAGES:
    if site_packages.is_dir() and str(site_packages) not in sys.path:
        site.addsitedir(str(site_packages))

def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _install_missing_test_dependencies() -> None:
    if _module_available("dronekit") and _module_available("pymavlink"):
        return

    python_candidates = [REPO_ROOT / "venv" / "bin" / "python", Path(sys.executable)]
    installer = next((candidate for candidate in python_candidates if candidate.exists()), None)
    if installer is None:
        raise RuntimeError("Unable to locate a Python interpreter to install test dependencies.")

    install_args = [
        str(installer),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        *CORE_MAVLINK_REQUIREMENTS,
    ]

    try:
        subprocess.run(install_args, cwd=str(REPO_ROOT), check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Failed to install missing test dependencies. "
            "Make sure network access is available or create the repo venv first."
        ) from exc

    for site_packages in _VENV_SITE_PACKAGES:
        if site_packages.is_dir() and str(site_packages) not in sys.path:
            site.addsitedir(str(site_packages))


_install_missing_test_dependencies()

from src.missions.planner import FieldBoundary, GeoPoint, MissionPlanner
from src.telemetry.collector import TelemetryManager
from src.telemetry.database import TelemetryDatabase, TelemetryDatabaseConfig


class RouteConnectionManager:
    def __init__(self):
        self.connected = True
        self._mode = "GUIDED"
        self._armed = False
        self._mission_items = []
        self._last_location = {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0}

    def get_connection_status(self):
        return {
            "state": "connected",
            "connected": True,
            "monitoring": True,
            "reconnecting": False,
            "retry_backoff_seconds": 0.0,
            "max_retry_backoff_seconds": 30.0,
            "next_retry_in_seconds": 0.0,
            "last_reconnect_attempt_at": None,
            "last_changed_at": 1_700_000_000.0,
            "last_error": None,
        }

    def get_vehicle_state(self):
        return {
            "armed": self._armed,
            "mode": self._mode,
            "location": dict(self._last_location),
            "battery": {"voltage": 12.2, "current": 3.4, "level_percent": 88},
            "ground_speed": 3.1,
            "air_speed": 3.6,
            "velocity": {"north": 0.2, "east": 0.1, "down": -0.1},
        }

    def get_prearm_status(self):
        return {
            "connected": True,
            "is_armable": True,
            "ekf_ok": True,
            "gps": {"fix_type": 6, "satellite_count": 16},
        }

    def get_navigation_status(self):
        return {
            "obstacle_avoidance": {
                "parameters": {"AVOID_ENABLE": 7},
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
                "parameters": {"TERRAIN_ENABLE": 1},
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
                {"sensor_id": 0, "orientation": 25, "distance_meters": 6.7, "source": "mavlink.distance_sensor"},
                {"sensor_id": 1, "orientation": 0, "distance_meters": 12.3, "source": "mavlink.distance_sensor"},
            ],
        }

    def arm(self):
        self._armed = True
        return {"success": True}

    def disarm(self):
        self._armed = False
        return {"success": True}

    def takeoff(self, altitude):
        return {"success": True, "altitude": altitude}

    def land(self):
        self._mode = "LAND"
        return {"success": True}

    def goto(self, location):
        self._last_location = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "altitude": location.altitude,
        }
        return {"success": True, "location": self._last_location}

    def set_mode(self, mode):
        self._mode = mode
        return {"success": True, "mode": mode}

    def upload_mission(self, mission_items):
        self._mission_items = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in mission_items]
        return {
            "success": True,
            "uploaded_count": len(self._mission_items),
            "skipped_count": 0,
            "skipped_items": [],
            "pixhawk_count": len(self._mission_items),
            "checksum": f"checksum-{len(self._mission_items)}",
        }

    def download_mission(self):
        return {
            "success": True,
            "count": len(self._mission_items),
            "items": list(self._mission_items),
            "checksum": f"checksum-{len(self._mission_items)}",
        }

    def verify_mission(self, expected_items):
        expected = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in expected_items]
        return {
            "success": True,
            "matches": expected == self._mission_items,
            "expected_count": len(expected),
            "pixhawk_count": len(self._mission_items),
            "expected_checksum": f"checksum-{len(expected)}",
            "pixhawk_checksum": f"checksum-{len(self._mission_items)}",
            "skipped_count": 0,
            "skipped_items": [],
        }

    def clear_pixhawk_mission(self):
        self._mission_items = []
        return {"success": True, "pixhawk_count": 0}


class RoutePayloadController:
    def __init__(self, photo_directory: Path):
        self.camera = None
        self.camera_trigger = None
        self.flow_sensor = None
        self.pressure_sensor = None
        self.tank_level_sensor = None
        self.prescription_controller = object()
        self._photo_directory = photo_directory
        self._calibration = {
            "flow_sensor": {"pulses_per_liter": 450.0},
            "pressure_sensor": {"min_voltage": 0.5, "max_voltage": 4.5, "min_psi": 0.0, "max_psi": 150.0},
            "tank_level_sensor": {"min_voltage": 0.5, "max_voltage": 4.5, "capacity_liters": 10.0, "minimum_level_percent": 10.0},
            "terrain_sensor": {"min_agl_meters": 2.0, "max_agl_meters": 120.0},
        }
        self._prescription_maps = {}
        self._application_records = [
            {
                "session": "spray-001",
                "metadata": {
                    "field_name": "North Field",
                    "product_name": "Herbicide A",
                    "field_boundary": {
                        "name": "North Field",
                        "vertices": [
                            {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
                            {"latitude": 40.1, "longitude": -74.1, "altitude": 50.0},
                            {"latitude": 40.2, "longitude": -74.1, "altitude": 50.0},
                            {"latitude": 40.2, "longitude": -74.2, "altitude": 50.0},
                        ],
                    },
                },
                "total_volume_liters": 9.0,
                "application_rate_liters_per_hectare": 18.0,
            }
        ]

    def get_payload_status(self):
        return {"spray_pump": {"status": "off"}, "camera": {"available": False}}

    def get_calibration_config(self):
        return {group: values.copy() for group, values in self._calibration.items()}

    def update_calibration_config(self, calibration):
        for group, values in calibration.items():
            self._calibration.setdefault(group, {}).update(values)
        return {"before": {}, "after": self.get_calibration_config(), "applied": calibration, "persistent": True}

    def list_application_records(self):
        return list(self._application_records)

    def get_application_record(self, session):
        for record in self._application_records:
            if record["session"] == session:
                return record
        return None

    def import_prescription_map(self, payload_text, name, source_format=None, activate=False):
        map_id = f"map-{len(self._prescription_maps) + 1}"
        record = {
            "map_id": map_id,
            "name": name,
            "payload_text": payload_text,
            "source_format": source_format,
            "active": bool(activate),
        }
        self._prescription_maps[map_id] = record
        return record

    def activate_prescription_map(self, map_id):
        if map_id not in self._prescription_maps:
            return None
        for record in self._prescription_maps.values():
            record["active"] = False
        self._prescription_maps[map_id]["active"] = True
        return self._prescription_maps[map_id]

    def list_prescription_maps(self):
        return list(self._prescription_maps.values())

    def get_prescription_status(self):
        active_map = next((record for record in self._prescription_maps.values() if record.get("active")), None)
        return {
            "configured": True,
            "enabled": True,
            "active_map": active_map,
            "maps": self.list_prescription_maps(),
            "current_zone": {"label": "North Field"},
            "target_rate_liters_per_hectare": 18.0,
            "current_flow_rate_liters_per_minute": 2.2,
            "ground_speed_mps": 3.4,
            "effective_ground_speed_mps": 3.4,
            "swath_width_m": 12.0,
            "speed_sync_enabled": True,
        }

    def arm_spray(self, session=None, telemetry_snapshot=None):
        return True

    def disarm_spray(self, telemetry_snapshot=None):
        return True


@pytest.fixture()
def async_server_api(monkeypatch, tmp_path):
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("pydantic")

    from src.api import server as server_module
    from src.api.server import ServerAPI

    monkeypatch.setattr(server_module.config.api, "auth_enabled", True)
    monkeypatch.setattr(server_module.config.api, "api_key", "test-key")
    monkeypatch.setattr(server_module.config.api, "api_key_role", "admin")
    monkeypatch.setattr(server_module.config.api, "api_key_roles", {"test-key": "admin"})
    monkeypatch.setattr(server_module.config.api, "audit_log_file", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(server_module.config.api, "config_database_file", str(tmp_path / "config" / "profiles.sqlite3"))
    monkeypatch.setattr(server_module.config.api, "command_authority_enabled", True)
    monkeypatch.setattr(server_module.config.api, "safety_gates_enabled", True)
    monkeypatch.setattr(server_module.config.storage, "geotiff_database_file", str(tmp_path / "geotiff" / "geotiff.sqlite3"))
    monkeypatch.setattr(server_module.config.storage, "geotiff_asset_directory", str(tmp_path / "geotiff" / "assets"))
    monkeypatch.setattr(server_module.config.storage, "swarm_database_file", str(tmp_path / "swarm" / "swarm.sqlite3"))
    monkeypatch.setattr(server_module.config.storage, "telemetry_database_file", str(tmp_path / "telemetry" / "telemetry.sqlite3"))

    telemetry_db = TelemetryDatabase(
        TelemetryDatabaseConfig(
            path=Path(tmp_path / "telemetry" / "telemetry.sqlite3"),
            max_bytes=1024 * 1024,
            backup_count=3,
            vacuum_interval_seconds=0,
        )
    )
    telemetry_manager = TelemetryManager(database=telemetry_db)
    now = time.time()
    for offset, latitude in [(120, 40.1000), (60, 40.1005), (0, 40.1010)]:
        telemetry_manager.collector.add_point(
            {
                "timestamp": now - offset,
                "ground_speed": 3.0 + (offset / 120.0),
                "heading": 90.0,
                "location": {"latitude": latitude, "longitude": -74.2 + ((120 - offset) / 2400.0), "altitude": 50.0 + (offset / 120.0)},
                "battery": {"level_percent": 80 - offset / 10.0},
                "gps": {"fix_type": 6, "satellite_count": 14},
            }
        )

    mission_planner = MissionPlanner(max_waypoints=100)
    mission_planner.add_waypoint(40.1, -74.2, 50.0)
    mission_planner.add_waypoint(40.1008, -74.1992, 50.3)
    mission_planner.add_field_boundary(
        FieldBoundary(
            "North Field",
            [
                GeoPoint(40.1, -74.2),
                GeoPoint(40.1, -74.1),
                GeoPoint(40.2, -74.1),
                GeoPoint(40.2, -74.2),
            ],
            altitude=50.0,
        )
    )

    payload_controller = RoutePayloadController(Path(tmp_path / "photos"))
    server_api = ServerAPI(
        RouteConnectionManager(),
        mission_planner,
        payload_controller,
        telemetry_manager,
    )
    yield server_api
    telemetry_manager.stop()
