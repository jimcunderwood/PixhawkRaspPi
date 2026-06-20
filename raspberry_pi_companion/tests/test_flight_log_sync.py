import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.server import FlightLogReplayRequest
from src.logsync.manager import FlightLogSyncManager


class DummyConnectionManager:
    def register_callback(self, *_args, **_kwargs):
        return None


class DummyTelemetryManager:
    def get_current(self):
        return {"mode": "GUIDED"}

    def get_history(self):
        return [{"timestamp": 1_700_000_000.0, "ground_speed": 3.1}]


def make_archive(root: Path, session: str, timestamp: str, reason: str = "landing") -> Path:
    bundle_dir = root / session / timestamp
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "pixhawk").mkdir(parents=True, exist_ok=True)
    (bundle_dir / "companion").mkdir(parents=True, exist_ok=True)
    (bundle_dir / "companion" / "telemetry-history.json").write_text(json.dumps([{"timestamp": 1}]))
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "session": session,
                "reason": reason,
                "created_at": 1_700_000_000.0,
                "created_at_iso": "2023-11-14T22:13:20Z",
                "pixhawk_files": ["pixhawk/pixhawk_00001.bin"],
                "companion_files": ["companion/telemetry-history.json"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    archive_path = bundle_dir.with_suffix(".zip")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle_dir.parent))
    return archive_path


def make_manager(tmp_path: Path) -> FlightLogSyncManager:
    storage_config = SimpleNamespace(
        flight_log_directory=str(tmp_path / "flight-logs"),
        flight_log_sync_delay_seconds=0.0,
        flight_log_download_limit=5,
        flight_log_max_drive_fraction=0.5,
        flight_log_backup_count=3,
        flight_log_cloud_upload_enabled=False,
        flight_log_cloud_upload_url="",
        flight_log_cloud_upload_timeout_seconds=5,
    )
    return FlightLogSyncManager(DummyConnectionManager(), object(), DummyTelemetryManager(), storage_config)


def test_flight_log_sync_history_and_replay(tmp_path):
    manager = make_manager(tmp_path)
    archive_a = make_archive(manager.base_directory, "flight_guided", "20240618T160000Z", "landing")
    time.sleep(0.01)
    archive_b = make_archive(manager.base_directory, "flight_guided", "20240618T170000Z", "manual")

    history = manager.history(limit=5)
    assert [entry["archive_path"] for entry in history][:2] == [str(archive_b), str(archive_a)]
    assert history[0]["pixhawk_file_count"] == 1
    assert history[0]["companion_file_count"] == 1

    replayed = manager.replay(str(archive_a))
    assert replayed["archive_path"] == str(archive_a)
    assert replayed["session"] == "flight_guided"
    assert replayed["upload"] == {"enabled": False}


def test_flight_log_sync_replay_can_upload(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    archive = make_archive(manager.base_directory, "flight_guided", "20240618T180000Z")
    calls = {}

    def fake_upload(archive_path, manifest_path):
        calls["archive_path"] = archive_path
        calls["manifest_path"] = manifest_path
        return {"enabled": True, "status": "uploaded"}

    monkeypatch.setattr(manager, "_upload_archive", fake_upload)

    replayed = manager.replay(str(archive), upload=True)
    assert replayed["upload"]["status"] == "uploaded"
    assert calls["archive_path"] == archive
    assert calls["manifest_path"].name == "manifest.json"


def test_flight_log_sync_enforces_storage_budget_oldest_first(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    manager.base_directory.mkdir(parents=True, exist_ok=True)

    archive_old = make_archive(manager.base_directory, "mission_a", "20240618T150000Z")
    time.sleep(0.01)
    archive_mid = make_archive(manager.base_directory, "mission_b", "20240618T160000Z")
    time.sleep(0.01)
    archive_new = make_archive(manager.base_directory, "mission_c", "20240618T170000Z")

    monkeypatch.setattr("src.logsync.manager.shutil.disk_usage", lambda _path: SimpleNamespace(total=300, used=0, free=300))
    monkeypatch.setattr(manager, "_directory_size_bytes", lambda: 200)

    manager._enforce_storage_budget()

    assert not archive_old.exists()
    assert archive_mid.exists()
    assert archive_new.exists()


def test_flight_log_sync_uses_free_space_budget_and_cleans_bundle_dir(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    manager.base_directory.mkdir(parents=True, exist_ok=True)

    bundle_paths = {}

    def fake_download(target_directory):
        path = target_directory / "pixhawk.bin"
        path.write_bytes(b"abc")
        bundle_paths["bundle_dir"] = target_directory.parent
        return [path]

    def fake_collect(target_directory):
        path = target_directory / "telemetry.json"
        path.write_text("{}")
        return [path]

    def fake_upload(archive_path, manifest_path):
        bundle_paths["archive_path"] = archive_path
        bundle_paths["manifest_path"] = manifest_path
        return {"enabled": True, "status": "uploaded"}

    monkeypatch.setattr(manager, "_download_pixhawk_logs", fake_download)
    monkeypatch.setattr(manager, "_collect_companion_artifacts", fake_collect)
    monkeypatch.setattr(manager, "_upload_archive", fake_upload)

    disk_usage_calls = {}

    def fake_disk_usage(path):
        disk_usage_calls["path"] = path
        return SimpleNamespace(total=1000, used=900, free=100)

    monkeypatch.setattr("src.logsync.manager.shutil.disk_usage", fake_disk_usage)

    result = manager.sync_now(reason="manual")

    bundle_dir = Path(result["bundle_directory"])
    archive_path = Path(result["archive_path"])

    assert result["status"] == "success"
    assert result["upload"]["status"] == "uploaded"
    assert not bundle_dir.exists()
    assert archive_path.exists()
    assert disk_usage_calls["path"] == manager.base_directory
    assert bundle_paths["archive_path"] == archive_path
    assert bundle_paths["manifest_path"].name == "manifest.json"


def test_flight_log_sync_download_latest_archive(tmp_path):
    manager = make_manager(tmp_path)
    archive_a = make_archive(manager.base_directory, "flight_guided", "20240618T160000Z", "landing")
    time.sleep(0.01)
    archive_b = make_archive(manager.base_directory, "flight_guided", "20240618T170000Z", "manual")

    assert manager.download_archive() == archive_b
    assert manager.download_archive(str(archive_a.name)) == archive_a


def test_flight_log_sync_cleanup_all_removes_archives_and_files(tmp_path):
    manager = make_manager(tmp_path)
    archive = make_archive(manager.base_directory, "flight_guided", "20240618T170000Z", "manual")
    extra_file = manager.base_directory / "misc.txt"
    extra_file.parent.mkdir(parents=True, exist_ok=True)
    extra_file.write_text("x")

    result = manager.cleanup_all()

    assert result["removed"]["archives"] == 1
    assert result["removed"]["other_files"] >= 1
    assert not archive.exists()
    assert not extra_file.exists()


@pytest.mark.asyncio
async def test_log_sync_routes_surface_history_and_replay(async_server_api):
    app = async_server_api.get_app()
    authority = async_server_api.control_authority.acquire("pytest", operator="qa", force=True)
    command_token = authority["authority"]["token"]
    async_server_api.flight_log_sync_manager = SimpleNamespace(
        status=lambda: {
            "status": "idle",
            "running": False,
            "base_directory": "/var/lib/drone-companion/flight-logs",
            "updated_at": 1_700_000_100.0,
        },
        history=lambda limit=10: [
            {
                "archive_path": "/var/lib/drone-companion/flight-logs/flight_guided/20240618T170000Z.zip",
                "name": "20240618T170000Z.zip",
                "session": "flight_guided",
                "reason": "landing",
                "pixhawk_file_count": 1,
                "companion_file_count": 1,
                "updated_at": 1_700_000_200.0,
            }
        ],
        replay=lambda archive_path, upload=False: {
            "archive_path": archive_path,
            "name": Path(archive_path).name,
            "session": "flight_guided",
            "reason": "landing",
            "upload": {"enabled": bool(upload)},
            "replayed_at": 1_700_000_300.0,
        },
    )

    status = await next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/log-sync/status")()
    history = await next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/log-sync/history")()
    replay = await next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/log-sync/replay")(
        FlightLogReplayRequest(archive_path="/var/lib/drone-companion/flight-logs/flight_guided/20240618T170000Z.zip"),
        x_control_token=command_token,
    )

    assert status.data["base_directory"].endswith("flight-logs")
    assert history.data["bundles"][0]["session"] == "flight_guided"
    assert replay.data["upload"]["enabled"] is False
