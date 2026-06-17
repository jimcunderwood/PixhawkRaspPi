"""
FastAPI REST and WebSocket Server
Main API interface for ground station communication
"""

import asyncio
import hashlib
import hmac
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
from typing import Callable, Dict, List, Optional, Set

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Security, WebSocket, WebSocketDisconnect
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
        self.active_event_websocket_clients: Set[WebSocket] = set()
        self.command_event_subscribers: Dict[str, Callable[[Dict], object]] = {}
        self.command_event_lock = threading.Lock()
        self.idempotency_records: Dict[str, Dict] = {}
        self.idempotency_lock = threading.Lock()
        self.audit_logger = AuditLogger(config.api.audit_log_file)
        self.config_profiles = ConfigProfileStore(config.api.config_database_file)
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
            self.audit_logger = AuditLogger(config.api.audit_log_file)
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
            "api_key_configured": bool(self._configured_api_key_roles()),
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
                        "idempotency_ttl_seconds": config.api.idempotency_ttl_seconds,
                        "roles": [role.value for role in ApiRole],
                        "telemetry_freshness_enabled": config.api.telemetry_freshness_enabled,
                        "telemetry_stale_seconds": config.api.telemetry_stale_seconds,
                        "payload_stale_seconds": config.api.payload_stale_seconds,
                        "audit_log_file": config.api.audit_log_file,
                        "config_database_file": config.api.config_database_file,
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
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {str(e)}")

    def get_app(self):
        """Get FastAPI application"""
        return self.app
