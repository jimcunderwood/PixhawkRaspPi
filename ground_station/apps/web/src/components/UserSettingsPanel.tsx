import { useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import { StatusChip } from '../../../../packages/ui/src';
import { mockFleetConfig } from '../../../../shared/fleet/mock';
import {
  createDefaultRuntimeProfile,
  type GroundStationLoginRequest,
  type GroundStationSessionUser,
  type GroundStationUserSettings,
} from '../../../../shared/types/settings';
import type { FleetConfig, DroneFleetEntry, TransportKind } from '../../../../shared/types/fleet';

type UserSettingsPanelProps = {
  authenticated: boolean;
  hasUsers: boolean;
  loading?: boolean;
  saving?: boolean;
  message?: string;
  sessionUser?: GroundStationSessionUser;
  settingsDraft: GroundStationUserSettings;
  defaultCompanionBaseUrl?: string;
  authorityStatus?: string;
  acquiringAuthorityDroneId?: string;
  onLogin: (request: GroundStationLoginRequest) => Promise<boolean>;
  onLogout: () => Promise<void>;
  onSave: () => Promise<void>;
  onDraftChange: Dispatch<SetStateAction<GroundStationUserSettings>>;
  onAcquireAuthority: (profileId: string, droneId: string) => Promise<void>;
  collapsed?: boolean;
  onToggleCollapse: () => void;
};

function cloneSettings(settings: GroundStationUserSettings): GroundStationUserSettings {
  return JSON.parse(JSON.stringify(settings)) as GroundStationUserSettings;
}

function cloneFleet(fleet: FleetConfig): FleetConfig {
  return JSON.parse(JSON.stringify(fleet)) as FleetConfig;
}

function buildUniqueProfileId(existing: GroundStationUserSettings): string {
  const base = `profile-${existing.profiles.length + 1}`;
  if (!existing.profiles.some((profile) => profile.profile_id === base)) {
    return base;
  }

  let suffix = 2;
  while (existing.profiles.some((profile) => profile.profile_id === `${base}-${suffix}`)) {
    suffix += 1;
  }
  return `${base}-${suffix}`;
}

function ensurePrimaryEndpoint(drone: DroneFleetEntry): string {
  return drone.transport.endpoint || drone.endpoints?.[0] || '';
}

function updateProfile(
  settings: GroundStationUserSettings,
  profileId: string,
  updater: (profile: GroundStationUserSettings['profiles'][number]) => GroundStationUserSettings['profiles'][number],
): GroundStationUserSettings {
  return {
    ...settings,
    profiles: settings.profiles.map((profile) => (profile.profile_id === profileId ? updater(profile) : profile)),
  };
}

function normalizeEndpoints(drone: DroneFleetEntry, endpoints: string[]): DroneFleetEntry {
  const cleaned = endpoints.map((endpoint) => endpoint.trim()).filter(Boolean);
  const fallback = ensurePrimaryEndpoint(drone);
  const nextEndpoints = cleaned.length ? cleaned : fallback ? [fallback] : [];
  const primaryEndpoint = nextEndpoints[0] ?? fallback;

  return {
    ...drone,
    transport: {
      ...drone.transport,
      endpoint: primaryEndpoint,
    },
    endpoints: nextEndpoints,
  };
}

export function UserSettingsPanel({
  authenticated,
  hasUsers,
  loading = false,
  saving = false,
  message,
  sessionUser,
  settingsDraft,
  defaultCompanionBaseUrl,
  authorityStatus,
  acquiringAuthorityDroneId,
  onLogin,
  onLogout,
  onSave,
  onDraftChange,
  onAcquireAuthority,
  collapsed = false,
  onToggleCollapse,
}: UserSettingsPanelProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [createUsername, setCreateUsername] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [createDisplayName, setCreateDisplayName] = useState('');

  const activeProfileIndex = useMemo(() => {
    const exactIndex = settingsDraft.profiles.findIndex((profile) => profile.profile_id === settingsDraft.active_profile_id);
    return exactIndex >= 0 ? exactIndex : 0;
  }, [settingsDraft.active_profile_id, settingsDraft.profiles]);

  const activeProfile = settingsDraft.profiles[activeProfileIndex] ?? settingsDraft.profiles[0];
  const activeFleet = activeProfile?.fleet ?? cloneFleet(mockFleetConfig);
  const activeDroneId = activeProfile?.selected_drone_id ?? activeFleet.drones[0]?.drone_id;
  const activeDrone = activeFleet.drones.find((drone) => drone.drone_id === activeDroneId) ?? activeFleet.drones[0];
  const profileOptions = settingsDraft.profiles;

  function mutateSettings(updater: (current: GroundStationUserSettings) => GroundStationUserSettings) {
    onDraftChange(updater(cloneSettings(settingsDraft)));
  }

  function setProfileField(profileId: string, updater: (profile: GroundStationUserSettings['profiles'][number]) => GroundStationUserSettings['profiles'][number]) {
    mutateSettings((current) => ({
      ...current,
      profiles: current.profiles.map((profile) => (profile.profile_id === profileId ? updater(profile) : profile)),
    }));
  }

  function setActiveProfile(profileId: string) {
    mutateSettings((current) => ({ ...current, active_profile_id: profileId }));
  }

  function addProfile() {
    mutateSettings((current) => {
      const profileId = buildUniqueProfileId(current);
      const source = current.profiles[activeProfileIndex] ?? current.profiles[0] ?? createDefaultRuntimeProfile('profile-default', 'Primary profile', cloneFleet(mockFleetConfig), defaultCompanionBaseUrl);
      const nextProfile = cloneSettings({
        user_id: current.user_id,
        username: current.username,
        display_name: current.display_name,
        active_profile_id: current.active_profile_id,
        profiles: [source],
      }).profiles[0];

      return {
        ...current,
        active_profile_id: profileId,
        profiles: [
          ...current.profiles,
          {
            ...nextProfile,
            profile_id: profileId,
            label: `${source.label ?? 'Profile'} copy`,
          },
        ],
      };
    });
  }

  function duplicateProfile() {
    if (!activeProfile) {
      return;
    }

    mutateSettings((current) => {
      const profileId = buildUniqueProfileId(current);
      return {
        ...current,
        active_profile_id: profileId,
        profiles: [
          ...current.profiles,
          {
            ...cloneSettings({
              ...current,
              profiles: [activeProfile],
            }).profiles[0],
            profile_id: profileId,
            label: `${activeProfile.label} copy`,
          },
        ],
      };
    });
  }

  function deleteProfile(profileId: string) {
    mutateSettings((current) => {
      if (current.profiles.length <= 1) {
        return current;
      }

      const profiles = current.profiles.filter((profile) => profile.profile_id !== profileId);
      return {
        ...current,
        active_profile_id: current.active_profile_id === profileId ? profiles[0].profile_id : current.active_profile_id,
        profiles,
      };
    });
  }

  function addDrone(profileId: string) {
    mutateSettings((current) =>
      updateProfile(current, profileId, (profile) => {
        const nextIndex = profile.fleet.drones.length + 1;
        const nextDroneId = `drone-${String(nextIndex).padStart(2, '0')}`;
        return {
          ...profile,
          fleet: {
            ...profile.fleet,
            drones: [
              ...profile.fleet.drones,
              {
                drone_id: nextDroneId,
                callsign: `Drone ${nextIndex}`,
                role: 'wing',
                transport: {
                  type: profile.fleet.default_transport ?? 'websocket',
                  endpoint: '',
                  api_key: '',
                  control_token: '',
                },
                endpoints: [''],
                status: 'idle',
              },
            ],
          },
        };
      }),
    );
  }

  function deleteDrone(profileId: string, droneId: string) {
    mutateSettings((current) =>
      updateProfile(current, profileId, (profile) => {
        if (profile.fleet.drones.length <= 1) {
          return profile;
        }

        const drones = profile.fleet.drones.filter((drone) => drone.drone_id !== droneId);
        return {
          ...profile,
          selected_drone_id: profile.selected_drone_id === droneId ? drones[0].drone_id : profile.selected_drone_id,
          fleet: {
            ...profile.fleet,
            drones,
          },
        };
      }),
    );
  }

  function setSelectedDrone(profileId: string, droneId: string) {
    setProfileField(profileId, (profile) => ({
      ...profile,
      selected_drone_id: droneId,
    }));
  }

  async function handleSignIn() {
    await onLogin({
      username,
      password,
      create: false,
    });
  }

  async function handleCreateUser() {
    const nextUsername = createUsername.trim();
    const success = await onLogin({
      username: nextUsername,
      password: createPassword,
      display_name: createDisplayName || nextUsername,
      create: true,
    });

    if (success) {
      setCreateUserOpen(false);
      setUsername(nextUsername);
      setPassword('');
      setCreateUsername('');
      setCreatePassword('');
      setCreateDisplayName('');
    }
  }

  return (
    <section className="sidebar-panel sidebar-accordion settings-panel">
      <div className="sidebar-panel-head">
        <div>
          <span className="panel-label">User settings</span>
          <h3>{authenticated ? 'Stored profile access' : 'Sign in'}</h3>
        </div>
        {authenticated ? (
          <button type="button" className="ghost-button" onClick={onToggleCollapse}>
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
        ) : null}
      </div>

      {collapsed ? null : (
      <div className="stack">
        {authenticated ? (
          <>
            <div className="stack">
              <StatusChip label="User" value={sessionUser?.display_name ?? sessionUser?.username ?? 'signed in'} tone="good" />
              <StatusChip label="Storage" value="SQLite-backed session" tone="neutral" />
              <StatusChip
                label="Drone"
                value={activeDrone?.callsign ?? activeDrone?.drone_id ?? 'not selected'}
                tone={activeDrone ? 'good' : 'warn'}
              />
              <StatusChip
                label="Api Key"
                value={activeDrone?.transport.api_key?.trim() ? 'configured' : 'missing'}
                tone={activeDrone?.transport.api_key?.trim() ? 'good' : 'warn'}
              />
              <StatusChip
                label="Authority"
                value={activeDrone?.transport.control_token?.trim() ? authorityStatus ?? 'token stored' : authorityStatus ?? 'not requested'}
                tone={activeDrone?.transport.control_token?.trim() ? 'good' : 'neutral'}
              />
            </div>

            <div className="settings-actions">
              <button type="button" className="secondary-button" onClick={onSave} disabled={saving || loading}>
                {saving ? 'Saving...' : 'Save settings'}
              </button>
              <button type="button" className="ghost-button" onClick={onLogout} disabled={saving || loading}>
                Sign out
              </button>
            </div>

            <label className="field">
              <span>Active profile</span>
              <select
                value={settingsDraft.active_profile_id}
                onChange={(event) => setActiveProfile(event.target.value)}
              >
                {profileOptions.map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>
                    {profile.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="settings-actions">
              <button type="button" className="secondary-button" onClick={addProfile}>
                Add profile
              </button>
              <button type="button" className="secondary-button" onClick={duplicateProfile} disabled={!activeProfile}>
                Duplicate
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => activeProfile && deleteProfile(activeProfile.profile_id)}
                disabled={!activeProfile || settingsDraft.profiles.length <= 1}
              >
                Delete
              </button>
            </div>

            {activeProfile ? (
              <div className="stack">
                <label className="field">
                  <span>Profile label</span>
                  <input
                    value={activeProfile.label}
                    onChange={(event) =>
                      setProfileField(activeProfile.profile_id, (profile) => ({
                        ...profile,
                        label: event.target.value,
                      }))
                    }
                  />
                </label>

                <label className="field">
                  <span>Configured drone</span>
                  <select
                    value={activeProfile.selected_drone_id ?? activeDrone?.drone_id ?? ''}
                    onChange={(event) => setSelectedDrone(activeProfile.profile_id, event.target.value)}
                  >
                    {activeProfile.fleet.drones.map((drone) => (
                      <option key={drone.drone_id} value={drone.drone_id}>
                        {drone.callsign ?? drone.drone_id}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="profile-drone-header">
                  <span className="metric-title">Drone connection</span>
                  <button type="button" className="ghost-button" onClick={() => addDrone(activeProfile.profile_id)}>
                    Add drone
                  </button>
                </div>
                {activeDrone ? (
                  <div className="stack">
                    <div className="settings-drone-head">
                      <strong>{activeDrone.callsign ?? activeDrone.drone_id}</strong>
                      <div className="settings-drone-actions">
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => deleteDrone(activeProfile.profile_id, activeDrone.drone_id)}
                          disabled={activeProfile.fleet.drones.length <= 1}
                        >
                          Remove
                        </button>
                      </div>
                    </div>

                    <div className="config-grid">
                      <label className="field">
                        <span>Drone ID</span>
                        <input
                          value={activeDrone.drone_id}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => {
                              const nextDroneId = event.target.value;
                              return {
                                ...profile,
                                selected_drone_id:
                                  profile.selected_drone_id === activeDrone.drone_id ? nextDroneId : profile.selected_drone_id,
                                fleet: {
                                  ...profile.fleet,
                                  drones: profile.fleet.drones.map((entry) =>
                                    entry.drone_id === activeDrone.drone_id ? { ...entry, drone_id: nextDroneId } : entry,
                                  ),
                                },
                              };
                            })
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Callsign</span>
                        <input
                          value={activeDrone.callsign ?? ''}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => ({
                              ...profile,
                              fleet: {
                                ...profile.fleet,
                                drones: profile.fleet.drones.map((entry) =>
                                  entry.drone_id === activeDrone.drone_id ? { ...entry, callsign: event.target.value } : entry,
                                ),
                              },
                            }))
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Role</span>
                        <input
                          value={activeDrone.role ?? ''}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => ({
                              ...profile,
                              fleet: {
                                ...profile.fleet,
                                drones: profile.fleet.drones.map((entry) =>
                                  entry.drone_id === activeDrone.drone_id ? { ...entry, role: event.target.value } : entry,
                                ),
                              },
                            }))
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Transport</span>
                        <select
                          value={activeDrone.transport.type}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => ({
                              ...profile,
                              fleet: {
                                ...profile.fleet,
                                drones: profile.fleet.drones.map((entry) =>
                                  entry.drone_id === activeDrone.drone_id
                                    ? {
                                        ...entry,
                                        transport: {
                                          ...entry.transport,
                                          type: event.target.value as TransportKind,
                                        },
                                      }
                                    : entry,
                                ),
                              },
                            }))
                          }
                        >
                          {['http', 'websocket', 'ipc', 'udp', 'mavlink', 'ble', 'native'].map((kind) => (
                            <option key={kind} value={kind}>
                              {kind}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field">
                        <span>Companion endpoint</span>
                        <input
                          value={activeDrone.transport.endpoint}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => ({
                              ...profile,
                              fleet: {
                                ...profile.fleet,
                                drones: profile.fleet.drones.map((entry) =>
                                  entry.drone_id === activeDrone.drone_id
                                    ? {
                                        ...entry,
                                        transport: {
                                          ...entry.transport,
                                          endpoint: event.target.value,
                                        },
                                        endpoints: [event.target.value, ...(entry.endpoints ?? []).slice(1)],
                                      }
                                    : entry,
                                ),
                              },
                            }))
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Telemetry refresh interval (ms)</span>
                        <input
                          type="number"
                          min={250}
                          max={5000}
                          step={50}
                          value={activeDrone.telemetry_refresh_interval_ms ?? 1000}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => ({
                              ...profile,
                              fleet: {
                                ...profile.fleet,
                                drones: profile.fleet.drones.map((entry) =>
                                  entry.drone_id === activeDrone.drone_id
                                    ? {
                                        ...entry,
                                        telemetry_refresh_interval_ms: Number.isFinite(event.target.valueAsNumber)
                                          ? event.target.valueAsNumber
                                          : undefined,
                                      }
                                    : entry,
                                ),
                              },
                            }))
                          }
                          placeholder="1000"
                        />
                      </label>
                      <label className="field">
                        <span>Api Key</span>
                        <input
                          value={activeDrone.transport.api_key ?? ''}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => ({
                              ...profile,
                              fleet: {
                                ...profile.fleet,
                                drones: profile.fleet.drones.map((entry) =>
                                  entry.drone_id === activeDrone.drone_id
                                    ? {
                                        ...entry,
                                        transport: {
                                          ...entry.transport,
                                          api_key: event.target.value,
                                        },
                                      }
                                    : entry,
                                ),
                              },
                            }))
                          }
                          placeholder="x-api-key"
                          autoComplete="off"
                          spellCheck={false}
                        />
                      </label>
                      <label className="field">
                        <span>Control token</span>
                        <input
                          value={activeDrone.transport.control_token ?? ''}
                          onChange={(event) =>
                            setProfileField(activeProfile.profile_id, (profile) => ({
                              ...profile,
                              fleet: {
                                ...profile.fleet,
                                drones: profile.fleet.drones.map((entry) =>
                                  entry.drone_id === activeDrone.drone_id
                                    ? {
                                        ...entry,
                                        transport: {
                                          ...entry.transport,
                                          control_token: event.target.value,
                                        },
                                      }
                                    : entry,
                                ),
                              },
                            }))
                          }
                          placeholder="x-control-token"
                          autoComplete="off"
                          spellCheck={false}
                        />
                      </label>
                      <div className="field authority-field">
                        <span>Control authority</span>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => void onAcquireAuthority(activeProfile.profile_id, activeDrone.drone_id)}
                          disabled={saving || loading || acquiringAuthorityDroneId === activeDrone.drone_id}
                        >
                          {acquiringAuthorityDroneId === activeDrone.drone_id ? 'Acquiring...' : 'Acquire authority'}
                        </button>
                      </div>
                    </div>

                    <div className="stack">
                      <span className="metric-title">Alternate endpoints</span>
                      {(activeDrone.endpoints?.length ? activeDrone.endpoints : [ensurePrimaryEndpoint(activeDrone)]).map(
                        (endpoint, endpointIndex, endpointValues) => (
                          <div className="endpoint-row" key={`${activeDrone.drone_id}-${endpointIndex}`}>
                            <input
                              value={endpoint}
                              onChange={(event) =>
                                setProfileField(activeProfile.profile_id, (profile) => ({
                                  ...profile,
                                  fleet: {
                                    ...profile.fleet,
                                    drones: profile.fleet.drones.map((entry) => {
                                      if (entry.drone_id !== activeDrone.drone_id) {
                                        return entry;
                                      }

                                      const nextEndpoints = [...(entry.endpoints ?? endpointValues)];
                                      nextEndpoints[endpointIndex] = event.target.value;
                                      return normalizeEndpoints(entry, nextEndpoints);
                                    }),
                                  },
                                }))
                              }
                            />
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() =>
                                setProfileField(activeProfile.profile_id, (profile) => ({
                                  ...profile,
                                  fleet: {
                                    ...profile.fleet,
                                    drones: profile.fleet.drones.map((entry) => {
                                      if (entry.drone_id !== activeDrone.drone_id) {
                                        return entry;
                                      }

                                      const nextEndpoints = [...(entry.endpoints ?? endpointValues)];
                                      nextEndpoints.splice(endpointIndex, 1);
                                      return normalizeEndpoints(entry, nextEndpoints);
                                    }),
                                  },
                                }))
                              }
                              disabled={endpointValues.length <= 1}
                            >
                              Remove
                            </button>
                          </div>
                        ),
                      )}
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() =>
                          setProfileField(activeProfile.profile_id, (profile) => ({
                            ...profile,
                            fleet: {
                              ...profile.fleet,
                              drones: profile.fleet.drones.map((entry) => {
                                if (entry.drone_id !== activeDrone.drone_id) {
                                  return entry;
                                }

                                const nextEndpoints = [...(entry.endpoints ?? [ensurePrimaryEndpoint(activeDrone)]), ''];
                                return normalizeEndpoints(entry, nextEndpoints);
                              }),
                            },
                          }))
                        }
                      >
                        Add endpoint
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            <p className="hint">Save settings to persist the active profile and drone endpoints in SQLite.</p>
          </>
        ) : (
          <>
            <p className="hint">Sign in to load your saved connection profiles.</p>
            <label className="field">
              <span>Username</span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                spellCheck={false}
                placeholder="pilot"
              />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                spellCheck={false}
              />
            </label>
            <div className="settings-actions">
              <button type="button" className="secondary-button" onClick={handleSignIn} disabled={loading}>
                Sign in
              </button>
              <button type="button" className="ghost-button" onClick={() => setCreateUserOpen(true)} disabled={loading}>
                Create user
              </button>
            </div>
          </>
        )}

        {message ? <p className="hint">{message}</p> : null}
      </div>
      )}
      {createUserOpen ? (
        <div className="settings-modal-backdrop" role="presentation">
          <div className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="create-user-title">
            <div className="settings-modal-head">
              <div>
                <span className="panel-label">User settings</span>
                <h3 id="create-user-title">Create user</h3>
              </div>
              <button type="button" className="ghost-button" onClick={() => setCreateUserOpen(false)} disabled={loading}>
                Close
              </button>
            </div>

            <div className="stack">
              <label className="field">
                <span>Username</span>
                <input
                  value={createUsername}
                  onChange={(event) => setCreateUsername(event.target.value)}
                  autoComplete="username"
                  spellCheck={false}
                  placeholder="pilot"
                />
              </label>
              <label className="field">
                <span>Password</span>
                <input
                  type="password"
                  value={createPassword}
                  onChange={(event) => setCreatePassword(event.target.value)}
                  autoComplete="new-password"
                  spellCheck={false}
                />
              </label>
              <label className="field">
                <span>Display name</span>
                <input
                  value={createDisplayName}
                  onChange={(event) => setCreateDisplayName(event.target.value)}
                  autoComplete="name"
                  spellCheck={false}
                  placeholder="Pilot"
                />
              </label>
              <div className="settings-actions">
                <button type="button" className="secondary-button" onClick={handleCreateUser} disabled={loading}>
                  {loading ? 'Creating...' : 'Create user'}
                </button>
                <button type="button" className="ghost-button" onClick={() => setCreateUserOpen(false)} disabled={loading}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
