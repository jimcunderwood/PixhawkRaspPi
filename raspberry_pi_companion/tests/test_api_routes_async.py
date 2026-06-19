import io
from pathlib import Path

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from PIL import Image

from src.api import server as server_module
from src.api.server import (
    BaseStationWizardRequest,
    ControlAuthorityRequest,
    FarmExportRequest,
    GeoTiffBoundsRequest,
    PpkProcessRequest,
    SwarmConfig,
    StorageFileDeleteRequest,
)

pytestmark = pytest.mark.asyncio


def get_route_endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in (route.methods or []):
            return route.endpoint
    raise AssertionError(f"Route not found: {method} {path}")


async def test_httpx_async_client_covers_core_routes(async_server_api):
    app = async_server_api.get_app()
    async_server_api.control_authority.acquire("pytest", operator="qa", force=True)

    health = await get_route_endpoint(app, "/health", "GET")()
    readiness = await get_route_endpoint(app, "/readiness", "GET")()
    system_info = await get_route_endpoint(app, "/info", "GET")()
    telemetry_current = await get_route_endpoint(app, "/api/telemetry/current", "GET")()
    telemetry_history = await get_route_endpoint(app, "/api/telemetry/history", "GET")(seconds=120)
    telemetry_stats = await get_route_endpoint(app, "/api/telemetry/stats", "GET")(seconds=120)
    safety_status = await get_route_endpoint(app, "/api/safety/status", "GET")()
    compliance_remote_id = await get_route_endpoint(app, "/api/compliance/remote-id", "GET")()
    compliance_waivers = await get_route_endpoint(app, "/api/compliance/waivers", "GET")()
    payload_status = await get_route_endpoint(app, "/api/payload/status", "GET")()
    prescription_status = await get_route_endpoint(app, "/api/payload/prescription/status", "GET")()
    prescription_maps = await get_route_endpoint(app, "/api/payload/prescription/maps", "GET")()
    calibration_status = await get_route_endpoint(app, "/api/calibration/status", "GET")()
    farm_status = await get_route_endpoint(app, "/api/farm/status", "GET")()
    swarm_status = await get_route_endpoint(app, "/api/swarm/status", "GET")()
    swarm_config = await get_route_endpoint(app, "/api/swarm/config", "GET")()
    swarm_coordination = await get_route_endpoint(app, "/api/swarm/coordination", "GET")()
    fleet_status = await get_route_endpoint(app, "/api/fleet/status", "GET")()

    for response in [
        health,
        readiness,
        system_info,
        telemetry_current,
        telemetry_history,
        telemetry_stats,
        safety_status,
        compliance_remote_id,
        compliance_waivers,
        payload_status,
        prescription_status,
        prescription_maps,
        calibration_status,
        farm_status,
        swarm_status,
        swarm_config,
        swarm_coordination,
        fleet_status,
    ]:
        assert response is not None

    mission_stats = await get_route_endpoint(app, "/api/mission/stats", "GET")()
    assert mission_stats.data is not None
    assert mission_stats is not None


async def test_httpx_async_client_covers_calibration_farm_swarm_and_geotiff(async_server_api, tmp_path):
    app = async_server_api.get_app()
    async_server_api.payload_controller.camera = type("Camera", (), {"photo_directory": tmp_path, "is_available": lambda self: True})()

    authority = async_server_api.control_authority.acquire("pytest", operator="qa", force=True)
    command_token = authority["authority"]["token"]

    save_base_station = await get_route_endpoint(app, "/api/calibration/rtk/base-stations", "POST")(
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
    ppk_job = await get_route_endpoint(app, "/api/calibration/ppk/process", "POST")(
        PpkProcessRequest(session="spray-001", base_station_id="base-01", telemetry_window_seconds=120),
        x_control_token=command_token,
    )
    export_isoxml = await get_route_endpoint(app, "/api/farm/integrations/isoxml/export", "POST")(
        FarmExportRequest(session="spray-001"),
        x_control_token=command_token,
    )
    sync_agleader = await get_route_endpoint(app, "/api/farm/integrations/agleader/sync", "POST")(
        FarmExportRequest(session="spray-001"),
        x_control_token=command_token,
    )
    report = await get_route_endpoint(app, "/api/farm/reports/automated", "POST")(
        FarmExportRequest(session="spray-001"),
        x_control_token=command_token,
    )

    swarm_config = (await get_route_endpoint(app, "/api/swarm/config", "GET")()).data
    swarm_config["enabled"] = True
    swarm_config["role"] = "leader"
    swarm_config["fusion"]["mode"] = "relative_pose"
    swarm_config["peers"][0]["role"] = "leader"
    validate_swarm = await get_route_endpoint(app, "/api/swarm/config/validate", "POST")(SwarmConfig.model_validate(swarm_config))
    update_swarm = await get_route_endpoint(app, "/api/swarm/config", "PUT")(SwarmConfig.model_validate(swarm_config), x_control_token=command_token)
    broadcast = await get_route_endpoint(app, "/api/swarm/broadcast", "POST")()
    telemetry_history = await get_route_endpoint(app, "/api/swarm/telemetry/history", "GET")(seconds=120, limit=2)

    image = Image.new("RGB", (64, 32), color=(40, 180, 120))
    geotiff_bytes = io.BytesIO()
    image.save(geotiff_bytes, format="TIFF")
    preview_bytes, preview_meta = async_server_api._preview_image_from_geotiff(geotiff_bytes.getvalue(), 48)
    geotiff_asset = async_server_api.geotiff_assets.save_asset(
        name="Field North",
        source_filename="field-north.tif",
        bounds=GeoTiffBoundsRequest(north=40.2, south=40.1, east=-74.1, west=-74.2).model_dump(),
        source_bytes=geotiff_bytes.getvalue(),
        preview_bytes=preview_bytes,
        preview_meta=preview_meta,
    )
    geotiff_list = async_server_api.geotiff_assets.list_assets()
    geotiff_detail = async_server_api.geotiff_assets.get_asset(geotiff_asset["asset_id"])
    geotiff_preview = await get_route_endpoint(app, "/api/mapping/geotiff/{asset_id}/preview", "GET")(asset_id=geotiff_asset["asset_id"])
    geotiff_delete = async_server_api.geotiff_assets.delete_asset(geotiff_asset["asset_id"])

    assert save_base_station.data["active"] is True
    assert ppk_job.data["request"]["base_station_id"] == "base-01"
    assert export_isoxml.data["archive_path"].endswith(".zip")
    assert sync_agleader.data["payload"]["telemetry_samples"] == 3
    assert report.data["summary"]["telemetry_samples"] == 3
    assert validate_swarm.data["role"] == "leader"
    assert update_swarm.data["role"] == "leader"
    assert broadcast.data["fusion"]["peer_count"] >= 0
    assert len(telemetry_history.data["samples"]) >= 0
    assert geotiff_asset["asset_id"].startswith("geotiff-")
    assert geotiff_detail["source_filename"] == "field-north.tif"
    assert geotiff_preview.status_code == 200
    assert geotiff_delete is True


async def test_httpx_async_client_covers_storage_status_listing_and_delete(async_server_api, tmp_path):
    app = async_server_api.get_app()
    server_module.config.storage.flight_log_directory = str(tmp_path / "flight-logs")
    server_module.config.storage.geotiff_asset_directory = str(tmp_path / "geotiff" / "assets")
    server_module.config.payload.spray_application_record_directory = str(tmp_path / "application-records")
    server_module.config.api.audit_log_file = str(tmp_path / "audit" / "events.jsonl")
    async_server_api.flight_log_sync_manager = type(
        "FlightLogSyncManager",
        (),
        {"base_directory": Path(tmp_path / "flight-logs")},
    )()
    async_server_api.payload_controller.camera = type(
        "Camera",
        (),
        {"photo_directory": Path(tmp_path / "photos")},
    )()
    authority = async_server_api.control_authority.acquire("pytest", operator="qa", force=True)
    command_token = authority["authority"]["token"]

    flight_log_root = Path(tmp_path / "flight-logs" / "mission-a")
    media_root = Path(tmp_path / "photos" / "mission-b")
    audit_root = Path(tmp_path / "audit")
    geotiff_root = Path(tmp_path / "geotiff" / "assets")
    spray_root = Path(tmp_path / "application-records")
    for root in [flight_log_root, media_root, audit_root, geotiff_root, spray_root]:
        root.mkdir(parents=True, exist_ok=True)

    flight_log_file = flight_log_root / "20240618T160000Z.zip"
    flight_log_file.write_bytes(b"zip")
    photo_file = media_root / "photo-1.jpg"
    photo_file.write_bytes(b"jpg")
    video_file = media_root / "video-1.mp4"
    video_file.write_bytes(b"mp4")
    audit_file = audit_root / "events.jsonl"
    audit_file.write_text("audit")

    storage_status = await get_route_endpoint(app, "/api/storage/status", "GET")()
    storage_files = await get_route_endpoint(app, "/api/storage/files", "GET")()
    delete_result = await get_route_endpoint(app, "/api/storage/files", "DELETE")(
        StorageFileDeleteRequest(paths=[str(photo_file), str(flight_log_file)]),
        x_control_token=command_token,
    )

    assert storage_status.usage["flight_logs"]["path"].endswith("flight-logs")
    assert storage_status.usage["camera_media"]["path"].endswith("photos")
    assert "files" in storage_files.data
    assert isinstance(storage_files.data["files"], list)
    assert delete_result.data["removed"] == [str(photo_file), str(flight_log_file)]
    assert not photo_file.exists()
    assert not flight_log_file.exists()
