export type TransportKind = 'http' | 'websocket' | 'ipc' | 'udp' | 'mavlink' | 'ble' | 'native';

export type DroneTransport = {
  type: TransportKind;
  endpoint: string;
  api_key?: string;
  control_token?: string;
  path?: string;
  channel?: string;
};

export type DroneCapability = string;

export type DroneFleetEntry = {
  drone_id: string;
  callsign?: string;
  role?: string;
  transport: DroneTransport;
  endpoints?: string[];
  capabilities?: DroneCapability[];
  status?: string;
  last_heartbeat?: string;
};

export type DeviceProfile = {
  profile_id: string;
  runtime: 'web' | 'desktop' | 'mobile' | 'embedded';
  preferred_transports: TransportKind[];
};

export type FleetConfig = {
  fleet_id: string;
  default_transport?: TransportKind;
  drones: DroneFleetEntry[];
  device_profiles?: DeviceProfile[];
};
