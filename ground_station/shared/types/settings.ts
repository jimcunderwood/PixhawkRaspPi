import type { FleetConfig, DroneFleetEntry } from './fleet';
import type { TransportKind } from './fleet';

export type GroundStationDroneProfile = Omit<DroneFleetEntry, 'transport'> & {
  transport: {
    type: TransportKind;
    endpoint: string;
    api_key?: string;
    control_token?: string;
    path?: string;
    channel?: string;
  };
  endpoints?: string[];
  telemetry_refresh_interval_ms?: number;
};

export type GroundStationRuntimeProfile = {
  profile_id: string;
  label: string;
  companion_base_url?: string;
  selected_drone_id?: string;
  fleet: FleetConfig;
};

export type GroundStationUserSettings = {
  user_id: string;
  username: string;
  display_name?: string;
  active_profile_id: string;
  profiles: GroundStationRuntimeProfile[];
  updated_at?: string;
};

export type GroundStationSessionUser = {
  user_id: string;
  username: string;
  display_name?: string;
};

export type GroundStationSessionState = {
  authenticated: boolean;
  has_users: boolean;
  user?: GroundStationSessionUser;
  settings?: GroundStationUserSettings;
  created?: boolean;
  created_username?: string;
};

export type GroundStationLoginRequest = {
  username: string;
  password: string;
  display_name?: string;
  create?: boolean;
  bootstrap_api_key?: string;
};

function withDefaultApiKey(fleet: FleetConfig, apiKey?: string): FleetConfig {
  const trimmedApiKey = apiKey?.trim();
  if (!trimmedApiKey) {
    return fleet;
  }

  return {
    ...fleet,
    drones: fleet.drones.map((drone) => ({
      ...drone,
      transport: {
        ...drone.transport,
        api_key: drone.transport.api_key?.trim() || trimmedApiKey,
      },
    })),
  };
}

export function createDefaultRuntimeProfile(
  profileId: string,
  label: string,
  fleet: FleetConfig,
  companionBaseUrl?: string,
  apiKey?: string,
): GroundStationRuntimeProfile {
  return {
    profile_id: profileId,
    label,
    companion_base_url: companionBaseUrl,
    selected_drone_id: fleet.drones[0]?.drone_id,
    fleet: withDefaultApiKey(fleet, apiKey),
  };
}

export function createDefaultUserSettings(
  userId: string | undefined,
  username = 'pilot',
  displayName = 'Pilot',
  fleet: FleetConfig,
  companionBaseUrl?: string,
  apiKey?: string,
): GroundStationUserSettings {
  return {
    user_id: userId ?? `user-${username.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'pilot'}`,
    username,
    display_name: displayName,
    active_profile_id: 'profile-default',
    profiles: [createDefaultRuntimeProfile('profile-default', 'Primary profile', fleet, companionBaseUrl, apiKey)],
  };
}
