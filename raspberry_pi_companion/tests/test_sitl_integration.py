import os

import pytest

from src.config.settings import ConnectionType, MAVLinkConfig
from src.mavlink.connection_manager import ConnectionManager
from src.missions.planner import MissionPlanner


pytestmark = pytest.mark.integration


def test_sitl_mission_upload_download_verify_cycle():
    sitl_uri = os.getenv("PX4_SITL_URI") or os.getenv("MAVLINK_SITL_URI")
    if not sitl_uri:
        pytest.skip("Set PX4_SITL_URI or MAVLINK_SITL_URI to run the SITL integration test.")

    if ":" in sitl_uri and sitl_uri.count(":") >= 2:
        host, port_text = sitl_uri.rsplit(":", 1)
        udp_ip = host.split("://", 1)[-1]
        udp_port = int(port_text)
    else:
        udp_ip = "127.0.0.1"
        udp_port = 5760

    manager = ConnectionManager(
        MAVLinkConfig(
            connection_type=ConnectionType.UDP,
            udp_ip=udp_ip,
            udp_port=udp_port,
            udp_direction="out",
            timeout=10,
        )
    )
    planner = MissionPlanner(max_waypoints=10)
    planner.add_waypoint(40.1, -74.2, 50.0)
    planner.add_waypoint(40.1005, -74.1995, 52.0)

    try:
        if not manager.connect(start_monitor=False):
            pytest.skip("SITL endpoint is configured but the vehicle did not connect.")

        upload = manager.upload_mission(planner.mission_items)
        download = manager.download_mission()
        verify = manager.verify_mission(planner.mission_items)

        assert upload["success"] is True
        assert upload["uploaded_count"] == len(planner.mission_items)
        assert download["success"] is True
        assert download["count"] == len(planner.mission_items)
        assert verify["success"] is True
        assert verify["matches"] is True
    finally:
        manager.disconnect()
