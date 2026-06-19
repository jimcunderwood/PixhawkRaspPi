import io

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from PIL import Image

from src.api.server import (
    BaseStationWizardRequest,
    ControlAuthorityRequest,
    FarmExportRequest,
    GeoTiffBoundsRequest,
    PpkProcessRequest,
    SwarmConfig,
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
