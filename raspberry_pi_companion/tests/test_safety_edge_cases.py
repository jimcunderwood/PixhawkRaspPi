import time

from src.config.settings import SafetyConfig
from src.safety.manager import GeofenceZone, SafetyManager


class RecordingConnection:
    def __init__(self):
        self.commands = []

    def set_mode(self, mode):
        self.commands.append(("mode", mode))
        return True

    def land(self):
        self.commands.append(("land", None))
        return True


def test_zone_transition_updates_blockers_and_landing_zone(tmp_path):
    manager = SafetyManager(SafetyConfig(safety_state_file=str(tmp_path / "safety.json")))
    manager.upsert_zone(
        GeofenceZone(
            name="No Fly North",
            zone_type="no_fly",
            polygon=[
                {"latitude": 40.10, "longitude": -74.20},
                {"latitude": 40.10, "longitude": -74.10},
                {"latitude": 40.20, "longitude": -74.10},
                {"latitude": 40.20, "longitude": -74.20},
            ],
        )
    )
    manager.upsert_zone(
        GeofenceZone(
            name="Landing South",
            zone_type="landing_zone",
            polygon=[
                {"latitude": 40.00, "longitude": -74.30},
                {"latitude": 40.00, "longitude": -74.25},
                {"latitude": 40.05, "longitude": -74.25},
                {"latitude": 40.05, "longitude": -74.30},
            ],
        )
    )
    now = time.time()

    clear = manager.evaluate_snapshot(
        {
            "timestamp": now,
            "location": {"latitude": 40.08, "longitude": -74.22, "altitude": 55.0},
            "battery": {"level_percent": 80},
            "gps": {"fix_type": 6},
        }
    )
    blocked = manager.evaluate_snapshot(
        {
            "timestamp": now + 1.0,
            "location": {"latitude": 40.15, "longitude": -74.15, "altitude": 55.0},
            "battery": {"level_percent": 80},
            "gps": {"fix_type": 6},
        }
    )

    assert clear["blockers"] == []
    assert clear["landing_zone"]["name"] == "Landing South"
    assert any("no-fly zone" in blocker for blocker in blocked["blockers"])
    assert blocked["recommended_action"] == "land"
    assert blocked["landing_zone"]["name"] == "Landing South"


def test_battery_state_machine_advances_warn_rtl_and_land(tmp_path, monkeypatch):
    connection = RecordingConnection()
    manager = SafetyManager(
        SafetyConfig(safety_state_file=str(tmp_path / "safety.json")),
        connection_manager=connection,
    )

    clock = {"value": 1_700_000_000.0}

    def fake_time():
        return clock["value"]

    monkeypatch.setattr("src.safety.manager.time.time", fake_time)

    for battery_level, advance in [(28, 1.0), (18, 4.0), (5, 4.0)]:
        manager.register_telemetry_point(
            {
                "timestamp": clock["value"],
                "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
                "battery": {"level_percent": battery_level},
                "gps": {"fix_type": 6},
            }
        )
        clock["value"] += advance

    assert connection.commands == [("mode", "RTL"), ("land", None)]
    assert manager.get_status()["last_action"] == "land"
