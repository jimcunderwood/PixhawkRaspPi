import type { FleetStatus } from './fleet-status';
import type { PrescriptionStatus } from './prescription';

export type BaseStationStatus = {
  station_id?: string;
  name?: string;
  latitude?: number | null;
  longitude?: number | null;
  altitude_m?: number | null;
  antenna_height_m?: number | null;
  correction_port?: string | null;
  correction_baudrate?: number | null;
  mount_type?: string | null;
  notes?: string | null;
  active?: boolean;
  created_at?: number;
  updated_at?: number;
};

export type CalibrationPpkJobRequest = {
  job_id?: string;
  session?: string | null;
  base_station_id?: string | null;
  telemetry_window_seconds?: number | null;
  source_label?: string | null;
  notes?: string | null;
  telemetry_history?: Array<Record<string, unknown>>;
};

export type PpkJobStatus = {
  job_id?: string;
  session?: string | null;
  base_station?: BaseStationStatus | null;
  base_station_id?: string | null;
  status?: string;
  source_label?: string | null;
  telemetry_window_seconds?: number | null;
  request?: CalibrationPpkJobRequest | Record<string, unknown>;
  summary?: Record<string, unknown>;
  quality?: Record<string, unknown>;
  notes?: string | null;
  updated_at?: number;
};

export type CalibrationStatus = {
  enabled?: boolean;
  rtk_enabled?: boolean;
  ppk_enabled?: boolean;
  base_station_count?: number;
  active_base_station?: BaseStationStatus | null;
  base_stations?: BaseStationStatus[];
  recent_jobs?: PpkJobStatus[];
  last_job?: PpkJobStatus | null;
  updated_at?: number;
};

export type FarmIntegrationStatus = {
  enabled?: boolean;
  configured?: boolean;
  agleader_configured?: boolean;
  isoxml_output_directory?: string;
  report_output_directory?: string;
  latest_isoxml_export?: Record<string, unknown> | null;
  latest_report?: Record<string, unknown> | null;
  recent_isoxml_exports?: Array<Record<string, unknown>>;
  recent_reports?: Array<Record<string, unknown>>;
  updated_at?: number;
};

export type FlightLogSyncStatus = {
  status?: string;
  running?: boolean;
  last_landing_at?: number | null;
  last_armed_at?: number | null;
  base_directory?: string;
  updated_at?: number | null;
};

export type FlightLogSyncHistoryEntry = {
  archive_path?: string;
  name?: string;
  session?: string;
  reason?: string;
  created_at?: number;
  created_at_iso?: string;
  pixhawk_file_count?: number;
  companion_file_count?: number;
  size_bytes?: number;
  updated_at?: number;
};

export type SwarmCoordinationStatus = {
  swarm_id?: string;
  self_drone_id?: string;
  formation_mode?: string;
  leader_drone_id?: string;
  assignments?: Array<{
    drone_id?: string;
    callsign?: string;
    role?: string;
    sector_index?: number;
    sector_count?: number;
    target_follow?: string | null;
    position?: Record<string, unknown>;
    last_seen_at?: number;
  }>;
  collision_avoidance?: {
    enabled?: boolean;
    nearest_peer?: {
      drone_id?: string;
      horizontal_m?: number;
      vertical_m?: number;
      updated_at?: number;
    } | null;
    active_alerts?: Array<{
      drone_id_a?: string;
      drone_id_b?: string;
      horizontal_m?: number;
      vertical_m?: number;
      threshold_m?: number;
      severity?: 'info' | 'warning' | 'critical';
      suggested_action?: string;
    }>;
    recommended_action?: string;
  } | Record<string, unknown>;
  fusion?: {
    confidence?: number;
    reference_node_id?: string;
  } | Record<string, unknown>;
  updated_at?: number;
};

export type ConnectionState = 'connected' | 'connecting' | 'disconnected' | 'unknown';

export type HealthResponse = {
  status?: string;
  message?: string;
  data?: {
    status?: string;
    message?: string;
    version?: string;
    uptime_seconds?: number;
    connected?: boolean;
    api_ready?: boolean;
  };
};

export type VehicleStatus = {
  armed?: boolean;
  mode?: string;
  location?: {
    latitude?: number;
    longitude?: number;
    altitude?: number;
  };
  battery?: {
    voltage?: number;
    current?: number;
    level_percent?: number;
  };
  ground_speed?: number;
  air_speed?: number;
  heading?: number;
  gps?: {
    fix_type?: number;
    satellite_count?: number;
  };
};

export type ReadinessStatus = {
  checks?: Array<{
    name?: string;
    status?: string;
    detail?: string;
  }>;
  healthy?: boolean;
  warning_count?: number;
  critical_count?: number;
};

export type SafetyStatus = {
  geofences?: Array<{
    name: string;
    type?: string;
    enabled?: boolean;
  }>;
  waivers?: Record<string, unknown>;
  remote_id?: Record<string, unknown>;
};

export type MissionStats = {
  waypoint_count?: number;
  active?: boolean;
  completed?: number;
  total_distance_m?: number;
  estimated_duration_s?: number;
};

export type NavigationStatus = {
  obstacle_avoidance?: Record<string, unknown>;
  terrain_following?: Record<string, unknown>;
  distance_sensors?: Array<Record<string, unknown>>;
};

export type WeatherBriefing = {
  station_id?: string;
  metar_raw?: string | null;
  taf_raw?: string | null;
  metar?: {
    raw?: string | null;
    station_id?: string | null;
    issued_at?: string | null;
    visibility_sm?: number | null;
    ceiling_ft?: number | null;
    wind?: {
      direction?: string | null;
      speed_kt?: number | null;
      gust_kt?: number | null;
    };
    hazards?: string[];
    flight_category?: 'VFR' | 'MVFR' | 'IFR' | 'LIFR' | null;
  };
  taf?: {
    raw?: string | null;
    station_id?: string | null;
    issued_at?: string | null;
    valid_until?: string | null;
    hazards?: string[];
    significant_changes?: string[];
  };
  ready?: boolean;
  blocking_reasons?: string[];
  advisories?: string[];
  source?: Record<string, unknown>;
  updated_at?: number;
  updated_at_iso?: string;
};

export type WeatherStatus = {
  enabled?: boolean;
  station_id?: string;
  configured?: boolean;
  last_briefing?: WeatherBriefing | null;
};

export type EdgeAiScanResult = {
  available?: boolean;
  backend?: string;
  detections?: Array<{
    label?: string;
    confidence?: number;
    bbox?: {
      x1?: number;
      y1?: number;
      x2?: number;
      y2?: number;
    };
  }>;
  obstacle_detections?: Array<{
    label?: string;
    confidence?: number;
    bbox?: {
      x1?: number;
      y1?: number;
      x2?: number;
      y2?: number;
    };
  }>;
  obstacle_risk?: boolean;
  scan_at?: number;
  error?: string | null;
};

export type EdgeAiStatus = {
  enabled?: boolean;
  backend?: string;
  configured?: boolean;
  model_path?: string;
  labels_path?: string;
  confidence_threshold?: number;
  sample_interval_seconds?: number;
  last_scan_at?: number | null;
  last_result?: EdgeAiScanResult | null;
  last_error?: string | null;
};

export type TelemetrySnapshot = {
  timestamp?: number;
  armed?: boolean;
  mode?: string;
  ground_speed?: number;
  air_speed?: number;
  heading?: number;
  battery?: {
    level_percent?: number;
    voltage?: number;
    current?: number;
  };
  location?: {
    latitude?: number;
    longitude?: number;
    altitude?: number;
  };
};

export type CompanionSnapshot = {
  health?: HealthResponse;
  vehicle?: VehicleStatus;
  readiness?: ReadinessStatus;
  safety?: SafetyStatus;
  mission?: MissionStats;
  navigation?: NavigationStatus;
  weather?: WeatherStatus;
  edge_ai?: EdgeAiStatus;
  telemetry?: TelemetrySnapshot;
  fleet?: FleetStatus;
  prescription?: PrescriptionStatus;
  calibration?: CalibrationStatus;
  farm?: FarmIntegrationStatus;
  flight_log_sync?: FlightLogSyncStatus;
  swarm_coordination?: SwarmCoordinationStatus;
};

export type LatLngPoint = {
  latitude: number;
  longitude: number;
  altitude?: number;
};

export type MissionWaypoint = LatLngPoint & {
  id: string;
  label: string;
};

export type MissionEditorMode = 'view' | 'boundary' | 'waypoint';

export type TelemetrySeriesPoint = TelemetrySnapshot & {
  id: string;
};

export type TelemetryStreamState = 'connecting' | 'streaming' | 'reconnecting' | 'offline';
