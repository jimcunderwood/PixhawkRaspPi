"""
FastAPI REST and WebSocket Server
Main API interface for ground station communication
"""

import asyncio
import hmac
import logging
from enum import Enum
from typing import Dict, List, Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Security, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

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


class WaypointRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude: float = Field(
        ...,
        ge=config.mission.min_altitude,
        le=config.mission.max_altitude,
    )


class ArmRequest(BaseModel):
    arm: bool


class TakeoffRequest(BaseModel):
    altitude: float = Field(
        ...,
        ge=config.mission.min_altitude,
        le=config.mission.max_altitude,
    )


class LandRequest(BaseModel):
    pass


class GoToRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude: float = Field(
        ...,
        ge=config.mission.min_altitude,
        le=config.mission.max_altitude,
    )


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


class PayloadAction(str, Enum):
    SPRAY_START = "spray_start"
    SPRAY_STOP = "spray_stop"
    PHOTO = "photo"
    RECORD_START = "record_start"
    RECORD_STOP = "record_stop"


class PayloadControlRequest(BaseModel):
    action: PayloadAction


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


class ServerAPI:
    """REST and WebSocket API Server"""

    def __init__(self, connection_manager, mission_planner, payload_controller, telemetry_manager):
        self.connection_manager = connection_manager
        self.mission_planner = mission_planner
        self.payload_controller = payload_controller
        self.telemetry_manager = telemetry_manager
        self.active_websocket_clients: Set[WebSocket] = set()

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

    def _setup_routes(self):
        """Setup all API routes"""

        protected = [Depends(self._require_api_key)]

        @self.app.get("/health", tags=["System"])
        async def health_check():
            return {
                "status": "ok",
                "connected": self.connection_manager.connected,
                "auth_enabled": config.api.auth_enabled,
            }

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

        @self.app.post(
            "/api/vehicle/arm",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def arm_vehicle(request: ArmRequest):
            if request.arm:
                self._require_success(self.connection_manager.arm(), "Failed to arm vehicle.")
                return StatusResponse(status="success", message="Vehicle armed")

            self._require_success(self.connection_manager.disarm(), "Failed to disarm vehicle.")
            return StatusResponse(status="success", message="Vehicle disarmed")

        @self.app.post(
            "/api/vehicle/takeoff",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def takeoff(request: TakeoffRequest):
            self._require_success(self.connection_manager.takeoff(request.altitude), "Takeoff failed.")
            return StatusResponse(
                status="success",
                message=f"Takeoff initiated to {request.altitude}m",
            )

        @self.app.post(
            "/api/vehicle/land",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def land(request: Optional[LandRequest] = None):
            self._require_success(self.connection_manager.land(), "Landing command failed.")
            return StatusResponse(status="success", message="Landing initiated")

        @self.app.post(
            "/api/vehicle/goto",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def goto_location(request: GoToRequest):
            self._require_success(
                self.connection_manager.goto_location(
                    request.latitude,
                    request.longitude,
                    request.altitude,
                ),
                "Goto command failed.",
            )
            return StatusResponse(
                status="success",
                message=f"Flying to {request.latitude}, {request.longitude}",
            )

        @self.app.post(
            "/api/vehicle/mode",
            response_model=StatusResponse,
            tags=["Vehicle"],
            dependencies=protected,
        )
        async def change_mode(request: ModeChangeRequest):
            self._require_success(
                self.connection_manager.set_mode(request.mode),
                "Mode change failed.",
            )
            return StatusResponse(status="success", message=f"Mode changed to {request.mode}")

        @self.app.post(
            "/api/mission/add-waypoint",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def add_waypoint(request: WaypointRequest):
            self._require_success(
                self.mission_planner.add_waypoint(
                    request.latitude,
                    request.longitude,
                    request.altitude,
                ),
                "Failed to add waypoint.",
                status_code=400,
            )
            return StatusResponse(status="success", message="Waypoint added")

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
                data={"waypoints": self.mission_planner.get_mission()},
            )

        @self.app.post(
            "/api/mission/clear",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def clear_mission():
            self.mission_planner.clear_mission()
            return StatusResponse(status="success", message="Mission cleared")

        @self.app.post(
            "/api/mission/start",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def start_mission():
            self._require_success(
                self.mission_planner.start_mission(),
                "Failed to start mission. Add at least one waypoint first.",
                status_code=400,
            )
            return StatusResponse(status="success", message="Mission tracking started")

        @self.app.post(
            "/api/mission/pause",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def pause_mission():
            self.mission_planner.pause_mission()
            return StatusResponse(status="success", message="Mission paused")

        @self.app.post(
            "/api/mission/resume",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def resume_mission():
            self.mission_planner.resume_mission()
            return StatusResponse(status="success", message="Mission resumed")

        @self.app.post(
            "/api/mission/abort",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def abort_mission():
            self.mission_planner.abort_mission()
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
            "/api/field-boundaries",
            response_model=StatusResponse,
            tags=["Mission"],
            dependencies=protected,
        )
        async def add_field_boundary(request: FieldBoundaryRequest):
            from ..missions.planner import FieldBoundary, GeoPoint

            vertices = [GeoPoint(vertex.latitude, vertex.longitude) for vertex in request.vertices]
            boundary = FieldBoundary(request.name, vertices, request.altitude)

            self._require_success(
                self.mission_planner.add_field_boundary(boundary),
                "Failed to add field boundary.",
                status_code=400,
            )
            return StatusResponse(status="success", message="Field boundary added")

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

        @self.app.post(
            "/api/payload/control",
            response_model=StatusResponse,
            tags=["Payload"],
            dependencies=protected,
        )
        async def control_payload(request: PayloadControlRequest):
            if request.action == PayloadAction.SPRAY_START:
                self._require_success(
                    self.payload_controller.arm_spray(),
                    "Failed to activate spray.",
                )
                return StatusResponse(status="success", message="Spray activated")

            if request.action == PayloadAction.SPRAY_STOP:
                self._require_success(
                    self.payload_controller.disarm_spray(),
                    "Failed to deactivate spray.",
                )
                return StatusResponse(status="success", message="Spray deactivated")

            if not self.payload_controller.camera:
                raise HTTPException(status_code=503, detail="Camera not available.")

            if request.action == PayloadAction.PHOTO:
                self._require_success(
                    self.payload_controller.camera.capture_photo("/tmp/photo.jpg"),
                    "Photo capture failed.",
                )
                return StatusResponse(status="success", message="Photo captured")

            if request.action == PayloadAction.RECORD_START:
                self._require_success(
                    self.payload_controller.camera.start_video_recording("/tmp/video.mp4"),
                    "Video recording start failed.",
                )
                return StatusResponse(status="success", message="Recording started")

            self._require_success(
                self.payload_controller.camera.stop_video_recording(),
                "Video recording stop failed.",
            )
            return StatusResponse(status="success", message="Recording stopped")

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
