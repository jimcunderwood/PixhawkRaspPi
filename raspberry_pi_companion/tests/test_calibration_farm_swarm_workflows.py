import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("pydantic")

from src.calibration.workflow import CalibrationWorkflowConfig, CalibrationWorkflowManager
from src.farm.manager import FarmIntegrationConfig, FarmIntegrationManager
from src.swarm.database import SwarmDatabase, SwarmDatabaseConfig
from src.swarm.manager import SwarmManager


class DummyTelemetryHistory:
    def __call__(self, seconds):
        base = time.time()
        return [
            {
                "timestamp": base - 12,
                "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
                "ground_speed": 3.5,
            },
            {
                "timestamp": base - 6,
                "location": {"latitude": 40.1008, "longitude": -74.1992, "altitude": 50.2},
                "ground_speed": 3.8,
            },
            {
                "timestamp": base,
                "location": {"latitude": 40.1016, "longitude": -74.1984, "altitude": 50.3},
                "ground_speed": 4.0,
            },
        ]


class DummyPayloadController:
    def __init__(self):
        self._record = {
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

    def get_application_record(self, session):
        return self._record if session == self._record["session"] else None

    def list_application_records(self):
        return [self._record]


class DummyTelemetryManager:
    def get_history(self, seconds=None):
        return DummyTelemetryHistory()(seconds)

    def get_current(self):
        return {
            "timestamp": time.time(),
            "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
            "ground_speed": 3.8,
            "heading": 92.0,
            "gps": {"fix_type": 6, "satellite_count": 15},
        }


def test_calibration_manager_creates_base_station_and_ppk_job(tmp_path):
    manager = CalibrationWorkflowManager(
        CalibrationWorkflowConfig(database_file=tmp_path / "calibration.sqlite3"),
        telemetry_history_getter=DummyTelemetryHistory(),
    )

    station = manager.save_base_station(
        {
            "station_id": "base-01",
            "name": "Field base",
            "latitude": 40.1,
            "longitude": -74.2,
            "antenna_height_m": 1.5,
            "correction_port": "/dev/ttyUSB0",
            "correction_baudrate": 115200,
        },
        activate=True,
    )
    job = manager.process_ppk_job(
        {
            "session": "spray-001",
            "base_station_id": "base-01",
            "telemetry_window_seconds": 600,
            "source_label": "telemetry-history",
        }
    )

    try:
        assert station["active"] is True
        assert manager.get_status()["active_base_station"]["station_id"] == "base-01"
        assert job["status"] == "complete"
        assert job["summary"]["sample_count"] == 3
        assert job["request"]["base_station_id"] == "base-01"
        assert job["quality"]["correction_applied"] is True
    finally:
        manager.close()


def test_farm_manager_exports_isoxml_and_report(tmp_path):
    farm = FarmIntegrationManager(
        FarmIntegrationConfig(
            enabled=True,
            database_file=tmp_path / "farm.sqlite3",
            isoxml_output_directory=tmp_path / "isoxml",
            report_output_directory=tmp_path / "reports",
            agleader_endpoint="https://agleader.example/api",
        ),
        payload_controller=DummyPayloadController(),
        telemetry_manager=DummyTelemetryManager(),
    )

    isoxml = farm.export_isoxml(session="spray-001")
    sync = farm.sync_agleader(session="spray-001")
    report = farm.generate_automated_report(session="spray-001")

    assert "<ISOXML" in isoxml["xml"]
    assert isoxml["archive_path"].endswith(".zip")
    assert sync["payload"]["telemetry_samples"] == 3
    assert report["summary"]["telemetry_samples"] == 3
    assert report["report_path"].endswith(".json")
    status = farm.get_status()
    assert status["recent_isoxml_exports"]
    assert status["recent_reports"]


def test_swarm_coordination_status_reports_leader_following(tmp_path):
    database = SwarmDatabase(
        SwarmDatabaseConfig(
            path=tmp_path / "swarm.sqlite3",
            max_bytes=1024 * 1024,
            backup_count=2,
            vacuum_interval_seconds=0,
        )
    )
    manager = SwarmManager(database, local_state_getter=lambda: {
        "timestamp": time.time(),
        "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
        "armed": True,
        "mode": "GUIDED",
        "battery": {"level_percent": 88},
        "ground_speed": 3.2,
        "heading": 91.0,
        "gps": {"fix_type": 6, "satellite_count": 15, "horizontal_accuracy": 0.35},
    })

    manager.update_config(
        {
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
                    "callsign": "Wing",
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
    )
    manager.broadcast_local_snapshot()
    manager.ingest_telemetry_message(
        {
            "swarm_id": "field-alpha-swarm",
            "source_drone_id": "drone-02",
            "sample_id": "peer-002",
            "sequence": 2,
            "timestamp": time.time(),
            "received_at": time.time(),
            "role": "follower",
            "location": {
                "latitude": 40.1004,
                "longitude": -74.1996,
                "altitude": 50.4,
                "source": "gps",
            },
            "vehicle": {"armed": False, "mode": "AUTO", "battery_percent": 72},
        }
    )

    try:
        coordination = manager.get_coordination_status()
        assert coordination["formation_mode"] == "leader_follower"
        assert coordination["leader_drone_id"] == "drone-01"
        assert coordination["assignments"]
        assert coordination["collision_avoidance"]["recommended_action"] in {"continue", "separate", "hold"}
    finally:
        database.close()
