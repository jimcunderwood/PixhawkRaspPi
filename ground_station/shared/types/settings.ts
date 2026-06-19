import type { FleetConfig, DroneFleetEntry } from './fleet';
import type { TransportKind } from './fleet';

export type GroundStationDroneProfile = Omit<DroneFleetEntry, 'transport'> & {
  transport: {
    type: TransportKind;
    endpoint: string;
    path?: string;
    channel?: string;
  };
  endpoints?: string[];
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
};

export type GroundStationLoginRequest = {
  username: string;
  password: string;
  display_name?: string;
  create?: boolean;
};

export function createDefaultRuntimeProfile(
  profileId: string,
  label: string,
  fleet: FleetConfig,
  companionBaseUrl?: string,
): GroundStationRuntimeProfile {
  return {
    profile_id: profileId,
    label,
    companion_base_url: companionBaseUrl,
    selected_drone_id: fleet.drones[0]?.drone_id,
    fleet,
  };
}

export function createDefaultUserSettings(
  userId: string | undefined,
  username = 'pilot',
  displayName = 'Pilot',
  fleet: FleetConfig,
  companionBaseUrl?: string,
): GroundStationUserSettings {
  return {
    user_id: userId ?? `user-${username.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'pilot'}`,
    username,
    display_name: displayName,
    active_profile_id: 'profile-default',
    profiles: [
      createDefaultRuntimeProfile('profile-default', 'Primary profile', fleet, companionBaseUrl),
    ],
  };
}
