"""
Main Companion Computer Application
Initializes and runs the Raspberry Pi companion software
"""

import logging
import sys
import signal
from typing import Optional
import uvicorn

from src.config.settings import config
from src.mavlink.connection_manager import ConnectionManager
from src.missions.planner import MissionPlanner
from src.payloads.controller import PayloadController
from src.telemetry.collector import TelemetryManager
from src.api.server import ServerAPI

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
            self.mission_planner = MissionPlanner(config.mission.max_waypoints)

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

        # Setup signal handlers
        def signal_handler(sig, frame):
            logger.info("Shutdown signal received")
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start API server
        self.run_api_server(config.api.host, config.api.port)

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
