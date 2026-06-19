import type { DroneTransport, TransportKind } from './fleet';
import type { LatLngPoint } from './base';

export type SwarmRole = 'leader' | 'follower' | 'relay' | 'observer' | 'anchor';

export type SwarmFusionMode = 'none' | 'separation_only' | 'weighted_gnss' | 'relative_pose';

export type SwarmPeerTrust = 'primary' | 'trusted' | 'normal' | 'degraded';

export type SwarmTelemetryQuality = {
  fix_type?: number;
  satellite_count?: number;
  hdop?: number;
  vdop?: number;
  horizontal_accuracy_m?: number;
  vertical_accuracy_m?: number;
  age_ms?: number;
  trust_score?: number;
};

export type SwarmTelemetryLocation = LatLngPoint & {
  source: 'gps' | 'rtk' | 'peer_fused' | 'manual';
  accuracy_m?: number;
  covariance_m?: [number, number, number];
};

export type SwarmTelemetryVector = {
  north_mps?: number;
  east_mps?: number;
  down_mps?: number;
  ground_speed_mps?: number;
  heading_deg?: number;
};

export type SwarmTelemetryVehicle = {
  armed?: boolean;
  mode?: string;
  battery_percent?: number;
};

export type SwarmTelemetryMessage = {
  swarm_id: string;
  source_drone_id: string;
  sample_id: string;
  sequence: number;
  timestamp: number;
  received_at: number;
  role: SwarmRole;
  location: SwarmTelemetryLocation;
  velocity?: SwarmTelemetryVector;
  quality?: SwarmTelemetryQuality;
  vehicle?: SwarmTelemetryVehicle;
  link?: {
    transport: TransportKind;
    latency_ms?: number;
    signal_strength_dbm?: number;
    packet_loss_percent?: number;
  };
};

export type SwarmPeerConfig = {
  drone_id: string;
  callsign?: string;
  role: SwarmRole;
  transport: DroneTransport;
  trust?: SwarmPeerTrust;
  max_age_seconds?: number;
  max_horizontal_error_m?: number;
  max_vertical_error_m?: number;
  requires_rtk?: boolean;
};

export type SwarmTelemetryBroadcastConfig = {
  enabled: boolean;
  rate_hz: number;
  include_location: boolean;
  include_velocity: boolean;
  include_quality: boolean;
  include_vehicle_state: boolean;
  include_alerts: boolean;
};

export type SwarmFusionWeights = {
  self_position: number;
  peer_position: number;
  peer_velocity: number;
  heading: number;
  quality: number;
};

export type SwarmFusionConfig = {
  mode: SwarmFusionMode;
  min_peer_count: number;
  max_peer_age_seconds: number;
  require_reference_node: boolean;
  reference_node_id?: string;
  use_peer_velocity: boolean;
  weights: SwarmFusionWeights;
};

export type SwarmSafetyConfig = {
  min_horizontal_separation_m: number;
  min_vertical_separation_m: number;
  warn_distance_m: number;
  critical_distance_m: number;
  hold_on_loss: boolean;
  hold_timeout_seconds: number;
};

export type SwarmConfig = {
  swarm_id: string;
  enabled: boolean;
  self_drone_id: string;
  role: SwarmRole;
  transport: DroneTransport;
  peers: SwarmPeerConfig[];
  broadcast: SwarmTelemetryBroadcastConfig;
  fusion: SwarmFusionConfig;
  safety: SwarmSafetyConfig;
};

export type SwarmSeparationAlert = {
  drone_id_a: string;
  drone_id_b: string;
  horizontal_m: number;
  vertical_m: number;
  threshold_m: number;
  severity: 'info' | 'warning' | 'critical';
  suggested_action?: string;
};

export type SwarmFusionState = {
  swarm_id: string;
  self_drone_id: string;
  fused_location: LatLngPoint;
  raw_location?: LatLngPoint;
  confidence: number;
  peer_count: number;
  reference_node_id?: string;
  nearest_peer?: {
    drone_id: string;
    horizontal_m: number;
    vertical_m: number;
    updated_at: number;
  };
  separation_alerts: SwarmSeparationAlert[];
};

export type SwarmStatus = {
  swarm_id: string;
  self_drone_id: string;
  enabled: boolean;
  healthy_peer_count: number;
  peer_count: number;
  fusion_mode: SwarmFusionMode;
  last_update?: string;
  alerts: SwarmSeparationAlert[];
};
