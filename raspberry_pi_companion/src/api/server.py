"""
FastAPI REST and WebSocket Server
Main API interface for ground station communication
"""

import logging
import asyncio
from typing import Set, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Pydantic Models for API

class StatusResponse(BaseModel):
    status: str
    message: str
    data: Dict = None


class VehicleStateResponse(BaseModel):
    armed: bool
    mode: str
    location: Dict
    attitude: Dict
    battery: Dict
    velocity: Dict


class WaypointRequest(BaseModel):
    latitude: float
    longitude: float
    altitude: float


class MissionRequest(BaseModel):
    waypoints: list


class PayloadControlRequest(BaseModel):
    action: str  # spray_start, spray_stop, photo, record_start, record_stop


class ArmRequest(BaseModel):
    arm: bool


class TakeoffRequest(BaseModel):
    altitude: float


class LandRequest(BaseModel):
    pass


class GoToRequest(BaseModel):
    latitude: float
    longitude: float
    altitude: float


class ModeChangeRequest(BaseModel):
    mode: str


class FieldBoundaryRequest(BaseModel):
    name: str
    vertices: list  # List of [lat, lon] pairs
    altitude: float = 0.0


class ServerAPI:
    """REST and WebSocket API Server"""

    def __init__(self, connection_manager, mission_planner, payload_controller, telemetry_manager):
        self.connection_manager = connection_manager
        self.mission_planner = mission_planner
        self.payload_controller = payload_controller
        self.telemetry_manager = telemetry_manager
        self.active_websocket_clients: Set[WebSocket] = set()
        
        self.app = FastAPI(title="Agricultural Drone API")
        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self):
        """Setup CORS and other middleware"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        """Setup all API routes"""
        
        # Health Check
        @self.app.get("/health")
        async def health_check():
            return {
                "status": "ok",
                "connected": self.connection_manager.connected,
            }

        # Vehicle Status
        @self.app.get("/api/vehicle/status")
        async def get_vehicle_status():
            state = self.connection_manager.get_vehicle_state()
            if state:
                return StatusResponse(status="success", message="Vehicle status retrieved", data=state)
            return StatusResponse(status="error", message="Unable to get vehicle status")

        # Arm/Disarm
        @self.app.post("/api/vehicle/arm")
        async def arm_vehicle(request: ArmRequest):
            try:
                if request.arm:
                    if self.connection_manager.arm():
                        return StatusResponse(status="success", message="Vehicle armed")
                    return StatusResponse(status="error", message="Failed to arm vehicle")
                else:
                    if self.connection_manager.disarm():
                        return StatusResponse(status="success", message="Vehicle disarmed")
                    return StatusResponse(status="error", message="Failed to disarm vehicle")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Takeoff
        @self.app.post("/api/vehicle/takeoff")
        async def takeoff(request: TakeoffRequest):
            try:
                if self.connection_manager.takeoff(request.altitude):
                    return StatusResponse(
                        status="success", 
                        message=f"Takeoff initiated to {request.altitude}m"
                    )
                return StatusResponse(status="error", message="Takeoff failed")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Land
        @self.app.post("/api/vehicle/land")
        async def land(request: LandRequest = None):
            try:
                if self.connection_manager.land():
                    return StatusResponse(status="success", message="Landing initiated")
                return StatusResponse(status="error", message="Landing failed")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Go To Location
        @self.app.post("/api/vehicle/goto")
        async def goto_location(request: GoToRequest):
            try:
                if self.connection_manager.goto_location(
                    request.latitude, request.longitude, request.altitude
                ):
                    return StatusResponse(
                        status="success",
                        message=f"Flying to {request.latitude}, {request.longitude}"
                    )
                return StatusResponse(status="error", message="Goto failed")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Change Mode
        @self.app.post("/api/vehicle/mode")
        async def change_mode(request: ModeChangeRequest):
            try:
                if self.connection_manager.set_mode(request.mode):
                    return StatusResponse(status="success", message=f"Mode changed to {request.mode}")
                return StatusResponse(status="error", message="Mode change failed")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Mission Planning - Waypoints
        @self.app.post("/api/mission/add-waypoint")
        async def add_waypoint(request: WaypointRequest):
            try:
                if self.mission_planner.add_waypoint(
                    request.latitude, request.longitude, request.altitude
                ):
                    return StatusResponse(status="success", message="Waypoint added")
                return StatusResponse(status="error", message="Failed to add waypoint")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.get("/api/mission/waypoints")
        async def get_mission():
            try:
                mission = self.mission_planner.get_mission()
                return StatusResponse(
                    status="success",
                    message="Mission retrieved",
                    data=mission
                )
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.post("/api/mission/clear")
        async def clear_mission():
            try:
                self.mission_planner.clear_mission()
                return StatusResponse(status="success", message="Mission cleared")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.post("/api/mission/start")
        async def start_mission():
            try:
                if self.mission_planner.start_mission():
                    return StatusResponse(status="success", message="Mission started")
                return StatusResponse(status="error", message="Failed to start mission")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.post("/api/mission/pause")
        async def pause_mission():
            try:
                self.mission_planner.pause_mission()
                return StatusResponse(status="success", message="Mission paused")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.post("/api/mission/resume")
        async def resume_mission():
            try:
                self.mission_planner.resume_mission()
                return StatusResponse(status="success", message="Mission resumed")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.post("/api/mission/abort")
        async def abort_mission():
            try:
                self.mission_planner.abort_mission()
                return StatusResponse(status="success", message="Mission aborted")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.get("/api/mission/stats")
        async def get_mission_stats():
            try:
                stats = self.mission_planner.get_statistics()
                return StatusResponse(
                    status="success",
                    message="Mission statistics retrieved",
                    data=stats
                )
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Field Boundaries
        @self.app.post("/api/field-boundaries")
        async def add_field_boundary(request: FieldBoundaryRequest):
            try:
                from ..missions.planner import GeoPoint, FieldBoundary
                
                vertices = [GeoPoint(lat, lon) for lat, lon in request.vertices]
                boundary = FieldBoundary(request.name, vertices, request.altitude)
                
                if self.mission_planner.add_field_boundary(boundary):
                    return StatusResponse(status="success", message="Field boundary added")
                return StatusResponse(status="error", message="Failed to add field boundary")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.get("/api/field-boundaries")
        async def get_field_boundaries():
            try:
                boundaries = self.mission_planner.get_field_boundaries()
                return StatusResponse(
                    status="success",
                    message="Field boundaries retrieved",
                    data=boundaries
                )
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Payload Control
        @self.app.post("/api/payload/control")
        async def control_payload(request: PayloadControlRequest):
            try:
                if request.action == "spray_start":
                    if self.payload_controller.arm_spray():
                        return StatusResponse(status="success", message="Spray activated")
                    return StatusResponse(status="error", message="Failed to activate spray")
                
                elif request.action == "spray_stop":
                    if self.payload_controller.disarm_spray():
                        return StatusResponse(status="success", message="Spray deactivated")
                    return StatusResponse(status="error", message="Failed to deactivate spray")
                
                elif request.action == "photo":
                    if self.payload_controller.camera:
                        if self.payload_controller.camera.capture_photo("/tmp/photo.jpg"):
                            return StatusResponse(status="success", message="Photo captured")
                    return StatusResponse(status="error", message="Camera not available")
                
                elif request.action == "record_start":
                    if self.payload_controller.camera:
                        if self.payload_controller.camera.start_video_recording("/tmp/video.mp4"):
                            return StatusResponse(status="success", message="Recording started")
                    return StatusResponse(status="error", message="Camera not available")
                
                elif request.action == "record_stop":
                    if self.payload_controller.camera:
                        if self.payload_controller.camera.stop_video_recording():
                            return StatusResponse(status="success", message="Recording stopped")
                    return StatusResponse(status="error", message="Camera not available")
                
                else:
                    return StatusResponse(status="error", message="Unknown payload action")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.get("/api/payload/status")
        async def get_payload_status():
            try:
                status = self.payload_controller.get_payload_status()
                return StatusResponse(
                    status="success",
                    message="Payload status retrieved",
                    data=status
                )
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # Telemetry
        @self.app.get("/api/telemetry/current")
        async def get_current_telemetry():
            try:
                telemetry = self.telemetry_manager.get_current()
                if telemetry:
                    return StatusResponse(
                        status="success",
                        message="Current telemetry retrieved",
                        data=telemetry
                    )
                return StatusResponse(status="error", message="No telemetry data available")
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.get("/api/telemetry/history")
        async def get_telemetry_history(seconds: int = None):
            try:
                history = self.telemetry_manager.get_history(seconds)
                return StatusResponse(
                    status="success",
                    message="Telemetry history retrieved",
                    data=history
                )
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        @self.app.get("/api/telemetry/stats")
        async def get_telemetry_stats(seconds: int = 60):
            try:
                stats = self.telemetry_manager.get_statistics(seconds)
                return StatusResponse(
                    status="success",
                    message="Telemetry statistics retrieved",
                    data=stats
                )
            except Exception as e:
                return StatusResponse(status="error", message=str(e))

        # WebSocket for live telemetry
        @self.app.websocket("/ws/telemetry")
        async def websocket_telemetry(websocket: WebSocket):
            await websocket.accept()
            client_id = id(websocket)
            self.active_websocket_clients.add(websocket)
            
            try:
                # Register with telemetry system
                self.telemetry_manager.subscribe(
                    str(client_id),
                    lambda data: asyncio.create_task(self._send_ws(websocket, data))
                )
                
                # Keep connection open
                while True:
                    try:
                        # Wait for any incoming message (to detect disconnection)
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
                except:
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
