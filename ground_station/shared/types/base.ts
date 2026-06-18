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
  telemetry?: TelemetrySnapshot;
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
