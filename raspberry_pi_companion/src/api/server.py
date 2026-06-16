"""
FastAPI REST and WebSocket Server
Main API interface for ground station communication
"""

import asyncio
import hmac
import logging
import os
import secrets
import shutil
import tempfile
import threading
import time
from enum import Enum
from typing import Dict, List, Optional, Set

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Security, WebSocket, WebSocketDisconnect
from fastapi.routing import APIRoute
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask

from ..audit.logger import AuditLogger
from ..config.settings import config

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

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


class ObstacleAvoidanceBehaviorRequest(str, Enum):
    STOP = "stop"
    SLIDE = "slide"


class BendyRulerTypeRequest(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class TerrainSourceRequest(str, Enum):
    RANGEFINDER = "rangefinder"
    TERRAIN_DATABASE = "terrain_database"


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


class TerrainFollowingSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    source: Optional[TerrainSourceRequest] = None
    min_agl_meters: Optional[float] = Field(None, ge=0.0, le=config.mission.max_altitude)
    max_agl_meters: Optional[float] = Field(None, gt=0.0, le=config.mission.max_altitude)
    target_agl_meters: Optional[float] = Field(None, ge=0.0, le=config.mission.max_altitude)
    use_rangefinder_for_waypoints: Optional[bool] = None
    rtl_terrain_enabled: Optional[bool] = None
    terrain_spacing_meters: Optional[float] = Field(None, gt=0.0, le=1000.0)


class NavigationConfigRequest(BaseModel):
    obstacle_avoidance: Optional[ObstacleAvoidanceSettingsRequest] = None
    terrain_following: Optional[TerrainFollowingSettingsRequest] = None
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


class ControlAuthorityRequest(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=80)
    operator: Optional[str] = Field(None, max_length=120)
    force: bool = False
    lease_seconds: Optional[int] = Field(None, ge=5, le=300)


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

    def __init__(self, connection_manager, mission_planner, payload_controller, telemetry_manager):
        self.connection_manager = connection_manager
        self.mission_planner = mission_planner
        self.payload_controller = payload_controller
        self.telemetry_manager = telemetry_manager
        self.active_websocket_clients: Set[WebSocket] = set()
        self.audit_logger = AuditLogger(config.api.audit_log_file)
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
        )
        self._setup_middleware()
        self._setup_routes()
        self._setup_versioned_api_aliases()

        if config.api.auth_enabled and not config.api.api_key:
            logger.warning("API authentication is enabled, but API_KEY is not configured.")

    def _setup_middleware(self):
        """Setup CORS and other middleware"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=config.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _require_api_key(self, api_key: Optional[str] = Security(api_key_header)):
        """Validate the shared API key for control endpoints."""
        self._require_api_key_value(api_key)

    def _require_api_key_header_or_query(
        self,
        request: Request,
        api_key: Optional[str] = Security(api_key_header),
    ):
        """Validate API key supplied by header or query parameter."""
        self._require_api_key_value(api_key or request.query_params.get("api_key"))

    def _require_api_key_value(self, api_key: Optional[str]):
        """Validate a supplied shared API key."""
        if not config.api.auth_enabled:
            return

        if not config.api.api_key:
            raise HTTPException(
                status_code=503,
                detail="API_KEY is not configured on the companion computer.",
            )

        if not api_key or not hmac.compare_digest(api_key, config.api.api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key.")

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

    def _get_readiness_data(self) -> Dict:
        vehicle_state = self.connection_manager.get_vehicle_state()
        prearm_status = self.connection_manager.get_prearm_status()
        payload_status = self.payload_controller.get_payload_status()
        navigation_config = self._get_navigation_config()
        navigation_status = self._get_navigation_status()
        obstacle_config = navigation_config.get("obstacle_avoidance", {})
        terrain_config = navigation_config.get("terrain_following", {})

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
            "navigation_config": navigation_config,
            "navigation_status": navigation_status,
            "terrain": (prearm_status or {}).get("terrain"),
            "spray_pump_status": payload_status.get("spray_pump", {}).get("status"),
            "storage": storage,
            "auth_enabled": config.api.auth_enabled,
            "api_key_configured": bool(config.api.api_key),
            "safety_gates_enabled": config.api.safety_gates_enabled,
            "telemetry_freshness_enabled": config.api.telemetry_freshness_enabled,
            "telemetry_last_update": getattr(self.telemetry_manager, "last_update", 0),
            "telemetry_stale_seconds": config.api.telemetry_stale_seconds,
        }
        last_update = checks["telemetry_last_update"]
        checks["telemetry_age_seconds"] = time.time() - last_update if last_update else None
        checks["blocking_reasons"] = self._get_readiness_blockers(checks)
        return ReadinessCheck(ready=not checks["blocking_reasons"], checks=checks).model_dump()

    def _get_readiness_blockers(self, checks: Dict) -> List[str]:
        gps = checks["gps"] or {}
        blocking_reasons = []
        if not checks["pixhawk_connected"]:
            blocking_reasons.append("Pixhawk is not connected.")
        if not checks["vehicle_status_available"]:
            blocking_reasons.append("Vehicle status is unavailable.")
        if checks["is_armable"] is False:
            blocking_reasons.append("Vehicle is not armable.")
        if checks["ekf_ok"] is False:
            blocking_reasons.append("EKF is not healthy.")
        if gps and gps.get("fix_type", 0) < 3:
            blocking_reasons.append("GPS does not have a 3D fix.")
        if checks["camera_expected"] and not checks["camera_available"]:
            blocking_reasons.append("Camera is enabled but unavailable.")
        if checks["camera_trigger_expected"] and not checks["camera_trigger_available"]:
            blocking_reasons.append("Camera trigger is enabled but unavailable.")
        if checks["flow_sensor_expected"] and not checks["flow_sensor_available"]:
            blocking_reasons.append("Flow sensor is enabled but unavailable.")
        if checks["pressure_sensor_expected"] and not checks["pressure_sensor_available"]:
            blocking_reasons.append("Pressure sensor is enabled but unavailable.")
        if checks["tank_level_sensor_expected"] and not checks["tank_level_sensor_available"]:
            blocking_reasons.append("Tank level sensor is enabled but unavailable.")
        tank_level = checks.get("tank_level") or {}
        if tank_level.get("is_below_minimum"):
            blocking_reasons.append("Tank level is below configured minimum.")
        terrain_config = (checks.get("navigation_config") or {}).get("terrain_following", {})
        terrain_status = checks.get("terrain") or {}
        if (
            checks["terrain_following_expected"]
            and terrain_config.get("source") == "rangefinder"
            and terrain_status.get("rangefinder_distance_meters") is None
        ):
            blocking_reasons.append("Terrain following is enabled but rangefinder terrain data is unavailable.")
        if checks["spray_pump_status"] == "error":
            blocking_reasons.append("Spray pump is in error state.")
        if checks["storage"] is not None and "error" in checks["storage"]:
            blocking_reasons.append("Storage check failed.")
        if config.api.auth_enabled and not checks["api_key_configured"]:
            blocking_reasons.append("API auth is enabled but API_KEY is not configured.")
        telemetry_age = checks.get("telemetry_age_seconds")
        if (
            config.api.telemetry_freshness_enabled
            and (telemetry_age is None or telemetry_age > config.api.telemetry_stale_seconds)
        ):
            blocking_reasons.append("Vehicle telemetry is stale or unavailable.")
        return blocking_reasons

    def _get_safety_blockers(self, command: str) -> List[str]:
        if not config.api.safety_gates_enabled:
            return []

        readiness = self._get_readiness_data()
        checks = readiness["checks"]
        gps = checks.get("gps") or {}
        blockers = []

        if command in {"vehicle.arm", "vehicle.takeoff", "vehicle.goto", "mission.start", "payload.spray_start"}:
            if not checks["pixhawk_connected"]:
                blockers.append("Pixhawk is not connected.")
            if not checks["vehicle_status_available"]:
                blockers.append("Vehicle status is unavailable.")
            if checks["ekf_ok"] is False:
                blockers.append("EKF is not healthy.")
            if gps and gps.get("fix_type", 0) < 3:
                blockers.append("GPS does not have a 3D fix.")
            terrain_config = (checks.get("navigation_config") or {}).get("terrain_following", {})
            terrain_status = checks.get("terrain") or {}
            if (
                checks.get("terrain_following_expected")
                and terrain_config.get("source") == "rangefinder"
                and terrain_status.get("rangefinder_distance_meters") is None
            ):
                blockers.append("Terrain following is enabled but rangefinder terrain data is unavailable.")

        if command in {"vehicle.arm", "vehicle.takeoff", "mission.start"}:
            if checks["is_armable"] is False:
                blockers.append("Vehicle is not armable.")

        if command == "payload.spray_start":
            if checks["flow_sensor_expected"] and not checks["flow_sensor_available"]:
                blockers.append("Flow sensor is enabled but unavailable.")
            if checks["pressure_sensor_expected"] and not checks["pressure_sensor_available"]:
                blockers.append("Pressure sensor is enabled but unavailable.")
            if checks["tank_level_sensor_expected"] and not checks["tank_level_sensor_available"]:
                blockers.append("Tank level sensor is enabled but unavailable.")
            tank_level = checks.get("tank_level") or {}
            if tank_level.get("is_below_minimum"):
                blockers.append("Tank level is below configured minimum.")
            if checks["spray_pump_status"] == "error":
                blockers.append("Spray pump is in error state.")

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

    def _require_command_authority(self, token: Optional[str]):
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

    def _audit_command(
        self,
        action: str,
        outcome: str,
        parameters: Optional[Dict] = None,
        details: Optional[Dict] = None,
    ):
        try:
            self.audit_logger.record(action, outcome, parameters=parameters, details=details)
        except Exception as e:
            logger.error(f"Failed to write audit event: {str(e)}")

    def _audit_http_error(self, action: str, parameters: Dict, error: HTTPException):
        outcome = "blocked" if error.status_code == 409 else "failed"
        details = {"status_code": error.status_code, "detail": error.detail}
        self._audit_command(action, outcome, parameters=parameters, details=details)

    def _setup_versioned_api_aliases(self):
        """Expose /api/v1 aliases while preserving existing /api paths."""
        existing_paths = {route.path for route in self.app.routes}
        for route in list(self.app.routes):
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
                continue

            versioned_path = route.path.replace("/api/", "/api/v1/", 1)
            if versioned_path in existing_paths:
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
                methods=list(route.methods or []),
                operation_id=f"v1_{route.operation_id}" if route.operation_id else None,
                include_in_schema=True,
                response_class=route.response_class,
                name=f"v1_{route.name}",
            )
            existing_paths.add(versioned_path)

    def _setup_routes(self):
        """Setup all API routes"""

        protected = [Depends(self._require_api_key)]
        protected_header_or_query = [Depends(self._require_api_key_header_or_query)]

        @self.app.get("/health", tags=["System"])
        async def health_check():
            return {
                "status": "ok",
                "connected": self.connection_manager.connected,
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
                        "telemetry_freshness_enabled": config.api.telemetry_freshness_enabled,
                        "telemetry_stale_seconds": config.api.telemetry_stale_seconds,
                        "payload_stale_seconds": config.api.payload_stale_seconds,
                        "audit_log_file": config.api.audit_log_file,
                        "cors_origins": config.api.cors_origins,
                    },
                    "mavlink": {
                        "connection_type": config.mavlink.connection_type.value,
                        "port": config.mavlink.port,
                        "baudrate": config.mavlink.baudrate,
                        "udp_ip": config.mavlink.udp_ip,
                        "udp_port": config.mavlink.udp_port,
                        "udp_direction": config.mavlink.udp_direction,
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
                        },
                        "terrain_following_defaults": {
                            "target_agl_meters": config.mission.terrain_target_agl_meters,
                            "use_rangefinder_for_waypoints": config.mission.terrain_use_rangefinder_for_waypoints,
                            "rtl_terrain_enabled": config.mission.terrain_rtl_enabled,
                            "terrain_spacing_meters": config.mission.terrain_spacing_meters,
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
                },
            )

        @self.app.get(
            "/api/system/audit",
            response_model=StatusResponse,
            tags=["System"],
            dependencies=protected,
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
            authority = self.control_authority.acquire(
                request.client_id,
                operator=request.operator,
                force=request.force,
                lease_seconds=request.lease_seconds,
            )
            self._audit_command(
                "control.authority_acquire",
                "success",
                parameters=request.model_dump(exclude={"force"}),
                details={"forced": request.force},
            )
            return StatusResponse(
                status="success",
                message="Control authority acquired",
                data=authority,
            )

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
            authority = self.control_authority.renew(
                x_control_token,
                lease_seconds=request.lease_seconds,
            )
            self._audit_command(
                "control.authority_renew",
                "success",
                parameters={"client_id": request.client_id, "operator": request.operator},
            )
            return StatusResponse(
                status="success",
                message="Control authority renewed",
                data=authority,
            )

        @self.app.delete(
            "/api/control/authority",
            response_model=StatusResponse,
            tags=["Control"],
            dependencies=protected,
        )
        async def release_control_authority(x_control_token: Optional[str] = Header(None)):
            released = self.control_authority.release(x_control_token)
            self._audit_command(
                "control.authority_release",
                "success",
                details=released,
            )
            return StatusResponse(
                status="success",
                message="Control authority released",
                data=released,
            )

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
                self._require_command_authority(x_control_token)
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
                self._require_command_authority(x_control_token)
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

        @self.app.post(
            "/api/emergency/hold",
            response_model=StatusResponse,
            tags=["Emergency"],
            dependencies=protected,
        )
        async def emergency_hold():
            action = "emergency.hold"
            try:
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
            self._require_command_authority(x_control_token)
            self.mission_planner.pause_mission()
            self._audit_command(action, "success", parameters=parameters)
            return StatusResponse(status="success", message="Mission paused")

        @self.app.post(
            "/api/mission/resume",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def resume_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.resume"
            parameters = {}
            self._require_command_authority(x_control_token)
            self.mission_planner.resume_mission()
            self._audit_command(action, "success", parameters=parameters)
            return StatusResponse(status="success", message="Mission resumed")

        @self.app.post(
            "/api/mission/abort",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def abort_mission(x_control_token: Optional[str] = Header(None)):
            action = "mission.abort"
            parameters = {}
            self._require_command_authority(x_control_token)
            self.mission_planner.abort_mission()
            self._audit_command(action, "success", parameters=parameters)
            return StatusResponse(status="success", message="Mission aborted")

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
            result = self.connection_manager.verify_mission(self.mission_planner.mission_items)
            self._require_success(result.get("success"), "Pixhawk mission verification failed.")
            return StatusResponse(status="success", message="Pixhawk mission verification completed", data=result)

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
                    self._require_success(
                        self.payload_controller.camera.start_video_recording("/tmp/video.mp4"),
                        "Video recording start failed.",
                    )
                    self._audit_command(action, "success", parameters=parameters)
                    return StatusResponse(status="success", message="Recording started")
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
                record = self.payload_controller.create_application_record(
                    session,
                    metadata=request.model_dump(exclude_none=True),
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
            if config.api.auth_enabled:
                supplied_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
                if not config.api.api_key:
                    await websocket.close(code=1011, reason="API_KEY is not configured.")
                    return
                if not supplied_key or not hmac.compare_digest(supplied_key, config.api.api_key):
                    await websocket.close(code=1008, reason="Invalid or missing API key.")
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

    async def _send_ws(self, websocket: WebSocket, data: dict):
        """Send WebSocket message"""
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {str(e)}")

    def get_app(self):
        """Get FastAPI application"""
        return self.app
