import time

from src.payloads.controller import SprayApplicationRecordStore
from src.telemetry.database import TelemetryDatabase, TelemetryDatabaseConfig


def test_telemetry_database_round_trip_and_statistics(tmp_path):
    db_path = tmp_path / "telemetry" / "telemetry.sqlite3"
    database = TelemetryDatabase(
        TelemetryDatabaseConfig(
            path=db_path,
            max_bytes=1024 * 1024,
            backup_count=3,
            vacuum_interval_seconds=0,
        )
    )

    try:
        now = time.time()
        database.record(
            {
                "timestamp": now - 10,
                "datetime": "2023-11-14T22:13:20",
                "armed": True,
                "mode": "GUIDED",
                "ground_speed": 3.5,
                "air_speed": 4.0,
                "heading": 90.0,
                "is_armable": True,
                "system_status": "ACTIVE",
                "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 52.0},
                "attitude": {"roll": 0.1, "pitch": 0.2, "yaw": 0.3},
                "velocity": {"north": 1.0, "east": 2.0, "down": -0.5},
                "battery": {"voltage": 12.2, "current": 4.8, "level_percent": 87},
                "gps": {"fix_type": 6, "fix_name": "3D Fix", "satellite_count": 12},
                "payload": {
                    "spray_pump": {"status": "on"},
                    "flow_sensor": {"flow_rate_liters_per_minute": 2.5, "total_volume_liters": 7.5},
                },
            }
        )
        database.record(
            {
                "timestamp": now,
                "datetime": "2023-11-14T22:13:30",
                "armed": False,
                "mode": "LAND",
                "ground_speed": 1.0,
                "air_speed": 1.5,
                "heading": 120.0,
                "is_armable": True,
                "system_status": "ACTIVE",
                "location": {"latitude": 40.2, "longitude": -74.1, "altitude": 48.0},
                "battery": {"voltage": 12.0, "current": 4.2, "level_percent": 80},
            }
        )

        history = database.query()
        stats = database.statistics(seconds=60)

        assert len(history) == 2
        assert history[0]["location"]["latitude"] == 40.1
        assert stats["count"] == 2
        assert stats["battery"]["current"] == 80
        assert stats["altitude"]["max"] == 52.0
    finally:
        database.close()


def test_spray_application_export_geojson_and_report(tmp_path):
    store = SprayApplicationRecordStore(str(tmp_path / "records"))
    session_manifest = {
        "session": "field-12",
        "status": "stopped",
        "started_at": 1_700_000_000.0,
        "stopped_at": 1_700_000_030.0,
        "duration_seconds": 30.0,
        "total_volume_liters": 9.0,
        "start_telemetry": {"location": {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0}},
        "stop_telemetry": {"location": {"latitude": 40.2, "longitude": -74.1, "altitude": 51.0}},
    }
    payload_status = {"spray_pump": {"status": "off"}}
    metadata = {
        "field_name": "North Field",
        "product_name": "Herbicide A",
        "applicator_name": "Operator One",
        "field_boundary": {
            "name": "North Field",
            "vertices": [
                {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
                {"latitude": 40.1, "longitude": -74.1, "altitude": 50.0},
                {"latitude": 40.2, "longitude": -74.1, "altitude": 50.0},
                {"latitude": 40.2, "longitude": -74.2, "altitude": 50.0},
            ],
        },
    }

    record = store.create_record(session_manifest, payload_status, metadata=metadata)
    geojson = store.export_geojson("field-12")
    report = store.generate_compliance_report(
        "field-12",
        operator_signature="Operator One",
        signed_at=1_700_000_040.0,
        report_format="epa",
    )

    assert record["metadata"]["field_name"] == "North Field"
    assert geojson["type"] == "FeatureCollection"
    assert any(feature["geometry"]["type"] == "Polygon" for feature in geojson["features"])
    assert any(feature["geometry"]["type"] == "LineString" for feature in geojson["features"])
    assert report["operator_signature"] == "Operator One"
    assert report["application"]["application_rate_liters_per_hectare"] is not None
    assert report["geojson"]["type"] == "FeatureCollection"
