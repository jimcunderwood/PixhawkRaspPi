"""
Main Companion Computer Application
Initializes and runs the Raspberry Pi companion software
"""

import logging
from typing import Optional
import uvicorn

from src.config.settings import config
from src.mavlink.connection_manager import ConnectionManager
from src.missions.planner import (
    NavigationConfig,
    MissionPlanner,
)
from src.payloads.controller import PayloadController
from src.telemetry.collector import TelemetryManager
from src.api.server import ServerAPI

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _startup_navigation_config() -> NavigationConfig:
    """Build persisted mission navigation defaults from environment settings."""
    return NavigationConfig.from_dict(
        {
            "obstacle_avoidance": {
                "enabled": config.mission.obstacle_avoidance_enabled,
                "mode": config.mission.obstacle_avoidance_mode,
                "margin_meters": config.mission.obstacle_avoidance_margin_meters,
                "lookahead_meters": config.mission.obstacle_avoidance_lookahead_meters,
                "backup_speed_mps": config.mission.obstacle_avoidance_backup_speed_mps,
                "min_altitude_meters": config.mission.obstacle_avoidance_min_altitude_meters,
                "proximity_type": config.mission.obstacle_avoidance_proximity_type,
                "behavior": config.mission.obstacle_avoidance_behavior,
                "bendy_ruler_type": config.mission.obstacle_avoidance_bendy_ruler_type,
                "obstacle_database_size": config.mission.obstacle_database_size,
                "sensor": {
                    "source": config.mission.obstacle_avoidance_sensor_source,
                    "coverage_mode": config.mission.obstacle_avoidance_sensor_coverage_mode,
                    "mavlink_sensor_id": config.mission.obstacle_avoidance_sensor_mavlink_id,
                    "gpio_pin": config.mission.obstacle_avoidance_sensor_gpio_pin,
                    "gpio_active_low": config.mission.obstacle_avoidance_sensor_gpio_active_low,
                    "ros_enabled": config.mission.obstacle_avoidance_sensor_ros_enabled,
                    "ros_backend": config.mission.obstacle_avoidance_sensor_ros_backend,
                    "ros_topic": config.mission.obstacle_avoidance_sensor_ros_topic,
                    "ros_frame_id": config.mission.obstacle_avoidance_sensor_ros_frame_id,
                    "ros_message_type": config.mission.obstacle_avoidance_sensor_ros_message_type,
                },
            },
            "terrain_following": {
                "enabled": config.payload.terrain_following_enabled,
                "source": config.payload.terrain_sensor_source,
                "min_agl_meters": config.payload.terrain_min_agl_meters,
                "max_agl_meters": config.payload.terrain_max_agl_meters,
                "target_agl_meters": config.mission.terrain_target_agl_meters,
                "use_rangefinder_for_waypoints": config.mission.terrain_use_rangefinder_for_waypoints,
                "rtl_terrain_enabled": config.mission.terrain_rtl_enabled,
                "terrain_spacing_meters": config.mission.terrain_spacing_meters,
                "ros_bridge_enabled": config.mission.terrain_ros_bridge_enabled,
                "ros_backend": config.mission.terrain_ros_backend,
                "ros_topic": config.mission.terrain_ros_topic,
                "mavros_topic": config.mission.terrain_mavros_topic,
                "ros_frame_id": config.mission.terrain_ros_frame_id,
            },
        }
    )


class CompanionComputer:
    """Main application class"""

    def __init__(self):
        self.connection_manager: Optional[ConnectionManager] = None
        self.mission_planner: Optional[MissionPlanner] = None
        self.payload_controller: Optional[PayloadController] = None
        self.telemetry_manager: Optional[TelemetryManager] = None
        self.api_server: Optional[ServerAPI] = None
        self._running = False

    def initialize(self) -> bool:
        """Initialize all systems"""
        try:
            logger.info("Initializing Agricultural Drone Companion Computer...")

            # Initialize connection manager
            logger.info("Initializing MAVLink connection...")
            self.connection_manager = ConnectionManager(config.mavlink)
            
            if not self.connection_manager.connect():
                logger.error("Failed to connect to Pixhawk")
                return False

            # Initialize mission planner
            logger.info("Initializing mission planner...")
            self.mission_planner = MissionPlanner(
                config.mission.max_waypoints,
                config.mission.storage_file,
                navigation_config=_startup_navigation_config(),
            )
            self.connection_manager.apply_navigation_config(_startup_navigation_config())

            # Initialize payload controller
            logger.info("Initializing payload controller...")
            self.payload_controller = PayloadController(config.payload)

            # Initialize telemetry manager
            logger.info("Initializing telemetry system...")
            self.telemetry_manager = TelemetryManager(
                max_history=config.telemetry.history_size,
                update_interval=config.telemetry.update_interval
            )
            self.telemetry_manager.initialize(
                self.connection_manager.get_vehicle_state
            )

            # Initialize API server
            logger.info("Initializing API server...")
            self.api_server = ServerAPI(
                self.connection_manager,
                self.mission_planner,
                self.payload_controller,
                self.telemetry_manager
            )

            logger.info("✓ Initialization complete")
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            self.cleanup()
            return False

    def run_api_server(self, host: str = "0.0.0.0", port: int = 8000):
        """Run the API server"""
        try:
            logger.info(f"Starting API server on {host}:{port}...")
            self._running = True
            
            uvicorn.run(
                self.api_server.get_app(),
                host=host,
                port=port,
                log_level=config.log_level.lower()
            )

        except Exception as e:
            logger.error(f"API server error: {str(e)}")
            self._running = False

    def run(self):
        """Run the companion computer"""
        if not self.initialize():
            logger.error("Failed to initialize companion computer")
            return
        try:
            # Start API server. Uvicorn handles SIGINT/SIGTERM and returns
            # once shutdown has completed, allowing us to clean up gracefully.
            self.run_api_server(config.api.host, config.api.port)
        finally:
            self.cleanup()

    def cleanup(self):
        """Cleanup all resources"""
        logger.info("Cleaning up...")

        try:
            if self.telemetry_manager:
                self.telemetry_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping telemetry: {str(e)}")

        try:
            if self.payload_controller:
                self.payload_controller.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up payloads: {str(e)}")

        try:
            if self.connection_manager:
                self.connection_manager.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting from vehicle: {str(e)}")

        logger.info("Cleanup complete")
        self._running = False


def main():
    """Application entry point"""
    app = CompanionComputer()
    app.run()


if __name__ == "__main__":
    main()
