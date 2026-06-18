"""
Configuration management for Raspberry Pi Companion Computer
Handles connection settings, hardware configuration, and operational parameters
"""

import os
from enum import Enum
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _parse_connection_type(value: str) -> 'ConnectionType':
    try:
        return ConnectionType(value.strip().lower())
    except Exception:
        return ConnectionType.SERIAL


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: str) -> list:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_api_key_roles(value: str) -> dict:
    roles = {"viewer", "operator", "admin", "maintenance"}
    api_key_roles = {}

    for item in _parse_csv(value):
        if "=" in item:
            first, second = item.split("=", 1)
        elif ":" in item:
            first, second = item.split(":", 1)
        else:
            continue

        first = first.strip()
        second = second.strip()
        if not first or not second:
            continue

        if first.lower() in roles:
            api_key_roles[second] = first.lower()
        elif second.lower() in roles:
            api_key_roles[first] = second.lower()

    return api_key_roles


def _parse_optional_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    return int(value)


def _parse_optional_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    return float(value)


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
    port: str = os.getenv("MAVLINK_PORT", "/dev/serial0")
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
    debug: bool = _parse_bool(os.getenv("API_DEBUG", "False"))
    api_key: str = os.getenv("API_KEY", "")
    api_key_role: str = os.getenv("API_KEY_ROLE", "admin").strip().lower()
    api_key_roles: dict = None
    auth_enabled: bool = _parse_bool(os.getenv("API_AUTH_ENABLED", "True"))
    safety_gates_enabled: bool = _parse_bool(os.getenv("SAFETY_GATES_ENABLED", "True"))
    command_authority_enabled: bool = _parse_bool(os.getenv("COMMAND_AUTHORITY_ENABLED", "True"))
    command_authority_lease_seconds: int = int(os.getenv("COMMAND_AUTHORITY_LEASE_SECONDS", "30"))
    idempotency_ttl_seconds: int = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "300"))
    telemetry_freshness_enabled: bool = _parse_bool(os.getenv("TELEMETRY_FRESHNESS_ENABLED", "True"))
    telemetry_stale_seconds: float = float(os.getenv("TELEMETRY_STALE_SECONDS", "3"))
    payload_stale_seconds: float = float(os.getenv("PAYLOAD_STALE_SECONDS", "3"))
    audit_log_max_bytes: int = int(os.getenv("AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
    audit_log_backup_count: int = int(os.getenv("AUDIT_LOG_BACKUP_COUNT", "5"))
    audit_log_file: str = os.getenv(
        "AUDIT_LOG_FILE",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "audit", "events.jsonl"),
    )
    config_database_file: str = os.getenv(
        "CONFIG_DATABASE_FILE",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "config", "profiles.sqlite3"),
    )
    cors_origins: list = None

    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = _parse_csv(os.getenv("CORS_ORIGINS", "*")) or ["*"]
        if self.api_key_roles is None:
            self.api_key_roles = _parse_api_key_roles(os.getenv("API_KEY_ROLES", ""))
        if self.api_key and self.api_key not in self.api_key_roles:
            self.api_key_roles[self.api_key] = self.api_key_role


@dataclass
class PayloadConfig:
    """Payload hardware configuration"""
    spray_pump_pin: int = int(os.getenv("SPRAY_PUMP_PIN", "17"))
    camera_enabled: bool = _parse_bool(os.getenv("CAMERA_ENABLED", "True"))
    camera_port: int = int(os.getenv("CAMERA_PORT", "0"))
    camera_trigger_enabled: bool = _parse_bool(os.getenv("CAMERA_TRIGGER_ENABLED", "False"))
    camera_trigger_pin: int = int(os.getenv("CAMERA_TRIGGER_PIN", "22"))
    camera_trigger_pulse_ms: float = float(os.getenv("CAMERA_TRIGGER_PULSE_MS", "100"))
    data_directory: str = os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion")
    photo_directory: str = os.getenv(
        "PHOTO_DIRECTORY",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "photos"),
    )
    spray_session_directory: str = os.getenv(
        "SPRAY_SESSION_DIRECTORY",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "spray-sessions"),
    )
    flow_sensor_pin: int = int(os.getenv("FLOW_SENSOR_PIN", "27"))
    flow_sensor_enabled: bool = _parse_bool(os.getenv("FLOW_SENSOR_ENABLED", "True"))
    flow_sensor_pulses_per_liter: float = float(os.getenv("FLOW_SENSOR_PULSES_PER_LITER", "450"))
    pressure_sensor_enabled: bool = _parse_bool(os.getenv("PRESSURE_SENSOR_ENABLED", "False"))
    pressure_sensor_source: str = os.getenv("PRESSURE_SENSOR_SOURCE", "adc").strip().lower()
    pressure_sensor_pin: int | None = _parse_optional_int(os.getenv("PRESSURE_SENSOR_PIN", ""))
    pressure_sensor_adc_channel: int = int(os.getenv("PRESSURE_SENSOR_ADC_CHANNEL", "0"))
    pressure_sensor_min_voltage: float = float(os.getenv("PRESSURE_SENSOR_MIN_VOLTAGE", "0.5"))
    pressure_sensor_max_voltage: float = float(os.getenv("PRESSURE_SENSOR_MAX_VOLTAGE", "4.5"))
    pressure_sensor_min_psi: float = float(os.getenv("PRESSURE_SENSOR_MIN_PSI", "0"))
    pressure_sensor_max_psi: float = float(os.getenv("PRESSURE_SENSOR_MAX_PSI", "150"))
    tank_level_sensor_enabled: bool = _parse_bool(os.getenv("TANK_LEVEL_SENSOR_ENABLED", "False"))
    tank_level_sensor_source: str = os.getenv("TANK_LEVEL_SENSOR_SOURCE", "adc").strip().lower()
    tank_level_sensor_pin: int | None = _parse_optional_int(os.getenv("TANK_LEVEL_SENSOR_PIN", ""))
    tank_level_sensor_adc_channel: int = int(os.getenv("TANK_LEVEL_SENSOR_ADC_CHANNEL", "1"))
    tank_level_sensor_min_voltage: float = float(os.getenv("TANK_LEVEL_SENSOR_MIN_VOLTAGE", "0.5"))
    tank_level_sensor_max_voltage: float = float(os.getenv("TANK_LEVEL_SENSOR_MAX_VOLTAGE", "4.5"))
    tank_capacity_liters: float = float(os.getenv("TANK_CAPACITY_LITERS", "10"))
    tank_min_level_percent: float = float(os.getenv("TANK_MIN_LEVEL_PERCENT", "10"))
    rtk_enabled: bool = _parse_bool(os.getenv("RTK_ENABLED", "False"))
    rtk_correction_port: str = os.getenv("RTK_CORRECTION_PORT", "/dev/ttyUSB0")
    rtk_correction_baudrate: int = int(os.getenv("RTK_CORRECTION_BAUDRATE", "115200"))
    ppk_enabled: bool = _parse_bool(os.getenv("PPK_ENABLED", "False"))
    ppk_log_directory: str = os.getenv(
        "PPK_LOG_DIRECTORY",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "ppk"),
    )
    spray_application_record_directory: str = os.getenv(
        "SPRAY_APPLICATION_RECORD_DIRECTORY",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "application-records"),
    )
    terrain_following_enabled: bool = _parse_bool(os.getenv("TERRAIN_FOLLOWING_ENABLED", "False"))
    terrain_sensor_source: str = os.getenv("TERRAIN_SENSOR_SOURCE", "rangefinder").strip().lower()
    terrain_sensor_pin: int | None = _parse_optional_int(os.getenv("TERRAIN_SENSOR_PIN", ""))
    terrain_min_agl_meters: float = float(os.getenv("TERRAIN_MIN_AGL_METERS", "2"))
    terrain_max_agl_meters: float = float(os.getenv("TERRAIN_MAX_AGL_METERS", "120"))


@dataclass
class MissionConfig:
    """Mission planning configuration"""
    data_directory: str = os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion")
    storage_file: str = os.getenv(
        "MISSION_FILE",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "missions", "mission.json"),
    )
    max_waypoints: int = int(os.getenv("MAX_WAYPOINTS", "100"))
    min_altitude: float = float(os.getenv("MIN_ALTITUDE", "5"))  # meters
    max_altitude: float = float(os.getenv("MAX_ALTITUDE", "120"))  # meters
    default_airspeed: float = float(os.getenv("DEFAULT_AIRSPEED", "5"))  # m/s
    loiter_radius: float = float(os.getenv("LOITER_RADIUS", "50"))  # meters
    obstacle_avoidance_enabled: bool = _parse_bool(os.getenv("OBSTACLE_AVOIDANCE_ENABLED", "False"))
    obstacle_avoidance_mode: str = os.getenv("OBSTACLE_AVOIDANCE_MODE", "simple").strip().lower()
    obstacle_avoidance_margin_meters: float = float(os.getenv("OBSTACLE_AVOIDANCE_MARGIN_METERS", "2"))
    obstacle_avoidance_lookahead_meters: float = float(os.getenv("OBSTACLE_AVOIDANCE_LOOKAHEAD_METERS", "5"))
    obstacle_avoidance_backup_speed_mps: float = float(os.getenv("OBSTACLE_AVOIDANCE_BACKUP_SPEED_MPS", "0"))
    obstacle_avoidance_min_altitude_meters: float = float(os.getenv("OBSTACLE_AVOIDANCE_MIN_ALTITUDE_METERS", "0"))
    obstacle_avoidance_proximity_type: int | None = _parse_optional_int(
        os.getenv("OBSTACLE_AVOIDANCE_PROXIMITY_TYPE", "4")
    )
    obstacle_avoidance_behavior: str = os.getenv("OBSTACLE_AVOIDANCE_BEHAVIOR", "slide").strip().lower()
    obstacle_avoidance_bendy_ruler_type: str = os.getenv(
        "OBSTACLE_AVOIDANCE_BENDY_RULER_TYPE",
        "horizontal",
    ).strip().lower()
    obstacle_database_size: int | None = _parse_optional_int(os.getenv("OBSTACLE_DATABASE_SIZE", ""))
    obstacle_avoidance_sensor_source: str = os.getenv("OBSTACLE_AVOIDANCE_SENSOR_SOURCE", "mavlink").strip().lower()
    obstacle_avoidance_sensor_coverage_mode: str = os.getenv(
        "OBSTACLE_AVOIDANCE_SENSOR_COVERAGE_MODE",
        "forward",
    ).strip().lower()
    obstacle_avoidance_sensor_mavlink_id: int | None = _parse_optional_int(
        os.getenv("OBSTACLE_AVOIDANCE_SENSOR_MAVLINK_ID", "1")
    )
    obstacle_avoidance_sensor_gpio_pin: int | None = _parse_optional_int(
        os.getenv("OBSTACLE_AVOIDANCE_SENSOR_GPIO_PIN", "")
    )
    obstacle_avoidance_sensor_gpio_active_low: bool = _parse_bool(
        os.getenv("OBSTACLE_AVOIDANCE_SENSOR_GPIO_ACTIVE_LOW", "True")
    )
    obstacle_avoidance_sensor_ros_enabled: bool = _parse_bool(
        os.getenv("OBSTACLE_AVOIDANCE_SENSOR_ROS_ENABLED", "False")
    )
    obstacle_avoidance_sensor_ros_backend: str = os.getenv(
        "OBSTACLE_AVOIDANCE_SENSOR_ROS_BACKEND",
        "mavros",
    ).strip().lower()
    obstacle_avoidance_sensor_ros_topic: str = os.getenv("OBSTACLE_AVOIDANCE_SENSOR_ROS_TOPIC", "").strip()
    obstacle_avoidance_sensor_ros_frame_id: str = os.getenv("OBSTACLE_AVOIDANCE_SENSOR_ROS_FRAME_ID", "").strip()
    obstacle_avoidance_sensor_ros_message_type: str = os.getenv(
        "OBSTACLE_AVOIDANCE_SENSOR_ROS_MESSAGE_TYPE",
        "std_msgs/Float32",
    ).strip()
    terrain_target_agl_meters: float | None = _parse_optional_float(os.getenv("TERRAIN_TARGET_AGL_METERS", ""))
    terrain_use_rangefinder_for_waypoints: bool = _parse_bool(
        os.getenv("TERRAIN_USE_RANGEFINDER_FOR_WAYPOINTS", "True")
    )
    terrain_rtl_enabled: bool = _parse_bool(os.getenv("TERRAIN_RTL_ENABLED", "False"))
    terrain_spacing_meters: float | None = _parse_optional_float(os.getenv("TERRAIN_SPACING_METERS", ""))
    terrain_ros_bridge_enabled: bool = _parse_bool(os.getenv("TERRAIN_ROS_BRIDGE_ENABLED", "False"))
    terrain_ros_backend: str = os.getenv("TERRAIN_ROS_BACKEND", "mavros").strip().lower()
    terrain_ros_topic: str = os.getenv("TERRAIN_ROS_TOPIC", "").strip()
    terrain_mavros_topic: str = os.getenv("TERRAIN_MAVROS_TOPIC", "").strip()
    terrain_ros_frame_id: str = os.getenv("TERRAIN_ROS_FRAME_ID", "").strip()


@dataclass
class MappingConfig:
    """Photogrammetry, geotagging, and vegetation-mapping configuration."""
    survey_front_overlap: float = float(os.getenv("SURVEY_FRONT_OVERLAP", "0.70"))
    survey_side_overlap: float = float(os.getenv("SURVEY_SIDE_OVERLAP", "0.80"))
    survey_target_gsd_cm: float = float(os.getenv("SURVEY_TARGET_GSD_CM", "2.5"))
    survey_default_altitude_m: float = float(os.getenv("SURVEY_DEFAULT_ALTITUDE_M", "60"))
    survey_default_heading_deg: float = float(os.getenv("SURVEY_DEFAULT_HEADING_DEG", "0"))
    survey_flight_speed_mps: float = float(os.getenv("SURVEY_FLIGHT_SPEED_MPS", "5"))
    survey_terrain_aware: bool = _parse_bool(os.getenv("SURVEY_TERRAIN_AWARE", "False"))
    survey_terrain_clearance_m: float = float(os.getenv("SURVEY_TERRAIN_CLEARANCE_M", "5"))
    survey_border_margin_m: float = float(os.getenv("SURVEY_BORDER_MARGIN_M", "0"))
    camera_sensor_width_mm: float = float(os.getenv("CAMERA_SENSOR_WIDTH_MM", "13.2"))
    camera_sensor_height_mm: float = float(os.getenv("CAMERA_SENSOR_HEIGHT_MM", "8.8"))
    camera_image_width_px: int = int(os.getenv("CAMERA_IMAGE_WIDTH_PX", "4000"))
    camera_image_height_px: int = int(os.getenv("CAMERA_IMAGE_HEIGHT_PX", "3000"))
    camera_focal_length_mm: float = float(os.getenv("CAMERA_FOCAL_LENGTH_MM", "8.8"))
    ndvi_enabled: bool = _parse_bool(os.getenv("NDVI_ENABLED", "False"))
    ndvi_red_band_index: int = int(os.getenv("NDVI_RED_BAND_INDEX", "0"))
    ndvi_nir_band_index: int = int(os.getenv("NDVI_NIR_BAND_INDEX", "1"))
    orthomosaic_preview_max_columns: int = int(os.getenv("ORTHOMOSAIC_PREVIEW_MAX_COLUMNS", "4"))
    orthomosaic_preview_tile_scale: float = float(os.getenv("ORTHOMOSAIC_PREVIEW_TILE_SCALE", "0.2"))
    lidar_enabled: bool = _parse_bool(os.getenv("LIDAR_ENABLED", "False"))
    lidar_topic: str = os.getenv("LIDAR_TOPIC", "").strip()
    lidar_frame_id: str = os.getenv("LIDAR_FRAME_ID", "base_link").strip()


@dataclass
class TelemetryConfig:
    """Telemetry streaming configuration"""
    update_interval: float = float(os.getenv("TELEMETRY_UPDATE_INTERVAL", "0.5"))  # seconds
    history_size: int = int(os.getenv("TELEMETRY_HISTORY_SIZE", "3600"))
    gps_timeout: float = float(os.getenv("GPS_TIMEOUT", "10"))


@dataclass
class StorageConfig:
    """Persistent storage and log-archive configuration."""
    telemetry_database_file: str = os.getenv(
        "TELEMETRY_DATABASE_FILE",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "telemetry", "telemetry.sqlite3"),
    )
    telemetry_database_max_bytes: int = int(os.getenv("TELEMETRY_DATABASE_MAX_BYTES", str(64 * 1024 * 1024)))
    telemetry_database_backup_count: int = int(os.getenv("TELEMETRY_DATABASE_BACKUP_COUNT", "10"))
    telemetry_database_vacuum_interval_seconds: int = int(
        os.getenv("TELEMETRY_DATABASE_VACUUM_INTERVAL_SECONDS", "3600")
    )
    flight_log_directory: str = os.getenv(
        "FLIGHT_LOG_DIRECTORY",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "flight-logs"),
    )
    flight_log_backup_count: int = int(os.getenv("FLIGHT_LOG_BACKUP_COUNT", "10"))
    flight_log_download_limit: int = int(os.getenv("FLIGHT_LOG_DOWNLOAD_LIMIT", "10"))
    flight_log_sync_delay_seconds: float = float(os.getenv("FLIGHT_LOG_SYNC_DELAY_SECONDS", "5"))
    flight_log_cloud_upload_enabled: bool = _parse_bool(os.getenv("FLIGHT_LOG_CLOUD_UPLOAD_ENABLED", "False"))
    flight_log_cloud_upload_url: str = os.getenv("FLIGHT_LOG_CLOUD_UPLOAD_URL", "").strip()
    flight_log_cloud_upload_timeout_seconds: int = int(
        os.getenv("FLIGHT_LOG_CLOUD_UPLOAD_TIMEOUT_SECONDS", "30")
    )


@dataclass
class SafetyConfig:
    """Companion-side geofence, failsafe, and compliance configuration."""
    safety_state_file: str = os.getenv(
        "SAFETY_STATE_FILE",
        os.path.join(os.getenv("APP_DATA_DIRECTORY", "/var/lib/drone-companion"), "safety", "state.json"),
    )
    autonomous_failsafe_enabled: bool = _parse_bool(os.getenv("AUTONOMOUS_FAILSAFE_ENABLED", "True"))
    altitude_hard_min_m: float = float(os.getenv("ALTITUDE_HARD_MIN_M", "0"))
    altitude_soft_min_m: float = float(os.getenv("ALTITUDE_SOFT_MIN_M", "2"))
    altitude_soft_max_m: float = float(os.getenv("ALTITUDE_SOFT_MAX_M", "110"))
    altitude_hard_max_m: float = float(os.getenv("ALTITUDE_HARD_MAX_M", "120"))
    dynamic_geofence_speed_threshold_mps: float = float(os.getenv("DYNAMIC_GEOFENCE_SPEED_THRESHOLD_MPS", "8"))
    dynamic_geofence_soft_ceiling_reduction_m_per_mps: float = float(
        os.getenv("DYNAMIC_GEOFENCE_SOFT_CEILING_REDUCTION_M_PER_MPS", "1.5")
    )
    lost_link_warn_seconds: float = float(os.getenv("LOST_LINK_WARN_SECONDS", "2"))
    lost_link_rtl_seconds: float = float(os.getenv("LOST_LINK_RTL_SECONDS", "5"))
    lost_link_land_seconds: float = float(os.getenv("LOST_LINK_LAND_SECONDS", "10"))
    low_battery_warn_percent: float = float(os.getenv("LOW_BATTERY_WARN_PERCENT", "30"))
    low_battery_rtl_percent: float = float(os.getenv("LOW_BATTERY_RTL_PERCENT", "20"))
    low_battery_land_percent: float = float(os.getenv("LOW_BATTERY_LAND_PERCENT", "10"))
    gps_loss_warn_seconds: float = float(os.getenv("GPS_LOSS_WARN_SECONDS", "2"))
    gps_loss_rtl_seconds: float = float(os.getenv("GPS_LOSS_RTL_SECONDS", "5"))
    gps_loss_land_seconds: float = float(os.getenv("GPS_LOSS_LAND_SECONDS", "10"))
    prearm_block_on_safety_switch: bool = _parse_bool(os.getenv("PREARM_BLOCK_ON_SAFETY_SWITCH", "True"))
    safety_switch_expected_on: bool = _parse_bool(os.getenv("SAFETY_SWITCH_EXPECTED_ON", "True"))
    motor_test_duration_seconds: float = float(os.getenv("MOTOR_TEST_DURATION_SECONDS", "2"))
    remote_id_enabled: bool = _parse_bool(os.getenv("REMOTE_ID_ENABLED", "False"))
    remote_id_operator_id: str = os.getenv("REMOTE_ID_OPERATOR_ID", "").strip()
    remote_id_serial_number: str = os.getenv("REMOTE_ID_SERIAL_NUMBER", "").strip()
    remote_id_description: str = os.getenv("REMOTE_ID_DESCRIPTION", "").strip()
    remote_id_broadcast_method: str = os.getenv("REMOTE_ID_BROADCAST_METHOD", "mavlink").strip().lower()
    part107_night_authorized: bool = _parse_bool(os.getenv("PART107_NIGHT_AUTHORIZED", "False"))
    part107_bvlos_authorized: bool = _parse_bool(os.getenv("PART107_BVLOS_AUTHORIZED", "False"))
    part107_waiver_notes: str = os.getenv("PART107_WAIVER_NOTES", "").strip()
    no_fly_zone_seed_file: str = os.getenv("NO_FLY_ZONE_SEED_FILE", "").strip()


class Config:
    """Main configuration class"""

    def __init__(self):
        self.mavlink = MAVLinkConfig()
        self.api = APIConfig()
        self.payload = PayloadConfig()
        self.mission = MissionConfig()
        self.mapping = MappingConfig()
        self.telemetry = TelemetryConfig()
        self.storage = StorageConfig()
        self.safety = SafetyConfig()
        self.environment = os.getenv("ENVIRONMENT", "production")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")


# Global config instance
config = Config()
