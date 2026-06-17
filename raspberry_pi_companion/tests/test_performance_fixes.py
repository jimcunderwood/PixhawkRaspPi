import asyncio
import json
import threading

from src.api import server as server_module
from src.audit.logger import AuditLogger
from src.payloads import controller as controller_module
from src.telemetry.collector import TelemetryCollector, TelemetryPoint


class FakeWebSocket:
    def __init__(self):
        self.text_messages = []
        self.json_messages = []

    async def send_text(self, data):
        self.text_messages.append(data)

    async def send_json(self, data):
        self.json_messages.append(data)


class FakeCamera:
    def __init__(self):
        self.read_calls = 0

    def isOpened(self):
        return True

    def read(self):
        self.read_calls += 1
        return True, {"frame": self.read_calls}


def test_audit_logger_rotates_and_recent_reads_backups(tmp_path):
    log_file = tmp_path / "audit" / "events.jsonl"
    logger = AuditLogger(str(log_file), max_bytes=220, backup_count=5)

    for seq in range(1, 6):
        logger.record(
            "vehicle.arm",
            "success",
            details={"seq": seq, "payload": "x" * 90},
        )

    assert log_file.exists()
    assert (tmp_path / "audit" / "events.jsonl.1").exists()

    recent = logger.recent(limit=10)
    assert [event["details"]["seq"] for event in recent] == [5, 4, 3, 2, 1]


def test_telemetry_point_and_history_round_trip():
    point = TelemetryPoint(
        123.456,
        {
            "ground_speed": 4.2,
            "battery": {"level_percent": 87},
        },
    )

    assert not hasattr(point, "__dict__")
    payload = point.to_dict()
    assert payload["timestamp"] == 123.456
    assert payload["ground_speed"] == 4.2
    assert json.loads(point.to_json()) == payload

    collector = TelemetryCollector(max_history=2)
    collector.add_point({"ground_speed": 4.2, "battery": {"level_percent": 87}})

    history = collector.get_history()
    assert history[0]["ground_speed"] == 4.2
    assert collector.get_current()["ground_speed"] == 4.2


def test_camera_capture_loop_sleeps_when_idle(monkeypatch):
    controller = controller_module.CameraController.__new__(controller_module.CameraController)
    controller._capture_running = True
    controller._camera = FakeCamera()
    controller.is_recording = False
    controller._video_writer = None
    controller._latest_frame = None
    controller._last_frame_time = None
    controller._lock = threading.Lock()
    controller._idle_capture_interval = 0.1

    sleeps = []

    def fake_sleep(duration):
        sleeps.append(duration)
        controller._capture_running = False

    monkeypatch.setattr(controller_module.time, "sleep", fake_sleep)

    controller._capture_loop()

    assert sleeps == [0.1]
    assert controller._camera.read_calls == 1
    assert controller._latest_frame == {"frame": 1}


def test_send_ws_uses_text_for_pre_serialized_payload():
    websocket = FakeWebSocket()
    server = server_module.ServerAPI.__new__(server_module.ServerAPI)

    asyncio.run(server._send_ws(websocket, "{\"ok\":true}"))

    assert websocket.text_messages == ["{\"ok\":true}"]
    assert websocket.json_messages == []
