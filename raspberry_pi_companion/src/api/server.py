"""
FastAPI REST and WebSocket Server
Main API interface for ground station communication
"""

import asyncio
import csv
import json
import hashlib
import hmac
import io
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from contextvars import ContextVar
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import cv2
import numpy as np
from PIL import Image
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Security, WebSocket, WebSocketDisconnect
from fastapi.routing import APIRoute
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.background import BackgroundTask

from ..audit.logger import AuditLogger
from ..config.profiles import ConfigProfileStore
from ..config.settings import config
from ..mapping.planner import (
    CameraSpec,
    GeotagRecord,
    MappingPlanner,
    PointCloudScanConfig,
    SurveyGridConfig,
    VegetationCaptureProfile,
)
from ..mapping.geotiff_store import GeoTiffAssetConfig, GeoTiffAssetStore
from ..calibration.workflow import CalibrationWorkflowConfig, CalibrationWorkflowManager
from ..farm.manager import FarmIntegrationConfig, FarmIntegrationManager
from ..safety.manager import GeofenceZone, SafetyManager
from ..vision.detector import EdgeObstacleDetector
from ..swarm.database import SwarmDatabase, SwarmDatabaseConfig
from ..swarm.manager import SwarmManager
from ..swarm.models import (
    SwarmConfig,
    SwarmFusionState,
    SwarmSeparationAlert,
    SwarmStatus,
    SwarmTelemetryMessage,
)
from ..weather.service import WeatherService

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
COMMAND_OUTCOME_EVENT_TYPES = {
    "success": "command.accepted",
    "blocked": "command.blocked",
    "failed": "command.failed",
}
SUCCESS_ACTION_EVENT_TYPES = {
    "control.authority_acquire": "authority.acquired",
    "control.authority_release": "authority.released",
    "mission.pixhawk_upload": "mission.uploaded",
    "mission.pixhawk_verify": "mission.verified",
    "payload.application_record_create": "spray_record.created",
}
IDEMPOTENCY_HEADER_NAMES = ("idempotency-key", "x-idempotency-key")
IDEMPOTENT_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ApiRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    MAINTENANCE = "maintenance"


class AuthenticatedPrincipal(BaseModel):
    role: ApiRole
    api_key_id: Optional[str] = None


api_auth_context: ContextVar[Optional[AuthenticatedPrincipal]] = ContextVar(
    "api_auth_context",
    default=None,
)
READ_ROLES = {ApiRole.VIEWER, ApiRole.OPERATOR, ApiRole.ADMIN, ApiRole.MAINTENANCE}
COMMAND_ROLES = {ApiRole.OPERATOR, ApiRole.ADMIN}
AUTHORITY_ROLES = {ApiRole.OPERATOR, ApiRole.ADMIN, ApiRole.MAINTENANCE}
MAINTENANCE_ROLES = {ApiRole.OPERATOR, ApiRole.ADMIN, ApiRole.MAINTENANCE}
AUDIT_ROLES = {ApiRole.ADMIN, ApiRole.MAINTENANCE}


def _to_lower_camel(tokens: List[str]) -> str:
    words = [token for token in tokens if token]
    if not words:
        return "operation"

    return words[0].lower() + "".join(
        word[:1].upper() + word[1:] for word in words[1:]
    )


def clean_openapi_operation_id(route: APIRoute) -> str:
    """Generate stable, client-friendly operation IDs from method and path."""
    methods = sorted(route.methods or [])
    method = methods[0].lower() if methods else "operation"
    path = getattr(route, "path_format", route.path)
    parts = []

    for raw_segment in path.strip("/").split("/"):
        if not raw_segment or raw_segment == "api":
            continue

        if raw_segment.startswith("{") and raw_segment.endswith("}"):
            segment_tokens = ["by", raw_segment[1:-1]]
        else:
            segment_tokens = re.split(r"[^0-9A-Za-z]+", raw_segment)

        parts.extend(token.lower() for token in segment_tokens if token)

    if parts and re.fullmatch(r"v[0-9]+", parts[0]):
        version = parts.pop(0)
        return _to_lower_camel([version, method, *parts])

    return _to_lower_camel([method, *parts])

DARK_SWAGGER_CSS = """
<style>
  body {
    background: #0e1117;
  }

  .swagger-ui {
    color: #e6edf3;
  }

  .swagger-ui .topbar {
    background: #161b22;
    border-bottom: 1px solid #30363d;
  }

  .swagger-ui .topbar .download-url-wrapper .select-label,
  .swagger-ui .info .title,
  .swagger-ui .info p,
  .swagger-ui .info li,
  .swagger-ui .opblock-tag,
  .swagger-ui table thead tr td,
  .swagger-ui table thead tr th,
  .swagger-ui .parameter__name,
  .swagger-ui .parameter__type,
  .swagger-ui .parameter__deprecated,
  .swagger-ui .parameter__in,
  .swagger-ui .response-col_status,
  .swagger-ui .response-col_description,
  .swagger-ui .tab li,
  .swagger-ui label,
  .swagger-ui .model-title,
  .swagger-ui .model,
  .swagger-ui .model-toggle:after,
  .swagger-ui .prop-format,
  .swagger-ui .prop-type,
  .swagger-ui .opblock-summary,
  .swagger-ui .opblock-summary-description,
  .swagger-ui .opblock-summary-path,
  .swagger-ui .opblock-summary-path__deprecated,
  .swagger-ui .opblock-description-wrapper p,
  .swagger-ui .opblock-external-docs-wrapper p,
  .swagger-ui .opblock-title_normal p,
  .swagger-ui .response-col_links,
  .swagger-ui .response-col_description__inner div,
  .swagger-ui .response-col_description__inner p,
  .swagger-ui .markdown p,
  .swagger-ui .markdown code,
  .swagger-ui .renderedMarkdown p,
  .swagger-ui .renderedMarkdown code,
  .swagger-ui .curl-command,
  .swagger-ui .curl-command h4,
  .swagger-ui .request-url,
  .swagger-ui .request-url pre {
    color: #e6edf3;
  }

  .swagger-ui .opblock-summary-path span,
  .swagger-ui .opblock-summary-operation-id,
  .swagger-ui .opblock-summary-path a,
  .swagger-ui .parameters-col_description,
  .swagger-ui .parameters-col_description p,
  .swagger-ui .parameter__enum,
  .swagger-ui .parameter__default,
  .swagger-ui .parameter__example,
  .swagger-ui .responses-header td,
  .swagger-ui .responses-table td,
  .swagger-ui .execute-wrapper,
  .swagger-ui .copy-to-clipboard,
  .swagger-ui .download-contents {
    color: #ffffff !important;
  }

  .swagger-ui .info .title small,
  .swagger-ui .info .title small pre,
  .swagger-ui .scheme-container,
  .swagger-ui .opblock,
  .swagger-ui .model-box,
  .swagger-ui section.models {
    background: #161b22;
    border-color: #30363d;
    box-shadow: none;
  }

  .swagger-ui .opblock .opblock-summary,
  .swagger-ui section.models h4,
  .swagger-ui .responses-inner,
  .swagger-ui .opblock-description-wrapper,
  .swagger-ui .opblock-external-docs-wrapper,
  .swagger-ui .opblock-title_normal {
    border-color: #30363d;
  }

  .swagger-ui .opblock.opblock-get {
    background: rgba(47, 129, 247, 0.13);
    border-color: #2f81f7;
  }

  .swagger-ui .opblock.opblock-post {
    background: rgba(35, 134, 54, 0.13);
    border-color: #238636;
  }

  .swagger-ui .opblock.opblock-put,
  .swagger-ui .opblock.opblock-patch {
    background: rgba(210, 153, 34, 0.13);
    border-color: #d29922;
  }

  .swagger-ui .opblock.opblock-delete {
    background: rgba(248, 81, 73, 0.13);
    border-color: #f85149;
  }

  .swagger-ui input,
  .swagger-ui textarea,
  .swagger-ui select {
    background: #0d1117;
    border-color: #30363d;
    color: #e6edf3;
  }

  .swagger-ui .btn,
  .swagger-ui .btn.authorize {
    background: #21262d;
    border-color: #8b949e;
    color: #e6edf3;
  }

  .swagger-ui .btn.execute {
    background: #238636;
    border-color: #2ea043;
    color: #ffffff;
  }

  .swagger-ui .highlight-code,
  .swagger-ui .microlight,
  .swagger-ui pre,
  .swagger-ui code {
    background: #0d1117 !important;
    color: #e6edf3 !important;
  }

  .swagger-ui .modal-ux {
    background: #161b22;
    border-color: #30363d;
  }

  .swagger-ui .modal-ux-header {
    border-color: #30363d;
  }

  .swagger-ui .modal-ux-content h4,
  .swagger-ui .modal-ux-content p,
  .swagger-ui .auth-container label {
    color: #e6edf3;
  }
</style>
"""


class StatusResponse(BaseModel):
    status: str
    message: str
    data: Optional[Dict] = None


class ReadinessCheck(BaseModel):
    ready: bool
    checks: Dict


class LocationRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude: float = Field(
        ...,
        ge=config.mission.min_altitude,
        le=config.mission.max_altitude,
    )


class WaypointRequest(BaseModel):
    location: LocationRequest
    altitude_frame: Optional[str] = Field(None, pattern="^(relative|terrain)$")


class ArmRequest(BaseModel):
    armed: bool


class TakeoffRequest(BaseModel):
    altitude: float = Field(
        ...,
        ge=config.mission.min_altitude,
        le=config.mission.max_altitude,
    )


class LandRequest(BaseModel):
    pass


class GoToRequest(BaseModel):
    location: LocationRequest


class ModeChangeRequest(BaseModel):
    mode: str = Field(..., min_length=2, max_length=20)

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        allowed_modes = {
            "ACRO",
            "ALT_HOLD",
            "AUTO",
            "BRAKE",
            "GUIDED",
            "LAND",
            "LOITER",
            "POSHOLD",
            "RTL",
            "STABILIZE",
        }
        mode = value.strip().upper()
        if mode not in allowed_modes:
            raise ValueError(f"Unsupported flight mode: {value}")
        return mode


class ObstacleAvoidanceModeRequest(str, Enum):
    DISABLED = "disabled"
    SIMPLE = "simple"
    BENDY_RULER = "bendy_ruler"


class ObstacleAvoidanceSensorSourceRequest(str, Enum):
    MAVLINK = "mavlink"
    GPIO = "gpio"
    ROS = "ros"


class ObstacleAvoidanceCoverageModeRequest(str, Enum):
    FORWARD = "forward"
    SURROUND_360 = "360"


class ObstacleAvoidanceBehaviorRequest(str, Enum):
    STOP = "stop"
    SLIDE = "slide"


class BendyRulerTypeRequest(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class TerrainSourceRequest(str, Enum):
    RANGEFINDER = "rangefinder"
    TERRAIN_DATABASE = "terrain_database"


class ObstacleAvoidanceSensorSettingsRequest(BaseModel):
    source: Optional[ObstacleAvoidanceSensorSourceRequest] = None
    coverage_mode: Optional[ObstacleAvoidanceCoverageModeRequest] = None
    mavlink_sensor_id: Optional[int] = Field(None, ge=0, le=255)
    gpio_pin: Optional[int] = Field(None, ge=0, le=40)
    gpio_active_low: Optional[bool] = None
    ros_enabled: Optional[bool] = None
    ros_backend: Optional[str] = Field(None, max_length=40)
    ros_topic: Optional[str] = Field(None, max_length=120)
    ros_frame_id: Optional[str] = Field(None, max_length=80)
    ros_message_type: Optional[str] = Field(None, max_length=80)


class ObstacleAvoidanceSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[ObstacleAvoidanceModeRequest] = None
    margin_meters: Optional[float] = Field(None, ge=0.0, le=100.0)
    lookahead_meters: Optional[float] = Field(None, gt=0.0, le=500.0)
    backup_speed_mps: Optional[float] = Field(None, ge=0.0, le=20.0)
    min_altitude_meters: Optional[float] = Field(None, ge=0.0, le=config.mission.max_altitude)
    proximity_type: Optional[int] = Field(None, ge=0, le=100)
    behavior: Optional[ObstacleAvoidanceBehaviorRequest] = None
    bendy_ruler_type: Optional[BendyRulerTypeRequest] = None
    obstacle_database_size: Optional[int] = Field(None, ge=0, le=10000)
    sensor: Optional[ObstacleAvoidanceSensorSettingsRequest] = None


class TerrainFollowingSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    source: Optional[TerrainSourceRequest] = None
    min_agl_meters: Optional[float] = Field(None, ge=0.0, le=config.mission.max_altitude)
    max_agl_meters: Optional[float] = Field(None, gt=0.0, le=config.mission.max_altitude)
    target_agl_meters: Optional[float] = Field(None, ge=0.0, le=config.mission.max_altitude)
    use_rangefinder_for_waypoints: Optional[bool] = None
    rtl_terrain_enabled: Optional[bool] = None
    terrain_spacing_meters: Optional[float] = Field(None, gt=0.0, le=1000.0)
    ros_bridge_enabled: Optional[bool] = None
    ros_backend: Optional[str] = Field(None, max_length=40)
    ros_topic: Optional[str] = Field(None, max_length=120)
    mavros_topic: Optional[str] = Field(None, max_length=120)
    ros_frame_id: Optional[str] = Field(None, max_length=80)


class NavigationConfigRequest(BaseModel):
    obstacle_avoidance: Optional[ObstacleAvoidanceSettingsRequest] = None
    terrain_following: Optional[TerrainFollowingSettingsRequest] = None
    apply_to_pixhawk: bool = False


class FlowSensorCalibrationRequest(BaseModel):
    pulses_per_liter: Optional[float] = Field(None, gt=0.0, le=100000.0)


class PressureSensorCalibrationRequest(BaseModel):
    min_voltage: Optional[float] = Field(None, ge=0.0, le=10.0)
    max_voltage: Optional[float] = Field(None, gt=0.0, le=10.0)
    min_psi: Optional[float] = Field(None, ge=0.0, le=10000.0)
    max_psi: Optional[float] = Field(None, gt=0.0, le=10000.0)

    @model_validator(mode="after")
    def validate_ranges(self):
        if (
            self.min_voltage is not None
            and self.max_voltage is not None
            and self.max_voltage <= self.min_voltage
        ):
            raise ValueError("pressure_sensor.max_voltage must be greater than min_voltage")
        if (
            self.min_psi is not None
            and self.max_psi is not None
            and self.max_psi <= self.min_psi
        ):
            raise ValueError("pressure_sensor.max_psi must be greater than min_psi")
        return self


class TankLevelCalibrationRequest(BaseModel):
    min_voltage: Optional[float] = Field(None, ge=0.0, le=10.0)
    max_voltage: Optional[float] = Field(None, gt=0.0, le=10.0)
    capacity_liters: Optional[float] = Field(None, gt=0.0, le=100000.0)
    minimum_level_percent: Optional[float] = Field(None, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def validate_ranges(self):
        if (
            self.min_voltage is not None
            and self.max_voltage is not None
            and self.max_voltage <= self.min_voltage
        ):
            raise ValueError("tank_level_sensor.max_voltage must be greater than min_voltage")
        return self


class TerrainSensorCalibrationRequest(BaseModel):
    min_agl_meters: Optional[float] = Field(None, ge=0.0, le=config.mission.max_altitude)
    max_agl_meters: Optional[float] = Field(None, gt=0.0, le=config.mission.max_altitude)

    @model_validator(mode="after")
    def validate_ranges(self):
        if (
            self.min_agl_meters is not None
            and self.max_agl_meters is not None
            and self.max_agl_meters <= self.min_agl_meters
        ):
            raise ValueError("terrain_sensor.max_agl_meters must be greater than min_agl_meters")
        return self


class CalibrationConfigRequest(BaseModel):
    flow_sensor: Optional[FlowSensorCalibrationRequest] = None
    pressure_sensor: Optional[PressureSensorCalibrationRequest] = None
    tank_level_sensor: Optional[TankLevelCalibrationRequest] = None
    terrain_sensor: Optional[TerrainSensorCalibrationRequest] = None

    @model_validator(mode="after")
    def require_update(self):
        updates = self.model_dump(exclude_none=True)
        if not any(updates.get(group) for group in updates):
            raise ValueError("At least one calibration group is required")
        return self


class ConfigProfileSaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_. -]+$")
    description: Optional[str] = Field(None, max_length=500)
    overwrite: bool = True


class ConfigProfileApplyRequest(BaseModel):
    apply_to_pixhawk: bool = False


class PayloadAction(str, Enum):
    SPRAY_START = "spray_start"
    SPRAY_STOP = "spray_stop"
    PHOTO = "photo"
    RECORD_START = "record_start"
    RECORD_STOP = "record_stop"


class PayloadControlRequest(BaseModel):
    action: PayloadAction
    session: Optional[str] = Field(None, min_length=1, max_length=80)

    @field_validator("session", mode="before")
    @classmethod
    def normalize_session(cls, value) -> Optional[str]:
        if value is None:
            return None

        session = str(value).strip()
        if not session:
            return None

        return session


class PrescriptionImportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    payload_text: str = Field(..., min_length=1)
    source_format: Optional[str] = Field(None, min_length=1, max_length=20)
    activate: bool = True


class PrescriptionActivateRequest(BaseModel):
    map_id: str = Field(..., min_length=1, max_length=120)


class FieldVertex(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


class FieldBoundaryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    vertices: List[FieldVertex] = Field(..., min_length=3)
    altitude: float = Field(
        0.0,
        ge=0.0,
        le=config.mission.max_altitude,
    )


class MappingCameraSpecRequest(BaseModel):
    sensor_width_mm: float = Field(..., gt=0.0, le=100.0)
    sensor_height_mm: float = Field(..., gt=0.0, le=100.0)
    image_width_px: int = Field(..., ge=1, le=50000)
    image_height_px: int = Field(..., ge=1, le=50000)
    focal_length_mm: float = Field(..., gt=0.0, le=200.0)


class TerrainSampleRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    elevation_m: float = Field(..., ge=-1000.0, le=10000.0)


class SurveyGridPlanRequest(BaseModel):
    field_boundary: FieldBoundaryRequest
    camera_spec: MappingCameraSpecRequest
    survey_config: Optional[Dict] = None
    terrain_samples: Optional[List[TerrainSampleRequest]] = None


class GeotagRecordRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=260)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_m: float = Field(..., ge=-1000.0, le=10000.0)
    captured_at: float = Field(..., ge=0.0)
    heading_deg: Optional[float] = Field(None, ge=0.0, le=360.0)
    trigger_timestamp: Optional[float] = Field(None, ge=0.0)
    gps_timestamp: Optional[float] = Field(None, ge=0.0)
    drone_id: Optional[str] = Field(None, max_length=80)


class GeotagExportRequest(BaseModel):
    session: Optional[str] = Field(None, min_length=1, max_length=80)
    records: Optional[List[GeotagRecordRequest]] = None
    gps_time_offset_s: float = Field(0.0, ge=-86400.0, le=86400.0)


class ExifGeotagRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=80)
    overwrite: bool = True
    output_session: Optional[str] = Field(None, min_length=1, max_length=80)


class NdviPreviewRequest(BaseModel):
    session: Optional[str] = Field(None, min_length=1, max_length=80)
    red_filename: Optional[str] = Field(None, min_length=1, max_length=260)
    nir_filename: Optional[str] = Field(None, min_length=1, max_length=260)
    red_band_index: int = Field(default=config.mapping.ndvi_red_band_index, ge=0, le=32)
    nir_band_index: int = Field(default=config.mapping.ndvi_nir_band_index, ge=0, le=32)


class OrthomosaicPreviewRequest(BaseModel):
    session: Optional[str] = Field(None, min_length=1, max_length=80)
    filenames: Optional[List[str]] = None
    limit: int = Field(default=24, ge=1, le=200)
    tile_scale: float = Field(default=config.mapping.orthomosaic_preview_tile_scale, gt=0.0, le=1.0)
    columns: int = Field(default=config.mapping.orthomosaic_preview_max_columns, ge=1, le=24)


class GeoTiffBoundsRequest(BaseModel):
    north: float = Field(..., ge=-90.0, le=90.0)
    south: float = Field(..., ge=-90.0, le=90.0)
    east: float = Field(..., ge=-180.0, le=180.0)
    west: float = Field(..., ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.north <= self.south:
            raise ValueError("north must be greater than south")
        if self.east <= self.west:
            raise ValueError("east must be greater than west")
        return self


class PointCloudScanRequest(BaseModel):
    field_boundary: FieldBoundaryRequest
    scan_config: Optional[Dict] = None


class SprayApplicationRecordRequest(BaseModel):
    field_name: Optional[str] = Field(None, max_length=120)
    product_name: Optional[str] = Field(None, max_length=120)
    product_epa_registration: Optional[str] = Field(None, max_length=80)
    applicator_name: Optional[str] = Field(None, max_length=120)
    applicator_license: Optional[str] = Field(None, max_length=80)
    target_rate: Optional[float] = Field(None, ge=0)
    target_rate_unit: Optional[str] = Field(None, max_length=40)
    weather: Optional[Dict] = None
    notes: Optional[str] = Field(None, max_length=1000)


class WeatherBriefingRequest(BaseModel):
    station_id: Optional[str] = Field(None, min_length=4, max_length=8, pattern=r"^[A-Za-z0-9]{4,8}$")
    metar_raw: Optional[str] = Field(None, max_length=5000)
    taf_raw: Optional[str] = Field(None, max_length=10000)


class EdgeAiScanRequest(BaseModel):
    sample_latest_frame: bool = True


class SprayComplianceReportRequest(BaseModel):
    operator_signature: str = Field(..., min_length=1, max_length=200)
    signed_at: Optional[float] = Field(None, ge=0.0)
    report_format: str = Field(default="epa", pattern="^(epa|faa)$")


class GeofenceZoneRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    zone_type: str = Field(default="no_fly", pattern="^(no_fly|landing_zone|emergency_landing|soft_limit)$")
    polygon: List[Dict[str, float]] = Field(default_factory=list)
    min_altitude_m: Optional[float] = None
    max_altitude_m: Optional[float] = None
    active: bool = True
    metadata: Dict = Field(default_factory=dict)


class RemoteIDRequest(BaseModel):
    enabled: Optional[bool] = None
    broadcast_method: Optional[str] = Field(None, pattern="^(mavlink|none|mock)$")
    operator_id: Optional[str] = Field(None, max_length=120)
    serial_number: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = Field(None, max_length=200)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    altitude_m: Optional[float] = None


class WaiverRequest(BaseModel):
    night_flight_authorized: Optional[bool] = None
    bvlos_authorized: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1000)


class ControlAuthorityRequest(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=80)
    operator: Optional[str] = Field(None, max_length=120)
    force: bool = False
    lease_seconds: Optional[int] = Field(None, ge=5, le=300)


class BaseStationWizardRequest(BaseModel):
    station_id: Optional[str] = Field(None, min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    altitude_m: Optional[float] = None
    antenna_height_m: Optional[float] = Field(None, ge=0.0)
    correction_port: Optional[str] = None
    correction_baudrate: Optional[int] = Field(None, ge=9600)
    mount_type: Optional[str] = Field(None, max_length=80)
    notes: Optional[str] = Field(None, max_length=1000)
    activate: bool = True


class PpkProcessRequest(BaseModel):
    job_id: Optional[str] = Field(None, min_length=1, max_length=80)
    session: Optional[str] = Field(None, min_length=1, max_length=80)
    base_station_id: Optional[str] = Field(None, min_length=1, max_length=80)
    telemetry_window_seconds: Optional[int] = Field(default=600, ge=1, le=86400)
    source_label: Optional[str] = Field(None, min_length=1, max_length=120)
    notes: Optional[str] = Field(None, max_length=1000)
    telemetry_history: Optional[List[Dict]] = None


class FarmExportRequest(BaseModel):
    session: Optional[str] = Field(None, min_length=1, max_length=80)
    report_format: str = Field(default="json", pattern="^(json|isoxml|agleader)$")


class ControlAuthority:
    """Single-controller command lease."""

    def __init__(self, default_lease_seconds: int = 30):
        self.default_lease_seconds = default_lease_seconds
        self._lock = threading.Lock()
        self._session = None

    def _is_active_locked(self) -> bool:
        return bool(self._session and self._session["expires_at"] > time.time())

    def acquire(
        self,
        client_id: str,
        operator: Optional[str] = None,
        force: bool = False,
        lease_seconds: Optional[int] = None,
    ) -> Dict:
        with self._lock:
            if self._is_active_locked() and not force and self._session["client_id"] != client_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Another client currently has command authority.",
                        "authority": self._status_locked(),
                    },
                )

            now = time.time()
            lease = lease_seconds or self.default_lease_seconds
            self._session = {
                "client_id": client_id,
                "operator": operator,
                "token": secrets.token_urlsafe(24),
                "acquired_at": now,
                "renewed_at": now,
                "expires_at": now + lease,
                "lease_seconds": lease,
            }
            return self._status_locked(include_token=True)

    def renew(self, token: str, lease_seconds: Optional[int] = None) -> Dict:
        with self._lock:
            self._require_token_locked(token)
            now = time.time()
            lease = lease_seconds or self._session["lease_seconds"]
            self._session["renewed_at"] = now
            self._session["expires_at"] = now + lease
            self._session["lease_seconds"] = lease
            return self._status_locked(include_token=True)

    def release(self, token: str) -> Dict:
        with self._lock:
            self._require_token_locked(token)
            released = self._status_locked(include_token=False)
            self._session = None
            return released

    def require(self, token: Optional[str]):
        if not config.api.command_authority_enabled:
            return
        with self._lock:
            self._require_token_locked(token)

    def _require_token_locked(self, token: Optional[str]):
        if not self._is_active_locked():
            self._session = None
            raise HTTPException(status_code=423, detail="No active command authority lease.")
        if not token or not hmac.compare_digest(token, self._session["token"]):
            raise HTTPException(status_code=403, detail="Invalid or missing command authority token.")

    def status(self, include_token: bool = False) -> Dict:
        with self._lock:
            return self._status_locked(include_token=include_token)

    def _status_locked(self, include_token: bool = False) -> Dict:
        session = self._session.copy() if self._session else None
        active = bool(session and session["expires_at"] > time.time())
        if not active:
            session = None

        if session and not include_token:
            session.pop("token", None)

        return {
            "enabled": config.api.command_authority_enabled,
            "active": bool(session),
            "authority": session,
        }


class ServerAPI:
    """REST and WebSocket API Server"""

    def __init__(
        self,
        connection_manager,
        mission_planner,
        payload_controller,
        telemetry_manager,
        swarm_manager: Optional[SwarmManager] = None,
        calibration_manager: Optional[CalibrationWorkflowManager] = None,
        farm_manager: Optional[FarmIntegrationManager] = None,
        safety_manager: Optional[SafetyManager] = None,
        weather_service: Optional[WeatherService] = None,
        edge_ai_detector: Optional[EdgeObstacleDetector] = None,
    ):
        self.connection_manager = connection_manager
        self.mission_planner = mission_planner
        self.payload_controller = payload_controller
        self.telemetry_manager = telemetry_manager
        self.swarm_manager = swarm_manager
        if self.swarm_manager is None:
            self.swarm_manager = SwarmManager(
                SwarmDatabase(
                    SwarmDatabaseConfig(
                        path=Path(tempfile.mkdtemp(prefix="swarm-")) / "swarm.sqlite3",
                    )
                ),
                local_state_getter=self.telemetry_manager.get_current,
            )
        self.calibration_manager = calibration_manager or CalibrationWorkflowManager(
            CalibrationWorkflowConfig(
                database_file=Path(tempfile.mkdtemp(prefix="calibration-")) / "workflow.sqlite3",
            ),
            telemetry_history_getter=self.telemetry_manager.get_history,
        )
        self.farm_manager = farm_manager or FarmIntegrationManager(
            FarmIntegrationConfig(
                enabled=False,
                database_file=Path(tempfile.mkdtemp(prefix="farm-")) / "integration.sqlite3",
                isoxml_output_directory=Path(tempfile.mkdtemp(prefix="isoxml-")),
                report_output_directory=Path(tempfile.mkdtemp(prefix="reports-")),
            ),
            payload_controller=self.payload_controller,
            telemetry_manager=self.telemetry_manager,
            swarm_manager=self.swarm_manager,
            calibration_manager=self.calibration_manager,
        )
        self.safety_manager = safety_manager or SafetyManager(
            config.safety,
            connection_manager=self.connection_manager,
            telemetry_manager=self.telemetry_manager,
        )
        self.weather_service = weather_service or WeatherService(config.weather)
        self.edge_ai_detector = edge_ai_detector or (
            EdgeObstacleDetector(
                config.edge_ai,
                frame_getter=self._get_latest_camera_frame,
            )
            if getattr(self.payload_controller, "camera", None)
            else None
        )
        if self.edge_ai_detector and config.edge_ai.enabled:
            try:
                self.edge_ai_detector.initialize()
            except Exception as exc:
                logger.warning("Failed to initialize edge AI detector: %s", exc)
        self.active_websocket_clients: Set[WebSocket] = set()
        self.active_event_websocket_clients: Set[WebSocket] = set()
        self.command_event_subscribers: Dict[str, Callable[[Dict], object]] = {}
        self.command_event_lock = threading.Lock()
        self.idempotency_records: Dict[str, Dict] = {}
        self.idempotency_lock = threading.Lock()
        self.audit_logger = AuditLogger(
            config.api.audit_log_file,
            max_bytes=config.api.audit_log_max_bytes,
            backup_count=config.api.audit_log_backup_count,
        )
        self.config_profiles = ConfigProfileStore(config.api.config_database_file)
        self.geotiff_assets = GeoTiffAssetStore(
            GeoTiffAssetConfig(
                database_file=Path(config.storage.geotiff_database_file),
                asset_directory=Path(config.storage.geotiff_asset_directory),
            )
        )
        self.control_authority = ControlAuthority(config.api.command_authority_lease_seconds)

        self.app = FastAPI(
            title="Agricultural Drone Companion API",
            description=(
                "REST and WebSocket control surface for the Raspberry Pi companion "
                "computer. Swagger UI is available at /docs."
            ),
            version="1.0.0",
            docs_url=None,
            redoc_url="/redoc",
            openapi_url="/openapi.json",
            generate_unique_id_function=clean_openapi_operation_id,
        )
        self._setup_middleware()
        self._setup_routes()
        self._setup_versioned_api_aliases()
        if getattr(self.telemetry_manager, "collector", None):
            try:
                self.telemetry_manager.collector.register_callback(self.safety_manager.register_telemetry_point)
                self.telemetry_manager.collector.register_callback(
                    lambda point: self.swarm_manager.ingest_local_snapshot(point.to_dict())
                    if self.swarm_manager
                    else None
                )
            except Exception:
                pass

        if config.api.auth_enabled and not self._configured_api_key_roles():
            logger.warning("API authentication is enabled, but no API keys are configured.")

    def _setup_middleware(self):
        """Setup CORS and other middleware"""

        @self.app.middleware("http")
        async def idempotency_middleware(request: Request, call_next):
            return await self._handle_idempotent_request(request, call_next)

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=config.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _get_idempotency_key(self, request: Request) -> Optional[str]:
        for header_name in IDEMPOTENCY_HEADER_NAMES:
            key = request.headers.get(header_name)
            if key and key.strip():
                return key.strip()
        return None

    def _idempotency_cache_id(self, request: Request, idempotency_key: str) -> str:
        supplied_key = request.headers.get("x-api-key") or request.query_params.get("api_key") or ""
        api_key_hash = hashlib.sha256(supplied_key.encode()).hexdigest()
        return hashlib.sha256(f"{api_key_hash}:{idempotency_key}".encode()).hexdigest()

    def _idempotency_fingerprint(self, request: Request, body: bytes) -> str:
        body_hash = hashlib.sha256(body).hexdigest()
        fingerprint = "\n".join(
            [
                request.method.upper(),
                request.url.path,
                request.url.query,
                body_hash,
            ]
        )
        return hashlib.sha256(fingerprint.encode()).hexdigest()

    def _prune_idempotency_records(self):
        now = time.time()
        expired_keys = [
            cache_id
            for cache_id, record in self.idempotency_records.items()
            if record["expires_at"] <= now
        ]
        for cache_id in expired_keys:
            self.idempotency_records.pop(cache_id, None)

    def _get_idempotency_record(self, cache_id: str) -> Optional[Dict]:
        with self.idempotency_lock:
            self._prune_idempotency_records()
            return self.idempotency_records.get(cache_id)

    def _store_idempotency_record(
        self,
        cache_id: str,
        fingerprint: str,
        response: Response,
        body: bytes,
    ):
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding"}
        }
        with self.idempotency_lock:
            self._prune_idempotency_records()
            self.idempotency_records[cache_id] = {
                "fingerprint": fingerprint,
                "status_code": response.status_code,
                "headers": headers,
                "body": body,
                "media_type": response.media_type,
                "expires_at": time.time() + config.api.idempotency_ttl_seconds,
            }

    def _build_idempotency_replay_response(self, record: Dict) -> Response:
        headers = dict(record["headers"])
        headers["x-idempotency-status"] = "replayed"
        return Response(
            content=record["body"],
            status_code=record["status_code"],
            headers=headers,
            media_type=record["media_type"],
        )

    async def _handle_idempotent_request(self, request: Request, call_next):
        if request.method.upper() not in IDEMPOTENT_HTTP_METHODS:
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        idempotency_key = self._get_idempotency_key(request)
        if not idempotency_key:
            return await call_next(request)
        if len(idempotency_key) > 200:
            return JSONResponse(
                status_code=400,
                content={"detail": "Idempotency key must be 200 characters or fewer."},
            )

        body = await request.body()
        async def receive_body():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive_body
        cache_id = self._idempotency_cache_id(request, idempotency_key)
        fingerprint = self._idempotency_fingerprint(request, body)
        record = self._get_idempotency_record(cache_id)
        if record:
            if record["fingerprint"] != fingerprint:
                return JSONResponse(
                    status_code=409,
                    headers={"x-idempotency-status": "conflict"},
                    content={
                        "detail": "Idempotency key was already used for a different request."
                    },
                )
            return self._build_idempotency_replay_response(record)

        response = await call_next(request)
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        self._store_idempotency_record(cache_id, fingerprint, response, response_body)
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding"}
        }
        headers["x-idempotency-status"] = "stored"
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    def _coerce_api_role(self, role: str) -> ApiRole:
        try:
            return ApiRole((role or "").strip().lower())
        except ValueError:
            raise HTTPException(status_code=503, detail=f"Invalid API role configured: {role}.")

    def _configured_api_key_roles(self) -> Dict[str, str]:
        api_key_roles = dict(config.api.api_key_roles or {})
        if config.api.api_key and config.api.api_key not in api_key_roles:
            api_key_roles[config.api.api_key] = config.api.api_key_role
        return api_key_roles

    def _api_key_id(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()[:12]

    def _set_auth_context(
        self,
        principal: AuthenticatedPrincipal,
        request: Optional[Request] = None,
    ) -> AuthenticatedPrincipal:
        api_auth_context.set(principal)
        if request is not None and hasattr(request, "state"):
            request.state.auth = principal
        return principal

    def _require_api_key(
        self,
        request: Request,
        api_key: Optional[str] = Security(api_key_header),
    ):
        """Validate the shared API key for control endpoints."""
        return self._require_api_key_value(api_key, request=request)

    def _require_api_key_header_or_query(
        self,
        request: Request,
        api_key: Optional[str] = Security(api_key_header),
    ):
        """Validate API key supplied by header or query parameter."""
        return self._require_api_key_value(
            api_key or request.query_params.get("api_key"),
            request=request,
        )

    def _require_api_key_value(
        self,
        api_key: Optional[str],
        request: Optional[Request] = None,
    ) -> AuthenticatedPrincipal:
        """Validate a supplied shared API key."""
        if not config.api.auth_enabled:
            return self._set_auth_context(
                AuthenticatedPrincipal(role=ApiRole.ADMIN),
                request=request,
            )

        api_key_roles = self._configured_api_key_roles()
        if not api_key_roles:
            raise HTTPException(
                status_code=503,
                detail="No API keys are configured on the companion computer.",
            )

        for configured_key, role in api_key_roles.items():
            if api_key and hmac.compare_digest(api_key, configured_key):
                return self._set_auth_context(
                    AuthenticatedPrincipal(
                        role=self._coerce_api_role(role),
                        api_key_id=self._api_key_id(configured_key),
                    ),
                    request=request,
                )

        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    def _require_roles(
        self,
        allowed_roles: Set[ApiRole],
        principal: Optional[AuthenticatedPrincipal] = None,
    ) -> Optional[AuthenticatedPrincipal]:
        if not config.api.auth_enabled:
            return principal or AuthenticatedPrincipal(role=ApiRole.ADMIN)

        principal = principal or api_auth_context.get()
        if principal is None:
            return None
        if principal.role not in allowed_roles:
            allowed = ", ".join(sorted(role.value for role in allowed_roles))
            raise HTTPException(
                status_code=403,
                detail=f"API role '{principal.role.value}' is not allowed. Required role: {allowed}.",
            )
        return principal

    def _require_audit_role(
        self,
        request: Request,
        api_key: Optional[str] = Security(api_key_header),
    ):
        principal = self._require_api_key_value(api_key, request=request)
        return self._require_roles(AUDIT_ROLES, principal)

    def _require_command_role(self, allowed_roles: Set[ApiRole] = COMMAND_ROLES):
        self._require_roles(allowed_roles)

    def _require_success(self, succeeded: bool, error_message: str, status_code: int = 409):
        if not succeeded:
            raise HTTPException(status_code=status_code, detail=error_message)

    def _get_navigation_config(self) -> Dict:
        if hasattr(self.mission_planner, "get_navigation_config"):
            return self.mission_planner.get_navigation_config()
        return {
            "obstacle_avoidance": {},
            "terrain_following": {},
        }

    def _get_navigation_status(self) -> Dict:
        if hasattr(self.connection_manager, "get_navigation_status"):
            return self.connection_manager.get_navigation_status()
        return {}

    def _get_connection_status(self) -> Dict:
        if hasattr(self.connection_manager, "get_connection_status"):
            return self.connection_manager.get_connection_status()
        connected = bool(getattr(self.connection_manager, "connected", False))
        return {
            "state": "connected" if connected else "offline",
            "connected": connected,
            "monitoring": False,
            "reconnecting": False,
            "retry_backoff_seconds": 0.0,
            "max_retry_backoff_seconds": 0.0,
            "last_changed_at": None,
            "last_error": None,
        }

    def _get_navigation_sensor_status(self) -> Dict:
        status = self._get_navigation_status()
        return {
            "obstacle_avoidance": status.get("obstacle_avoidance", {}).get("sensor", {}),
            "terrain_following": status.get("terrain_following", {}).get("terrain", {}),
            "distance_sensors": status.get("distance_sensors", []),
        }

    def _current_swarm_snapshot(self) -> Dict:
        snapshot = self.telemetry_manager.get_current() or {}
        if not snapshot and hasattr(self.connection_manager, "get_vehicle_state"):
            snapshot = self.connection_manager.get_vehicle_state() or {}
        return snapshot

    def _get_latest_camera_frame(self):
        camera = getattr(self.payload_controller, "camera", None)
        if not camera:
            return None
        if hasattr(camera, "get_latest_frame"):
            return camera.get_latest_frame()
        if hasattr(camera, "_get_latest_frame"):
            return camera._get_latest_frame()
        return None

    def _swarm_manager_or_none(self) -> Optional[SwarmManager]:
        return getattr(self, "swarm_manager", None)

    def _swarm_config_data(self) -> Dict:
        manager = self._swarm_manager_or_none()
        if not manager:
            raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
        return manager.get_config()

    def _swarm_status_data(self) -> Dict:
        manager = self._swarm_manager_or_none()
        if not manager:
            raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
        return manager.get_status()

    def _swarm_fusion_state_data(self) -> Dict:
        manager = self._swarm_manager_or_none()
        if not manager:
            raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
        state = manager.get_fusion_state()
        if state is None:
            return manager.recompute_fusion()
        return state

    def _swarm_telemetry_data(self, seconds: Optional[int] = None, limit: Optional[int] = None) -> Dict:
        manager = self._swarm_manager_or_none()
        if not manager:
            raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
        return {"samples": manager.get_telemetry(seconds=seconds, limit=limit)}

    def _swarm_alert_data(self, seconds: Optional[int] = None, limit: Optional[int] = None) -> Dict:
        manager = self._swarm_manager_or_none()
        if not manager:
            raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
        return {"alerts": manager.get_alerts(seconds=seconds, limit=limit)}

    def _swarm_coordination_data(self) -> Dict:
        manager = self._swarm_manager_or_none()
        if not manager:
            raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
        return manager.get_coordination_status()

    def _calibration_status_data(self) -> Dict:
        if not self.calibration_manager:
            raise HTTPException(status_code=503, detail="Calibration workflows are unavailable.")
        return self.calibration_manager.get_status()

    def _farm_status_data(self) -> Dict:
        if not self.farm_manager:
            raise HTTPException(status_code=503, detail="Farm management integration is unavailable.")
        return self.farm_manager.get_status()

    def _fleet_status_data(self) -> Dict:
        manager = self._swarm_manager_or_none()
        if not manager:
            raise HTTPException(status_code=503, detail="Swarm management is unavailable.")

        config = manager.get_config()
        telemetry_samples = manager.get_telemetry(limit=500)
        latest_by_drone: Dict[str, Dict] = {}
        for sample in telemetry_samples:
            drone_id = sample.get("source_drone_id")
            if not drone_id or drone_id in latest_by_drone:
                continue
            latest_by_drone[drone_id] = sample

        local_snapshot = self._current_swarm_snapshot()
        self_drone_id = config.get("self_drone_id")
        if self_drone_id and self_drone_id not in latest_by_drone and local_snapshot:
            latest_by_drone[self_drone_id] = {
                "source_drone_id": self_drone_id,
                "timestamp": local_snapshot.get("timestamp") or time.time(),
                "location": {
                    "latitude": (local_snapshot.get("location") or {}).get("latitude"),
                    "longitude": (local_snapshot.get("location") or {}).get("longitude"),
                    "altitude": (local_snapshot.get("location") or {}).get("altitude"),
                },
                "velocity": {
                    "ground_speed_mps": local_snapshot.get("ground_speed"),
                    "heading_deg": local_snapshot.get("heading"),
                },
                "vehicle": {
                    "armed": local_snapshot.get("armed"),
                    "mode": local_snapshot.get("mode"),
                },
            }

        drones = []
        peer_entries = config.get("peers", []) or []
        peer_lookup = {peer.get("drone_id"): peer for peer in peer_entries if peer.get("drone_id")}
        for peer in peer_entries:
            drone_id = peer.get("drone_id")
            sample = latest_by_drone.get(drone_id, {})
            location = sample.get("location") or {}
            velocity = sample.get("velocity") or {}
            vehicle = sample.get("vehicle") or {}
            drones.append(
                {
                    "drone_id": drone_id,
                    "callsign": peer.get("callsign"),
                    "role": peer.get("role"),
                    "transport": peer.get("transport"),
                    "capabilities": peer.get("capabilities", []),
                    "trust": peer.get("trust"),
                    "status": "active" if sample else peer.get("status") or "staged",
                    "last_heartbeat": peer.get("last_heartbeat"),
                    "last_seen_at": sample.get("timestamp"),
                    "position": {
                        "latitude": location.get("latitude"),
                        "longitude": location.get("longitude"),
                        "altitude": location.get("altitude"),
                        "heading": velocity.get("heading_deg"),
                    }
                    if location.get("latitude") is not None and location.get("longitude") is not None
                    else None,
                    "vehicle": vehicle or None,
                    "sample_id": sample.get("sample_id"),
                    "sequence": sample.get("sequence"),
                }
            )

        if self_drone_id and self_drone_id not in peer_lookup:
            sample = latest_by_drone.get(self_drone_id)
            if sample:
                location = sample.get("location") or {}
                velocity = sample.get("velocity") or {}
                drones.insert(
                    0,
                    {
                        "drone_id": self_drone_id,
                        "callsign": "Companion",
                        "role": config.get("role"),
                        "transport": config.get("transport"),
                        "capabilities": ["telemetry", "mission"],
                        "trust": "primary",
                        "status": "active",
                        "last_heartbeat": None,
                        "last_seen_at": sample.get("timestamp"),
                        "position": {
                            "latitude": location.get("latitude"),
                            "longitude": location.get("longitude"),
                            "altitude": location.get("altitude"),
                            "heading": velocity.get("heading_deg"),
                        },
                        "vehicle": sample.get("vehicle") or None,
                        "sample_id": sample.get("sample_id"),
                        "sequence": sample.get("sequence"),
                    },
                )

        active_drones = [drone for drone in drones if drone.get("status") == "active"]
        return {
            "fleet_id": config.get("swarm_id"),
            "self_drone_id": self_drone_id,
            "enabled": bool(config.get("enabled")),
            "peer_count": len(peer_entries),
            "active_drone_count": len(active_drones),
            "drones": drones,
            "fusion": self._swarm_fusion_state_data(),
            "status": self._swarm_status_data(),
            "updated_at": time.time(),
        }

    def _prescription_status_data(self) -> Dict:
        if not self.payload_controller:
            raise HTTPException(status_code=503, detail="Payload management is unavailable.")
        return self.payload_controller.get_prescription_status()

    def _prescription_maps_data(self) -> Dict:
        if not self.payload_controller:
            raise HTTPException(status_code=503, detail="Payload management is unavailable.")
        return {
            "maps": self.payload_controller.list_prescription_maps(),
            "status": self.payload_controller.get_prescription_status(),
        }

    def _weather_status_data(self) -> Dict:
        return self.weather_service.get_status() if self.weather_service else {"enabled": False}

    def _edge_ai_status_data(self) -> Dict:
        if not self.edge_ai_detector:
            return {"enabled": False, "available": False}
        return self.edge_ai_detector.get_status()

    def _current_safety_snapshot(self) -> Dict:
        snapshot = self.telemetry_manager.get_current() or {}
        if not snapshot and hasattr(self.connection_manager, "get_vehicle_state"):
            snapshot = self.connection_manager.get_vehicle_state() or {}
        return snapshot

    def _current_safety_evaluation(self) -> Dict:
        if not self.safety_manager:
            return {}
        return self.safety_manager.evaluate_snapshot(self._current_safety_snapshot())

    def _geofence_zone_from_request(self, request: GeofenceZoneRequest) -> GeofenceZone:
        return GeofenceZone(
            name=request.name,
            zone_type=request.zone_type,
            polygon=request.polygon,
            min_altitude_m=request.min_altitude_m,
            max_altitude_m=request.max_altitude_m,
            active=request.active,
            metadata=request.metadata,
        )

    def _mapping_camera_spec(self) -> CameraSpec:
        return CameraSpec(
            sensor_width_mm=config.mapping.camera_sensor_width_mm,
            sensor_height_mm=config.mapping.camera_sensor_height_mm,
            image_width_px=config.mapping.camera_image_width_px,
            image_height_px=config.mapping.camera_image_height_px,
            focal_length_mm=config.mapping.camera_focal_length_mm,
        )

    def _mapping_planner(self) -> MappingPlanner:
        return MappingPlanner(self._mapping_camera_spec())

    def _preview_image_from_geotiff(self, source_bytes: bytes, max_preview_size: int) -> tuple[bytes, Dict]:
        if Image is None:
            raise HTTPException(status_code=503, detail="Pillow is required for GeoTIFF previews.")

        try:
            with Image.open(io.BytesIO(source_bytes)) as image:
                if image.format not in {"TIFF", "TIF"}:
                    raise HTTPException(status_code=415, detail="Only GeoTIFF/TIFF images are supported.")

                width, height = image.size
                scale = min(1.0, float(max_preview_size) / float(max(width, height)))
                if scale < 1.0:
                    preview_size = (max(1, int(width * scale)), max(1, int(height * scale)))
                    preview = image.convert("RGB").resize(preview_size, Image.Resampling.LANCZOS)
                else:
                    preview = image.convert("RGB")

                preview_array = np.asarray(preview)
                if preview_array.ndim == 2:
                    preview_array = cv2.cvtColor(preview_array, cv2.COLOR_GRAY2RGB)

                return self._image_to_png_bytes(preview_array), {
                    "source_width_px": width,
                    "source_height_px": height,
                    "preview_width_px": int(preview_array.shape[1]),
                    "preview_height_px": int(preview_array.shape[0]),
                }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read GeoTIFF: {exc}") from exc

    def _geotiff_asset_response(self, asset: Dict) -> Dict:
        return {
            "asset_id": asset["asset_id"],
            "name": asset["name"],
            "source_filename": asset["source_filename"],
            "bounds": asset["bounds"],
            "source_width_px": asset["source_width_px"],
            "source_height_px": asset["source_height_px"],
            "preview_width_px": asset["preview_width_px"],
            "preview_height_px": asset["preview_height_px"],
            "source_size_bytes": asset["source_size_bytes"],
            "mime_type": asset["mime_type"],
            "created_at": asset["created_at"],
            "updated_at": asset["updated_at"],
            "preview_url": f"/api/mapping/geotiff/{asset['asset_id']}/preview",
        }

    def _field_boundary_from_request(self, request: FieldBoundaryRequest):
        from ..missions.planner import FieldBoundary, GeoPoint

        vertices = [GeoPoint(vertex.latitude, vertex.longitude) for vertex in request.vertices]
        return FieldBoundary(request.name, vertices, request.altitude)

    def _resolve_photo_path(self, session: Optional[str], filename: str) -> Optional[Path]:
        if not self.payload_controller.camera:
            return None
        return self.payload_controller.camera.get_photo_path(filename, session=session)

    def _photo_to_geotag_record(self, photo: Dict) -> Optional[GeotagRecord]:
        geotag = photo.get("geotag") or {}
        location = geotag.get("location") or {}
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if latitude is None or longitude is None:
            return None

        captured_at = (
            geotag.get("captured_at")
            or photo.get("captured_at")
            or photo.get("camera_trigger", {}).get("triggered_at")
            or time.time()
        )
        trigger_timestamp = photo.get("camera_trigger", {}).get("triggered_at")
        return GeotagRecord(
            filename=photo.get("filename", ""),
            latitude=float(latitude),
            longitude=float(longitude),
            altitude_m=float(location.get("altitude") or 0.0),
            captured_at=float(captured_at),
            heading_deg=geotag.get("heading"),
            trigger_timestamp=float(trigger_timestamp) if trigger_timestamp is not None else None,
            gps_timestamp=float(geotag.get("captured_at")) if geotag.get("captured_at") is not None else None,
            drone_id=photo.get("drone_id") or photo.get("session"),
        )

    def _camera_session_geotag_records(self, session: str) -> List[GeotagRecord]:
        if not self.payload_controller.camera:
            raise HTTPException(status_code=503, detail="Camera not available.")

        manifest = self.payload_controller.camera.get_session_manifest(session)
        if not manifest:
            raise HTTPException(status_code=404, detail="Photo session not found.")

        records: List[GeotagRecord] = []
        for photo in manifest.get("photos", []):
            record = self._photo_to_geotag_record(photo)
            if record is not None:
                records.append(record)
        if not records:
            raise HTTPException(status_code=404, detail="No geotagged photos found in the session.")
        return records

    def _resolve_geotag_export_records(self, request: GeotagExportRequest) -> List[GeotagRecord]:
        if request.records:
            return [GeotagRecord(**record.model_dump()) for record in request.records]
        if request.session:
            return self._camera_session_geotag_records(request.session)
        raise HTTPException(status_code=400, detail="Provide records or a photo session.")

    def _build_terrain_elevation_fn(self, terrain_samples: Optional[List[TerrainSampleRequest]], default_elevation: Optional[float] = None):
        samples = terrain_samples or []
        if not samples:
            if default_elevation is None:
                return None

            def _constant_elevation(_latitude: float, _longitude: float) -> float:
                return float(default_elevation)

            return _constant_elevation

        sample_points = [
            (sample.latitude, sample.longitude, sample.elevation_m)
            for sample in samples
        ]

        def _nearest_elevation(latitude: float, longitude: float) -> float:
            nearest = min(
                sample_points,
                key=lambda sample: (sample[0] - latitude) ** 2 + (sample[1] - longitude) ** 2,
            )
            return float(nearest[2])

        return _nearest_elevation

    def _image_to_png_bytes(self, image_array) -> bytes:
        success, encoded = cv2.imencode(".png", image_array)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to encode image preview.")
        return encoded.tobytes()

    def _get_calibration_config(self) -> Dict:
        if hasattr(self.payload_controller, "get_calibration_config"):
            return self.payload_controller.get_calibration_config()
        return {}

    def _update_calibration_config(self, calibration: Dict) -> Dict:
        if not hasattr(self.payload_controller, "update_calibration_config"):
            raise HTTPException(status_code=503, detail="Calibration updates are not available.")
        return self.payload_controller.update_calibration_config(calibration)

    def _serialize_config_value(self, value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {
                key: self._serialize_config_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._serialize_config_value(item) for item in value]
        return value

    def _serialize_dataclass_config(self, config_section) -> Dict:
        if not is_dataclass(config_section):
            return {}
        return {
            field.name: self._serialize_config_value(getattr(config_section, field.name))
            for field in fields(config_section)
        }

    def _current_config_snapshot(self) -> Dict:
        return {
            "runtime": {
                "environment": config.environment,
                "log_level": config.log_level,
            },
            "mavlink": self._serialize_dataclass_config(config.mavlink),
            "api": self._serialize_dataclass_config(config.api),
            "payload": self._serialize_dataclass_config(config.payload),
            "mission": self._serialize_dataclass_config(config.mission),
            "telemetry": self._serialize_dataclass_config(config.telemetry),
            "navigation": self._get_navigation_config(),
            "calibration": self._get_calibration_config(),
        }

    def _coerce_config_value(self, current_value, new_value):
        if isinstance(current_value, Enum):
            return type(current_value)(new_value)
        return new_value

    def _apply_dataclass_config(self, target, values: Dict) -> List[str]:
        if not is_dataclass(target):
            return []

        applied_fields = []
        valid_fields = {field.name for field in fields(target)}
        for field_name, value in (values or {}).items():
            if field_name not in valid_fields:
                continue
            current_value = getattr(target, field_name)
            setattr(target, field_name, self._coerce_config_value(current_value, value))
            applied_fields.append(field_name)

        return applied_fields

    def _apply_config_snapshot(self, configuration: Dict, apply_to_pixhawk: bool = False) -> Dict:
        applied = {}
        restart_recommended = []

        for section_name, target in (
            ("mavlink", config.mavlink),
            ("api", config.api),
            ("payload", config.payload),
            ("mission", config.mission),
            ("telemetry", config.telemetry),
        ):
            if section_name not in configuration:
                continue
            applied_fields = self._apply_dataclass_config(target, configuration.get(section_name) or {})
            applied[section_name] = applied_fields
            if applied_fields:
                restart_recommended.append(section_name)

        runtime_config = configuration.get("runtime") or {}
        runtime_applied = []
        if "environment" in runtime_config:
            config.environment = runtime_config["environment"]
            runtime_applied.append("environment")
        if "log_level" in runtime_config:
            config.log_level = runtime_config["log_level"]
            runtime_applied.append("log_level")
        if runtime_applied:
            applied["runtime"] = runtime_applied
            restart_recommended.append("runtime")

        if "api" in applied:
            self.audit_logger = AuditLogger(
                config.api.audit_log_file,
                max_bytes=config.api.audit_log_max_bytes,
                backup_count=config.api.audit_log_backup_count,
            )
            self.config_profiles = ConfigProfileStore(config.api.config_database_file)

        navigation_result = None
        pixhawk_apply_result = None
        navigation_config = configuration.get("navigation")
        if navigation_config:
            navigation_result = self.mission_planner.update_navigation_config(
                obstacle_avoidance=navigation_config.get("obstacle_avoidance"),
                terrain_following=navigation_config.get("terrain_following"),
            )
            applied["navigation"] = sorted(navigation_config.keys())
            if apply_to_pixhawk:
                pixhawk_apply_result = self.connection_manager.apply_navigation_config(navigation_result)
                self._require_success(
                    pixhawk_apply_result.get("success"),
                    "Configuration profile applied, but Pixhawk parameter application failed.",
                )

        calibration_result = None
        calibration_config = configuration.get("calibration")
        if calibration_config:
            calibration_result = self._update_calibration_config(calibration_config)
            applied["calibration"] = sorted(calibration_config.keys())

        return {
            "applied": applied,
            "navigation": navigation_result,
            "calibration": calibration_result,
            "pixhawk_apply_result": pixhawk_apply_result,
            "restart_recommended": sorted(set(restart_recommended)),
        }

    def _get_readiness_data(self) -> Dict:
        vehicle_state = self.connection_manager.get_vehicle_state()
        prearm_status = self.connection_manager.get_prearm_status()
        payload_status = self.payload_controller.get_payload_status()
        navigation_config = self._get_navigation_config()
        navigation_status = self._get_navigation_status()
        obstacle_config = navigation_config.get("obstacle_avoidance", {})
        terrain_config = navigation_config.get("terrain_following", {})
        obstacle_status = (navigation_status.get("obstacle_avoidance") or {}).get("sensor") or {}
        weather_status = self._weather_status_data()
        edge_ai_status = self._edge_ai_status_data()

        photo_directory = None
        storage = None
        if self.payload_controller.camera:
            photo_directory = str(self.payload_controller.camera.photo_directory)
            try:
                usage = shutil.disk_usage(photo_directory)
                storage = {
                    "path": photo_directory,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                }
            except OSError as e:
                storage = {"path": photo_directory, "error": str(e)}

        checks = {
            "pixhawk_connected": bool(self.connection_manager.connected),
            "pixhawk_connection": self._get_connection_status(),
            "vehicle_status_available": bool(vehicle_state),
            "gps": (prearm_status or {}).get("gps"),
            "ekf_ok": (prearm_status or {}).get("ekf_ok"),
            "is_armable": (prearm_status or {}).get("is_armable"),
            "last_status_text": (prearm_status or {}).get("last_status_text"),
            "prearm_messages": (prearm_status or {}).get("prearm_messages", []),
            "camera_expected": config.payload.camera_enabled,
            "camera_available": bool(
                self.payload_controller.camera
                and self.payload_controller.camera.is_available()
            ),
            "camera_trigger_expected": config.payload.camera_trigger_enabled,
            "camera_trigger_available": bool(self.payload_controller.camera_trigger),
            "flow_sensor_expected": config.payload.flow_sensor_enabled,
            "flow_sensor_available": bool(self.payload_controller.flow_sensor),
            "pressure_sensor_expected": config.payload.pressure_sensor_enabled,
            "pressure_sensor_available": bool(self.payload_controller.pressure_sensor),
            "tank_level_sensor_expected": config.payload.tank_level_sensor_enabled,
            "tank_level_sensor_available": bool(self.payload_controller.tank_level_sensor),
            "tank_level": payload_status.get("tank_level_sensor"),
            "rtk_expected": config.payload.rtk_enabled,
            "ppk_expected": config.payload.ppk_enabled,
            "obstacle_avoidance_expected": bool(obstacle_config.get("enabled")),
            "terrain_following_expected": bool(
                config.payload.terrain_following_enabled or terrain_config.get("enabled")
            ),
            "weather_expected": bool(config.weather.enabled and config.weather.station_id),
            "weather_status": weather_status,
            "weather_briefing": (weather_status.get("last_briefing") if weather_status else None),
            "edge_ai_expected": bool(config.edge_ai.enabled),
            "edge_ai_status": edge_ai_status,
            "navigation_config": navigation_config,
            "navigation_status": navigation_status,
            "obstacle_avoidance_sensor": obstacle_status,
            "terrain": (prearm_status or {}).get("terrain"),
            "spray_pump_status": payload_status.get("spray_pump", {}).get("status"),
            "storage": storage,
            "auth_enabled": config.api.auth_enabled,
            "api_key_configured": bool(self._configured_api_key_roles()),
            "safety_gates_enabled": config.api.safety_gates_enabled,
            "telemetry_freshness_enabled": config.api.telemetry_freshness_enabled,
            "telemetry_last_update": getattr(self.telemetry_manager, "last_update", 0),
            "telemetry_stale_seconds": config.api.telemetry_stale_seconds,
            "safety_status": self.safety_manager.get_status() if self.safety_manager else {},
        }
        last_update = checks["telemetry_last_update"]
        checks["telemetry_age_seconds"] = time.time() - last_update if last_update else None
        checks["blocking_reasons"] = self._get_readiness_blockers(checks)
        return ReadinessCheck(ready=not checks["blocking_reasons"], checks=checks).model_dump()

    def _get_readiness_blockers(self, checks: Dict) -> List[str]:
        blocking_reasons = []
        blocking_reasons.extend(self._get_navigation_blockers(checks, include_armable=True))
        blocking_reasons.extend(self._get_camera_blockers(checks))
        blocking_reasons.extend(self._get_payload_readiness_blockers(checks))
        blocking_reasons.extend(self._get_weather_blockers(checks))
        blocking_reasons.extend(self._get_system_blockers(checks))
        blocking_reasons.extend(self._get_companion_safety_blockers(checks))
        telemetry_age = checks.get("telemetry_age_seconds")
        if (
            config.api.telemetry_freshness_enabled
            and (telemetry_age is None or telemetry_age > config.api.telemetry_stale_seconds)
        ):
            blocking_reasons.append("Vehicle telemetry is stale or unavailable.")
        return blocking_reasons

    def _get_navigation_blockers(self, checks: Dict, include_armable: bool = False) -> List[str]:
        gps = checks["gps"] or {}
        blocking_reasons = []
        if not checks["pixhawk_connected"]:
            connection_state = (checks.get("pixhawk_connection") or {}).get("state")
            if connection_state == "reconnecting":
                blocking_reasons.append("Pixhawk is reconnecting.")
            else:
                blocking_reasons.append("Pixhawk is not connected.")
        if not checks["vehicle_status_available"]:
            blocking_reasons.append("Vehicle status is unavailable.")
        if include_armable and checks["is_armable"] is False:
            blocking_reasons.append("Vehicle is not armable.")
        if checks["ekf_ok"] is False:
            blocking_reasons.append("EKF is not healthy.")
        if gps and gps.get("fix_type", 0) < 3:
            blocking_reasons.append("GPS does not have a 3D fix.")
        blocking_reasons.extend(self._get_obstacle_avoidance_blockers(checks))
        blocking_reasons.extend(self._get_terrain_following_blockers(checks))
        return blocking_reasons

    def _get_obstacle_avoidance_blockers(self, checks: Dict) -> List[str]:
        blocking_reasons = []
        obstacle_config = (checks.get("navigation_config") or {}).get("obstacle_avoidance", {})
        obstacle_status = checks.get("obstacle_avoidance_sensor") or {}
        if checks["obstacle_avoidance_expected"]:
            source = obstacle_config.get("sensor", {}).get("source", "mavlink")
            if source == "mavlink" and not obstacle_status.get("available"):
                blocking_reasons.append("Obstacle avoidance is enabled but obstacle sensor data is unavailable.")
            if source == "gpio" and not obstacle_status.get("available"):
                blocking_reasons.append("Obstacle avoidance is enabled but GPIO obstacle sensor is unavailable.")
            if source == "ros" and not obstacle_status.get("available"):
                blocking_reasons.append("Obstacle avoidance is enabled but ROS obstacle sensor bridge is unavailable.")
        return blocking_reasons

    def _get_terrain_following_blockers(self, checks: Dict) -> List[str]:
        terrain_config = (checks.get("navigation_config") or {}).get("terrain_following", {})
        terrain_status = checks.get("terrain") or {}
        if (
            checks["terrain_following_expected"]
            and terrain_config.get("source") == "rangefinder"
            and terrain_status.get("rangefinder_distance_meters") is None
        ):
            return ["Terrain following is enabled but rangefinder terrain data is unavailable."]
        return []

    def _get_camera_blockers(self, checks: Dict) -> List[str]:
        blocking_reasons = []
        if checks["camera_expected"] and not checks["camera_available"]:
            blocking_reasons.append("Camera is enabled but unavailable.")
        if checks["camera_trigger_expected"] and not checks["camera_trigger_available"]:
            blocking_reasons.append("Camera trigger is enabled but unavailable.")
        return blocking_reasons

    def _get_weather_blockers(self, checks: Dict) -> List[str]:
        if not checks.get("weather_expected"):
            return []

        weather_status = checks.get("weather_status") or {}
        briefing = weather_status.get("last_briefing") or {}
        if not briefing:
            return ["Weather briefing is enabled but no METAR/TAF briefing is available."]
        if not briefing.get("ready", False):
            return list(briefing.get("blocking_reasons") or ["Weather briefing indicates unsafe conditions."])
        return []

    def _get_armable_blockers(self, checks: Dict) -> List[str]:
        if checks["is_armable"] is False:
            return ["Vehicle is not armable."]
        return []

    def _get_payload_readiness_blockers(self, checks: Dict) -> List[str]:
        blocking_reasons = []
        if checks["flow_sensor_expected"] and not checks["flow_sensor_available"]:
            blocking_reasons.append("Flow sensor is enabled but unavailable.")
        if checks["pressure_sensor_expected"] and not checks["pressure_sensor_available"]:
            blocking_reasons.append("Pressure sensor is enabled but unavailable.")
        if checks["tank_level_sensor_expected"] and not checks["tank_level_sensor_available"]:
            blocking_reasons.append("Tank level sensor is enabled but unavailable.")
        tank_level = checks.get("tank_level") or {}
        if tank_level.get("is_below_minimum"):
            blocking_reasons.append("Tank level is below configured minimum.")
        if checks["spray_pump_status"] == "error":
            blocking_reasons.append("Spray pump is in error state.")
        return blocking_reasons

    def _get_system_blockers(self, checks: Dict) -> List[str]:
        blocking_reasons = []
        if checks["storage"] is not None and "error" in checks["storage"]:
            blocking_reasons.append("Storage check failed.")
        if config.api.auth_enabled and not checks["api_key_configured"]:
            blocking_reasons.append("API auth is enabled but API_KEY is not configured.")
        return blocking_reasons

    def _get_companion_safety_blockers(self, checks: Dict) -> List[str]:
        if not self.safety_manager:
            return []

        blockers = []
        evaluation = self.safety_manager.evaluate_snapshot(self._current_safety_snapshot())
        blockers.extend(evaluation.get("blockers", []))
        if evaluation.get("recommended_action") in {"rtl", "land"}:
            blockers.append(f"Companion safety manager recommends {evaluation['recommended_action'].upper()}.")
        return blockers

    def _get_safety_blockers(self, command: str) -> List[str]:
        if not config.api.safety_gates_enabled:
            return []

        readiness = self._get_readiness_data()
        checks = readiness["checks"]
        blockers = []

        if command in {"vehicle.arm", "vehicle.takeoff", "vehicle.goto", "mission.start", "payload.spray_start"}:
            blockers.extend(self._get_navigation_blockers(checks))

        if command in {"vehicle.arm", "vehicle.takeoff", "mission.start"}:
            blockers.extend(self._get_armable_blockers(checks))

        if command == "payload.spray_start":
            blockers.extend(self._get_payload_readiness_blockers(checks))

        if self.safety_manager:
            evaluation = self.safety_manager.evaluate_snapshot(self._current_safety_snapshot())
            blockers.extend(evaluation.get("blockers", []))
            if command in {"vehicle.arm", "vehicle.takeoff", "vehicle.goto", "mission.start", "payload.spray_start"}:
                recommended_action = evaluation.get("recommended_action")
                if recommended_action in {"rtl", "land", "loiter"}:
                    blockers.append(
                        f"Companion safety manager recommends {recommended_action.upper()} before {command}."
                    )

        return blockers

    def _enforce_safety_gate(self, command: str):
        blockers = self._get_safety_blockers(command)
        if blockers:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"Safety gate blocked command: {command}",
                    "blocking_reasons": blockers,
                },
            )

    def _require_command_authority(
        self,
        token: Optional[str],
        allowed_roles: Set[ApiRole] = COMMAND_ROLES,
    ):
        self._require_command_role(allowed_roles)
        self.control_authority.require(token)

    def _get_freshness_blockers(self, command: str) -> List[str]:
        if not config.api.telemetry_freshness_enabled:
            return []

        blockers = []
        now = time.time()
        last_update = getattr(self.telemetry_manager, "last_update", 0)
        if command in {"vehicle.arm", "vehicle.takeoff", "vehicle.goto", "mission.start", "payload.spray_start"}:
            age = now - last_update if last_update else None
            if age is None or age > config.api.telemetry_stale_seconds:
                blockers.append(
                    f"Vehicle telemetry is stale or unavailable; last update age: {age if age is not None else 'never'}."
                )

        payload_status = self.payload_controller.get_payload_status()
        if command == "payload.spray_start":
            for key in ("flow_sensor", "pressure_sensor", "tank_level_sensor"):
                sensor_status = payload_status.get(key)
                if sensor_status and sensor_status.get("updated_at"):
                    age = now - sensor_status["updated_at"]
                    if age > config.api.payload_stale_seconds:
                        blockers.append(f"{key} data is stale; age: {age:.2f}s.")

        return blockers

    def _enforce_freshness_gate(self, command: str):
        blockers = self._get_freshness_blockers(command)
        if blockers:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"Freshness gate blocked command: {command}",
                    "blocking_reasons": blockers,
                },
            )

    def _enforce_command_gates(self, command: str, token: Optional[str]):
        self._require_command_authority(token)
        self._enforce_freshness_gate(command)
        self._enforce_safety_gate(command)

    async def _authorize_websocket(self, websocket: WebSocket) -> bool:
        if not config.api.auth_enabled:
            self._set_auth_context(AuthenticatedPrincipal(role=ApiRole.ADMIN))
            return True

        supplied_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
        api_key_roles = self._configured_api_key_roles()
        if not api_key_roles:
            await websocket.close(code=1011, reason="No API keys are configured.")
            return False

        for configured_key, role in api_key_roles.items():
            if supplied_key and hmac.compare_digest(supplied_key, configured_key):
                self._set_auth_context(
                    AuthenticatedPrincipal(
                        role=self._coerce_api_role(role),
                        api_key_id=self._api_key_id(configured_key),
                    )
                )
                return True

        await websocket.close(code=1008, reason="Invalid or missing API key.")
        return False

    def _subscribe_command_events(self, client_id: str, send_callback: Callable[[Dict], object]):
        with self.command_event_lock:
            self.command_event_subscribers[client_id] = send_callback
        logger.info(f"Client {client_id} subscribed to command events")

    def _unsubscribe_command_events(self, client_id: str):
        with self.command_event_lock:
            removed = self.command_event_subscribers.pop(client_id, None)
        if removed:
            logger.info(f"Client {client_id} unsubscribed from command events")

    def _publish_command_event(self, event: Dict):
        disconnected = []
        with self.command_event_lock:
            subscribers = list(self.command_event_subscribers.items())

        for client_id, send_callback in subscribers:
            try:
                send_callback(event)
            except Exception as e:
                logger.warning(f"Failed to send command event to {client_id}: {str(e)}")
                disconnected.append(client_id)

        for client_id in disconnected:
            self._unsubscribe_command_events(client_id)

    def _command_event_from_audit(self, event_type: str, audit_event: Dict) -> Dict:
        return {
            "type": event_type,
            "timestamp": audit_event["timestamp"],
            "action": audit_event["action"],
            "outcome": audit_event["outcome"],
            "parameters": audit_event.get("parameters", {}),
            "details": audit_event.get("details", {}),
        }

    def _publish_audit_events(self, audit_event: Dict):
        event_type = COMMAND_OUTCOME_EVENT_TYPES.get(audit_event["outcome"])
        if event_type:
            self._publish_command_event(self._command_event_from_audit(event_type, audit_event))

        if audit_event["outcome"] != "success":
            return

        action = audit_event["action"]
        success_event_type = SUCCESS_ACTION_EVENT_TYPES.get(action)
        if success_event_type:
            self._publish_command_event(
                self._command_event_from_audit(success_event_type, audit_event)
            )

        if action.startswith("emergency."):
            self._publish_command_event(
                self._command_event_from_audit("emergency.triggered", audit_event)
            )

    def _audit_command(
        self,
        action: str,
        outcome: str,
        parameters: Optional[Dict] = None,
        details: Optional[Dict] = None,
    ):
        try:
            audit_event = self.audit_logger.record(
                action,
                outcome,
                parameters=parameters,
                details=details,
            )
            self._publish_audit_events(audit_event)
        except Exception as e:
            logger.error(f"Failed to write audit event: {str(e)}")

    def _audit_http_error(self, action: str, parameters: Dict, error: HTTPException):
        outcome = "blocked" if error.status_code == 409 else "failed"
        details = {"status_code": error.status_code, "detail": error.detail}
        self._audit_command(action, outcome, parameters=parameters, details=details)

    def _setup_versioned_api_aliases(self):
        """Expose /api/v1 aliases while preserving existing /api paths."""
        existing_route_methods = {
            (route.path, method)
            for route in self.app.routes
            if isinstance(route, APIRoute)
            for method in route.methods or []
        }
        for route in list(self.app.routes):
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
                continue

            versioned_path = route.path.replace("/api/", "/api/v1/", 1)
            alias_methods = [
                method
                for method in sorted(route.methods or [])
                if (versioned_path, method) not in existing_route_methods
            ]
            if not alias_methods:
                continue

            self.app.add_api_route(
                versioned_path,
                route.endpoint,
                response_model=route.response_model,
                status_code=route.status_code,
                tags=route.tags,
                dependencies=route.dependencies,
                summary=route.summary,
                description=route.description,
                response_description=route.response_description,
                responses=route.responses,
                deprecated=route.deprecated,
                methods=alias_methods,
                include_in_schema=True,
                response_class=route.response_class,
                name=f"v1_{route.name}",
            )
            for method in alias_methods:
                existing_route_methods.add((versioned_path, method))

    def _setup_routes(self):
        """Setup all API routes"""

        protected = [Depends(self._require_api_key)]
        protected_audit = [Depends(self._require_audit_role)]
        protected_header_or_query = [Depends(self._require_api_key_header_or_query)]

        @self.app.get("/health", tags=["System"])
        async def health_check():
            connection_status = self._get_connection_status()
            return {
                "status": "ok",
                "connected": self.connection_manager.connected,
                "pixhawk_connection": connection_status,
                "pixhawk_connection_state": connection_status.get("state"),
                "auth_enabled": config.api.auth_enabled,
            }

        @self.app.get(
            "/api/system/info",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
        )
        async def system_info():
            return StatusResponse(
                status="success",
                message="System information retrieved",
                data={
                    "application": {
                        "name": self.app.title,
                        "version": self.app.version,
                        "environment": config.environment,
                    },
                    "api": {
                        "auth_enabled": config.api.auth_enabled,
                        "safety_gates_enabled": config.api.safety_gates_enabled,
                        "command_authority_enabled": config.api.command_authority_enabled,
                        "command_authority_lease_seconds": config.api.command_authority_lease_seconds,
                        "idempotency_ttl_seconds": config.api.idempotency_ttl_seconds,
                        "roles": [role.value for role in ApiRole],
                        "telemetry_freshness_enabled": config.api.telemetry_freshness_enabled,
                        "telemetry_stale_seconds": config.api.telemetry_stale_seconds,
                        "payload_stale_seconds": config.api.payload_stale_seconds,
                        "audit_log_file": config.api.audit_log_file,
                        "config_database_file": config.api.config_database_file,
                        "cors_origins": config.api.cors_origins,
                    },
                    "storage": {
                        "geotiff_database_file": config.storage.geotiff_database_file,
                        "geotiff_asset_directory": config.storage.geotiff_asset_directory,
                        "swarm_database_file": config.storage.swarm_database_file,
                    },
                    "weather": {
                        "enabled": config.weather.enabled,
                        "station_id": config.weather.station_id,
                        "metar_url_template": config.weather.metar_url_template,
                        "taf_url_template": config.weather.taf_url_template,
                        "timeout_seconds": config.weather.timeout_seconds,
                        "max_metar_age_minutes": config.weather.max_metar_age_minutes,
                        "min_visibility_sm": config.weather.min_visibility_sm,
                        "min_ceiling_ft": config.weather.min_ceiling_ft,
                        "max_wind_kt": config.weather.max_wind_kt,
                        "max_gust_kt": config.weather.max_gust_kt,
                        "allow_ifr": config.weather.allow_ifr,
                    },
                    "edge_ai": {
                        "enabled": config.edge_ai.enabled,
                        "backend": config.edge_ai.backend,
                        "model_path": config.edge_ai.model_path,
                        "labels_path": config.edge_ai.labels_path,
                        "input_size": config.edge_ai.input_size,
                        "confidence_threshold": config.edge_ai.confidence_threshold,
                        "iou_threshold": config.edge_ai.iou_threshold,
                        "sample_interval_seconds": config.edge_ai.sample_interval_seconds,
                    },
                    "mavlink": {
                        "connection_type": config.mavlink.connection_type.value,
                        "port": config.mavlink.port,
                        "baudrate": config.mavlink.baudrate,
                        "udp_ip": config.mavlink.udp_ip,
                        "udp_port": config.mavlink.udp_port,
                        "udp_direction": config.mavlink.udp_direction,
                        "connection_status": self._get_connection_status(),
                    },
                    "mission": {
                        "max_waypoints": config.mission.max_waypoints,
                        "min_altitude": config.mission.min_altitude,
                        "max_altitude": config.mission.max_altitude,
                        "default_airspeed": config.mission.default_airspeed,
                        "loiter_radius": config.mission.loiter_radius,
                        "storage_file": config.mission.storage_file,
                        "obstacle_avoidance_defaults": {
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
                        "terrain_following_defaults": {
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
                    },
                    "navigation": {
                        "config": self._get_navigation_config(),
                        "pixhawk": self._get_navigation_status(),
                    },
                    "payload": {
                        "camera_enabled": config.payload.camera_enabled,
                        "camera_port": config.payload.camera_port,
                        "camera_trigger_enabled": config.payload.camera_trigger_enabled,
                        "camera_trigger_pin": config.payload.camera_trigger_pin,
                        "camera_trigger_pulse_ms": config.payload.camera_trigger_pulse_ms,
                        "flow_sensor_enabled": config.payload.flow_sensor_enabled,
                        "flow_sensor_pulses_per_liter": config.payload.flow_sensor_pulses_per_liter,
                        "spray_pump_pin": config.payload.spray_pump_pin,
                        "flow_sensor_pin": config.payload.flow_sensor_pin,
                        "pressure_sensor": {
                            "enabled": config.payload.pressure_sensor_enabled,
                            "source": config.payload.pressure_sensor_source,
                            "gpio_pin": config.payload.pressure_sensor_pin,
                            "adc_channel": config.payload.pressure_sensor_adc_channel,
                            "min_voltage": config.payload.pressure_sensor_min_voltage,
                            "max_voltage": config.payload.pressure_sensor_max_voltage,
                            "min_psi": config.payload.pressure_sensor_min_psi,
                            "max_psi": config.payload.pressure_sensor_max_psi,
                        },
                        "tank_level_sensor": {
                            "enabled": config.payload.tank_level_sensor_enabled,
                            "source": config.payload.tank_level_sensor_source,
                            "gpio_pin": config.payload.tank_level_sensor_pin,
                            "adc_channel": config.payload.tank_level_sensor_adc_channel,
                            "min_voltage": config.payload.tank_level_sensor_min_voltage,
                            "max_voltage": config.payload.tank_level_sensor_max_voltage,
                            "capacity_liters": config.payload.tank_capacity_liters,
                            "minimum_level_percent": config.payload.tank_min_level_percent,
                        },
                        "rtk": {
                            "enabled": config.payload.rtk_enabled,
                            "correction_port": config.payload.rtk_correction_port,
                            "correction_baudrate": config.payload.rtk_correction_baudrate,
                        },
                        "ppk": {
                            "enabled": config.payload.ppk_enabled,
                            "log_directory": config.payload.ppk_log_directory,
                        },
                        "spray_application_record_directory": config.payload.spray_application_record_directory,
                        "terrain_following": {
                            "enabled": config.payload.terrain_following_enabled,
                            "sensor_source": config.payload.terrain_sensor_source,
                            "sensor_pin": config.payload.terrain_sensor_pin,
                            "min_agl_meters": config.payload.terrain_min_agl_meters,
                            "max_agl_meters": config.payload.terrain_max_agl_meters,
                        },
                        "data_directory": config.payload.data_directory,
                        "photo_directory": config.payload.photo_directory,
                        "spray_session_directory": config.payload.spray_session_directory,
                    },
                    "telemetry": {
                        "update_interval": config.telemetry.update_interval,
                        "history_size": config.telemetry.history_size,
                        "gps_timeout": config.telemetry.gps_timeout,
                    },
                    "mapping": {
                        "survey_front_overlap": config.mapping.survey_front_overlap,
                        "survey_side_overlap": config.mapping.survey_side_overlap,
                        "survey_target_gsd_cm": config.mapping.survey_target_gsd_cm,
                        "survey_default_altitude_m": config.mapping.survey_default_altitude_m,
                        "survey_default_heading_deg": config.mapping.survey_default_heading_deg,
                        "survey_flight_speed_mps": config.mapping.survey_flight_speed_mps,
                        "survey_terrain_aware": config.mapping.survey_terrain_aware,
                        "survey_terrain_clearance_m": config.mapping.survey_terrain_clearance_m,
                        "survey_border_margin_m": config.mapping.survey_border_margin_m,
                        "camera_sensor_width_mm": config.mapping.camera_sensor_width_mm,
                        "camera_sensor_height_mm": config.mapping.camera_sensor_height_mm,
                        "camera_image_width_px": config.mapping.camera_image_width_px,
                        "camera_image_height_px": config.mapping.camera_image_height_px,
                        "camera_focal_length_mm": config.mapping.camera_focal_length_mm,
                        "ndvi_enabled": config.mapping.ndvi_enabled,
                        "ndvi_red_band_index": config.mapping.ndvi_red_band_index,
                        "ndvi_nir_band_index": config.mapping.ndvi_nir_band_index,
                        "orthomosaic_preview_max_columns": config.mapping.orthomosaic_preview_max_columns,
                        "orthomosaic_preview_tile_scale": config.mapping.orthomosaic_preview_tile_scale,
                        "lidar_enabled": config.mapping.lidar_enabled,
                        "lidar_topic": config.mapping.lidar_topic,
                        "lidar_frame_id": config.mapping.lidar_frame_id,
                    },
                },
            )

        @self.app.get(
            "/api/system/audit",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected_audit,
        )
        async def get_audit_events(
            limit: int = 100,
            action: Optional[str] = None,
            outcome: Optional[str] = None,
        ):
            if limit < 1 or limit > 1000:
                raise HTTPException(status_code=400, detail="limit must be between 1 and 1000.")

            return StatusResponse(
                status="success",
                message="Audit events retrieved",
                data={
                    "events": self.audit_logger.recent(
                        limit=limit,
                        action=action,
                        outcome=outcome,
                    )
                },
            )

        @self.app.get(
            "/api/control/authority",
            response_model=StatusResponse,
            tags=["Control"],
            dependencies=protected,
        )
        async def get_control_authority():
            return StatusResponse(
                status="success",
                message="Control authority status retrieved",
                data=self.control_authority.status(),
            )

        @self.app.post(
            "/api/control/authority",
            response_model=StatusResponse,
            tags=["Control"],
            dependencies=protected,
        )
        async def acquire_control_authority(request: ControlAuthorityRequest):
            action = "control.authority_acquire"
            parameters = request.model_dump(exclude={"force"})
            try:
                self._require_command_role(AUTHORITY_ROLES)
                authority = self.control_authority.acquire(
                    request.client_id,
                    operator=request.operator,
                    force=request.force,
                    lease_seconds=request.lease_seconds,
                )
                self._audit_command(
                    action,
                    "success",
                    parameters=parameters,
                    details={"forced": request.force},
                )
                return StatusResponse(
                    status="success",
                    message="Control authority acquired",
                    data=authority,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/control/authority/renew",
            response_model=StatusResponse,
            tags=["Control"],
            dependencies=protected,
        )
        async def renew_control_authority(
            request: ControlAuthorityRequest,
            x_control_token: Optional[str] = Header(None),
        ):
            action = "control.authority_renew"
            parameters = {"client_id": request.client_id, "operator": request.operator}
            try:
                self._require_command_role(AUTHORITY_ROLES)
                authority = self.control_authority.renew(
                    x_control_token,
                    lease_seconds=request.lease_seconds,
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message="Control authority renewed",
                    data=authority,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.delete(
            "/api/control/authority",
            response_model=StatusResponse,
            tags=["Control"],
            dependencies=protected,
        )
        async def release_control_authority(x_control_token: Optional[str] = Header(None)):
            action = "control.authority_release"
            try:
                self._require_command_role(AUTHORITY_ROLES)
                released = self.control_authority.release(x_control_token)
                self._audit_command(action, "success", details=released)
                return StatusResponse(
                    status="success",
                    message="Control authority released",
                    data=released,
                )
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.get(
            "/api/readiness",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
        )
        async def readiness_check():
            return StatusResponse(
                status="success",
                message="Readiness checks completed",
                data=self._get_readiness_data(),
            )

        @self.app.post(
            "/api/weather/briefing",
            response_model=StatusResponse,
            tags=["Weather"],
            dependencies=protected,
        )
        async def create_weather_briefing(request: WeatherBriefingRequest):
            briefing = self.weather_service.build_briefing(
                station_id=request.station_id,
                metar_raw=request.metar_raw,
                taf_raw=request.taf_raw,
            )
            return StatusResponse(
                status="success",
                message="Weather briefing generated",
                data=briefing.to_dict(),
            )

        @self.app.get(
            "/api/weather/status",
            response_model=StatusResponse,
            tags=["Weather"],
            dependencies=protected,
        )
        async def weather_status():
            return StatusResponse(
                status="success",
                message="Weather status retrieved",
                data=self._weather_status_data(),
            )

        @self.app.post(
            "/api/vision/obstacles/scan",
            response_model=StatusResponse,
            tags=["Vision"],
            dependencies=protected,
        )
        async def scan_obstacles(request: Optional[EdgeAiScanRequest] = None):
            if not self.edge_ai_detector:
                raise HTTPException(status_code=503, detail="Edge AI detector is not configured.")
            result = self.edge_ai_detector.scan()
            return StatusResponse(
                status="success",
                message="Obstacle scan completed",
                data=result,
            )

        @self.app.get(
            "/api/vision/obstacles/status",
            response_model=StatusResponse,
            tags=["Vision"],
            dependencies=protected,
        )
        async def vision_status():
            return StatusResponse(
                status="success",
                message="Edge AI status retrieved",
                data=self._edge_ai_status_data(),
            )

        @self.app.get("/swagger", include_in_schema=False)
        @self.app.get("/Swagger", include_in_schema=False)
        async def swagger_redirect():
            return RedirectResponse(url="/docs")

        @self.app.get("/docs", include_in_schema=False)
        async def swagger_ui_html():
            response = get_swagger_ui_html(
                openapi_url=self.app.openapi_url,
                title=f"{self.app.title} - Swagger UI",
                swagger_ui_parameters={"persistAuthorization": True},
            )
            html = response.body.decode("utf-8")
            return HTMLResponse(html.replace("</head>", f"{DARK_SWAGGER_CSS}</head>"))

        @self.app.get(
            "/api/vehicle/status",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def get_vehicle_status():
            state = self.connection_manager.get_vehicle_state()
            if not state:
                raise HTTPException(status_code=503, detail="Unable to get vehicle status.")
            return StatusResponse(status="success", message="Vehicle status retrieved", data=state)

        @self.app.get(
            "/api/vehicle/prearm",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def get_prearm_status():
            status = self.connection_manager.get_prearm_status()
            if not status:
                raise HTTPException(status_code=503, detail="Unable to get pre-arm status.")
            return StatusResponse(status="success", message="Pre-arm status retrieved", data=status)

        @self.app.get(
            "/api/config/calibration",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
        )
        async def get_calibration_config():
            return StatusResponse(
                status="success",
                message="Calibration configuration retrieved",
                data={"calibration": self._get_calibration_config()},
            )

        @self.app.patch(
            "/api/config/calibration",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
        )
        @self.app.post(
            "/api/config/calibration",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
        )
        async def update_calibration_config(
            request: CalibrationConfigRequest,
            x_control_token: Optional[str] = Header(None),
        ):
            action = "config.calibration_update"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                result = self._update_calibration_config(parameters)
                self._audit_command(action, "success", parameters=parameters, details=result)
                return StatusResponse(
                    status="success",
                    message="Calibration configuration updated",
                    data={"calibration": result["after"], "changes": result},
                )
            except ValueError as e:
                error = HTTPException(status_code=400, detail=str(e))
                self._audit_http_error(action, parameters, error)
                raise error
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/config/profiles",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected_audit,
        )
        async def list_config_profiles():
            profiles = self.config_profiles.list_profiles()
            return StatusResponse(
                status="success",
                message="Configuration profiles retrieved",
                data={"profiles": profiles},
            )

        @self.app.post(
            "/api/config/profiles",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
        )
        async def save_config_profile(
            request: ConfigProfileSaveRequest,
            x_control_token: Optional[str] = Header(None),
        ):
            action = "config.profile_store"
            parameters = request.model_dump()
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                profile = self.config_profiles.save_profile(
                    request.name,
                    self._current_config_snapshot(),
                    description=request.description,
                    overwrite=request.overwrite,
                )
                self._audit_command(
                    action,
                    "success",
                    parameters=parameters,
                    details={
                        "profile": profile["name"],
                        "groups": sorted(profile["configuration"].keys()),
                    },
                )
                return StatusResponse(
                    status="success",
                    message="Configuration profile stored",
                    data={"profile": profile},
                )
            except FileExistsError as e:
                error = HTTPException(status_code=409, detail=str(e))
                self._audit_http_error(action, parameters, error)
                raise error
            except ValueError as e:
                error = HTTPException(status_code=400, detail=str(e))
                self._audit_http_error(action, parameters, error)
                raise error
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/config/profiles/{name}",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected_audit,
        )
        async def get_config_profile(name: str):
            action = "config.profile_retrieve"
            parameters = {"name": name}
            profile = self.config_profiles.get_profile(name)
            if not profile:
                error = HTTPException(status_code=404, detail="Configuration profile not found.")
                self._audit_http_error(action, parameters, error)
                raise error

            self._audit_command(
                action,
                "success",
                parameters=parameters,
                details={
                    "profile": profile["name"],
                    "groups": sorted(profile["configuration"].keys()),
                },
            )
            return StatusResponse(
                status="success",
                message="Configuration profile retrieved",
                data={"profile": profile},
            )

        @self.app.post(
            "/api/config/profiles/{name}/apply",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
        )
        async def apply_config_profile(
            name: str,
            request: Optional[ConfigProfileApplyRequest] = None,
            x_control_token: Optional[str] = Header(None),
        ):
            action = "config.profile_apply"
            apply_request = request or ConfigProfileApplyRequest()
            parameters = {"name": name, **apply_request.model_dump()}
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                profile = self.config_profiles.get_profile(name)
                if not profile:
                    raise HTTPException(status_code=404, detail="Configuration profile not found.")

                result = self._apply_config_snapshot(
                    profile["configuration"],
                    apply_to_pixhawk=apply_request.apply_to_pixhawk,
                )
                self._audit_command(
                    action,
                    "success",
                    parameters=parameters,
                    details={
                        "profile": profile["name"],
                        "result": result,
                    },
                )
                return StatusResponse(
                    status="success",
                    message="Configuration profile applied",
                    data={"profile": profile["name"], "result": result},
                )
            except ValueError as e:
                error = HTTPException(status_code=400, detail=str(e))
                self._audit_http_error(action, parameters, error)
                raise error
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/navigation/config",
            response_model=StatusResponse,
            tags=["Navigation"],
            dependencies=protected,
        )
        async def get_navigation_config():
            return StatusResponse(
                status="success",
                message="Navigation configuration retrieved",
                data={
                    "config": self._get_navigation_config(),
                    "pixhawk": self._get_navigation_status(),
                },
            )

        @self.app.post(
            "/api/navigation/config",
            response_model=StatusResponse,
            tags=["Navigation"],
            dependencies=protected,
        )
        async def update_navigation_config(
            request: NavigationConfigRequest,
            x_control_token: Optional[str] = Header(None),
        ):
            action = "navigation.config_update"
            parameters = request.model_dump(exclude_none=True, mode="json")
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                updated = self.mission_planner.update_navigation_config(
                    obstacle_avoidance=(
                        request.obstacle_avoidance.model_dump(exclude_none=True, mode="json")
                        if request.obstacle_avoidance
                        else None
                    ),
                    terrain_following=(
                        request.terrain_following.model_dump(exclude_none=True, mode="json")
                        if request.terrain_following
                        else None
                    ),
                )
                apply_result = None
                if request.apply_to_pixhawk:
                    apply_result = self.connection_manager.apply_navigation_config(updated)
                    self._require_success(
                        apply_result.get("success"),
                        "Navigation configuration saved, but Pixhawk parameter application failed.",
                    )

                data = {
                    "config": updated,
                    "pixhawk": self._get_navigation_status(),
                    "apply_result": apply_result,
                }
                self._audit_command(action, "success", parameters=parameters, details=data)
                return StatusResponse(
                    status="success",
                    message="Navigation configuration updated",
                    data=data,
                )
            except ValueError as e:
                error = HTTPException(status_code=400, detail=str(e))
                self._audit_http_error(action, parameters, error)
                raise error
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/navigation/apply",
            response_model=StatusResponse,
            tags=["Navigation"],
            dependencies=protected,
        )
        async def apply_navigation_config(x_control_token: Optional[str] = Header(None)):
            action = "navigation.config_apply"
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                navigation_config = self._get_navigation_config()
                result = self.connection_manager.apply_navigation_config(navigation_config)
                self._require_success(result.get("success"), "Navigation parameter application failed.")
                self._audit_command(action, "success", parameters=navigation_config, details=result)
                return StatusResponse(
                    status="success",
                    message="Navigation configuration applied to Pixhawk",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.get(
            "/api/navigation/sensors",
            response_model=StatusResponse,
            tags=["Navigation"],
            dependencies=protected,
        )
        async def get_navigation_sensors():
            return StatusResponse(
                status="success",
                message="Navigation sensor data retrieved",
                data=self._get_navigation_sensor_status(),
            )

        @self.app.get(
            "/api/swarm/config",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_config():
            return StatusResponse(
                status="success",
                message="Swarm configuration retrieved",
                data=self._swarm_config_data(),
            )

        @self.app.put(
            "/api/swarm/config",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def update_swarm_config(request: SwarmConfig, x_control_token: Optional[str] = Header(None)):
            action = "swarm.config_update"
            parameters = request.model_dump(mode="json")
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                manager = self._swarm_manager_or_none()
                if not manager:
                    raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
                updated = manager.update_config(parameters)
                self._audit_command(action, "success", parameters=parameters, details={"swarm_id": updated["swarm_id"]})
                return StatusResponse(
                    status="success",
                    message="Swarm configuration updated",
                    data=updated,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/swarm/config/validate",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def validate_swarm_config(request: SwarmConfig):
            manager = self._swarm_manager_or_none()
            if not manager:
                raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
            validated = manager.validate_config(request.model_dump(mode="json"))
            return StatusResponse(
                status="success",
                message="Swarm configuration validated",
                data=validated,
            )

        @self.app.get(
            "/api/swarm/status",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_status():
            return StatusResponse(
                status="success",
                message="Swarm status retrieved",
                data=self._swarm_status_data(),
            )

        @self.app.get(
            "/api/swarm/telemetry",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_telemetry(seconds: Optional[int] = Query(None, ge=1), limit: Optional[int] = Query(None, ge=1)):
            return StatusResponse(
                status="success",
                message="Swarm telemetry retrieved",
                data=self._swarm_telemetry_data(seconds=seconds, limit=limit),
            )

        @self.app.get(
            "/api/swarm/telemetry/history",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_telemetry_history(seconds: Optional[int] = Query(None, ge=1), limit: Optional[int] = Query(None, ge=1)):
            return StatusResponse(
                status="success",
                message="Swarm telemetry history retrieved",
                data=self._swarm_telemetry_data(seconds=seconds, limit=limit),
            )

        @self.app.get(
            "/api/swarm/alerts",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_alerts(seconds: Optional[int] = Query(None, ge=1), limit: Optional[int] = Query(None, ge=1)):
            return StatusResponse(
                status="success",
                message="Swarm alerts retrieved",
                data=self._swarm_alert_data(seconds=seconds, limit=limit),
            )

        @self.app.get(
            "/api/swarm/separation",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_separation():
            state = self._swarm_fusion_state_data()
            return StatusResponse(
                status="success",
                message="Swarm separation state retrieved",
                data={
                    "alerts": state.get("separation_alerts", []),
                    "nearest_peer": state.get("nearest_peer"),
                },
            )

        @self.app.get(
            "/api/swarm/fusion",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_fusion():
            return StatusResponse(
                status="success",
                message="Swarm fusion state retrieved",
                data=self._swarm_fusion_state_data(),
            )

        @self.app.get(
            "/api/swarm/peers",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def list_swarm_peers():
            manager = self._swarm_manager_or_none()
            if not manager:
                raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
            return StatusResponse(
                status="success",
                message="Swarm peers retrieved",
                data={"peers": manager.get_peers()},
            )

        @self.app.get(
            "/api/swarm/peers/{drone_id}",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_peer(drone_id: str):
            manager = self._swarm_manager_or_none()
            if not manager:
                raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
            peer = manager.get_peer(drone_id)
            if not peer:
                raise HTTPException(status_code=404, detail="Swarm peer not found.")
            return StatusResponse(
                status="success",
                message="Swarm peer retrieved",
                data=peer,
            )

        @self.app.post(
            "/api/swarm/peers/{drone_id}/heartbeat",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def heartbeat_swarm_peer(drone_id: str):
            manager = self._swarm_manager_or_none()
            if not manager:
                raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
            peer = manager.heartbeat_peer(drone_id)
            if not peer:
                raise HTTPException(status_code=404, detail="Swarm peer not found.")
            return StatusResponse(
                status="success",
                message="Swarm peer heartbeat recorded",
                data=peer,
            )

        @self.app.post(
            "/api/swarm/broadcast",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def broadcast_swarm_state():
            manager = self._swarm_manager_or_none()
            if not manager:
                raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
            snapshot = self._current_swarm_snapshot()
            sample = manager.broadcast_local_snapshot(snapshot)
            if not sample:
                raise HTTPException(status_code=503, detail="No swarm telemetry snapshot is available.")
            fusion = manager.get_fusion_state() or manager.recompute_fusion()
            return StatusResponse(
                status="success",
                message="Swarm telemetry broadcasted",
                data={"sample": sample, "fusion": fusion},
            )

        @self.app.post(
            "/api/swarm/fusion/recompute",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def recompute_swarm_fusion():
            manager = self._swarm_manager_or_none()
            if not manager:
                raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
            return StatusResponse(
                status="success",
                message="Swarm fusion recomputed",
                data=manager.recompute_fusion(),
            )

        @self.app.post(
            "/api/swarm/fusion/reset",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def reset_swarm_fusion():
            manager = self._swarm_manager_or_none()
            if not manager:
                raise HTTPException(status_code=503, detail="Swarm management is unavailable.")
            return StatusResponse(
                status="success",
                message="Swarm fusion reset",
                data=manager.reset(),
            )

        @self.app.get(
            "/api/swarm/coordination",
            response_model=StatusResponse,
            tags=["Swarm"],
            dependencies=protected,
        )
        async def get_swarm_coordination():
            return StatusResponse(
                status="success",
                message="Swarm coordination retrieved",
                data=self._swarm_coordination_data(),
            )

        @self.app.get(
            "/api/fleet/status",
            response_model=StatusResponse,
            tags=["Fleet"],
            dependencies=protected,
        )
        async def get_fleet_status():
            return StatusResponse(
                status="success",
                message="Fleet status retrieved",
                data=self._fleet_status_data(),
            )

        @self.app.post(
            "/api/vehicle/arm",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def arm_vehicle(request: ArmRequest, x_control_token: Optional[str] = Header(None)):
            action = "vehicle.arm" if request.armed else "vehicle.disarm"
            parameters = {"armed": request.armed}
            try:
                if request.armed:
                    self._enforce_command_gates(action, x_control_token)
                    self._require_success(self.connection_manager.arm(), "Failed to arm vehicle.")
                    self._audit_command(action, "success", parameters=parameters)
                    return StatusResponse(status="success", message="Vehicle armed")

                self._require_command_authority(x_control_token)
                self._require_success(self.connection_manager.disarm(), "Failed to disarm vehicle.")
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Vehicle disarmed")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/vehicle/takeoff",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def takeoff(request: TakeoffRequest, x_control_token: Optional[str] = Header(None)):
            action = "vehicle.takeoff"
            parameters = {"altitude": request.altitude}
            try:
                self._enforce_command_gates(action, x_control_token)
                self._require_success(self.connection_manager.takeoff(request.altitude), "Takeoff failed.")
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message=f"Takeoff initiated to {request.altitude}m",
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/vehicle/land",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def land(request: Optional[LandRequest] = None, x_control_token: Optional[str] = Header(None)):
            action = "vehicle.land"
            parameters = {}
            try:
                self._require_command_authority(x_control_token)
                self._require_success(self.connection_manager.land(), "Landing command failed.")
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Landing initiated")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/vehicle/goto",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def goto_location(request: GoToRequest, x_control_token: Optional[str] = Header(None)):
            action = "vehicle.goto"
            parameters = {"location": request.location.model_dump()}
            try:
                self._enforce_command_gates(action, x_control_token)
                self._require_success(
                    self.connection_manager.goto_location(
                        request.location.latitude,
                        request.location.longitude,
                        request.location.altitude,
                    ),
                    "Goto command failed.",
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message=f"Flying to {request.location.latitude}, {request.location.longitude}",
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/vehicle/mode",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def change_mode(request: ModeChangeRequest, x_control_token: Optional[str] = Header(None)):
            action = "vehicle.mode"
            parameters = {"mode": request.mode}
            try:
                self._require_command_authority(x_control_token)
                self._require_success(
                    self.connection_manager.set_mode(request.mode),
                    "Mode change failed.",
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message=f"Mode changed to {request.mode}")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/emergency/land",
            response_model=StatusResponse,
            tags=["Emergency"],
            dependencies=protected,
        )
        async def emergency_land():
            action = "emergency.land"
            try:
                self._require_command_role()
                stopped = self.payload_controller.disarm_spray(
                    telemetry_snapshot=self.telemetry_manager.get_current()
                )
                landed = self.connection_manager.land()
                self._require_success(landed, "Emergency land command failed.")
                self._audit_command(
                    action,
                    "success",
                    details={"spray_stopped": stopped, "landing_commanded": landed},
                )
                return StatusResponse(
                    status="success",
                    message="Emergency landing initiated",
                    data={"spray_stopped": stopped, "landing_commanded": landed},
                )
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.post(
            "/api/emergency/rtl",
            response_model=StatusResponse,
            tags=["Emergency"],
            dependencies=protected,
        )
        async def emergency_rtl():
            action = "emergency.rtl"
            try:
                self._require_command_role()
                stopped = self.payload_controller.disarm_spray(
                    telemetry_snapshot=self.telemetry_manager.get_current()
                )
                rtl = self.connection_manager.set_mode("RTL")
                self._require_success(rtl, "Emergency RTL command failed.")
                self._audit_command(
                    action,
                    "success",
                    details={"spray_stopped": stopped, "rtl_commanded": rtl},
                )
                return StatusResponse(
                    status="success",
                    message="Emergency RTL initiated",
                    data={"spray_stopped": stopped, "rtl_commanded": rtl},
                )
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.post(
            "/api/emergency/stop-spray",
            response_model=StatusResponse,
            tags=["Emergency"],
            dependencies=protected,
        )
        async def emergency_stop_spray():
            action = "emergency.stop_spray"
            try:
                self._require_command_role()
                stopped = self.payload_controller.disarm_spray(
                    telemetry_snapshot=self.telemetry_manager.get_current()
                )
                self._require_success(stopped, "Emergency spray stop failed.")
                self._audit_command(action, "success", details={"spray_stopped": stopped})
                return StatusResponse(
                    status="success",
                    message="Emergency spray stop completed",
                    data={"spray_stopped": stopped},
                )
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.get(
            "/api/safety/status",
            response_model=StatusResponse,
            tags=["Safety"],
            dependencies=protected,
        )
        async def get_safety_status():
            return StatusResponse(
                status="success",
                message="Safety status retrieved",
                data=self.safety_manager.get_status() if self.safety_manager else {},
            )

        @self.app.get(
            "/api/safety/checklist",
            response_model=StatusResponse,
            tags=["Safety"],
            dependencies=protected,
        )
        async def get_preflight_checklist():
            checklist = self.safety_manager.get_preflight_checklist(self._current_safety_snapshot()) if self.safety_manager else {}
            return StatusResponse(
                status="success",
                message="Preflight checklist retrieved",
                data=checklist,
            )

        @self.app.get(
            "/api/safety/geofences",
            response_model=StatusResponse,
            tags=["Safety"],
            dependencies=protected,
        )
        async def list_geofences():
            return StatusResponse(
                status="success",
                message="Geofences retrieved",
                data={"zones": self.safety_manager.list_zones() if self.safety_manager else []},
            )

        @self.app.post(
            "/api/safety/geofences",
            response_model=StatusResponse,
            tags=["Safety"],
            dependencies=protected,
        )
        async def add_geofence(zone: GeofenceZoneRequest, x_control_token: Optional[str] = Header(None)):
            action = "safety.geofence_create"
            parameters = zone.model_dump()
            try:
                self._require_command_authority(x_control_token)
                saved = self.safety_manager.upsert_zone(self._geofence_zone_from_request(zone)) if self.safety_manager else zone.model_dump()
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Geofence saved", data=saved)
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.delete(
            "/api/safety/geofences/{name}",
            response_model=StatusResponse,
            tags=["Safety"],
            dependencies=protected,
        )
        async def remove_geofence(name: str, x_control_token: Optional[str] = Header(None)):
            action = "safety.geofence_delete"
            parameters = {"name": name}
            try:
                self._require_command_authority(x_control_token)
                removed = self.safety_manager.delete_zone(name) if self.safety_manager else False
                if not removed:
                    raise HTTPException(status_code=404, detail="Geofence not found.")
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Geofence removed", data={"removed": True})
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/safety/emergency-landing-zones",
            response_model=StatusResponse,
            tags=["Safety"],
            dependencies=protected,
        )
        async def get_emergency_landing_zones():
            snapshot = self._current_safety_snapshot()
            latitude = (snapshot.get("location") or {}).get("latitude")
            longitude = (snapshot.get("location") or {}).get("longitude")
            landing_zone = self.safety_manager.identify_emergency_landing_zone(latitude, longitude) if self.safety_manager else None
            return StatusResponse(
                status="success",
                message="Emergency landing zone retrieved",
                data={"landing_zone": landing_zone.to_dict() if landing_zone else None},
            )

        @self.app.get(
            "/api/compliance/remote-id",
            response_model=StatusResponse,
            tags=["Compliance"],
            dependencies=protected,
        )
        async def get_remote_id():
            return StatusResponse(
                status="success",
                message="Remote ID configuration retrieved",
                data=self.safety_manager.get_remote_id() if self.safety_manager else {},
            )

        @self.app.put(
            "/api/compliance/remote-id",
            response_model=StatusResponse,
            tags=["Compliance"],
            dependencies=protected,
        )
        async def update_remote_id(request: RemoteIDRequest, x_control_token: Optional[str] = Header(None)):
            action = "compliance.remote_id_update"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token)
                updated = self.safety_manager.update_remote_id(parameters) if self.safety_manager else parameters
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Remote ID configuration updated", data=updated)
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/compliance/waivers",
            response_model=StatusResponse,
            tags=["Compliance"],
            dependencies=protected,
        )
        async def get_waivers():
            return StatusResponse(
                status="success",
                message="Waiver configuration retrieved",
                data=self.safety_manager.get_waivers() if self.safety_manager else {},
            )

        @self.app.put(
            "/api/compliance/waivers",
            response_model=StatusResponse,
            tags=["Compliance"],
            dependencies=protected,
        )
        async def update_waivers(request: WaiverRequest, x_control_token: Optional[str] = Header(None)):
            action = "compliance.waiver_update"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token)
                updated = self.safety_manager.update_waivers(parameters) if self.safety_manager else parameters
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Waiver configuration updated", data=updated)
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/arming/checks",
            response_model=StatusResponse,
            tags=["Arming"],
            dependencies=protected,
        )
        async def get_arming_checks():
            return StatusResponse(
                status="success",
                message="Arming checks retrieved",
                data={
                    "prearm": self.connection_manager.get_prearm_status(),
                    "safety": self.safety_manager.get_preflight_checklist(self._current_safety_snapshot()) if self.safety_manager else {},
                    "companion_safety": self.safety_manager.get_status() if self.safety_manager else {},
                },
            )

        @self.app.post(
            "/api/arming/motor-test",
            response_model=StatusResponse,
            tags=["Arming"],
            dependencies=protected,
        )
        async def motor_test(request: Optional[Dict] = None, x_control_token: Optional[str] = Header(None)):
            action = "arming.motor_test"
            parameters = request or {}
            try:
                self._require_command_authority(x_control_token)
                checklist = {
                    "procedure": [
                        "Confirm propellers are removed or aircraft is secured.",
                        "Verify safety switch state and Remote ID status.",
                        "Perform short motor spin test only in a controlled environment.",
                    ],
                    "duration_seconds": config.safety.motor_test_duration_seconds,
                    "esc_calibration": "Follow airframe manufacturer instructions before enabling motors.",
                }
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message="Motor test and ESC calibration procedure prepared",
                    data=checklist,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/emergency/hold",
            response_model=StatusResponse,
            tags=["Emergency"],
            dependencies=protected,
        )
        async def emergency_hold():
            action = "emergency.hold"
            try:
                self._require_command_role()
                stopped = self.payload_controller.disarm_spray(
                    telemetry_snapshot=self.telemetry_manager.get_current()
                )
                held = self.connection_manager.set_mode("BRAKE") or self.connection_manager.set_mode("LOITER")
                self._require_success(held, "Emergency hold command failed.")
                self._audit_command(
                    action,
                    "success",
                    details={"spray_stopped": stopped, "hold_commanded": held},
                )
                return StatusResponse(
                    status="success",
                    message="Emergency hold initiated",
                    data={"spray_stopped": stopped, "hold_commanded": held},
                )
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.post(
            "/api/mission/add-waypoint",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def add_waypoint(request: WaypointRequest, x_control_token: Optional[str] = Header(None)):
            action = "mission.add_waypoint"
            parameters = {
                "location": request.location.model_dump(),
                "altitude_frame": request.altitude_frame,
            }
            try:
                self._require_command_authority(x_control_token)
                self._require_success(
                    self.mission_planner.add_waypoint(
                        request.location.latitude,
                        request.location.longitude,
                        request.location.altitude,
                        altitude_frame=request.altitude_frame,
                    ),
                    "Failed to add waypoint.",
                    status_code=400,
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Waypoint added")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/mission/waypoints",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def get_mission():
            return StatusResponse(
                status="success",
                message="Mission retrieved",
                data={
                    "waypoints": self.mission_planner.get_mission(),
                    "statistics": self.mission_planner.get_statistics(),
                    "execution": {
                        "is_executing": self.mission_planner.is_executing,
                        "current_mission_index": self.mission_planner.current_mission_index,
                    },
                },
            )

        @self.app.get(
            "/api/mission/state",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def get_mission_state():
            return StatusResponse(
                status="success",
                message="Mission state retrieved",
                data=self.mission_planner.get_state(),
            )

        @self.app.delete(
            "/api/mission/waypoints/{index}",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def remove_waypoint(index: int, x_control_token: Optional[str] = Header(None)):
            action = "mission.remove_waypoint"
            parameters = {"index": index}
            try:
                self._require_command_authority(x_control_token)
                self._require_success(
                    self.mission_planner.remove_waypoint(index),
                    "Waypoint not found.",
                    status_code=404,
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message="Waypoint removed",
                    data=self.mission_planner.get_state(),
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mission/clear",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def clear_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.clear"
            parameters = {}
            try:
                self._require_command_authority(x_control_token)
                self.mission_planner.clear_mission()
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Mission cleared")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mission/start",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def start_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.start"
            parameters = {}
            try:
                self._enforce_command_gates(action, x_control_token)
                self._require_success(
                    self.mission_planner.start_mission(),
                    "Failed to start mission. Add at least one waypoint first.",
                    status_code=400,
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Mission tracking started")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mission/pause",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def pause_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.pause"
            parameters = {}
            try:
                self._require_command_authority(x_control_token)
                self.mission_planner.pause_mission()
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Mission paused")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mission/resume",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def resume_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.resume"
            parameters = {}
            try:
                self._require_command_authority(x_control_token)
                self.mission_planner.resume_mission()
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Mission resumed")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mission/abort",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def abort_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.abort"
            parameters = {}
            try:
                self._require_command_authority(x_control_token)
                self.mission_planner.abort_mission()
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Mission aborted")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/mission/stats",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def get_mission_stats():
            return StatusResponse(
                status="success",
                message="Mission statistics retrieved",
                data=self.mission_planner.get_statistics(),
            )

        @self.app.post(
            "/api/mission/pixhawk/upload",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def upload_mission_to_pixhawk(x_control_token: Optional[str] = Header(None)):
            action = "mission.pixhawk_upload"
            try:
                self._require_command_authority(x_control_token)
                result = self.connection_manager.upload_mission(self.mission_planner.mission_items)
                self._require_success(result.get("success"), "Pixhawk mission upload failed.")
                self._audit_command(action, "success", details=result)
                return StatusResponse(status="success", message="Mission uploaded to Pixhawk", data=result)
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.get(
            "/api/mission/pixhawk/download",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def download_mission_from_pixhawk():
            result = self.connection_manager.download_mission()
            self._require_success(result.get("success"), "Pixhawk mission download failed.")
            return StatusResponse(status="success", message="Mission downloaded from Pixhawk", data=result)

        @self.app.get(
            "/api/mission/pixhawk/verify",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def verify_pixhawk_mission():
            action = "mission.pixhawk_verify"
            try:
                result = self.connection_manager.verify_mission(self.mission_planner.mission_items)
                self._require_success(result.get("success"), "Pixhawk mission verification failed.")
                self._audit_command(action, "success", details=result)
                return StatusResponse(
                    status="success",
                    message="Pixhawk mission verification completed",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.delete(
            "/api/mission/pixhawk",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def clear_pixhawk_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.pixhawk_clear"
            try:
                self._require_command_authority(x_control_token)
                result = self.connection_manager.clear_pixhawk_mission()
                self._require_success(result.get("success"), "Pixhawk mission clear failed.")
                self._audit_command(action, "success", details=result)
                return StatusResponse(status="success", message="Pixhawk mission cleared", data=result)
            except HTTPException as e:
                self._audit_http_error(action, {}, e)
                raise

        @self.app.post(
            "/api/field-boundaries",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def add_field_boundary(request: FieldBoundaryRequest, x_control_token: Optional[str] = Header(None)):
            from ..missions.planner import FieldBoundary, GeoPoint

            vertices = [GeoPoint(vertex.latitude, vertex.longitude) for vertex in request.vertices]
            boundary = FieldBoundary(request.name, vertices, request.altitude)

            action = "mission.add_field_boundary"
            parameters = request.model_dump()
            try:
                self._require_command_authority(x_control_token)
                self._require_success(
                    self.mission_planner.add_field_boundary(boundary),
                    "Failed to add field boundary.",
                    status_code=400,
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Field boundary added")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/field-boundaries",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def get_field_boundaries():
            return StatusResponse(
                status="success",
                message="Field boundaries retrieved",
                data=self.mission_planner.get_field_boundaries(),
            )

        @self.app.delete(
            "/api/field-boundaries/{name}",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def remove_field_boundary(name: str, x_control_token: Optional[str] = Header(None)):
            action = "mission.remove_field_boundary"
            parameters = {"name": name}
            try:
                self._require_command_authority(x_control_token)
                self._require_success(
                    self.mission_planner.remove_field_boundary(name),
                    "Field boundary not found.",
                    status_code=404,
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message="Field boundary removed",
                    data=self.mission_planner.get_state(),
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mapping/survey-grid",
            response_model=StatusResponse,
            tags=["Mapping"],
            dependencies=protected,
        )
        async def generate_survey_grid(request: SurveyGridPlanRequest, x_control_token: Optional[str] = Header(None)):
            action = "mapping.survey_grid"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token)
                boundary = self._field_boundary_from_request(request.field_boundary)
                survey_config = dict(request.survey_config or {})
                if "altitude_agl_m" not in survey_config:
                    survey_config["altitude_agl_m"] = config.mapping.survey_default_altitude_m
                if "front_overlap" not in survey_config:
                    survey_config["front_overlap"] = config.mapping.survey_front_overlap
                if "side_overlap" not in survey_config:
                    survey_config["side_overlap"] = config.mapping.survey_side_overlap
                if "target_gsd_cm" not in survey_config:
                    survey_config["target_gsd_cm"] = config.mapping.survey_target_gsd_cm
                if "flight_speed_mps" not in survey_config:
                    survey_config["flight_speed_mps"] = config.mapping.survey_flight_speed_mps
                if "line_heading_deg" not in survey_config:
                    survey_config["line_heading_deg"] = config.mapping.survey_default_heading_deg
                if "terrain_aware" not in survey_config:
                    survey_config["terrain_aware"] = config.mapping.survey_terrain_aware
                if "terrain_clearance_m" not in survey_config:
                    survey_config["terrain_clearance_m"] = config.mapping.survey_terrain_clearance_m
                if "border_margin_m" not in survey_config:
                    survey_config["border_margin_m"] = config.mapping.survey_border_margin_m

                terrain_fn = self._build_terrain_elevation_fn(
                    request.terrain_samples,
                    default_elevation=boundary.altitude,
                )
                plan = self._mapping_planner().generate_survey_grid(
                    boundary,
                    SurveyGridConfig(**survey_config),
                    terrain_elevation_fn=terrain_fn,
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message="Survey grid generated",
                    data=plan.to_dict(),
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mapping/geotag/export",
            tags=["Mapping"],
            dependencies=protected,
        )
        async def export_geotag_csv(request: GeotagExportRequest, x_control_token: Optional[str] = Header(None)):
            action = "mapping.geotag_export"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token)
                records = self._resolve_geotag_export_records(request)
                synchronized = self._mapping_planner().synchronize_capture_timestamps(
                    records,
                    gps_time_offset_s=request.gps_time_offset_s,
                )
                buffer = io.StringIO()
                writer = csv.DictWriter(
                    buffer,
                    fieldnames=[
                        "filename",
                        "latitude",
                        "longitude",
                        "altitude_m",
                        "captured_at_utc",
                        "heading_deg",
                        "trigger_timestamp",
                        "gps_timestamp",
                        "drone_id",
                    ],
                )
                writer.writeheader()
                for record in synchronized:
                    writer.writerow(record.to_csv_row())

                content = buffer.getvalue()
                self._audit_command(action, "success", parameters=parameters, details={"record_count": len(synchronized)})
                return Response(
                    content=content,
                    media_type="text/csv",
                    headers={"content-disposition": 'attachment; filename="geotags.csv"'},
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mapping/geotag/exif",
            response_model=StatusResponse,
            tags=["Mapping"],
            dependencies=protected,
        )
        async def geotag_session_images(request: ExifGeotagRequest, x_control_token: Optional[str] = Header(None)):
            action = "mapping.geotag_exif"
            parameters = request.model_dump()
            if not self.payload_controller.camera:
                error = HTTPException(status_code=503, detail="Camera not available.")
                self._audit_http_error(action, parameters, error)
                raise error

            try:
                self._require_command_authority(x_control_token)
                records = self._camera_session_geotag_records(request.session)
                tagged = []
                skipped = []
                output_session = request.output_session or (f"{request.session}_geotagged" if not request.overwrite else request.session)
                for photo_record in records:
                    source_path = self._resolve_photo_path(request.session, photo_record.filename)
                    if not source_path:
                        skipped.append(photo_record.filename)
                        continue

                    target_path = source_path
                    if not request.overwrite:
                        target_path = Path(self.payload_controller.camera.photo_directory) / output_session / source_path.name
                    self._mapping_planner().write_geotagged_image(source_path, photo_record, target_path)
                    tagged.append(str(target_path))

                self._audit_command(
                    action,
                    "success",
                    parameters=parameters,
                    details={"tagged_count": len(tagged), "skipped_count": len(skipped)},
                )
                return StatusResponse(
                    status="success",
                    message="EXIF geotagging completed",
                    data={
                        "session": request.session,
                        "overwrite": request.overwrite,
                        "output_session": output_session if not request.overwrite else request.session,
                        "tagged_count": len(tagged),
                        "skipped_count": len(skipped),
                        "tagged_files": tagged,
                        "skipped_files": skipped,
                    },
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mapping/ndvi/preview",
            tags=["Mapping"],
            dependencies=protected,
        )
        async def build_ndvi_preview(request: NdviPreviewRequest, x_control_token: Optional[str] = Header(None)):
            action = "mapping.ndvi_preview"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token)
                if not self.payload_controller.camera:
                    raise HTTPException(status_code=503, detail="Camera not available.")
                if not request.session and (not request.red_filename or not request.nir_filename):
                    raise HTTPException(status_code=400, detail="Provide a session or red/nir filenames.")

                if request.session:
                    red_filename = request.red_filename or "red.jpg"
                    nir_filename = request.nir_filename or "nir.jpg"
                    red_path = self._resolve_photo_path(request.session, red_filename)
                    nir_path = self._resolve_photo_path(request.session, nir_filename)
                else:
                    red_path = self._resolve_photo_path(None, request.red_filename or "")
                    nir_path = self._resolve_photo_path(None, request.nir_filename or "")

                if not red_path or not nir_path:
                    raise HTTPException(status_code=404, detail="Red or NIR image not found.")

                red_image = cv2.imread(str(red_path), cv2.IMREAD_UNCHANGED)
                nir_image = cv2.imread(str(nir_path), cv2.IMREAD_UNCHANGED)
                if red_image is None or nir_image is None:
                    raise HTTPException(status_code=400, detail="Failed to load one or more NDVI source images.")

                def _select_band(image, band_index: int):
                    if image.ndim == 2:
                        return image
                    if band_index >= image.shape[2]:
                        raise HTTPException(status_code=400, detail="Band index is out of range for the selected image.")
                    return image[..., band_index]

                red_band = _select_band(red_image, request.red_band_index)
                nir_band = _select_band(nir_image, request.nir_band_index)
                if red_band.shape != nir_band.shape:
                    nir_band = cv2.resize(
                        nir_band,
                        (red_band.shape[1], red_band.shape[0]),
                        interpolation=cv2.INTER_AREA,
                    )
                ndvi = self._mapping_planner().calculate_ndvi(red_band, nir_band)
                preview = self._mapping_planner().ndvi_false_color(ndvi)
                self._audit_command(action, "success", parameters=parameters)
                return Response(
                    content=self._image_to_png_bytes(preview),
                    media_type="image/png",
                    headers={"content-disposition": 'inline; filename="ndvi-preview.png"'},
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mapping/orthomosaic/preview",
            tags=["Mapping"],
            dependencies=protected,
        )
        async def build_orthomosaic_preview(request: OrthomosaicPreviewRequest, x_control_token: Optional[str] = Header(None)):
            action = "mapping.orthomosaic_preview"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token)
                if not self.payload_controller.camera:
                    raise HTTPException(status_code=503, detail="Camera not available.")

                if request.filenames:
                    filenames = request.filenames
                elif request.session:
                    photos = self.payload_controller.camera.get_recent_photos(request.limit, session=request.session)
                    filenames = [photo["filename"] for photo in photos]
                else:
                    raise HTTPException(status_code=400, detail="Provide a session or filenames.")

                image_paths = []
                for filename in filenames[: request.limit]:
                    if request.session:
                        photo_path = self._resolve_photo_path(request.session, filename)
                    else:
                        photo_path = self._resolve_photo_path(None, filename)
                    if photo_path:
                        image_paths.append(photo_path)

                if not image_paths:
                    raise HTTPException(status_code=404, detail="No preview images were found.")

                mosaic = self._mapping_planner().build_preview_mosaic(
                    image_paths,
                    tile_scale=request.tile_scale,
                    columns=request.columns,
                )
                self._audit_command(action, "success", parameters=parameters, details={"tile_count": mosaic.tile_count})
                return Response(
                    content=self._image_to_png_bytes(mosaic.image),
                    media_type="image/png",
                    headers={"content-disposition": 'inline; filename="orthomosaic-preview.png"'},
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mapping/geotiff/upload",
            response_model=StatusResponse,
            tags=["Mapping"],
            dependencies=protected,
        )
        async def upload_geotiff(
            request: Request,
            x_control_token: Optional[str] = Header(None),
            name: Optional[str] = Query(default=None, max_length=120),
            filename: Optional[str] = Query(default=None, max_length=260),
            north: float = Query(..., ge=-90.0, le=90.0),
            south: float = Query(..., ge=-90.0, le=90.0),
            east: float = Query(..., ge=-180.0, le=180.0),
            west: float = Query(..., ge=-180.0, le=180.0),
            max_preview_size: int = Query(default=4096, ge=256, le=10000),
        ):
            action = "mapping.geotiff_upload"
            parameters = {
                "name": name,
                "filename": filename,
                "north": north,
                "south": south,
                "east": east,
                "west": west,
                "max_preview_size": max_preview_size,
            }
            try:
                self._require_command_authority(x_control_token)
                source_bytes = await request.body()
                if not source_bytes:
                    raise HTTPException(status_code=400, detail="GeoTIFF payload is empty.")

                content_type = (request.headers.get("content-type") or "").lower()
                if content_type and "tiff" not in content_type and "octet-stream" not in content_type:
                    raise HTTPException(status_code=415, detail="Upload must be a TIFF/GeoTIFF payload.")

                bounds = GeoTiffBoundsRequest.model_validate(
                    {"north": north, "south": south, "east": east, "west": west}
                )
                preview_bytes, preview_meta = self._preview_image_from_geotiff(source_bytes, max_preview_size)
                asset = self.geotiff_assets.save_asset(
                    name=name,
                    source_filename=filename,
                    bounds=bounds.model_dump(),
                    source_bytes=source_bytes,
                    preview_bytes=preview_bytes,
                    preview_meta=preview_meta,
                    mime_type=(request.headers.get("content-type") or "image/tiff").split(";")[0].strip() or "image/tiff",
                )
                self._audit_command(action, "success", parameters=parameters, details={"asset_id": asset["asset_id"]})
                return StatusResponse(
                    status="success",
                    message="GeoTIFF uploaded",
                    data=self._geotiff_asset_response(asset),
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/mapping/geotiff",
            response_model=StatusResponse,
            tags=["Mapping"],
            dependencies=protected,
        )
        async def list_geotiff_assets():
            assets = [self._geotiff_asset_response(asset) for asset in self.geotiff_assets.list_assets()]
            return StatusResponse(
                status="success",
                message="GeoTIFF assets retrieved",
                data={"assets": assets},
            )

        @self.app.get(
            "/api/mapping/geotiff/{asset_id}",
            response_model=StatusResponse,
            tags=["Mapping"],
            dependencies=protected,
        )
        async def get_geotiff_asset(asset_id: str):
            metadata = self.geotiff_assets.get_asset(asset_id)
            if not metadata:
                raise HTTPException(status_code=404, detail="GeoTIFF asset not found.")
            return StatusResponse(
                status="success",
                message="GeoTIFF metadata retrieved",
                data=self._geotiff_asset_response(metadata),
            )

        @self.app.get(
            "/api/mapping/geotiff/{asset_id}/preview",
            tags=["Mapping"],
            dependencies=protected,
        )
        async def get_geotiff_preview(asset_id: str):
            metadata = self.geotiff_assets.get_asset(asset_id)
            if not metadata:
                raise HTTPException(status_code=404, detail="GeoTIFF asset not found.")
            preview_path = Path(metadata["preview_path"])
            if not preview_path.is_file():
                raise HTTPException(status_code=404, detail="GeoTIFF preview not found.")
            return FileResponse(preview_path, media_type="image/png")

        @self.app.delete(
            "/api/mapping/geotiff/{asset_id}",
            response_model=StatusResponse,
            tags=["Mapping"],
            dependencies=protected,
        )
        async def delete_geotiff_asset(asset_id: str, x_control_token: Optional[str] = Header(None)):
            action = "mapping.geotiff_delete"
            parameters = {"asset_id": asset_id}
            try:
                self._require_command_authority(x_control_token)
                removed = self.geotiff_assets.delete_asset(asset_id)
                if not removed:
                    raise HTTPException(status_code=404, detail="GeoTIFF asset not found.")
                self._audit_command(action, "success", parameters=parameters, details={"asset_id": asset_id})
                return StatusResponse(
                    status="success",
                    message="GeoTIFF asset deleted",
                    data={"asset_id": asset_id},
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/mapping/point-cloud/scan",
            response_model=StatusResponse,
            tags=["Mapping"],
            dependencies=protected,
        )
        async def generate_point_cloud_scan(request: PointCloudScanRequest, x_control_token: Optional[str] = Header(None)):
            action = "mapping.point_cloud_scan"
            parameters = request.model_dump(exclude_none=True)
            try:
                self._require_command_authority(x_control_token)
                boundary = self._field_boundary_from_request(request.field_boundary)
                scan_config = PointCloudScanConfig(**(request.scan_config or {}))
                points = self._mapping_planner().generate_point_cloud_scan(boundary, scan_config)
                self._audit_command(action, "success", parameters=parameters, details={"point_count": len(points)})
                return StatusResponse(
                    status="success",
                    message="Point cloud scan generated",
                    data={
                        "field_boundary": request.field_boundary.model_dump(),
                        "scan_config": {
                            "enabled": scan_config.enabled,
                            "altitude_levels_m": list(scan_config.altitude_levels_m),
                            "orbit_radius_m": scan_config.orbit_radius_m,
                            "perimeter_margin_m": scan_config.perimeter_margin_m,
                            "grid_spacing_m": scan_config.grid_spacing_m,
                            "include_center_pass": scan_config.include_center_pass,
                        },
                        "points": [point.to_dict() for point in points],
                    },
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/payload/control",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def control_payload(request: PayloadControlRequest, x_control_token: Optional[str] = Header(None)):
            parameters = request.model_dump()
            if request.action == PayloadAction.SPRAY_START:
                action = "payload.spray_start"
                try:
                    self._enforce_command_gates(action, x_control_token)
                    self._require_command_authority(x_control_token)
                    self._require_success(
                        self.payload_controller.arm_spray(
                            session=request.session,
                            telemetry_snapshot=self.telemetry_manager.get_current(),
                        ),
                        "Failed to activate spray.",
                    )
                    self._audit_command(action, "success", parameters=parameters)
                    return StatusResponse(status="success", message="Spray activated")
                except HTTPException as e:
                    self._audit_http_error(action, parameters, e)
                    raise

            if request.action == PayloadAction.SPRAY_STOP:
                action = "payload.spray_stop"
                try:
                    self._require_command_role()
                    self._require_success(
                        self.payload_controller.disarm_spray(
                            telemetry_snapshot=self.telemetry_manager.get_current(),
                        ),
                        "Failed to deactivate spray.",
                    )
                    self._audit_command(action, "success", parameters=parameters)
                    return StatusResponse(status="success", message="Spray deactivated")
                except HTTPException as e:
                    self._audit_http_error(action, parameters, e)
                    raise

            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            if request.action == PayloadAction.PHOTO:
                action = "payload.photo"
                try:
                    self._require_command_authority(x_control_token)
                    photo = self.payload_controller.camera.capture_photo(
                        session=request.session,
                        telemetry_snapshot=self.telemetry_manager.get_current(),
                    )
                    self._require_success(photo is not None, "Photo capture failed.")
                    photo_url = (
                        f"/api/payload/camera/sessions/{photo['session']}"
                        f"/photos/{photo['filename']}"
                    )
                    self._audit_command(
                        action,
                        "success",
                        parameters=parameters,
                        details={"filename": photo["filename"], "session": photo["session"]},
                    )
                    return StatusResponse(
                        status="success",
                        message="Photo captured",
                        data={
                            "filename": photo["filename"],
                            "path": photo["path"],
                            "session": photo["session"],
                            "url": photo_url,
                        },
                    )
                except HTTPException as e:
                    self._audit_http_error(action, parameters, e)
                    raise

            if request.action == PayloadAction.RECORD_START:
                action = "payload.record_start"
                try:
                    self._require_command_authority(x_control_token)
                    video_path = self.payload_controller.camera.build_video_recording_path(
                        session=request.session,
                    )
                    self._require_success(
                        self.payload_controller.camera.start_video_recording(str(video_path)),
                        "Video recording start failed.",
                    )
                    self._audit_command(action, "success", parameters=parameters)
                    return StatusResponse(
                        status="success",
                        message="Recording started",
                        data={
                            "filename": video_path.name,
                            "path": str(video_path),
                            "session": request.session or "default",
                        },
                    )
                except HTTPException as e:
                    self._audit_http_error(action, parameters, e)
                    raise

            action = "payload.record_stop"
            try:
                self._require_command_authority(x_control_token)
                self._require_success(
                    self.payload_controller.camera.stop_video_recording(),
                    "Video recording stop failed.",
                )
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(status="success", message="Recording stopped")
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/payload/status",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_payload_status():
            return StatusResponse(
                status="success",
                message="Payload status retrieved",
                data=self.payload_controller.get_payload_status(),
            )

        @self.app.get(
            "/api/payload/prescription/status",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_prescription_status():
            return StatusResponse(
                status="success",
                message="Prescription status retrieved",
                data=self._prescription_status_data(),
            )

        @self.app.get(
            "/api/payload/prescription/maps",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def list_prescription_maps():
            return StatusResponse(
                status="success",
                message="Prescription maps retrieved",
                data=self._prescription_maps_data(),
            )

        @self.app.post(
            "/api/payload/prescription/maps",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def import_prescription_map(request: PrescriptionImportRequest, x_control_token: Optional[str] = Header(None)):
            action = "payload.prescription_import"
            parameters = request.model_dump(mode="json")
            try:
                if not getattr(self.payload_controller, "prescription_controller", None):
                    raise HTTPException(status_code=503, detail="Prescription control is unavailable.")
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                result = self.payload_controller.import_prescription_map(
                    request.payload_text,
                    request.name,
                    source_format=request.source_format,
                    activate=request.activate,
                )
                self._audit_command(action, "success", parameters=parameters, details={"map_id": result.get("map_id")})
                return StatusResponse(
                    status="success",
                    message="Prescription map imported",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/payload/prescription/maps/activate",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def activate_prescription_map(request: PrescriptionActivateRequest, x_control_token: Optional[str] = Header(None)):
            action = "payload.prescription_activate"
            parameters = request.model_dump(mode="json")
            try:
                if not getattr(self.payload_controller, "prescription_controller", None):
                    raise HTTPException(status_code=503, detail="Prescription control is unavailable.")
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                result = self.payload_controller.activate_prescription_map(request.map_id)
                if not result:
                    raise HTTPException(status_code=404, detail="Prescription map not found.")
                self._audit_command(action, "success", parameters=parameters, details={"map_id": request.map_id})
                return StatusResponse(
                    status="success",
                    message="Prescription map activated",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/calibration/status",
            response_model=StatusResponse,
            tags=["Calibration"],
            dependencies=protected,
        )
        async def get_calibration_status():
            return StatusResponse(
                status="success",
                message="Calibration workflow status retrieved",
                data=self._calibration_status_data(),
            )

        @self.app.post(
            "/api/calibration/rtk/base-stations",
            response_model=StatusResponse,
            tags=["Calibration"],
            dependencies=protected,
        )
        async def save_base_station(request: BaseStationWizardRequest, x_control_token: Optional[str] = Header(None)):
            action = "calibration.base_station_save"
            parameters = request.model_dump(mode="json")
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                if not self.calibration_manager:
                    raise HTTPException(status_code=503, detail="Calibration workflows are unavailable.")
                result = self.calibration_manager.save_base_station(request.model_dump(mode="json"), activate=request.activate)
                self._audit_command(action, "success", parameters=parameters, details={"station_id": result.get("station_id")})
                return StatusResponse(
                    status="success",
                    message="Base station saved",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/calibration/rtk/base-stations/{station_id}/activate",
            response_model=StatusResponse,
            tags=["Calibration"],
            dependencies=protected,
        )
        async def activate_base_station(station_id: str, x_control_token: Optional[str] = Header(None)):
            action = "calibration.base_station_activate"
            parameters = {"station_id": station_id}
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                if not self.calibration_manager:
                    raise HTTPException(status_code=503, detail="Calibration workflows are unavailable.")
                result = self.calibration_manager.activate_base_station(station_id)
                if not result:
                    raise HTTPException(status_code=404, detail="Base station not found.")
                self._audit_command(action, "success", parameters=parameters, details={"station_id": station_id})
                return StatusResponse(
                    status="success",
                    message="Base station activated",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/calibration/ppk/process",
            response_model=StatusResponse,
            tags=["Calibration"],
            dependencies=protected,
        )
        async def process_ppk(request: PpkProcessRequest, x_control_token: Optional[str] = Header(None)):
            action = "calibration.ppk_process"
            parameters = request.model_dump(mode="json", exclude_none=True)
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                if not self.calibration_manager:
                    raise HTTPException(status_code=503, detail="Calibration workflows are unavailable.")
                result = self.calibration_manager.process_ppk_job(request.model_dump(mode="json"))
                self._audit_command(action, "success", parameters=parameters, details={"job_id": result.get("job_id")})
                return StatusResponse(
                    status="success",
                    message="PPK post-processing completed",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/farm/status",
            response_model=StatusResponse,
            tags=["Farm"],
            dependencies=protected,
        )
        async def get_farm_status():
            return StatusResponse(
                status="success",
                message="Farm integration status retrieved",
                data=self._farm_status_data(),
            )

        @self.app.post(
            "/api/farm/integrations/isoxml/export",
            response_model=StatusResponse,
            tags=["Farm"],
            dependencies=protected,
        )
        async def export_isoxml(request: FarmExportRequest, x_control_token: Optional[str] = Header(None)):
            action = "farm.isoxml_export"
            parameters = request.model_dump(mode="json")
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                if not self.farm_manager:
                    raise HTTPException(status_code=503, detail="Farm management integration is unavailable.")
                result = self.farm_manager.export_isoxml(session=request.session)
                self._audit_command(action, "success", parameters=parameters, details={"session": request.session})
                return StatusResponse(
                    status="success",
                    message="ISOXML export generated",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/farm/integrations/agleader/sync",
            response_model=StatusResponse,
            tags=["Farm"],
            dependencies=protected,
        )
        async def sync_agleader(request: FarmExportRequest, x_control_token: Optional[str] = Header(None)):
            action = "farm.agleader_sync"
            parameters = request.model_dump(mode="json")
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                if not self.farm_manager:
                    raise HTTPException(status_code=503, detail="Farm management integration is unavailable.")
                result = self.farm_manager.sync_agleader(session=request.session)
                self._audit_command(action, "success", parameters=parameters, details={"session": request.session})
                return StatusResponse(
                    status="success",
                    message="agLeader sync payload prepared",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.post(
            "/api/farm/reports/automated",
            response_model=StatusResponse,
            tags=["Farm"],
            dependencies=protected,
        )
        async def generate_automated_report(request: FarmExportRequest, x_control_token: Optional[str] = Header(None)):
            action = "farm.automated_report"
            parameters = request.model_dump(mode="json")
            try:
                self._require_command_authority(x_control_token, MAINTENANCE_ROLES)
                if not self.farm_manager:
                    raise HTTPException(status_code=503, detail="Farm management integration is unavailable.")
                result = self.farm_manager.generate_automated_report(session=request.session)
                self._audit_command(action, "success", parameters=parameters, details={"session": request.session})
                return StatusResponse(
                    status="success",
                    message="Automated farm report generated",
                    data=result,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/payload/spray/sessions",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_spray_sessions():
            sessions = self.payload_controller.list_spray_sessions()
            for session in sessions:
                session["url"] = f"/api/payload/spray/sessions/{session['session']}"

            return StatusResponse(
                status="success",
                message="Spray sessions retrieved",
                data={"sessions": sessions},
            )

        @self.app.get(
            "/api/payload/spray/sessions/{session}",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_spray_session(session: str):
            spray_session = self.payload_controller.get_spray_session(session)
            if not spray_session:
                raise HTTPException(status_code=404, detail="Spray session not found.")

            return StatusResponse(
                status="success",
                message="Spray session retrieved",
                data=spray_session,
            )

        @self.app.get(
            "/api/payload/spray/application-records",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def list_spray_application_records():
            return StatusResponse(
                status="success",
                message="Spray application records retrieved",
                data={"records": self.payload_controller.list_application_records()},
            )

        @self.app.get(
            "/api/payload/spray/sessions/{session}/application-record",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_spray_application_record(session: str):
            record = self.payload_controller.get_application_record(session)
            if not record:
                raise HTTPException(status_code=404, detail="Spray application record not found.")
            return StatusResponse(
                status="success",
                message="Spray application record retrieved",
                data=record,
            )

        @self.app.post(
            "/api/payload/spray/sessions/{session}/application-record",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def create_spray_application_record(
            session: str,
            request: SprayApplicationRecordRequest,
            x_control_token: Optional[str] = Header(None),
        ):
            action = "payload.application_record_create"
            parameters = {"session": session, **request.model_dump()}
            try:
                self._require_command_authority(x_control_token)
                metadata = request.model_dump(exclude_none=True)
                if request.field_name:
                    boundary = self.mission_planner.field_boundaries.get(request.field_name)
                    if boundary:
                        metadata["field_boundary"] = {
                            "name": boundary.name,
                            "altitude": boundary.altitude,
                            "vertices": [
                                {
                                    "latitude": vertex.latitude,
                                    "longitude": vertex.longitude,
                                    "altitude": getattr(vertex, "altitude", boundary.altitude),
                                }
                                for vertex in boundary.vertices
                            ],
                        }
                record = self.payload_controller.create_application_record(
                    session,
                    metadata=metadata,
                )
                if not record:
                    raise HTTPException(status_code=404, detail="Spray session not found.")
                self._audit_command(action, "success", parameters=parameters)
                return StatusResponse(
                    status="success",
                    message="Spray application record created",
                    data=record,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/payload/spray/sessions/{session}/geojson",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def export_spray_geojson(session: str):
            telemetry_history = self.telemetry_manager.get_history()
            geojson = self.payload_controller.application_records.export_geojson(
                session,
                telemetry_history=telemetry_history,
            )
            if not geojson:
                raise HTTPException(status_code=404, detail="Spray application record not found.")

            return StatusResponse(
                status="success",
                message="Spray GeoJSON exported",
                data=geojson,
            )

        @self.app.post(
            "/api/payload/spray/sessions/{session}/compliance-report",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def generate_spray_compliance_report(
            session: str,
            request: SprayComplianceReportRequest,
        ):
            telemetry_history = self.telemetry_manager.get_history()
            report = self.payload_controller.application_records.generate_compliance_report(
                session,
                operator_signature=request.operator_signature,
                signed_at=request.signed_at,
                report_format=request.report_format,
                telemetry_history=telemetry_history,
            )
            if not report:
                raise HTTPException(status_code=404, detail="Spray application record not found.")

            return StatusResponse(
                status="success",
                message="Spray compliance report generated",
                data=report,
            )

        @self.app.post(
            "/api/payload/camera/sessions/{session}/photos",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def capture_session_photo(session: str, x_control_token: Optional[str] = Header(None)):
            action = "payload.photo"
            parameters = {"session": session}
            if not self.payload_controller.camera:
                error = HTTPException(status_code=503, detail="Camera not available.")
                self._audit_http_error(action, parameters, error)
                raise error

            try:
                self._require_command_authority(x_control_token)
                photo = self.payload_controller.camera.capture_photo(
                    session=session,
                    telemetry_snapshot=self.telemetry_manager.get_current(),
                )
                self._require_success(photo is not None, "Photo capture failed.")
                photo["url"] = (
                    f"/api/payload/camera/sessions/{photo['session']}"
                    f"/photos/{photo['filename']}"
                )
                self._audit_command(
                    action,
                    "success",
                    parameters=parameters,
                    details={"filename": photo["filename"], "session": photo["session"]},
                )

                return StatusResponse(
                    status="success",
                    message="Photo captured",
                    data=photo,
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/payload/camera/sessions",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_photo_sessions():
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            sessions = self.payload_controller.camera.list_photo_sessions()
            for session_info in sessions:
                session_info["manifest_url"] = (
                    f"/api/payload/camera/sessions/{session_info['session']}/manifest"
                )
                session_info["photos_url"] = (
                    f"/api/payload/camera/sessions/{session_info['session']}/photos"
                )
                session_info["archive_url"] = (
                    f"/api/payload/camera/sessions/{session_info['session']}/archive"
                )
                latest_photo = session_info.get("latest_photo")
                if latest_photo:
                    latest_photo["url"] = (
                        f"/api/payload/camera/sessions/{latest_photo['session']}"
                        f"/photos/{latest_photo['filename']}"
                    )

            return StatusResponse(
                status="success",
                message="Photo sessions retrieved",
                data={"sessions": sessions},
            )

        @self.app.get(
            "/api/payload/camera/sessions/{session}/manifest",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_session_manifest(session: str):
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            manifest = self.payload_controller.camera.get_session_manifest(session)
            if manifest is None:
                raise HTTPException(status_code=404, detail="Photo session not found.")

            for photo in manifest.get("photos", []):
                photo["url"] = (
                    f"/api/payload/camera/sessions/{photo['session']}"
                    f"/photos/{photo['filename']}"
                )
            latest_photo = manifest.get("latest_photo")
            if latest_photo:
                latest_photo["url"] = (
                    f"/api/payload/camera/sessions/{latest_photo['session']}"
                    f"/photos/{latest_photo['filename']}"
                )

            manifest["archive_url"] = (
                f"/api/payload/camera/sessions/{manifest['session']}/archive"
            )

            return StatusResponse(
                status="success",
                message="Photo session manifest retrieved",
                data=manifest,
            )

        @self.app.get(
            "/api/payload/camera/sessions/{session}/photos",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_session_photos(session: str, limit: int = 100):
            if limit < 1 or limit > 500:
                raise HTTPException(status_code=400, detail="limit must be between 1 and 500.")
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            photos = self.payload_controller.camera.get_recent_photos(limit, session=session)
            for photo in photos:
                photo["url"] = (
                    f"/api/payload/camera/sessions/{photo['session']}"
                    f"/photos/{photo['filename']}"
                )

            return StatusResponse(
                status="success",
                message="Session photos retrieved",
                data={
                    "session": self.payload_controller.camera.sanitize_session(session),
                    "photos": photos,
                },
            )

        @self.app.delete(
            "/api/payload/camera/sessions/{session}/photos",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def reset_session_photos(session: str, x_control_token: Optional[str] = Header(None)):
            action = "payload.photos_reset"
            parameters = {"session": session}
            if not self.payload_controller.camera:
                error = HTTPException(status_code=503, detail="Camera not available.")
                self._audit_http_error(action, parameters, error)
                raise error

            try:
                self._require_command_authority(x_control_token)
                removed = self.payload_controller.camera.reset_photos(session=session)
                sanitized_session = self.payload_controller.camera.sanitize_session(session)
                self._audit_command(
                    action,
                    "success",
                    parameters=parameters,
                    details={"removed": removed, "session": sanitized_session},
                )
                return StatusResponse(
                    status="success",
                    message="Session photos reset",
                    data={
                        "removed": removed,
                        "session": sanitized_session,
                    },
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/payload/camera/sessions/{session}/archive",
            tags=["Payload"],
            dependencies=protected,
        )
        async def archive_session_photos(session: str):
            if not session.strip():
                raise HTTPException(status_code=400, detail="session is required.")
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            archive_file = tempfile.NamedTemporaryFile(
                prefix="drone_photos_",
                suffix=".zip",
                delete=False,
            )
            archive_path = archive_file.name
            archive_file.close()

            archive = self.payload_controller.camera.get_session_archive_path(
                session,
                archive_path,
            )
            if not archive:
                try:
                    os.unlink(archive_path)
                except OSError:
                    pass
                raise HTTPException(status_code=404, detail="Photo session not found or empty.")

            safe_session = self.payload_controller.camera.sanitize_session(session)
            return FileResponse(
                archive,
                media_type="application/zip",
                filename=f"{safe_session}_photos.zip",
                background=BackgroundTask(os.unlink, archive_path),
            )

        @self.app.get(
            "/api/payload/camera/sessions/{session}/photos/{filename}",
            tags=["Payload"],
            dependencies=protected_header_or_query,
        )
        async def get_session_photo(session: str, filename: str):
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            photo_path = self.payload_controller.camera.get_photo_path(filename, session=session)
            if not photo_path:
                raise HTTPException(status_code=404, detail="Photo not found.")

            return FileResponse(photo_path, media_type="image/jpeg")

        @self.app.get(
            "/api/payload/camera/photos",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def get_recent_camera_photos(limit: int = 10, session: Optional[str] = None):
            if limit < 1 or limit > 100:
                raise HTTPException(status_code=400, detail="limit must be between 1 and 100.")
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            photos = self.payload_controller.camera.get_recent_photos(limit, session=session)
            for photo in photos:
                photo["url"] = (
                    f"/api/payload/camera/sessions/{photo['session']}"
                    f"/photos/{photo['filename']}"
                )

            return StatusResponse(
                status="success",
                message="Recent photos retrieved",
                data={"photos": photos, "session": session},
            )

        @self.app.delete(
            "/api/payload/camera/photos",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def reset_camera_photos(session: Optional[str] = None, x_control_token: Optional[str] = Header(None)):
            action = "payload.photos_reset"
            parameters = {"session": session}
            if not self.payload_controller.camera:
                error = HTTPException(status_code=503, detail="Camera not available.")
                self._audit_http_error(action, parameters, error)
                raise error

            try:
                self._require_command_authority(x_control_token)
                removed = self.payload_controller.camera.reset_photos(session=session)
                self._audit_command(
                    action,
                    "success",
                    parameters=parameters,
                    details={"removed": removed, "session": session},
                )
                return StatusResponse(
                    status="success",
                    message="Photos reset",
                    data={"removed": removed, "session": session},
                )
            except HTTPException as e:
                self._audit_http_error(action, parameters, e)
                raise

        @self.app.get(
            "/api/payload/camera/photos/archive",
            tags=["Payload"],
            dependencies=protected,
        )
        async def archive_camera_photos(session: str):
            if not session.strip():
                raise HTTPException(status_code=400, detail="session is required.")
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            archive_file = tempfile.NamedTemporaryFile(
                prefix="drone_photos_",
                suffix=".zip",
                delete=False,
            )
            archive_path = archive_file.name
            archive_file.close()

            archive = self.payload_controller.camera.get_session_archive_path(
                session,
                archive_path,
            )
            if not archive:
                try:
                    os.unlink(archive_path)
                except OSError:
                    pass
                raise HTTPException(status_code=404, detail="Photo session not found or empty.")

            safe_session = self.payload_controller.camera.sanitize_session(session)
            return FileResponse(
                archive,
                media_type="application/zip",
                filename=f"{safe_session}_photos.zip",
                background=BackgroundTask(os.unlink, archive_path),
            )

        @self.app.get(
            "/api/payload/camera/photos/{filename}",
            tags=["Payload"],
            dependencies=protected_header_or_query,
        )
        async def get_camera_photo(filename: str, session: Optional[str] = None):
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            photo_path = self.payload_controller.camera.get_photo_path(filename, session=session)
            if not photo_path:
                raise HTTPException(status_code=404, detail="Photo not found.")

            return FileResponse(photo_path, media_type="image/jpeg")

        @self.app.get(
            "/api/payload/camera/stream",
            tags=["Payload"],
            dependencies=protected_header_or_query,
        )
        async def stream_camera(fps: int = 10, quality: int = 80):
            if fps < 1 or fps > 30:
                raise HTTPException(status_code=400, detail="fps must be between 1 and 30.")
            if quality < 1 or quality > 100:
                raise HTTPException(status_code=400, detail="quality must be between 1 and 100.")
            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            return StreamingResponse(
                self.payload_controller.camera.generate_mjpeg_frames(
                    fps=fps,
                    jpeg_quality=quality,
                ),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

        @self.app.get(
            "/api/telemetry/current",
            response_model=StatusResponse,
            tags=["Telemetry"],
            dependencies=protected,
        )
        async def get_current_telemetry():
            telemetry = self.telemetry_manager.get_current()
            if not telemetry:
                raise HTTPException(status_code=404, detail="No telemetry data available.")
            return StatusResponse(
                status="success",
                message="Current telemetry retrieved",
                data=telemetry,
            )

        @self.app.get(
            "/api/telemetry/history",
            response_model=StatusResponse,
            tags=["Telemetry"],
            dependencies=protected,
        )
        async def get_telemetry_history(seconds: Optional[int] = None):
            if seconds is not None and seconds <= 0:
                raise HTTPException(status_code=400, detail="seconds must be positive.")

            return StatusResponse(
                status="success",
                message="Telemetry history retrieved",
                data={"history": self.telemetry_manager.get_history(seconds)},
            )

        @self.app.get(
            "/api/telemetry/stats",
            response_model=StatusResponse,
            tags=["Telemetry"],
            dependencies=protected,
        )
        async def get_telemetry_stats(seconds: int = 60):
            if seconds <= 0:
                raise HTTPException(status_code=400, detail="seconds must be positive.")

            return StatusResponse(
                status="success",
                message="Telemetry statistics retrieved",
                data=self.telemetry_manager.get_statistics(seconds),
            )

        @self.app.websocket("/ws/telemetry")
        async def websocket_telemetry(websocket: WebSocket):
            if not await self._authorize_websocket(websocket):
                return

            await websocket.accept()
            client_id = id(websocket)
            loop = asyncio.get_running_loop()
            self.active_websocket_clients.add(websocket)

            try:
                self.telemetry_manager.subscribe(
                    str(client_id),
                    lambda data: asyncio.run_coroutine_threadsafe(
                        self._send_ws(websocket, data),
                        loop,
                    ),
                )

                while True:
                    try:
                        await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    except asyncio.TimeoutError:
                        continue
                    except WebSocketDisconnect:
                        break

            except Exception as e:
                logger.error(f"WebSocket error: {str(e)}")
            finally:
                self.active_websocket_clients.discard(websocket)
                self.telemetry_manager.unsubscribe(str(client_id))
                try:
                    await websocket.close()
                except Exception:
                    pass

        @self.app.websocket("/ws/swarm")
        async def websocket_swarm(websocket: WebSocket):
            if not await self._authorize_websocket(websocket):
                return

            await websocket.accept()
            client_id = f"swarm-{id(websocket)}"
            loop = asyncio.get_running_loop()

            manager = self._swarm_manager_or_none()
            if not manager:
                await websocket.close(code=1011, reason="Swarm management is unavailable.")
                return

            try:
                manager.subscribe(
                    client_id,
                    lambda event: asyncio.run_coroutine_threadsafe(
                        self._send_ws(websocket, event),
                        loop,
                    ),
                )

                while True:
                    try:
                        await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    except asyncio.TimeoutError:
                        continue
                    except WebSocketDisconnect:
                        break

            except Exception as e:
                logger.error(f"Swarm WebSocket error: {str(e)}")
            finally:
                manager.unsubscribe(client_id)
                try:
                    await websocket.close()
                except Exception:
                    pass

        @self.app.websocket("/ws/events")
        async def websocket_events(websocket: WebSocket):
            if not await self._authorize_websocket(websocket):
                return

            await websocket.accept()
            client_id = str(id(websocket))
            loop = asyncio.get_running_loop()
            self.active_event_websocket_clients.add(websocket)

            try:
                self._subscribe_command_events(
                    client_id,
                    lambda event: asyncio.run_coroutine_threadsafe(
                        self._send_ws(websocket, event),
                        loop,
                    ),
                )

                while True:
                    try:
                        await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    except asyncio.TimeoutError:
                        continue
                    except WebSocketDisconnect:
                        break

            except Exception as e:
                logger.error(f"Command event WebSocket error: {str(e)}")
            finally:
                self.active_event_websocket_clients.discard(websocket)
                self._unsubscribe_command_events(client_id)
                try:
                    await websocket.close()
                except Exception:
                    pass

    async def _send_ws(self, websocket: WebSocket, data: dict):
        """Send WebSocket message"""
        try:
            if isinstance(data, str):
                await websocket.send_text(data)
            else:
                await websocket.send_json(data)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {str(e)}")

    def get_app(self):
        """Get FastAPI application"""
        return self.app
