import time

from src.telemetry.collector import TelemetryCollector
from src.telemetry.database import TelemetryDatabase, TelemetryDatabaseConfig


def test_telemetry_database_query_statistics_and_clear(tmp_path):
    database = TelemetryDatabase(
        TelemetryDatabaseConfig(
            path=tmp_path / "telemetry.sqlite3",
            max_bytes=1024 * 1024,
            backup_count=3,
            vacuum_interval_seconds=0,
        )
    )

    try:
        now = time.time()
        database.record(
            {
                "timestamp": now - 30,
                "datetime": "2024-01-01T00:00:00",
                "ground_speed": 3.2,
                "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 51.0},
                "battery": {"level_percent": 82},
            }
        )
        database.record(
            {
                "timestamp": now - 5,
                "datetime": "2024-01-01T00:00:25",
                "ground_speed": 4.0,
                "location": {"latitude": 40.2, "longitude": -74.1, "altitude": 54.0},
                "battery": {"level_percent": 78},
            }
        )

        history = database.query(seconds=60)
        stats = database.statistics(seconds=60)
        recent_only = database.query(seconds=10)

        assert len(history) == 2
        assert history[0]["location"]["latitude"] == 40.1
        assert len(recent_only) == 1
        assert stats["count"] == 2
        assert stats["battery"]["current"] == 78
        assert stats["altitude"]["max"] == 54.0

        database.clear()
        assert database.query() == []
    finally:
        database.close()


def test_telemetry_collector_persists_history_and_callbacks(tmp_path):
    database = TelemetryDatabase(
        TelemetryDatabaseConfig(
            path=tmp_path / "collector.sqlite3",
            max_bytes=1024 * 1024,
            backup_count=2,
            vacuum_interval_seconds=0,
        )
    )
    collector = TelemetryCollector(database=database)
    seen = []
    collector.register_callback(lambda point: seen.append(point.to_dict()))

    collector.add_point(
        {
            "ground_speed": 3.8,
            "battery": {"level_percent": 90},
            "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
        }
    )
    collector.add_point(
        {
            "ground_speed": 4.2,
            "battery": {"level_percent": 87},
            "location": {"latitude": 40.1005, "longitude": -74.1995, "altitude": 50.5},
        }
    )

    history = collector.get_history()
    stats = collector.get_statistics(seconds=60)

    assert len(seen) == 2
    assert collector.get_current()["ground_speed"] == 4.2
    assert len(history) == 2
    assert stats["count"] == 2
    assert stats["battery"]["current"] == 87

    collector.clear_history()
    assert collector.get_history() == []
    collector.stop()
