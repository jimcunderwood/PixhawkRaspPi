"""
Configuration management for Raspberry Pi Companion Computer
Handles connection settings, hardware configuration, and operational parameters
"""

import os
from enum import Enum
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _parse_connection_type(value: str) -> 'ConnectionType':
    try:
        return ConnectionType(value.strip().lower())
    except Exception:
        return ConnectionType.SERIAL


class ConnectionType(Enum):
    """MAVLink connection types"""
    SERIAL = "serial"
    UDP = "udp"
    TCP = "tcp"


@dataclass
class MAVLinkConfig:
    """MAVLink connection configuration"""
    connection_type: ConnectionType = _parse_connection_type(
        os.getenv("MAVLINK_CONNECTION_TYPE", "serial")
    )
    port: str = os.getenv("MAVLINK_PORT", "/dev/serial1")
    baudrate: int = int(os.getenv("MAVLINK_BAUDRATE", "57600"))
    udp_ip: str = os.getenv("MAVLINK_UDP_IP", "127.0.0.1")
    udp_port: int = int(os.getenv("MAVLINK_UDP_PORT", "14550"))
    udp_direction: str = os.getenv("MAVLINK_UDP_DIRECTION", "out").strip().lower()
    timeout: int = int(os.getenv("MAVLINK_TIMEOUT", "30"))


@dataclass
class APIConfig:
    """REST API configuration"""
    host: str = os.getenv("API_HOST", "0.0.0.0")
    port: int = int(os.getenv("API_PORT", "8000"))
    debug: bool = os.getenv("API_DEBUG", "False").lower() == "true"
    cors_origins: list = None

    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = ["*"]


@dataclass
class PayloadConfig:
    """Payload hardware configuration"""
    spray_pump_pin: int = int(os.getenv("SPRAY_PUMP_PIN", "17"))
    camera_enabled: bool = os.getenv("CAMERA_ENABLED", "True").lower() == "true"
    camera_port: int = int(os.getenv("CAMERA_PORT", "0"))
    flow_sensor_pin: int = int(os.getenv("FLOW_SENSOR_PIN", "27"))
    flow_sensor_enabled: bool = os.getenv("FLOW_SENSOR_ENABLED", "True").lower() == "true"


@dataclass
class MissionConfig:
    """Mission planning configuration"""
    max_waypoints: int = int(os.getenv("MAX_WAYPOINTS", "100"))
    min_altitude: float = float(os.getenv("MIN_ALTITUDE", "5"))  # meters
    max_altitude: float = float(os.getenv("MAX_ALTITUDE", "120"))  # meters
    default_airspeed: float = float(os.getenv("DEFAULT_AIRSPEED", "5"))  # m/s
    loiter_radius: float = float(os.getenv("LOITER_RADIUS", "50"))  # meters


@dataclass
class TelemetryConfig:
    """Telemetry streaming configuration"""
    update_interval: float = float(os.getenv("TELEMETRY_UPDATE_INTERVAL", "0.5"))  # seconds
    history_size: int = int(os.getenv("TELEMETRY_HISTORY_SIZE", "3600"))
    gps_timeout: float = float(os.getenv("GPS_TIMEOUT", "10"))


class Config:
    """Main configuration class"""

    def __init__(self):
        self.mavlink = MAVLinkConfig()
        self.api = APIConfig()
        self.payload = PayloadConfig()
        self.mission = MissionConfig()
        self.telemetry = TelemetryConfig()
        self.environment = os.getenv("ENVIRONMENT", "production")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")


# Global config instance
config = Config()
