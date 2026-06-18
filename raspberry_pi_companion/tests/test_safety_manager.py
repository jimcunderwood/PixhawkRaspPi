from src.config.settings import SafetyConfig
from src.safety.manager import GeofenceZone, SafetyManager


class FakeConnection:
    def __init__(self):
        self.commands = []

    def set_mode(self, mode):
        self.commands.append(("mode", mode))
        return True

    def land(self):
        self.commands.append(("land", None))
        return True


def test_safety_manager_detects_no_fly_zone_and_generates_checklist(tmp_path):
    config = SafetyConfig(safety_state_file=str(tmp_path / "safety.json"))
    connection = FakeConnection()
    manager = SafetyManager(config, connection_manager=connection)
    manager.upsert_zone(
        GeofenceZone(
            name="Restricted",
            zone_type="no_fly",
            polygon=[
                {"latitude": 40.0, "longitude": -74.0},
                {"latitude": 40.0, "longitude": -73.9},
                {"latitude": 40.1, "longitude": -73.9},
                {"latitude": 40.1, "longitude": -74.0},
            ],
        )
    )

    evaluation = manager.evaluate_snapshot(
        {
            "timestamp": 1_700_000_000.0,
            "location": {"latitude": 40.05, "longitude": -73.95, "altitude": 150.0},
            "battery": {"level_percent": 8},
            "gps": {"fix_type": 2},
            "ground_speed": 12.0,
        }
    )

    assert evaluation["blockers"]
    assert evaluation["recommended_action"] == "land"
    assert evaluation["landing_zone"] is None
    assert manager.get_preflight_checklist()["ready"] is False


def test_safety_manager_updates_remote_id_and_waivers(tmp_path):
    config = SafetyConfig(safety_state_file=str(tmp_path / "safety.json"))
    manager = SafetyManager(config)

    remote_id = manager.update_remote_id(
        {
            "enabled": True,
            "operator_id": "pilot-1",
            "serial_number": "RID-123",
            "broadcast_method": "mavlink",
        }
    )
    waivers = manager.update_waivers(
        {
            "night_flight_authorized": True,
            "bvlos_authorized": False,
            "notes": "Night ops allowed under waiver.",
        }
    )

    assert remote_id["enabled"] is True
    assert remote_id["operator_id"] == "pilot-1"
    assert waivers["night_flight_authorized"] is True
