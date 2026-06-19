"""Pydantic models for companion swarm contracts."""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class SwarmRole(str, Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    RELAY = "relay"
    OBSERVER = "observer"
    ANCHOR = "anchor"


class SwarmFusionMode(str, Enum):
    NONE = "none"
    SEPARATION_ONLY = "separation_only"
    WEIGHTED_GNSS = "weighted_gnss"
    RELATIVE_POSE = "relative_pose"


class SwarmPeerTrust(str, Enum):
    PRIMARY = "primary"
    TRUSTED = "trusted"
    NORMAL = "normal"
    DEGRADED = "degraded"


class SwarmTransportKind(str, Enum):
    HTTP = "http"
    WEBSOCKET = "websocket"
    IPC = "ipc"
    UDP = "udp"
    MAVLINK = "mavlink"
    BLE = "ble"
    NATIVE = "native"


class SwarmTransportConfig(BaseModel):
    type: SwarmTransportKind
    endpoint: str = Field(..., min_length=1)
    path: Optional[str] = None
    channel: Optional[str] = None


class SwarmPeerConfig(BaseModel):
    drone_id: str = Field(..., min_length=1)
    callsign: Optional[str] = None
    role: SwarmRole
    transport: SwarmTransportConfig
    trust: Optional[SwarmPeerTrust] = None
    max_age_seconds: Optional[float] = Field(None, gt=0.0)
    max_horizontal_error_m: Optional[float] = Field(None, gt=0.0)
    max_vertical_error_m: Optional[float] = Field(None, gt=0.0)
    requires_rtk: Optional[bool] = None


class SwarmTelemetryBroadcastConfig(BaseModel):
    enabled: bool
    rate_hz: float = Field(..., gt=0.0, le=20.0)
    include_location: bool
    include_velocity: bool
    include_quality: bool
    include_vehicle_state: bool
    include_alerts: bool


class SwarmFusionWeights(BaseModel):
    self_position: float = Field(..., ge=0.0)
    peer_position: float = Field(..., ge=0.0)
    peer_velocity: float = Field(..., ge=0.0)
    heading: float = Field(..., ge=0.0)
    quality: float = Field(..., ge=0.0)


class SwarmFusionConfig(BaseModel):
    mode: SwarmFusionMode
    min_peer_count: int = Field(..., ge=0)
    max_peer_age_seconds: float = Field(..., gt=0.0)
    require_reference_node: bool
    reference_node_id: Optional[str] = None
    use_peer_velocity: bool
    weights: SwarmFusionWeights


class SwarmSafetyConfig(BaseModel):
    min_horizontal_separation_m: float = Field(..., gt=0.0)
    min_vertical_separation_m: float = Field(..., gt=0.0)
    warn_distance_m: float = Field(..., gt=0.0)
    critical_distance_m: float = Field(..., gt=0.0)
    hold_on_loss: bool
    hold_timeout_seconds: float = Field(..., gt=0.0)


class SwarmConfig(BaseModel):
    swarm_id: str = Field(..., min_length=1)
    enabled: bool
    self_drone_id: str = Field(..., min_length=1)
    role: SwarmRole
    transport: SwarmTransportConfig
    peers: List[SwarmPeerConfig] = Field(..., min_length=1)
    broadcast: SwarmTelemetryBroadcastConfig
    fusion: SwarmFusionConfig
    safety: SwarmSafetyConfig


class SwarmTelemetryQuality(BaseModel):
    fix_type: Optional[int] = Field(None, ge=0)
    satellite_count: Optional[int] = Field(None, ge=0)
    hdop: Optional[float] = Field(None, ge=0.0)
    vdop: Optional[float] = Field(None, ge=0.0)
    horizontal_accuracy_m: Optional[float] = Field(None, ge=0.0)
    vertical_accuracy_m: Optional[float] = Field(None, ge=0.0)
    age_ms: Optional[float] = Field(None, ge=0.0)
    trust_score: Optional[float] = Field(None, ge=0.0, le=1.0)


class SwarmTelemetryLocation(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude: Optional[float] = None
    source: str = Field(..., min_length=1)
    accuracy_m: Optional[float] = Field(None, ge=0.0)
    covariance_m: Optional[List[float]] = Field(None, min_length=3, max_length=3)


class SwarmTelemetryVector(BaseModel):
    north_mps: Optional[float] = None
    east_mps: Optional[float] = None
    down_mps: Optional[float] = None
    ground_speed_mps: Optional[float] = Field(None, ge=0.0)
    heading_deg: Optional[float] = Field(None, ge=0.0, le=360.0)


class SwarmTelemetryVehicle(BaseModel):
    armed: Optional[bool] = None
    mode: Optional[str] = None
    battery_percent: Optional[float] = Field(None, ge=0.0, le=100.0)


class SwarmTelemetryLink(BaseModel):
    transport: SwarmTransportKind
    latency_ms: Optional[float] = Field(None, ge=0.0)
    signal_strength_dbm: Optional[float] = None
    packet_loss_percent: Optional[float] = Field(None, ge=0.0, le=100.0)


class SwarmTelemetryMessage(BaseModel):
    swarm_id: str = Field(..., min_length=1)
    source_drone_id: str = Field(..., min_length=1)
    sample_id: str = Field(..., min_length=1)
    sequence: int = Field(..., ge=0)
    timestamp: float = Field(..., ge=0.0)
    received_at: float = Field(..., ge=0.0)
    role: SwarmRole
    location: SwarmTelemetryLocation
    velocity: Optional[SwarmTelemetryVector] = None
    quality: Optional[SwarmTelemetryQuality] = None
    vehicle: Optional[SwarmTelemetryVehicle] = None
    link: Optional[SwarmTelemetryLink] = None


class SwarmSeparationAlert(BaseModel):
    drone_id_a: str = Field(..., min_length=1)
    drone_id_b: str = Field(..., min_length=1)
    horizontal_m: float = Field(..., ge=0.0)
    vertical_m: float = Field(..., ge=0.0)
    threshold_m: float = Field(..., ge=0.0)
    severity: str = Field(..., pattern="^(info|warning|critical)$")
    suggested_action: Optional[str] = None


class SwarmFusionNearestPeer(BaseModel):
    drone_id: str = Field(..., min_length=1)
    horizontal_m: float = Field(..., ge=0.0)
    vertical_m: float = Field(..., ge=0.0)
    updated_at: float = Field(..., ge=0.0)


class SwarmFusionState(BaseModel):
    swarm_id: str = Field(..., min_length=1)
    self_drone_id: str = Field(..., min_length=1)
    fused_location: Dict[str, float]
    raw_location: Optional[Dict[str, object]] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    peer_count: int = Field(..., ge=0)
    reference_node_id: Optional[str] = None
    nearest_peer: Optional[SwarmFusionNearestPeer] = None
    separation_alerts: List[SwarmSeparationAlert] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_location(self):
        fused = self.fused_location
        if "latitude" not in fused or "longitude" not in fused:
            raise ValueError("fused_location requires latitude and longitude")
        return self


class SwarmStatus(BaseModel):
    swarm_id: str = Field(..., min_length=1)
    self_drone_id: str = Field(..., min_length=1)
    enabled: bool
    healthy_peer_count: int = Field(..., ge=0)
    peer_count: int = Field(..., ge=0)
    fusion_mode: SwarmFusionMode
    last_update: Optional[str] = None
    alerts: List[SwarmSeparationAlert] = Field(default_factory=list)
