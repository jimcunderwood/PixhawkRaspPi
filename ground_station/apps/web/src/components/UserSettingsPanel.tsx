import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react';
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
  onSave: (settings?: GroundStationUserSettings) => Promise<void>;
  onDraftChange: Dispatch<SetStateAction<GroundStationUserSettings>>;
  onAcquireAuthority: (profileId: string, droneId: string) => Promise<void>;
  onDroneDeleted: (droneId: string, replacementDroneId?: string) => void;
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

function buildFallbackDrone(reference?: DroneFleetEntry, droneId = 'drone-01'): DroneFleetEntry {
  const fallback = cloneFleet(mockFleetConfig).drones[0];
  const source = reference ?? fallback;
  return {
    ...fallback,
    ...source,
    drone_id: droneId,
    callsign: source.callsign ?? fallback.callsign ?? 'Replacement drone',
    transport: {
      ...fallback.transport,
      ...source.transport,
      endpoint: source.transport.endpoint || fallback.transport.endpoint,
    },
    endpoints: source.endpoints?.length ? [...source.endpoints] : [...(fallback.endpoints ?? [])],
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
  onDroneDeleted,
  collapsed = false,
  onToggleCollapse,
}: UserSettingsPanelProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [userEditorOpen, setUserEditorOpen] = useState(false);
  const [authMode, setAuthMode] = useState<'signIn' | 'create' | 'session'>('signIn');
  const [createUsername, setCreateUsername] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [createDisplayName, setCreateDisplayName] = useState('');
  const [createBootstrapApiKey, setCreateBootstrapApiKey] = useState('');
  const [droneEditorOpen, setDroneEditorOpen] = useState(false);
  const [editingDroneId, setEditingDroneId] = useState<string | undefined>();
  const [deleteDroneRequest, setDeleteDroneRequest] = useState<{
    profileId: string;
    droneId: string;
    label: string;
  } | null>(null);
  const droneIdInputRef = useRef<HTMLInputElement | null>(null);
  const userNameInputRef = useRef<HTMLInputElement | null>(null);
  const autoOpenedLoginPrompt = useRef(false);
  const previousAuthenticated = useRef<boolean | null>(null);

  const activeProfileIndex = useMemo(() => {
    const exactIndex = settingsDraft.profiles.findIndex((profile) => profile.profile_id === settingsDraft.active_profile_id);
    return exactIndex >= 0 ? exactIndex : 0;
  }, [settingsDraft.active_profile_id, settingsDraft.profiles]);

  const activeProfile = settingsDraft.profiles[activeProfileIndex] ?? settingsDraft.profiles[0];
  const activeFleet = activeProfile?.fleet ?? cloneFleet(mockFleetConfig);
  const activeDroneId = activeProfile?.selected_drone_id ?? activeFleet.drones[0]?.drone_id;
  const activeDrone = activeFleet.drones.find((drone) => drone.drone_id === activeDroneId) ?? activeFleet.drones[0];
  const profileOptions = settingsDraft.profiles;
  const editorProfile = activeProfile;
  const editorDrone =
    editorProfile?.fleet.drones.find((drone) => drone.drone_id === editingDroneId) ?? activeDrone;

  useEffect(() => {
    if (droneEditorOpen) {
      window.requestAnimationFrame(() => {
        droneIdInputRef.current?.focus();
        droneIdInputRef.current?.select();
      });
    }
  }, [droneEditorOpen, editingDroneId]);

  useEffect(() => {
    if (userEditorOpen) {
      window.requestAnimationFrame(() => {
        userNameInputRef.current?.focus();
        userNameInputRef.current?.select();
      });
    }
  }, [userEditorOpen]);

  useEffect(() => {
    if (!autoOpenedLoginPrompt.current && !authenticated && !hasUsers) {
      autoOpenedLoginPrompt.current = true;
      setUserEditorOpen(true);
      setAuthMode('signIn');
    }
  }, [authenticated, hasUsers]);

  useEffect(() => {
    const wasAuthenticated = previousAuthenticated.current;
    previousAuthenticated.current = authenticated;

    if (!authenticated && (wasAuthenticated === true || wasAuthenticated === null)) {
      setUserEditorOpen(true);
      setAuthMode('signIn');
    }
  }, [authenticated]);

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

  function openDroneEditor(droneId?: string) {
    setEditingDroneId(droneId ?? activeDrone?.drone_id);
    setDroneEditorOpen(true);
  }

  function createAndEditDrone() {
    let createdDroneId: string | undefined;
    mutateSettings((current) =>
      updateProfile(current, activeProfile.profile_id, (profile) => {
        const nextIndex = profile.fleet.drones.length + 1;
        const nextDroneId = `drone-${String(nextIndex).padStart(2, '0')}`;
        createdDroneId = nextDroneId;
        const nextDrone: DroneFleetEntry = {
          drone_id: nextDroneId,
          callsign: `Drone ${nextIndex}`,
          role: 'wing',
          transport: {
            type: profile.fleet.default_transport ?? 'http',
            endpoint: '',
            api_key: '',
            control_token: '',
          },
          endpoints: [''],
          status: 'idle',
        };

        return {
          ...profile,
          selected_drone_id: nextDroneId,
          fleet: {
            ...profile.fleet,
            drones: [...profile.fleet.drones, nextDrone],
          },
        };
      }),
    );
    setEditingDroneId(createdDroneId);
    setDroneEditorOpen(true);
  }

  function deleteDroneEverywhere(settings: GroundStationUserSettings, droneId: string): GroundStationUserSettings {
    const survivingDrones = settings.profiles.flatMap((profile) => profile.fleet.drones.filter((drone) => drone.drone_id !== droneId));
    const fallbackTemplate = survivingDrones[0] ?? buildFallbackDrone(undefined, 'drone-01');

    const profiles = settings.profiles.map((profile) => {
      const drones = profile.fleet.drones.filter((drone) => drone.drone_id !== droneId);
      if (drones.length) {
        return {
          ...profile,
          selected_drone_id: profile.selected_drone_id === droneId ? drones[0].drone_id : profile.selected_drone_id,
          fleet: {
            ...profile.fleet,
            drones,
          },
        };
      }

      const replacementDrone = buildFallbackDrone(fallbackTemplate, fallbackTemplate.drone_id === droneId ? 'drone-01' : fallbackTemplate.drone_id);
      return {
        ...profile,
        selected_drone_id: replacementDrone.drone_id,
        fleet: {
          ...profile.fleet,
          drones: [replacementDrone],
        },
      };
    });

    const activeProfile = profiles.find((profile) => profile.profile_id === settings.active_profile_id) ?? profiles[0];
    return {
      ...settings,
      profiles,
      active_profile_id: activeProfile?.profile_id ?? settings.active_profile_id,
    };
  }

  async function confirmDeleteDrone() {
    const request = deleteDroneRequest;
    if (!request) {
      return;
    }

    const nextSettings = deleteDroneEverywhere(settingsDraft, request.droneId);
    const profile = nextSettings.profiles.find((entry) => entry.profile_id === request.profileId);
    const remainingDroneId =
      profile?.fleet.drones.find((drone) => drone.drone_id !== request.droneId)?.drone_id ??
      profile?.fleet.drones[0]?.drone_id;

    onDraftChange(cloneSettings(nextSettings));
    setDeleteDroneRequest(null);

    await onSave(nextSettings);
    onDroneDeleted(request.droneId, remainingDroneId);

    if (remainingDroneId) {
      setEditingDroneId(remainingDroneId);
      setSelectedDrone(request.profileId, remainingDroneId);
      openDroneEditor(remainingDroneId);
    } else {
      setDroneEditorOpen(false);
    }
  }

  function setSelectedDrone(profileId: string, droneId: string) {
    setProfileField(profileId, (profile) => ({
      ...profile,
      selected_drone_id: droneId,
    }));
  }

  async function handleSignIn() {
    const nextUsername = username.trim();
    const nextPassword = password;
    try {
      await onLogin({
        username: nextUsername,
        password: nextPassword,
        create: false,
      });
      setAuthMode('session');
      setUserEditorOpen(false);
    } finally {
      setPassword('');
    }
  }

  async function handleCreateUser() {
    const nextUsername = createUsername.trim();
    const nextPassword = createPassword;
    if (!nextUsername || !nextPassword) {
      return;
    }
    const success = await onLogin({
      username: nextUsername,
      password: nextPassword,
      display_name: createDisplayName.trim() || nextUsername,
      create: true,
      bootstrap_api_key: createBootstrapApiKey.trim(),
    });

    if (success) {
      setAuthMode('signIn');
      setUserEditorOpen(true);
      setUsername(nextUsername);
      setPassword('');
      setCreateUsername('');
      setCreatePassword('');
      setCreateDisplayName('');
      setCreateBootstrapApiKey('');
    }
  }

  return (
    <section className="sidebar-panel sidebar-accordion settings-panel">
      <div className="sidebar-panel-head">
        <div>
          <span className="panel-label">User settings</span>
          <h3>{authenticated ? 'Stored profile access' : 'Sign in'}</h3>
        </div>
      </div>

      {collapsed ? null : (
      <div className="stack">
        {authenticated ? (
          <>
            <div className="stack">
              <label className="field">
                <span>Drone</span>
                <select
                  value={activeDrone?.drone_id ?? ''}
                  onChange={(event) => {
                    const nextDroneId = event.target.value;
                    setSelectedDrone(editorProfile.profile_id, nextDroneId);
                    openDroneEditor(nextDroneId);
                  }}
                >
                  {editorProfile.fleet.drones.map((drone) => (
                    <option key={drone.drone_id} value={drone.drone_id}>
                      {drone.callsign ?? drone.drone_id}
                    </option>
                  ))}
                </select>
              </label>
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
              <button type="button" className="secondary-button" onClick={() => openDroneEditor(activeDrone?.drone_id)} disabled={loading}>
                Drone settings
              </button>
              <button type="button" className="secondary-button" onClick={() => setUserEditorOpen(true)} disabled={loading}>
                Edit user settings
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="settings-actions">
              <button type="button" className="secondary-button" onClick={() => setUserEditorOpen(true)} disabled={loading}>
                User settings
              </button>
            </div>
          </>
        )}

        {message ? <p className="hint">{message}</p> : null}
      </div>
      )}
      {droneEditorOpen && editorProfile && editorDrone ? (
        <div className="settings-modal-backdrop" role="presentation">
          <div className="settings-modal setup-modal" role="dialog" aria-modal="true" aria-labelledby="drone-editor-title">
            <div className="settings-modal-head">
              <div>
                <span className="panel-label">Drone settings</span>
                <h3 id="drone-editor-title">{editingDroneId?.startsWith('__new__') ? 'Add drone' : 'Edit drone settings'}</h3>
              </div>
              <div className="settings-modal-head-actions">
                <button type="button" className="secondary-button" onClick={createAndEditDrone} disabled={loading || saving}>
                  Add drone
                </button>
                <button
                  type="button"
                  className="danger-button"
                  onClick={() =>
                    setDeleteDroneRequest({
                      profileId: editorProfile.profile_id,
                      droneId: editorDrone.drone_id,
                      label: editorDrone.callsign?.trim()
                        ? `${editorDrone.callsign} (${editorDrone.drone_id})`
                        : editorDrone.drone_id,
                    })
                  }
                  disabled={loading || saving || editorProfile.fleet.drones.length <= 1}
                >
                  Delete drone
                </button>
                <button type="button" className="ghost-button" onClick={() => setDroneEditorOpen(false)} disabled={loading || saving}>
                  Close
                </button>
              </div>
            </div>

            <label className="field">
              <span>Drone</span>
              <select
                value={editorDrone.drone_id}
                onChange={(event) => {
                  const nextDroneId = event.target.value;
                  setSelectedDrone(editorProfile.profile_id, nextDroneId);
                  openDroneEditor(nextDroneId);
                }}
              >
                {editorProfile.fleet.drones.map((drone) => (
                  <option key={drone.drone_id} value={drone.drone_id}>
                    {drone.callsign ?? drone.drone_id}
                  </option>
                ))}
              </select>
            </label>

            <div className="config-grid setup-config-grid">
              <label className="field">
                <span>Drone ID</span>
                <input
                  ref={droneIdInputRef}
                  value={editorDrone.drone_id}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => {
                      const nextDroneId = event.target.value;
                      return {
                        ...profile,
                        selected_drone_id:
                          profile.selected_drone_id === editorDrone.drone_id ? nextDroneId : profile.selected_drone_id,
                        fleet: {
                          ...profile.fleet,
                          drones: profile.fleet.drones.map((entry) =>
                            entry.drone_id === editorDrone.drone_id ? { ...entry, drone_id: nextDroneId } : entry,
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
                  value={editorDrone.callsign ?? ''}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => ({
                      ...profile,
                      fleet: {
                        ...profile.fleet,
                        drones: profile.fleet.drones.map((entry) =>
                          entry.drone_id === editorDrone.drone_id ? { ...entry, callsign: event.target.value } : entry,
                        ),
                      },
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>Role</span>
                <input
                  value={editorDrone.role ?? ''}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => ({
                      ...profile,
                      fleet: {
                        ...profile.fleet,
                        drones: profile.fleet.drones.map((entry) =>
                          entry.drone_id === editorDrone.drone_id ? { ...entry, role: event.target.value } : entry,
                        ),
                      },
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>Transport</span>
                <select
                  value={editorDrone.transport.type}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => ({
                      ...profile,
                      fleet: {
                        ...profile.fleet,
                        drones: profile.fleet.drones.map((entry) =>
                          entry.drone_id === editorDrone.drone_id
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
                  value={editorDrone.transport.endpoint}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => ({
                      ...profile,
                      fleet: {
                        ...profile.fleet,
                        drones: profile.fleet.drones.map((entry) =>
                          entry.drone_id === editorDrone.drone_id
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
                  value={editorDrone.telemetry_refresh_interval_ms ?? 1000}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => ({
                      ...profile,
                      fleet: {
                        ...profile.fleet,
                        drones: profile.fleet.drones.map((entry) =>
                          entry.drone_id === editorDrone.drone_id
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
                  value={editorDrone.transport.api_key ?? ''}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => ({
                      ...profile,
                      fleet: {
                        ...profile.fleet,
                        drones: profile.fleet.drones.map((entry) =>
                          entry.drone_id === editorDrone.drone_id
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
                  value={editorDrone.transport.control_token ?? ''}
                  onChange={(event) =>
                    setProfileField(editorProfile.profile_id, (profile) => ({
                      ...profile,
                      fleet: {
                        ...profile.fleet,
                        drones: profile.fleet.drones.map((entry) =>
                          entry.drone_id === editorDrone.drone_id
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
                  onClick={() => void onAcquireAuthority(editorProfile.profile_id, editorDrone.drone_id)}
                  disabled={saving || loading || acquiringAuthorityDroneId === editorDrone.drone_id}
                >
                  {acquiringAuthorityDroneId === editorDrone.drone_id ? 'Acquiring...' : 'Acquire authority'}
                </button>
              </div>
            </div>

            <div className="stack">
              <span className="metric-title">Alternate endpoints</span>
              {(editorDrone.endpoints?.length ? editorDrone.endpoints : [ensurePrimaryEndpoint(editorDrone)]).map(
                (endpoint, endpointIndex, endpointValues) => (
                  <div className="endpoint-row" key={`${editorDrone.drone_id}-${endpointIndex}`}>
                    <input
                      value={endpoint}
                      onChange={(event) =>
                        setProfileField(editorProfile.profile_id, (profile) => ({
                          ...profile,
                          fleet: {
                            ...profile.fleet,
                            drones: profile.fleet.drones.map((entry) => {
                              if (entry.drone_id !== editorDrone.drone_id) {
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
                        setProfileField(editorProfile.profile_id, (profile) => ({
                          ...profile,
                          fleet: {
                            ...profile.fleet,
                            drones: profile.fleet.drones.map((entry) => {
                              if (entry.drone_id !== editorDrone.drone_id) {
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
                  setProfileField(editorProfile.profile_id, (profile) => ({
                    ...profile,
                    fleet: {
                      ...profile.fleet,
                      drones: profile.fleet.drones.map((entry) => {
                        if (entry.drone_id !== editorDrone.drone_id) {
                          return entry;
                        }

                        const nextEndpoints = [...(entry.endpoints ?? [ensurePrimaryEndpoint(editorDrone)]), ''];
                        return normalizeEndpoints(entry, nextEndpoints);
                      }),
                    },
                  }))
                }
              >
                Add endpoint
              </button>
            </div>

            <div className="settings-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={async () => {
                  await onSave();
                  setDroneEditorOpen(false);
                }}
                disabled={saving || loading}
              >
                Save Drone
              </button>
              <button type="button" className="ghost-button" onClick={() => setDroneEditorOpen(false)} disabled={saving || loading}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {deleteDroneRequest ? (
        <div className="settings-modal-backdrop" role="presentation">
          <div className="settings-modal setup-modal" role="dialog" aria-modal="true" aria-labelledby="delete-drone-title">
            <div className="settings-modal-head">
              <div>
                <span className="panel-label">Delete drone</span>
                <h3 id="delete-drone-title">Confirm deletion</h3>
              </div>
              <button type="button" className="ghost-button" onClick={() => setDeleteDroneRequest(null)} disabled={loading || saving}>
                Close
              </button>
            </div>

            <p className="hint">
              Permanently delete <strong>{deleteDroneRequest.label}</strong> from all profiles? This removes the drone entry everywhere in the
              app and cannot be undone.
            </p>

            <div className="settings-actions">
              <button type="button" className="danger-button" onClick={() => void confirmDeleteDrone()} disabled={loading || saving}>
                Delete drone
              </button>
              <button type="button" className="ghost-button" onClick={() => setDeleteDroneRequest(null)} disabled={loading || saving}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {userEditorOpen ? (
        <div className="settings-modal-backdrop" role="presentation">
          <div className="settings-modal setup-modal" role="dialog" aria-modal="true" aria-labelledby="user-settings-title">
            <div className="settings-modal-head">
              <div>
                <span className="panel-label">User settings</span>
                <h3 id="user-settings-title">{authenticated ? 'Manage user settings' : authMode === 'create' ? 'Create user' : 'Sign in'}</h3>
              </div>
              <button type="button" className="ghost-button" onClick={() => setUserEditorOpen(false)} disabled={loading || saving}>
                Close
              </button>
            </div>

            <div className="stack">
              {authenticated ? (
                <>
                  <StatusChip label="User" value={sessionUser?.display_name ?? sessionUser?.username ?? 'signed in'} tone="good" />
                  <StatusChip label="Storage" value="SQLite-backed session" tone="neutral" />
                  <label className="field">
                    <span>Active profile</span>
                    <select value={settingsDraft.active_profile_id} onChange={(event) => setActiveProfile(event.target.value)}>
                      {profileOptions.map((profile) => (
                        <option key={profile.profile_id} value={profile.profile_id}>
                          {profile.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              ) : (
                <p className="hint">
                  {hasUsers
                    ? 'Sign in to load your saved connection profiles.'
                    : 'No users exist yet. Create the first user to start using the app. You will need the API key from the .env file.'}
                </p>
              )}
              {!authenticated && authMode === 'signIn' ? (
                <section className="auth-card">
                  <div className="auth-card-head">
                    <div>
                      <span className="metric-title">Sign In</span>
                      <p className="hint">Use an existing account to load stored settings.</p>
                    </div>
                  </div>
                  <label className="field">
                    <span>Username</span>
                    <input
                      ref={userNameInputRef}
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
                </section>
              ) : authenticated ? (
                <section className="auth-card">
                  <div className="auth-card-head">
                    <div>
                      <span className="metric-title">Session</span>
                      <p className="hint">You are signed in. Use logout to switch accounts.</p>
                    </div>
                  </div>
                  <div className="settings-actions">
                    <button type="button" className="ghost-button" onClick={onLogout} disabled={saving || loading}>
                      Sign out
                    </button>
                  </div>
                </section>
              ) : null}
              {!authenticated && authMode === 'create' ? (
                <section className="auth-card auth-card-accent">
                  <div className="auth-card-head">
                    <div>
                      <span className="metric-title">Create User</span>
                      <p className="hint">
                        {hasUsers
                          ? 'Create an additional account.'
                          : 'Create the first user to unlock the app. The bootstrap API key is required once.'}
                      </p>
                    </div>
                  </div>
                  <label className="field">
                    <span>New username</span>
                    <input
                      value={createUsername}
                      onChange={(event) => setCreateUsername(event.target.value)}
                      autoComplete="username"
                      spellCheck={false}
                      placeholder="pilot"
                    />
                  </label>
                  <label className="field">
                    <span>New password</span>
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
                  {!hasUsers ? (
                    <label className="field">
                      <span>Bootstrap API key</span>
                      <input
                        type="password"
                        value={createBootstrapApiKey}
                        onChange={(event) => setCreateBootstrapApiKey(event.target.value)}
                        autoComplete="off"
                        spellCheck={false}
                        placeholder="API_KEY from .env"
                      />
                    </label>
                  ) : null}
                </section>
              ) : null}
              <div className="settings-actions">
                {!authenticated ? (
                  authMode === 'signIn' ? (
                    <>
                      <button type="button" className="secondary-button" onClick={handleSignIn} disabled={loading}>
                        Sign in
                      </button>
                      <button type="button" className="ghost-button" onClick={() => setAuthMode('create')} disabled={loading}>
                        Create user
                      </button>
                    </>
                  ) : (
                    <>
                      <button type="button" className="secondary-button" onClick={handleCreateUser} disabled={loading}>
                        {loading ? 'Creating...' : 'Save user'}
                      </button>
                      <button type="button" className="ghost-button" onClick={() => setAuthMode('signIn')} disabled={loading}>
                        Back to sign in
                      </button>
                    </>
                  )
                ) : (
                  <>
                    <button type="button" className="secondary-button" onClick={() => void onSave()} disabled={saving || loading}>
                      Save settings
                    </button>
                    <button type="button" className="ghost-button" onClick={onLogout} disabled={saving || loading}>
                      Sign out
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
