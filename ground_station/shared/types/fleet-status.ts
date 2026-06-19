import type { DroneFleetEntry } from './fleet';

export type FleetDroneVehicleState = {
  armed?: boolean;
  mode?: string;
  battery_percent?: number;
};

export type FleetDroneStatus = DroneFleetEntry & {
  active?: boolean;
  trust?: string;
  last_seen_at?: number;
  sample_id?: string;
  sequence?: number;
  position?: {
    latitude?: number;
    longitude?: number;
    altitude?: number;
    heading?: number;
  } | null;
  vehicle?: FleetDroneVehicleState | null;
};

export type FleetStatus = {
  fleet_id?: string;
  self_drone_id?: string;
  enabled?: boolean;
  peer_count?: number;
  active_drone_count?: number;
  drones?: FleetDroneStatus[];
  fusion?: Record<string, unknown>;
  status?: Record<string, unknown>;
  updated_at?: number;
};
