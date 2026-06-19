export type PrescriptionZoneGeometry = {
  type?: string;
  coordinates?: unknown;
};

export type PrescriptionZone = {
  zone_id?: number;
  label?: string;
  target_rate_lpha?: number;
  geometry_type?: string;
  geometry?: PrescriptionZoneGeometry;
  priority?: number;
  created_at?: number;
  updated_at?: number;
};

export type PrescriptionMap = {
  map_id?: string;
  name?: string;
  description?: string;
  source_format?: string;
  default_rate_lpha?: number;
  swath_width_m?: number;
  active?: boolean;
  zones?: PrescriptionZone[];
  created_at?: number;
  updated_at?: number;
};

export type PrescriptionStatus = {
  enabled?: boolean;
  configured?: boolean;
  active_map?: PrescriptionMap | null;
  current_zone?: PrescriptionZone | null;
  target_rate_liters_per_hectare?: number | null;
  current_flow_rate_liters_per_minute?: number | null;
  recommended_duty_cycle?: number | null;
  ground_speed_mps?: number | null;
  speed_sync_enabled?: boolean;
  effective_ground_speed_mps?: number | null;
  swath_width_m?: number | null;
  location?: {
    latitude?: number;
    longitude?: number;
  } | null;
  updated_at?: number | null;
};
