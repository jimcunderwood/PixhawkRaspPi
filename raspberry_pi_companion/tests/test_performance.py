import asyncio
import time

import pytest

pytest.importorskip("fastapi")

from src.api.server import ServerAPI
from src.telemetry.database import TelemetryDatabase, TelemetryDatabaseConfig


pytestmark = pytest.mark.performance


class FakeWebSocket:
    def __init__(self):
        self.sent = 0

    async def send_text(self, data):
        self.sent += 1

    async def send_json(self, data):
        self.sent += 1


@pytest.mark.asyncio
async def test_websocket_send_throughput_stays_above_baseline():
    websocket = FakeWebSocket()
    server = ServerAPI.__new__(ServerAPI)
    payload = "{\"type\":\"telemetry\",\"sample\":1}"

    message_count = 5000
    start = time.perf_counter()
    for _ in range(message_count):
        await server._send_ws(websocket, payload)
    elapsed = time.perf_counter() - start
    rate = message_count / elapsed

    assert websocket.sent == message_count
    assert rate > 5000


def test_telemetry_database_write_rate_stays_above_baseline(tmp_path):
    database = TelemetryDatabase(
        TelemetryDatabaseConfig(
            path=tmp_path / "telemetry.sqlite3",
            max_bytes=1024 * 1024,
            backup_count=3,
            vacuum_interval_seconds=0,
        )
    )

    try:
        sample_count = 500
        start = time.perf_counter()
        for index in range(sample_count):
            database.record(
                {
                    "timestamp": 1_700_000_000.0 + index,
                    "ground_speed": 3.5,
                    "location": {"latitude": 40.1, "longitude": -74.2, "altitude": 50.0},
                    "battery": {"level_percent": 88},
                }
            )
        elapsed = time.perf_counter() - start
        rate = sample_count / elapsed

        assert rate > 100
    finally:
        database.close()
