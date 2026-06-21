import { useEffect, useMemo, useRef, useState } from 'react';
import { FieldMap } from './components/FieldMap';
import { CalibrationHistoryPanel } from './components/CalibrationHistoryPanel';
import { FleetPanel } from './components/FleetPanel';
import { FarmTimelinePanel } from './components/FarmTimelinePanel';
import { FlightLogTimelinePanel } from './components/FlightLogTimelinePanel';
import { FlightPathPlannerScreen } from './components/FlightPathPlannerScreen';
import { ShellStatusPanel } from './components/ShellStatusPanel';
import { SwarmConfigEditor } from './components/SwarmConfigEditor';
import { TelemetryCharts } from './components/TelemetryCharts';
import { UserSettingsPanel } from './components/UserSettingsPanel';
import { mockSnapshot } from './data/mockState';
import { useTelemetryStream } from './hooks/useTelemetryStream';
import {
  exportIsoxml,
  generateFarmReport,
  importPrescriptionMap,
  getBaseUrl,
  loadCompanionSnapshot,
  loadFlightLogSyncHistory,
  loadGeoTiffPreview,
  loadTelemetryCurrent,
  processPpkJob,
  replayFlightLogSyncBundle,
  saveBaseStation,
  syncAgLeader,
  uploadGeoTiffPreview,
} from './lib/companionClient';
import { MetricCard, StatusChip } from '../../../packages/ui/src';
import { mockFleetConfig } from '../../../shared/fleet/mock';
import {
  acquireControlAuthority,
  clearCompanionMission,
  loadFieldBoundaries,
  loadMissionState,
  uploadFieldBoundary,
  uploadMissionToPixhawk,
  uploadMissionWaypoint,
} from '../../../shared/api/mission';
import type { DroneFleetEntry, DroneTransport, FleetConfig, TransportKind } from '../../../shared/types/fleet';
import {
  appendDraftWaypoint,
  createMissionRouteDraft,
  type FlightPathParameters,
  serializeFlightPathParameters,
  serializeMissionRouteExport,
  updateDraftBoundary,
  updateDraftWaypoints,
} from '../../../shared/mission/routes';
import {
  type GroundStationLoginRequest,
  type GroundStationSessionState,
  type GroundStationUserSettings,
} from '../../../shared/types/settings';
import {
  deleteDroneFromUserSettings,
  loadSession as loadSettingsSession,
  loadUserSettings,
  login as loginUser,
  logout as logoutUser,
  saveUserSettings,
} from '../../../shared/api/settings';
import { buildSurveyPreview, computePolygonCenter } from '../../../shared/mission/planning';
import { detectShellContext } from './lib/shell';
import type { RuntimeConfig } from './runtimeConfig';
import type {
  CompanionSnapshot,
  ConnectionState,
  FlightLogSyncHistoryEntry,
  LatLngPoint,
  MissionEditorMode,
  MissionWaypoint,
} from './types';
import type { PpkJobStatus } from '../../../shared/types/base';

const DEFAULT_COMPANION_REFRESH_INTERVAL_MS = 500;
const MIN_COMPANION_REFRESH_INTERVAL_MS = 100;
const MAX_COMPANION_REFRESH_INTERVAL_MS = 5000;
const DEFAULT_FLIGHT_PATH_PARAMETERS: FlightPathParameters = {
  altitude_m: 60,
  speed_mps: 5,
  swath_width_m: 12,
  auto_optimize: true,
  boundary_pass: 'after',
};
const EMPTY_BREADCRUMB: [] = [];

type AppProps = {
  defaultCompanionBaseUrl?: string;
  runtimeConfig?: RuntimeConfig;
};

type FleetMarker = DroneFleetEntry & {
  active?: boolean;
  position?: {
    latitude?: number;
    longitude?: number;
    altitude?: number;
    heading?: number;
  };
  trust?: string;
  last_seen_at?: number;
  sample_id?: string;
  sequence?: number;
  vehicle?: {
    armed?: boolean;
    mode?: string;
    battery_percent?: number;
  } | null;
};

function normalizeConnectionState(snapshot: CompanionSnapshot): ConnectionState {
  if (snapshot.health?.data?.connected || snapshot.vehicle) {
    return 'connected';
  }

  if (snapshot.health) {
    return 'connecting';
  }

  return 'disconnected';
}

function telemetryToVehicle(telemetry?: CompanionSnapshot['telemetry']): CompanionSnapshot['vehicle'] | undefined {
  if (!telemetry) {
    return undefined;
  }

  const hasUsefulFields =
    telemetry.armed !== undefined ||
    telemetry.mode !== undefined ||
    telemetry.ground_speed !== undefined ||
    telemetry.air_speed !== undefined ||
    telemetry.heading !== undefined ||
    telemetry.location !== undefined ||
    telemetry.battery !== undefined;

  if (!hasUsefulFields) {
    return undefined;
  }

  return {
    armed: telemetry.armed,
    mode: telemetry.mode,
    ground_speed: telemetry.ground_speed,
    air_speed: telemetry.air_speed,
    heading: telemetry.heading,
    battery: telemetry.battery,
    location: telemetry.location,
  };
}

function clampRefreshInterval(value?: number): number {
  const candidate = Number.isFinite(value) ? Number(value) : DEFAULT_COMPANION_REFRESH_INTERVAL_MS;
  return Math.max(MIN_COMPANION_REFRESH_INTERVAL_MS, Math.min(MAX_COMPANION_REFRESH_INTERVAL_MS, Math.round(candidate)));
}

function formatMeters(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return '--';
  }

  return `${value.toFixed(1)} m`;
}

function formatPercent(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return '--';
  }

  return `${Math.round(value)}%`;
}

function formatOptionalNumber(value?: number | null, digits = 1, suffix = '') {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '--';
  }

  return `${value.toFixed(digits)}${suffix}`;
}

function formatAge(timestamp?: number | null) {
  if (!timestamp) {
    return '--';
  }

  const ageSeconds = Math.max(0, (Date.now() / 1000) - timestamp);
  if (ageSeconds < 60) {
    return `${Math.round(ageSeconds)}s ago`;
  }
  if (ageSeconds < 3600) {
    return `${Math.round(ageSeconds / 60)}m ago`;
  }
  return `${Math.round(ageSeconds / 3600)}h ago`;
}

function computeOverlayBounds(points: Array<LatLngPoint>, center: [number, number]) {
  if (points.length) {
    const latitudes = points.map((point) => point.latitude);
    const longitudes = points.map((point) => point.longitude);
    const south = Math.min(...latitudes);
    const north = Math.max(...latitudes);
    const west = Math.min(...longitudes);
    const east = Math.max(...longitudes);
    const latitudePadding = Math.max((north - south) * 0.18, 0.00035);
    const longitudePadding = Math.max((east - west) * 0.18, 0.00035);

    return [
      [south - latitudePadding, west - longitudePadding],
      [north + latitudePadding, east + longitudePadding],
    ] as [[number, number], [number, number]];
  }

  const [latitude, longitude] = center;
  return [
    [latitude - 0.0014, longitude - 0.0014],
    [latitude + 0.0014, longitude + 0.0014],
  ] as [[number, number], [number, number]];
}

function cloneSettings(settings: GroundStationUserSettings): GroundStationUserSettings {
  return JSON.parse(JSON.stringify(settings)) as GroundStationUserSettings;
}

const emptyUserSettings: GroundStationUserSettings = {
  user_id: '',
  username: '',
  active_profile_id: '',
  profiles: [],
};

function nonEmptyTrimmed(value?: string): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

function endpointProtocol(endpoint?: string): string | undefined {
  const trimmed = nonEmptyTrimmed(endpoint);
  if (!trimmed) {
    return undefined;
  }

  try {
    return new URL(trimmed).protocol.replace(':', '');
  } catch {
    return undefined;
  }
}

function candidateDroneEndpoints(drone?: DroneFleetEntry): string[] {
  const candidates = [drone?.transport.endpoint, ...(drone?.endpoints ?? [])]
    .map(nonEmptyTrimmed)
    .filter(Boolean) as string[];

  return [...new Set(candidates)];
}

function websocketEndpointAsHttp(endpoint?: string): string | undefined {
  const protocol = endpointProtocol(endpoint);
  if (protocol !== 'ws' && protocol !== 'wss') {
    return undefined;
  }

  const url = new URL(endpoint as string);
  url.protocol = protocol === 'wss' ? 'https:' : 'http:';
  return url.toString();
}

function selectCompanionApiBase(drone?: DroneFleetEntry, fallback?: string): string | undefined {
  const endpoints = candidateDroneEndpoints(drone);
  const fallbackBase = nonEmptyTrimmed(fallback);
  const explicitHttpEndpoint = endpoints.find((endpoint) => {
    const protocol = endpointProtocol(endpoint);
    return protocol === 'http' || protocol === 'https';
  });

  return explicitHttpEndpoint ?? fallbackBase ?? websocketEndpointAsHttp(endpoints[0]);
}

function selectTelemetryBase(drone?: DroneFleetEntry, fallback?: string): string | undefined {
  const endpoints = candidateDroneEndpoints(drone);
  const fallbackBase = nonEmptyTrimmed(fallback);
  const streamEndpoint = endpoints.find((endpoint) => {
    const protocol = endpointProtocol(endpoint);
    return protocol === 'ws' || protocol === 'wss' || protocol === 'http' || protocol === 'https';
  });

  return streamEndpoint ?? fallbackBase;
}

type SettingsSetupIssue = {
  field: string;
  message: string;
};

const validSetupEndpointProtocols = new Set(['http', 'https', 'ws', 'wss', 'udp']);
const setupTransportOptions: TransportKind[] = ['http', 'websocket', 'udp', 'mavlink', 'ipc', 'ble', 'native'];

function cloneFleetConfig(fleet: FleetConfig): FleetConfig {
  return JSON.parse(JSON.stringify(fleet)) as FleetConfig;
}

function defaultCompanionEndpoint(fallback?: string): string {
  return nonEmptyTrimmed(fallback) ?? 'http://192.168.1.140:8000';
}

function buildTelemetryEndpoint(companionEndpoint?: string): string {
  try {
    const url = new URL(defaultCompanionEndpoint(companionEndpoint));
    url.protocol = url.protocol === 'https:' || url.protocol === 'wss:' ? 'wss:' : 'ws:';
    url.pathname = '/ws/telemetry';
    url.search = '';
    url.hash = '';
    return url.toString();
  } catch {
    return 'ws://192.168.1.140:8000/ws/telemetry';
  }
}

function inferTransportKind(endpoint?: string): TransportKind {
  const protocol = endpointProtocol(endpoint);
  if (protocol === 'ws' || protocol === 'wss') {
    return 'websocket';
  }
  if (protocol === 'udp') {
    return 'udp';
  }
  return 'http';
}

function buildMinimumFleet(defaultCompanionBaseUrl?: string): FleetConfig {
  const endpoint = defaultCompanionEndpoint(defaultCompanionBaseUrl);
  const fleet = cloneFleetConfig(mockFleetConfig);
  const sourceDrone: DroneFleetEntry = fleet.drones[0] ?? {
    drone_id: 'drone-01',
    callsign: 'Primary drone',
    role: 'leader',
    transport: {
      type: 'http',
      endpoint,
      api_key: '',
      control_token: '',
    },
    endpoints: [endpoint, buildTelemetryEndpoint(endpoint)],
    status: 'active',
  };
  const drone: DroneFleetEntry = {
    ...sourceDrone,
    drone_id: sourceDrone?.drone_id?.trim() || 'drone-01',
    callsign: sourceDrone?.callsign?.trim() || 'Primary drone',
    role: sourceDrone?.role?.trim() || 'leader',
    transport: {
      ...(sourceDrone?.transport ?? { type: 'http', endpoint: '' }),
      type: inferTransportKind(endpoint),
      endpoint,
      api_key: sourceDrone?.transport?.api_key ?? '',
      control_token: sourceDrone?.transport?.control_token ?? '',
    },
    endpoints: [endpoint, buildTelemetryEndpoint(endpoint)],
    status: sourceDrone?.status ?? 'active',
  };

  return {
    ...fleet,
    default_transport: drone.transport.type,
    drones: [drone],
  };
}

function ensureRequiredSettingsShape(
  settings: GroundStationUserSettings,
  defaultCompanionBaseUrl?: string,
): GroundStationUserSettings {
  const next = cloneSettings(settings);
  if (!next.profiles.length) {
    next.profiles = [
      {
        profile_id: 'profile-default',
        label: 'Primary profile',
        companion_base_url: defaultCompanionBaseUrl,
        selected_drone_id: 'drone-01',
        fleet: buildMinimumFleet(defaultCompanionBaseUrl),
      },
    ];
    next.active_profile_id = 'profile-default';
    return next;
  }

  const activeProfile =
    next.profiles.find((profile) => profile.profile_id === next.active_profile_id) ??
    next.profiles[0];
  next.active_profile_id = activeProfile.profile_id;

  if (!activeProfile.label?.trim()) {
    activeProfile.label = 'Primary profile';
  }
  if (!activeProfile.fleet) {
    activeProfile.fleet = buildMinimumFleet(defaultCompanionBaseUrl);
  }
  if (!activeProfile.selected_drone_id || !activeProfile.fleet?.drones?.some((drone) => drone.drone_id === activeProfile.selected_drone_id)) {
    activeProfile.selected_drone_id = activeProfile.fleet?.drones?.[0]?.drone_id;
  }

  return next;
}

function endpointLooksUsable(endpoint?: string): boolean {
  const protocol = endpointProtocol(endpoint);
  return Boolean(protocol && validSetupEndpointProtocols.has(protocol));
}

function validateRequiredSettings(settings: GroundStationUserSettings): SettingsSetupIssue[] {
  const issues: SettingsSetupIssue[] = [];
  const profile =
    settings.profiles.find((entry) => entry.profile_id === settings.active_profile_id) ??
    settings.profiles[0];

  if (!settings.user_id || !settings.username) {
    issues.push({ field: 'User', message: 'The settings must belong to a signed-in user.' });
  }
  if (!profile) {
    issues.push({ field: 'Profile', message: 'Create at least one runtime profile.' });
    return issues;
  }
  if (!profile.label?.trim()) {
    issues.push({ field: 'Profile label', message: 'Enter a profile label.' });
  }
  if (!profile.fleet?.drones?.length) {
    issues.push({ field: 'Drone', message: 'Add at least one drone connection.' });
    return issues;
  }

  const drone =
    profile.fleet?.drones?.find((entry) => entry.drone_id === profile.selected_drone_id) ??
    profile.fleet?.drones?.[0];
  if (!drone.drone_id?.trim()) {
    issues.push({ field: 'Drone ID', message: 'Enter a stable drone ID.' });
  }
  if (!drone.callsign?.trim()) {
    issues.push({ field: 'Callsign', message: 'Enter a callsign for the primary drone.' });
  }
  if (!drone.transport?.type) {
    issues.push({ field: 'Transport', message: 'Select a transport type.' });
  }
  if (!drone.transport?.endpoint?.trim()) {
    issues.push({ field: 'Companion endpoint', message: 'Enter the endpoint for a Companion running on another machine or service, such as http://192.168.1.140:8000.' });
  } else if (!endpointLooksUsable(drone.transport.endpoint)) {
    issues.push({ field: 'Companion endpoint', message: 'Use a full URL with http://, https://, ws://, wss://, or udp://.' });
  }
  if (!drone.transport?.api_key?.trim()) {
    issues.push({ field: 'Api Key', message: 'Enter the API key copied from the companion install.' });
  }

  return issues;
}

function App({ defaultCompanionBaseUrl, runtimeConfig }: AppProps) {
  const geotiffInputRef = useRef<HTMLInputElement | null>(null);
  const prescriptionInputRef = useRef<HTMLInputElement | null>(null);
  const [sessionState, setSessionState] = useState<GroundStationSessionState>({
    authenticated: false,
    has_users: false,
  });
  const [settingsDraft, setSettingsDraft] = useState<GroundStationUserSettings>(emptyUserSettings);
  const [settingsMessage, setSettingsMessage] = useState('Sign in to load per-user connection profiles.');
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [requiredSetupOpen, setRequiredSetupOpen] = useState(false);
  const [statusSnapshot, setStatusSnapshot] = useState<CompanionSnapshot>(mockSnapshot);
  const [telemetrySnapshot, setTelemetrySnapshot] = useState<CompanionSnapshot['telemetry']>(mockSnapshot.telemetry);
  const [connectionState, setConnectionState] = useState<ConnectionState>('unknown');
  const [sourceLabel, setSourceLabel] = useState('mock data');
  const [refreshing, setRefreshing] = useState(true);
  const [missionMode, setMissionMode] = useState<MissionEditorMode>('view');
  const [screen, setScreen] = useState<'cockpit' | 'planner'>('cockpit');
  const [routeDraft, setRouteDraft] = useState(() => createMissionRouteDraft('Draft route'));
  const [flightPathParameters, setFlightPathParameters] = useState(DEFAULT_FLIGHT_PATH_PARAMETERS);
  const [plannerObstacles, setPlannerObstacles] = useState<Array<LatLngPoint & { radius_m?: number; label?: string }>>([]);
  const [plannerMode, setPlannerMode] = useState<MissionEditorMode>('view');
  const [routeMessage, setRouteMessage] = useState('Ready');
  const [imageryOverlayUrl, setImageryOverlayUrl] = useState<string | undefined>();
  const [imageryStatus, setImageryStatus] = useState('no overlay loaded');
  const [geotiffAssetId, setGeotiffAssetId] = useState<string | undefined>();
  const [geotiffStatus, setGeotiffStatus] = useState('no GeoTIFF loaded');
  const [geotiffBounds, setGeotiffBounds] = useState<[[number, number], [number, number]] | undefined>();
  const [authorityStatus, setAuthorityStatus] = useState('not requested');
  const [acquiringAuthorityDroneId, setAcquiringAuthorityDroneId] = useState<string | undefined>();
  const [prescriptionMessage, setPrescriptionMessage] = useState('no prescription loaded');
  const [calibrationMessage, setCalibrationMessage] = useState('no base station configured');
  const [farmMessage, setFarmMessage] = useState('farm integrations idle');
  const [flightLogMessage, setFlightLogMessage] = useState('flight log history not loaded');
  const [flightLogBundles, setFlightLogBundles] = useState<FlightLogSyncHistoryEntry[]>([]);
  const [uiRevision, setUiRevision] = useState(0);
  const [sidebarSections, setSidebarSections] = useState({
    drones: true,
    connection: true,
    mission: true,
    shell: true,
    settings: true,
  });
  const shellContext = useMemo(() => detectShellContext(), []);
  const [baseStationDraft, setBaseStationDraft] = useState({
    station_id: 'base-01',
    name: 'Field base station',
    latitude: '',
    longitude: '',
    altitude_m: '',
    antenna_height_m: '1.5',
    correction_port: '/dev/ttyUSB0',
    correction_baudrate: '115200',
    mount_type: 'tripod',
    notes: '',
  });
  const draftProfile = useMemo(() => {
    const current =
      settingsDraft.profiles.find((profile) => profile.profile_id === settingsDraft.active_profile_id) ??
      settingsDraft.profiles[0];
    return current;
  }, [settingsDraft]);
  const activeProfile = draftProfile;
  const fleetConfig = activeProfile?.fleet ?? undefined;
  const activeDroneId = activeProfile?.selected_drone_id ?? activeProfile?.fleet?.drones?.[0]?.drone_id;
  const activeRuntimeDrone =
    activeProfile?.fleet?.drones?.find((drone) => drone.drone_id === activeDroneId) ?? activeProfile?.fleet?.drones?.[0];
  const userAuthenticated = Boolean(sessionState.authenticated && sessionState.user);
  const companionBaseUrl = userAuthenticated ? selectCompanionApiBase(activeRuntimeDrone, defaultCompanionBaseUrl) : undefined;
  const telemetryBaseUrl = userAuthenticated ? selectTelemetryBase(activeRuntimeDrone, companionBaseUrl) : undefined;
  const telemetryRefreshIntervalMs = clampRefreshInterval(activeRuntimeDrone?.telemetry_refresh_interval_ms);
  const companionApiKey = useMemo(() => {
    return userAuthenticated ? activeRuntimeDrone?.transport.api_key?.trim() : undefined;
  }, [activeRuntimeDrone, userAuthenticated]);
  const controlToken = userAuthenticated ? activeRuntimeDrone?.transport.control_token?.trim() ?? '' : '';
  const requiredSettingsIssues = useMemo(
    () => (userAuthenticated ? validateRequiredSettings(settingsDraft) : []),
    [settingsDraft, userAuthenticated],
  );
  const companionPollingReady = Boolean(
    userAuthenticated &&
      companionBaseUrl &&
      companionApiKey &&
      requiredSettingsIssues.length === 0,
  );
  const setupProfile =
    settingsDraft.profiles.find((profile) => profile.profile_id === settingsDraft.active_profile_id) ??
    settingsDraft.profiles[0];
  const setupDrone =
    setupProfile?.fleet?.drones?.find((drone) => drone.drone_id === setupProfile.selected_drone_id) ??
    setupProfile?.fleet?.drones?.[0];
  const setupTelemetryEndpoint = setupDrone?.endpoints?.find((endpoint) => {
    const protocol = endpointProtocol(endpoint);
    return protocol === 'ws' || protocol === 'wss';
  }) ?? buildTelemetryEndpoint(setupDrone?.transport.endpoint || defaultCompanionBaseUrl);
  function toggleSidebarSection(section: keyof typeof sidebarSections) {
    setSidebarSections((current) => ({
      ...current,
      [section]: !current[section],
    }));
  }

  useEffect(() => {
    let cancelled = false;

    async function bootstrapSettings() {
      setSettingsLoading(true);
      try {
        const session = await loadSettingsSession();
        if (cancelled) {
          return;
        }

        if (!session?.authenticated || !session.user) {
          setSessionState(session ?? { authenticated: false, has_users: false });
          setSettingsDraft(emptyUserSettings);
          setSettingsMessage(
            session?.has_users
              ? 'Sign in to load stored settings.'
              : 'No users exist yet. Create the first user to continue.',
          );
          return;
        }

        let saved = session.settings ?? (await loadUserSettings());
        if (!saved) {
          throw new Error('No settings found for the authenticated user.');
        }

        if (!cancelled) {
          const preparedSettings = ensureRequiredSettingsShape(saved, defaultCompanionBaseUrl);
          const setupIssues = validateRequiredSettings(preparedSettings);
          setSessionState({ ...session, settings: preparedSettings });
          setSettingsDraft(cloneSettings(preparedSettings));
          setRequiredSetupOpen(setupIssues.length > 0);
          setSettingsMessage(
            setupIssues.length
              ? `Signed in as ${session.user.display_name ?? session.user.username}. Complete required setup.`
              : `Signed in as ${session.user.display_name ?? session.user.username}`,
          );
        }
      } catch {
        if (!cancelled) {
          setSessionState({ authenticated: false, has_users: false });
          setSettingsDraft(emptyUserSettings);
          setRequiredSetupOpen(false);
          setSettingsMessage('Settings service unavailable; sign in will be enabled when the local API is reachable.');
        }
      } finally {
        if (!cancelled) {
          setSettingsLoading(false);
        }
      }
    }

    void bootstrapSettings();

    return () => {
      cancelled = true;
    };
  }, [defaultCompanionBaseUrl]);

  useEffect(() => {
    if (!userAuthenticated) {
      setRequiredSetupOpen(false);
      return;
    }

    if (!settingsLoading && requiredSettingsIssues.length) {
      setRequiredSetupOpen(true);
    }
  }, [requiredSettingsIssues.length, settingsLoading, userAuthenticated]);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      if (!companionPollingReady) {
        setStatusSnapshot(mockSnapshot);
        setConnectionState('disconnected');
        setSourceLabel('mock data');
        setFlightLogBundles([]);
        setFlightLogMessage('flight log history unavailable');
        setRefreshing(false);
        return;
      }

      setRefreshing(true);
      try {
        const live = await loadCompanionSnapshot(companionApiKey || undefined, companionBaseUrl);
        if (cancelled) {
          return;
        }

        const merged = {
          ...mockSnapshot,
          ...live,
          health: live.health ?? mockSnapshot.health,
          vehicle: live.vehicle ?? mockSnapshot.vehicle,
          readiness: live.readiness ?? mockSnapshot.readiness,
          safety: live.safety ?? mockSnapshot.safety,
          mission: live.mission ?? mockSnapshot.mission,
          navigation: live.navigation ?? mockSnapshot.navigation,
          weather: live.weather ?? mockSnapshot.weather,
          edge_ai: live.edge_ai ?? mockSnapshot.edge_ai,
          telemetry: live.telemetry ?? mockSnapshot.telemetry,
          fleet: live.fleet ?? mockSnapshot.fleet,
          prescription: live.prescription ?? mockSnapshot.prescription,
          calibration: live.calibration ?? mockSnapshot.calibration,
          farm: live.farm ?? mockSnapshot.farm,
          flight_log_sync: live.flight_log_sync ?? mockSnapshot.flight_log_sync,
          swarm_coordination: live.swarm_coordination ?? mockSnapshot.swarm_coordination,
        } as CompanionSnapshot;

        const logBundles = await loadFlightLogSyncHistory(companionApiKey || undefined, companionBaseUrl);

        setStatusSnapshot(merged);
        setFlightLogBundles(logBundles);
        setFlightLogMessage(logBundles.length ? `Loaded ${logBundles.length} flight log bundle(s)` : 'No flight log bundles yet');
        setConnectionState(normalizeConnectionState(merged));
        setSourceLabel(companionApiKey ? 'companion api' : 'local mock + api fallback');
      } catch {
        if (!cancelled) {
          setStatusSnapshot(mockSnapshot);
          setConnectionState('unknown');
          setSourceLabel('mock data');
          setFlightLogBundles([]);
          setFlightLogMessage('flight log history unavailable');
        }
      } finally {
        if (!cancelled) {
          setRefreshing(false);
        }
      }
    }

    void refresh();

    if (!companionPollingReady) {
      return () => {
        cancelled = true;
      };
    }

    const timer = window.setInterval(() => {
      void refresh();
    }, telemetryRefreshIntervalMs);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [companionApiKey, companionBaseUrl, companionPollingReady, telemetryRefreshIntervalMs, userAuthenticated]);

  useEffect(() => {
    let cancelled = false;

    async function refreshTelemetry() {
      if (!companionPollingReady || !telemetryBaseUrl) {
        setTelemetrySnapshot(mockSnapshot.telemetry);
        return;
      }

      try {
        const liveTelemetry = await loadTelemetryCurrent(companionApiKey || undefined, telemetryBaseUrl);
        if (!cancelled) {
          setTelemetrySnapshot(liveTelemetry ?? mockSnapshot.telemetry);
        }
      } catch {
        if (!cancelled) {
          setTelemetrySnapshot(mockSnapshot.telemetry);
        }
      }
    }

    void refreshTelemetry();
    if (!companionPollingReady) {
      return () => {
        cancelled = true;
      };
    }

    const timer = window.setInterval(() => {
      void refreshTelemetry();
    }, Math.max(100, Math.min(telemetryRefreshIntervalMs, 500)));

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [companionApiKey, companionPollingReady, telemetryBaseUrl, telemetryRefreshIntervalMs, userAuthenticated]);

  useEffect(() => {
    setSettingsDraft((current) => ({
      ...current,
      ui_state: {
        ...(current.ui_state ?? {}),
        route_draft: routeDraft,
        flight_path_parameters: flightPathParameters,
        sidebar_sections: sidebarSections,
      },
    }));
  }, [flightPathParameters, routeDraft, sidebarSections]);

  useEffect(() => {
    const uiState = settingsDraft.ui_state;
    if (!uiState) {
      return;
    }

    if (uiState.route_draft) {
      setRouteDraft(uiState.route_draft);
    }
    if (uiState.flight_path_parameters) {
      setFlightPathParameters(uiState.flight_path_parameters);
    }
    if (uiState.sidebar_sections) {
      setSidebarSections((current) => ({
        ...current,
        ...uiState.sidebar_sections,
      }));
    }
  }, [settingsDraft.ui_state]);

  useEffect(() => {
    return () => {
      if (imageryOverlayUrl) {
        URL.revokeObjectURL(imageryOverlayUrl);
      }
    };
  }, [imageryOverlayUrl]);

  async function handleLogin(request: GroundStationLoginRequest): Promise<boolean> {
    setSettingsLoading(true);
    try {
      const session = await loginUser(request);
      if (request.create) {
        if (session?.created) {
          setSessionState({
            authenticated: false,
            has_users: true,
            created: true,
            created_username: session.created_username ?? request.username,
          });
          setSettingsDraft(emptyUserSettings);
          setRequiredSetupOpen(false);
          setSettingsMessage(`User ${session.created_username ?? request.username} created. Sign in with that username to continue.`);
          return true;
        }

        setSettingsMessage('User creation failed. Choose a different username and try again.');
        return false;
      }

      if (!session?.authenticated || !session.user) {
        setSettingsMessage('Login failed. Check the username and password.');
        return false;
      }

      let saved = session.settings ?? (await loadUserSettings());
      if (!saved) {
        throw new Error('No settings found for the authenticated user.');
      }

      const preparedSettings = ensureRequiredSettingsShape(saved, defaultCompanionBaseUrl);
      const setupIssues = validateRequiredSettings(preparedSettings);
      setSessionState({ ...session, settings: preparedSettings });
      setSettingsDraft(cloneSettings(preparedSettings));
      setRequiredSetupOpen(setupIssues.length > 0);
      setSettingsMessage(
        setupIssues.length
          ? `Signed in as ${session.user.display_name ?? session.user.username}. Complete required setup.`
          : `Signed in as ${session.user.display_name ?? session.user.username}`,
      );
      return true;
    } catch (error) {
      setSettingsMessage(`${request.create ? 'User creation' : 'Login'} failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      return false;
    } finally {
      setSettingsLoading(false);
    }
  }

  async function handleLogout() {
    setSettingsLoading(true);
    try {
      await logoutUser();
      setSessionState({ authenticated: false, has_users: sessionState.has_users });
      setSettingsDraft(emptyUserSettings);
      setRequiredSetupOpen(false);
      setSettingsMessage('Signed out. Log back in to restore saved profiles.');
    } catch (error) {
      setSettingsMessage(`Sign out failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    } finally {
      setSettingsLoading(false);
    }
  }

  async function handleSaveSettings(nextSettings?: GroundStationUserSettings) {
    setSettingsSaving(true);
    try {
      const settingsToSave = nextSettings ?? settingsDraft;
      const saved = await saveUserSettings(settingsToSave);
      if (!saved) {
        throw new Error('settings save failed');
      }

      setSettingsDraft(cloneSettings(saved));
      setSessionState((current) => ({
        ...current,
        authenticated: true,
        has_users: true,
        settings: saved,
      }));
      const setupIssues = validateRequiredSettings(saved);
      setRequiredSetupOpen(setupIssues.length > 0);
      setSettingsMessage(
        setupIssues.length
          ? 'Saved settings, but required connection setup is still incomplete.'
          : 'Saved user settings and applied the active profile.',
      );
    } catch (error) {
      setSettingsMessage(`Save failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    } finally {
      setSettingsSaving(false);
    }
  }

  async function handleDeleteDrone(droneId: string): Promise<GroundStationUserSettings | undefined> {
    setSettingsSaving(true);
    try {
      const deleted = await deleteDroneFromUserSettings(droneId);
      if (!deleted) {
        throw new Error('drone delete failed');
      }

      const session = await loadSettingsSession();
      const freshSettings = session?.authenticated ? (await loadUserSettings()) ?? session.settings : undefined;
      const saved = freshSettings ?? deleted;
      setSettingsDraft(cloneSettings(saved));
      setSessionState((current) => ({
        ...current,
        ...(session ?? {}),
        authenticated: session?.authenticated ?? true,
        has_users: session?.has_users ?? true,
        settings: saved,
      }));
      setRequiredSetupOpen(validateRequiredSettings(saved).length > 0);
      setUiRevision((current) => current + 1);
      setSettingsMessage('Deleted drone and refreshed session settings.');
      return saved;
    } finally {
      setSettingsSaving(false);
    }
  }

  function updateRequiredSetupProfile(
    updater: (profile: GroundStationUserSettings['profiles'][number]) => GroundStationUserSettings['profiles'][number],
  ) {
    setSettingsDraft((current) => {
      const prepared = ensureRequiredSettingsShape(current, defaultCompanionBaseUrl);
      const active =
        prepared.profiles.find((profile) => profile.profile_id === prepared.active_profile_id) ??
        prepared.profiles[0];
      return {
        ...prepared,
        active_profile_id: active.profile_id,
        profiles: prepared.profiles.map((profile) => (profile.profile_id === active.profile_id ? updater(profile) : profile)),
      };
    });
  }

  function updateRequiredSetupDrone(updater: (drone: DroneFleetEntry) => DroneFleetEntry) {
    setSettingsDraft((current) => {
      const prepared = ensureRequiredSettingsShape(current, defaultCompanionBaseUrl);
      const active =
        prepared.profiles.find((profile) => profile.profile_id === prepared.active_profile_id) ??
        prepared.profiles[0];
      const activeDrone =
        active.fleet?.drones?.find((drone) => drone.drone_id === active.selected_drone_id) ??
        active.fleet?.drones?.[0];

      if (!active || !activeDrone) {
        return prepared;
      }

      return {
        ...prepared,
        active_profile_id: active.profile_id,
        profiles: prepared.profiles.map((profile) => {
          if (profile.profile_id !== active.profile_id) {
            return profile;
          }

          let selectedDroneId = profile.selected_drone_id;
          const drones = profile.fleet?.drones?.map((drone) => {
            if (drone.drone_id !== activeDrone.drone_id) {
              return drone;
            }

            const nextDrone = updater(drone);
            if (profile.selected_drone_id === drone.drone_id) {
              selectedDroneId = nextDrone.drone_id;
            }
            return nextDrone;
          });

          return {
            ...profile,
            selected_drone_id:
              selectedDroneId && drones.some((drone) => drone.drone_id === selectedDroneId)
                ? selectedDroneId
                : drones[0]?.drone_id,
            fleet: {
              ...profile.fleet,
              default_transport: drones?.[0]?.transport.type ?? profile.fleet?.default_transport,
              drones: drones ?? [],
            },
          };
        }),
      };
    });
  }

  function updateRequiredSetupTelemetryEndpoint(endpoint: string) {
    updateRequiredSetupDrone((drone) => {
      const primaryEndpoint = drone.transport.endpoint || defaultCompanionEndpoint(defaultCompanionBaseUrl);
      const nonTelemetryEndpoints = (drone.endpoints ?? [])
        .filter((entry) => {
          const protocol = endpointProtocol(entry);
          return protocol !== 'ws' && protocol !== 'wss';
        })
        .filter((entry) => entry !== primaryEndpoint);
      return {
        ...drone,
        endpoints: [primaryEndpoint, endpoint, ...nonTelemetryEndpoints].filter((entry) => entry.trim()),
      };
    });
  }

  async function handleSaveRequiredSetup() {
    const preparedSettings = ensureRequiredSettingsShape(settingsDraft, defaultCompanionBaseUrl);
    const setupIssues = validateRequiredSettings(preparedSettings);
    setSettingsDraft(cloneSettings(preparedSettings));
    if (setupIssues.length) {
      setRequiredSetupOpen(true);
      setSettingsMessage('Complete the required connection fields before saving setup.');
      return;
    }

    setSettingsSaving(true);
    try {
      const saved = await saveUserSettings(preparedSettings);
      if (!saved) {
        throw new Error('settings save failed');
      }

      setSettingsDraft(cloneSettings(saved));
      setSessionState((current) => ({
        ...current,
        authenticated: true,
        has_users: true,
        settings: saved,
      }));
      setRequiredSetupOpen(false);
      setSettingsMessage('Saved required drone setup and applied the active profile.');
    } catch (error) {
      setSettingsMessage(`Setup save failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    } finally {
      setSettingsSaving(false);
    }
  }

  function selectDraftActiveDrone(droneId: string) {
    setSettingsDraft((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.profile_id === current.active_profile_id
          ? {
              ...profile,
              selected_drone_id: droneId,
            }
          : profile,
      ),
    }));
  }

  function updateDraftDroneTransport(
    profileId: string,
    droneId: string,
    updater: (transport: DroneTransport) => DroneTransport,
  ) {
    setSettingsDraft((current) => ({
      ...current,
      profiles: current.profiles.map((profile) =>
        profile.profile_id === profileId
          ? {
              ...profile,
              fleet: {
                ...profile.fleet,
                drones: profile.fleet?.drones?.map((drone) =>
                  drone.drone_id === droneId
                    ? {
                        ...drone,
                        transport: updater(drone.transport),
                      }
                    : drone,
                ),
              },
            }
          : profile,
      ),
    }));
  }

  function removeDroneFromLiveSnapshot(droneId: string, replacementDroneId?: string) {
    setStatusSnapshot((current) => {
      const fleet = current.fleet;
      if (!fleet?.drones?.length) {
        return current;
      }

      const survivingDrones = fleet.drones.filter((entry) => entry.drone_id !== droneId);
      const nextDrones = survivingDrones.length
        ? survivingDrones
        : replacementDroneId
          ? [
              {
                ...(fleet.drones.find((entry) => entry.drone_id === replacementDroneId) ?? fleet.drones[0]),
                drone_id: replacementDroneId,
              },
            ]
          : fleet.drones;

      return {
        ...current,
        fleet: {
          ...fleet,
          self_drone_id:
            fleet.self_drone_id === droneId
              ? replacementDroneId ?? nextDrones[0]?.drone_id
              : fleet.self_drone_id,
          active_drone_count: nextDrones.length,
          peer_count: nextDrones.length,
          drones: nextDrones.map((entry) =>
            entry.drone_id === replacementDroneId
              ? {
                  ...entry,
                  drone_id: replacementDroneId,
                }
              : entry,
          ),
        },
      };
    });
    setUiRevision((current) => current + 1);
  }

  function storeDraftControlToken(profileId: string | undefined, droneId: string | undefined, token: string) {
    if (!profileId || !droneId) {
      return;
    }

    updateDraftDroneTransport(profileId, droneId, (transport) => ({
      ...transport,
      control_token: token,
    }));
  }

  async function handleAcquireAuthority(profileId: string, droneId: string) {
    const profile = settingsDraft.profiles.find((entry) => entry.profile_id === profileId);
    const drone = profile?.fleet?.drones?.find((entry) => entry.drone_id === droneId);
    const apiBase = selectCompanionApiBase(drone, defaultCompanionBaseUrl);

    if (!drone || !apiBase) {
      setAuthorityStatus('api endpoint missing');
      return;
    }

    setAcquiringAuthorityDroneId(droneId);
    try {
      const authority = await acquireControlAuthority(
        apiBase,
        drone.transport.api_key?.trim() || undefined,
        `gs-route-${droneId}`,
        'ground-station',
      );
      if (authority?.token) {
        storeDraftControlToken(profileId, droneId, authority.token);
      }
      setAuthorityStatus(authority?.active ? 'authority acquired' : authority?.token ? 'authority request sent' : 'authority request failed');
    } finally {
      setAcquiringAuthorityDroneId(undefined);
    }
  }

  const telemetryStream = useTelemetryStream(
    companionApiKey || undefined,
    telemetryBaseUrl,
    statusSnapshot.telemetry ?? mockSnapshot.telemetry,
  );
  const telemetry = telemetryStream.latest ?? telemetrySnapshot ?? statusSnapshot.telemetry ?? mockSnapshot.telemetry;
  const liveVehicle = telemetryToVehicle(telemetryStream.latest ?? telemetrySnapshot);
  const vehicle = liveVehicle ?? telemetryToVehicle(statusSnapshot.telemetry ?? mockSnapshot.telemetry) ?? statusSnapshot.vehicle ?? mockSnapshot.vehicle;
  const readiness = statusSnapshot.readiness ?? mockSnapshot.readiness;
  const safety = statusSnapshot.safety ?? mockSnapshot.safety;
  const mission = statusSnapshot.mission ?? mockSnapshot.mission;
  const weather = statusSnapshot.weather ?? mockSnapshot.weather;
  const edgeAi = statusSnapshot.edge_ai ?? mockSnapshot.edge_ai;
  const fleetStatus = statusSnapshot.fleet ?? mockSnapshot.fleet;
  const prescriptionStatus = statusSnapshot.prescription ?? mockSnapshot.prescription;
  const calibrationStatus = statusSnapshot.calibration ?? mockSnapshot.calibration;
  const farmStatus = statusSnapshot.farm ?? mockSnapshot.farm;
  const swarmCoordination = statusSnapshot.swarm_coordination ?? mockSnapshot.swarm_coordination;
  const weatherBriefing = weather?.last_briefing;
  const weatherReady = weatherBriefing?.ready ?? false;
  const weatherTone = weatherBriefing
    ? weatherReady
      ? 'good'
      : 'warn'
    : 'neutral';
  const edgeAiResult = edgeAi?.last_result;
  const edgeAiTone = edgeAiResult
    ? edgeAiResult.obstacle_risk
      ? 'bad'
      : 'good'
    : edgeAi?.configured
      ? 'warn'
      : 'neutral';

  const readinessTone = readiness?.critical_count ? 'bad' : readiness?.warning_count ? 'warn' : 'good';
  const connectionTone =
    connectionState === 'connected'
      ? 'good'
      : connectionState === 'connecting'
        ? 'warn'
        : 'bad';
  const telemetryTone =
    telemetryStream.state === 'streaming'
      ? 'good'
      : telemetryStream.state === 'connecting'
        ? 'warn'
        : telemetryStream.state === 'reconnecting'
          ? 'warn'
          : 'bad';

  const checklist = readiness?.checks ?? [];
  const fallbackTelemetryPoints = useMemo(
    () => (telemetry ? [{ ...telemetry, id: 'seed-telemetry' }] : []),
    [telemetry],
  );
  const telemetryPoints = telemetryStream.samples.length ? telemetryStream.samples : fallbackTelemetryPoints;
  const boundaryDraft = routeDraft.boundary;
  const waypoints = routeDraft.waypoints;
  const prescriptionDutyCycle = prescriptionStatus?.recommended_duty_cycle;
  const prescriptionDutyCyclePercent = typeof prescriptionDutyCycle === 'number' ? prescriptionDutyCycle * 100 : undefined;

  const boundaryCenter = useMemo<LatLngPoint>(() => {
    const boundaryCenterPoint = computePolygonCenter(boundaryDraft);
    if (boundaryCenterPoint) {
      return boundaryCenterPoint;
    }

    if (vehicle?.location?.latitude !== undefined && vehicle.location.longitude !== undefined) {
      return {
        latitude: vehicle.location.latitude,
        longitude: vehicle.location.longitude,
        altitude: vehicle.location.altitude,
      };
    }

    return { latitude: 40.1123, longitude: -74.2129 };
  }, [boundaryDraft, vehicle?.location]);
  const [mapCenter, setMapCenter] = useState<[number, number]>(() => [boundaryCenter.latitude, boundaryCenter.longitude]);
  useEffect(() => {
    setMapCenter([boundaryCenter.latitude, boundaryCenter.longitude]);
  }, [boundaryCenter.latitude, boundaryCenter.longitude, routeDraft.name]);
  const surveyPreview = useMemo(() => buildSurveyPreview(boundaryDraft), [boundaryDraft]);
  const plannerCoverage = useMemo(
    () =>
      plannerObstacles.map((obstacle, index) => ({
        ...obstacle,
        radius: (obstacle.radius_m ?? 3) * 10,
        intensity: 0.18 + Math.min(index * 0.03, 0.2),
      })),
    [plannerObstacles],
  );
  const breadcrumb = telemetryStream.samples;
  const coverageOverlay = useMemo(
    () =>
      surveyPreview.flatMap((segment, segmentIndex) =>
        segment.map((point, pointIndex) => ({
          ...point,
          intensity: 0.08 + Math.min((segmentIndex + pointIndex) * 0.008, 0.14),
          radius: 18 + ((segmentIndex + pointIndex) % 4) * 4,
          label: pointIndex === 0 ? 'planned pass' : undefined,
        })),
      ),
    [surveyPreview],
  );
  const aerialOverlay = useMemo(() => {
    if (!imageryOverlayUrl) {
      return undefined;
    }

    return {
      url: imageryOverlayUrl,
      bounds: geotiffBounds ?? computeOverlayBounds(boundaryDraft, mapCenter),
      opacity: 0.76,
      label: imageryStatus,
    };
  }, [boundaryDraft, geotiffBounds, imageryOverlayUrl, imageryStatus, mapCenter]);

  const fleetMarkers = useMemo(
    () =>
      userAuthenticated && fleetConfig?.drones?.length
        ? fleetConfig.drones.map((drone, index) => {
        const liveDrone = fleetStatus?.drones?.find((entry) => entry.drone_id === drone.drone_id);
        const fleetEntry = (liveDrone ?? drone) as FleetMarker;
        const livePosition = fleetEntry.position;
        const position =
          livePosition?.latitude !== undefined && livePosition.longitude !== undefined
            ? {
                latitude: livePosition.latitude,
                longitude: livePosition.longitude,
                altitude: livePosition.altitude,
                heading: livePosition.heading,
              }
            : (fleetStatus?.self_drone_id === drone.drone_id || drone.drone_id === activeDroneId) &&
                vehicle?.location?.latitude !== undefined &&
                vehicle.location.longitude !== undefined
              ? {
                  latitude: vehicle.location.latitude,
                  longitude: vehicle.location.longitude,
                  altitude: vehicle.location.altitude,
                  heading: vehicle.heading,
                }
              : {
                  latitude: mapCenter[0] + 0.00035 * index,
                  longitude: mapCenter[1] - 0.00025 * index,
                  altitude: vehicle?.location?.altitude,
                  heading: vehicle?.heading,
                };

        return {
          ...fleetEntry,
          active: fleetEntry.drone_id === activeDroneId || fleetEntry.drone_id === fleetStatus?.self_drone_id,
          position,
        };
      })
        : [],
    [activeDroneId, fleetConfig?.drones, fleetStatus?.drones, fleetStatus?.self_drone_id, mapCenter, userAuthenticated, vehicle?.heading, vehicle?.location?.altitude, vehicle?.location?.latitude, vehicle?.location?.longitude],
  );
  function addBoundaryPoint(point: LatLngPoint) {
    if (missionMode !== 'boundary') {
      return;
    }

    setRouteDraft((current) => updateDraftBoundary(current, [...current.boundary, point]));
  }

  function addWaypoint(point: LatLngPoint) {
    if (missionMode !== 'waypoint') {
      return;
    }

    setRouteDraft((current) => appendDraftWaypoint(current, point));
  }

  function handleMapClick(point: LatLngPoint) {
    if (missionMode === 'boundary') {
      addBoundaryPoint(point);
    } else if (missionMode === 'waypoint') {
      addWaypoint(point);
    }
  }

  function openPlannerScreen() {
    setScreen('planner');
  }

  function removeLastBoundaryPoint() {
    setRouteDraft((current) => updateDraftBoundary(current, current.boundary.slice(0, -1)));
  }

  function clearBoundary() {
    setRouteDraft((current) => updateDraftBoundary(current, []));
  }

  function removeLastWaypoint() {
    setRouteDraft((current) => updateDraftWaypoints(current, current.waypoints.slice(0, -1)));
  }

  function clearWaypoints() {
    setRouteDraft((current) => updateDraftWaypoints(current, []));
  }

  function setBoundaryPoints(points: LatLngPoint[]) {
    setRouteDraft((current) => updateDraftBoundary(current, points));
  }

  function setWaypointPoints(points: MissionWaypoint[]) {
    setRouteDraft((current) => updateDraftWaypoints(current, points));
  }

  function generateFlightPath() {
    if (boundaryDraft.length < 3) {
      setRouteMessage('Add or import a boundary first');
      return;
    }

    const latitudes = boundaryDraft.map((point) => point.latitude);
    const longitudes = boundaryDraft.map((point) => point.longitude);
    const minLat = Math.min(...latitudes);
    const maxLat = Math.max(...latitudes);
    const minLng = Math.min(...longitudes);
    const maxLng = Math.max(...longitudes);
    const spacing = Math.max(2, flightPathParameters.swath_width_m / 111111);
    const nextWaypoints: MissionWaypoint[] = [];

    let row = 0;
    for (let latitude = minLat; latitude <= maxLat; latitude += spacing) {
      const points = row % 2 === 0
        ? [
            { latitude, longitude: minLng, altitude: flightPathParameters.altitude_m },
            { latitude, longitude: maxLng, altitude: flightPathParameters.altitude_m },
          ]
        : [
            { latitude, longitude: maxLng, altitude: flightPathParameters.altitude_m },
            { latitude, longitude: minLng, altitude: flightPathParameters.altitude_m },
          ];
      for (const point of points) {
        nextWaypoints.push({
          ...point,
          id: `wp-${nextWaypoints.length + 1}`,
          label: `WP-${String(nextWaypoints.length + 1).padStart(2, '0')}`,
        });
      }
      row += 1;
    }

    setRouteDraft((current) => updateDraftWaypoints(current, nextWaypoints));
    setRouteMessage(`Generated ${nextWaypoints.length} waypoints`);
  }

  function saveFlightPathParameters() {
    const blob = new Blob([
      serializeFlightPathParameters(routeDraft.name, flightPathParameters),
    ], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${routeDraft.name.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase() || 'mission-route'}.params.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setRouteMessage('Saved flight path parameters');
  }

  function saveRoute() {
    setRouteMessage(`Saved ${routeDraft.name} locally`);
  }

  function downloadRoute() {
    const blob = new Blob([serializeMissionRouteExport(routeDraft, fleetConfig)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${routeDraft.name.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase() || 'mission-route'}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setRouteMessage('Exported route JSON');
  }

  async function ensureControlToken(statusLabel: string): Promise<string> {
    let tokenToUse = controlToken;
    if (!tokenToUse) {
      const authority = await acquireControlAuthority(
        companionBaseUrl,
        companionApiKey || undefined,
        'gs-route',
        'ground-station',
      );
      tokenToUse = authority?.token ?? '';
      if (tokenToUse) {
        storeDraftControlToken(activeProfile?.profile_id, activeDroneId, tokenToUse);
      }
      setAuthorityStatus(authority?.active ? 'authority acquired' : authority?.token ? 'authority request sent' : 'authority request failed');
    }
    if (!tokenToUse) {
      setRouteMessage(`${statusLabel} requires control authority`);
    }
    return tokenToUse;
  }

  async function loadRouteFromCompanion() {
    try {
      const [missionState, boundaries] = await Promise.all([
        loadMissionState(companionBaseUrl, companionApiKey || undefined),
        loadFieldBoundaries(companionBaseUrl, companionApiKey || undefined),
      ]);
      const waypointEntries = missionState?.waypoints ?? [];
      const nextBoundary =
        boundaries.flatMap((entry) =>
          (entry.vertices ?? [])
            .map((vertex) => ({
              latitude: Number(vertex.latitude),
              longitude: Number(vertex.longitude),
              altitude: typeof vertex.altitude === 'number' ? vertex.altitude : undefined,
            }))
            .filter((point) => Number.isFinite(point.latitude) && Number.isFinite(point.longitude)),
        ) ?? [];
      const nextWaypoints = waypointEntries
        .map((entry, index) => {
          const location = (entry as { location?: LatLngPoint }).location;
          if (!location || location.latitude === undefined || location.longitude === undefined) {
            return undefined;
          }

          return {
            id: `companion-${index + 1}`,
            label: (entry as { label?: string }).label ?? `WP-${String(index + 1).padStart(2, '0')}`,
            latitude: location.latitude,
            longitude: location.longitude,
            altitude: location.altitude,
          };
        })
        .filter(Boolean) as MissionWaypoint[];

      setRouteDraft(
        createMissionRouteDraft(
          routeDraft.name,
          nextBoundary.length ? nextBoundary : routeDraft.boundary,
          nextWaypoints.length ? nextWaypoints : routeDraft.waypoints,
        ),
      );
      setRouteMessage('Loaded mission from companion');
    } catch (error) {
      setRouteMessage(`Failed to load companion route: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function uploadRouteToCompanion() {
    try {
      setRouteMessage('Uploading route to companion...');
      const tokenToUse = await ensureControlToken('Route upload');
      if (!tokenToUse) {
        return;
      }

      await clearCompanionMission(companionBaseUrl, companionApiKey || undefined, tokenToUse);
      if (routeDraft.boundary.length >= 3) {
        await uploadFieldBoundary(
          routeDraft.name,
          routeDraft.boundary,
          routeDraft.boundary[0]?.altitude,
          companionBaseUrl,
          companionApiKey || undefined,
          tokenToUse,
        );
      }
      for (const waypoint of routeDraft.waypoints) {
        await uploadMissionWaypoint(
          {
            latitude: waypoint.latitude,
            longitude: waypoint.longitude,
            altitude: waypoint.altitude ?? routeDraft.boundary[0]?.altitude ?? 0,
          },
          'relative',
          companionBaseUrl,
          companionApiKey || undefined,
          tokenToUse,
        );
      }
      await uploadMissionToPixhawk(companionBaseUrl, companionApiKey || undefined, tokenToUse);
      setRouteMessage(`Uploaded ${routeDraft.waypoints.length} waypoints to companion`);
    } catch (error) {
      setRouteMessage(`Upload failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function importPrescriptionFile(file: File) {
    try {
      setPrescriptionMessage(`importing ${file.name}...`);
      const tokenToUse = await ensureControlToken('Prescription import');
      if (!tokenToUse) {
        return;
      }

      const payloadText = await file.text();
      const sourceFormat = file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'geojson';
      const imported = await importPrescriptionMap(
        {
          name: file.name.replace(/\.[^.]+$/, '') || 'prescription-map',
          payload_text: payloadText,
          source_format: sourceFormat,
          activate: true,
        },
        companionApiKey || undefined,
        tokenToUse,
        companionBaseUrl,
      );

      if (!imported) {
        throw new Error('Prescription map upload failed');
      }

      setPrescriptionMessage(`active map: ${imported.name ?? imported.map_id ?? file.name}`);
      setStatusSnapshot((current) => ({
        ...current,
        prescription: {
          ...current.prescription,
          active_map: imported,
          configured: true,
          enabled: true,
        },
      }));
    } catch (error) {
      setPrescriptionMessage(`import failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function saveBaseStationWorkflow() {
    try {
      setCalibrationMessage('saving base station...');
      const tokenToUse = await ensureControlToken('Calibration workflow');
      if (!tokenToUse) {
        return;
      }

      const saved = await saveBaseStation(
        {
          station_id: baseStationDraft.station_id,
          name: baseStationDraft.name,
          latitude: baseStationDraft.latitude ? Number(baseStationDraft.latitude) : undefined,
          longitude: baseStationDraft.longitude ? Number(baseStationDraft.longitude) : undefined,
          altitude_m: baseStationDraft.altitude_m ? Number(baseStationDraft.altitude_m) : undefined,
          antenna_height_m: baseStationDraft.antenna_height_m ? Number(baseStationDraft.antenna_height_m) : undefined,
          correction_port: baseStationDraft.correction_port,
          correction_baudrate: baseStationDraft.correction_baudrate ? Number(baseStationDraft.correction_baudrate) : undefined,
          mount_type: baseStationDraft.mount_type,
          notes: baseStationDraft.notes,
          activate: true,
        },
        companionApiKey || undefined,
        tokenToUse,
        companionBaseUrl,
      );

      setCalibrationMessage(`base station ${saved?.station_id ?? 'saved'}`);
    } catch (error) {
      setCalibrationMessage(`save failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function processPpkWorkflow(job?: PpkJobStatus) {
    try {
      setCalibrationMessage(job?.job_id ? `re-running ${job.job_id}...` : 'processing PPK...');
      const tokenToUse = await ensureControlToken('PPK processing');
      if (!tokenToUse) {
        return;
      }

      const request = (job?.request as {
        job_id?: string;
        session?: string;
        base_station_id?: string;
        telemetry_window_seconds?: number;
        source_label?: string;
        notes?: string;
        telemetry_history?: Array<Record<string, unknown>>;
      } | undefined) ?? {};

      const processed = await processPpkJob(
        {
          job_id: undefined,
          session: request.session ?? routeDraft.name,
          base_station_id: request.base_station_id ?? calibrationStatus?.active_base_station?.station_id,
          telemetry_window_seconds: request.telemetry_window_seconds ?? 600,
          source_label: request.source_label ?? 'ground-station-telemetry',
          notes: request.notes,
          telemetry_history: request.telemetry_history ?? telemetryStream.samples.slice(-300),
        },
        companionApiKey || undefined,
        tokenToUse,
        companionBaseUrl,
      );

      const ppkSummary = processed?.summary as { estimated_horizontal_accuracy_m?: number } | undefined;
      setCalibrationMessage(
        `PPK ${(processed?.status as string | undefined) ?? 'processed'}${ppkSummary?.estimated_horizontal_accuracy_m ? `, est. ${Number(ppkSummary.estimated_horizontal_accuracy_m).toFixed(2)} m` : ''}`,
      );
    } catch (error) {
      setCalibrationMessage(`PPK failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function exportIsoxmlWorkflow() {
    try {
      setFarmMessage('exporting ISOXML...');
      const tokenToUse = await ensureControlToken('Farm export');
      if (!tokenToUse) {
        return;
      }

      const exported = await exportIsoxml(routeDraft.name, companionApiKey || undefined, tokenToUse, companionBaseUrl);
      const exportPayload = exported as { archive_path?: string } | undefined;
      setFarmMessage(`ISOXML ${exportPayload?.archive_path ? 'ready' : 'prepared'}`);
    } catch (error) {
      setFarmMessage(`ISOXML export failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function syncAgLeaderWorkflow() {
    try {
      setFarmMessage('syncing agLeader...');
      const tokenToUse = await ensureControlToken('agLeader sync');
      if (!tokenToUse) {
        return;
      }

      const result = await syncAgLeader(routeDraft.name, companionApiKey || undefined, tokenToUse, companionBaseUrl);
      const syncPayload = result as { status?: string } | undefined;
      setFarmMessage(`agLeader ${syncPayload?.status ?? 'queued'}`);
    } catch (error) {
      setFarmMessage(`agLeader sync failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function generateFarmReportWorkflow() {
    try {
      setFarmMessage('building report...');
      const tokenToUse = await ensureControlToken('Farm report');
      if (!tokenToUse) {
        return;
      }

      const result = await generateFarmReport(routeDraft.name, companionApiKey || undefined, tokenToUse, companionBaseUrl);
      const reportPayload = result as { report_path?: string } | undefined;
      setFarmMessage(`report ${reportPayload?.report_path ? 'saved' : 'ready'}`);
    } catch (error) {
      setFarmMessage(`report failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  async function replayFlightLogBundleWorkflow(bundle?: FlightLogSyncHistoryEntry) {
    if (!bundle?.archive_path) {
      setFlightLogMessage('Select a flight log bundle to replay');
      return;
    }

    const token = await ensureControlToken('Flight log replay');
    if (!token) {
      setFlightLogMessage('Flight log replay requires control authority');
      return;
    }

    const replayed = await replayFlightLogSyncBundle(
      String(bundle.archive_path),
      companionApiKey || undefined,
      token,
      companionBaseUrl,
      false,
    );
    setFlightLogMessage(replayed ? `Replayed ${replayed.name ?? replayed.archive_path}` : 'Flight log replay failed');
  }

  async function refreshFlightLogHistory() {
    try {
      const logBundles = await loadFlightLogSyncHistory(companionApiKey || undefined, companionBaseUrl);
      setFlightLogBundles(logBundles);
      setFlightLogMessage(logBundles.length ? `Loaded ${logBundles.length} flight log bundle(s)` : 'No flight log bundles yet');
    } catch {
      setFlightLogBundles([]);
      setFlightLogMessage('flight log history unavailable');
    }
  }

  function triggerPrescriptionPicker() {
    prescriptionInputRef.current?.click();
  }

  function clearAerialOverlay() {
    setImageryOverlayUrl((current) => {
      if (current) {
        URL.revokeObjectURL(current);
      }
      return undefined;
    });
    setImageryStatus('no overlay loaded');
    setGeotiffAssetId(undefined);
    setGeotiffBounds(undefined);
    setGeotiffStatus('no GeoTIFF loaded');
  }

  async function loadGeoTiffFromFile(file: File) {
    const defaultBounds = computeOverlayBounds(boundaryDraft, mapCenter);
    const [southWest, northEast] = defaultBounds;
    try {
      setGeotiffStatus(`uploading ${file.name}...`);
      const response = await uploadGeoTiffPreview(file, {
        north: northEast[0],
        south: southWest[0],
        east: northEast[1],
        west: southWest[1],
      }, {
        apiKey: companionApiKey || undefined,
        controlToken: controlToken || undefined,
        baseUrl: companionBaseUrl,
        filename: file.name,
        name: file.name.replace(/\.[^.]+$/, ''),
      });

      if (!response.asset_id || !response.preview_url) {
        throw new Error('GeoTIFF upload did not return a preview');
      }

      const previewBlob = await loadGeoTiffPreview(
        response.asset_id,
        companionApiKey || undefined,
        controlToken || undefined,
        companionBaseUrl,
      );
      const objectUrl = URL.createObjectURL(previewBlob);
      setImageryOverlayUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current);
        }
        return objectUrl;
      });
      setGeotiffAssetId(response.asset_id);
      setGeotiffBounds(
        response.bounds
          ? [[response.bounds.south, response.bounds.west], [response.bounds.north, response.bounds.east]]
          : defaultBounds,
      );
      setGeotiffStatus(`loaded GeoTIFF ${response.name ?? response.asset_id}`);
      setImageryStatus(`geotiff overlay ${response.asset_id}`);
      setRouteMessage(`GeoTIFF overlay ready: ${response.asset_id}`);
    } catch (error) {
      setGeotiffStatus(`GeoTIFF upload failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  }

  function triggerGeoTiffPicker() {
    geotiffInputRef.current?.click();
  }

  const activeSidebarDrone = activeRuntimeDrone ?? fleetConfig?.drones?.[0];
  const settingsPanel = (
    <UserSettingsPanel
      authenticated={sessionState.authenticated}
      hasUsers={sessionState.has_users}
      loading={settingsLoading}
      saving={settingsSaving}
      message={settingsMessage}
      sessionUser={sessionState.user}
      settingsDraft={settingsDraft}
      defaultCompanionBaseUrl={defaultCompanionBaseUrl}
      authorityStatus={authorityStatus}
      acquiringAuthorityDroneId={acquiringAuthorityDroneId}
      onLogin={handleLogin}
      onLogout={handleLogout}
      onSave={handleSaveSettings}
      onDraftChange={setSettingsDraft}
      onAcquireAuthority={handleAcquireAuthority}
      onDroneDeleted={async (droneId, replacementDroneId) => {
        removeDroneFromLiveSnapshot(droneId, replacementDroneId);
      }}
      onDeleteDrone={handleDeleteDrone}
      collapsed={userAuthenticated ? !sidebarSections.settings : false}
      onToggleCollapse={() => {
        if (userAuthenticated) {
          toggleSidebarSection('settings');
        }
      }}
    />
  );
  const requiredSetupModal = userAuthenticated && requiredSetupOpen ? (
    <div className="settings-modal-backdrop" role="presentation">
      <div className="settings-modal setup-modal" role="dialog" aria-modal="true" aria-labelledby="required-setup-title">
        <div className="settings-modal-head">
          <div>
            <span className="panel-label">Required setup</span>
            <h3 id="required-setup-title">Complete drone connection settings</h3>
          </div>
        </div>

        <div className="setup-issue-list">
          {requiredSettingsIssues.length ? (
            requiredSettingsIssues.map((issue) => (
              <div className="setup-issue" key={`${issue.field}-${issue.message}`}>
                <strong>{issue.field}</strong>
                <span>{issue.message}</span>
              </div>
            ))
          ) : (
            <div className="setup-issue">
              <strong>Ready</strong>
              <span>Required fields are complete. Save setup to continue.</span>
            </div>
          )}
        </div>

        <div className="config-grid setup-config-grid">
          <label className="field">
            <span>Profile label</span>
            <input
              value={setupProfile?.label ?? ''}
              onChange={(event) =>
                updateRequiredSetupProfile((profile) => ({
                  ...profile,
                  label: event.target.value,
                }))
              }
              placeholder="Primary profile"
            />
          </label>
          <label className="field">
            <span>Drone ID</span>
            <input
              value={setupDrone?.drone_id ?? ''}
              onChange={(event) =>
                updateRequiredSetupDrone((drone) => ({
                  ...drone,
                  drone_id: event.target.value,
                }))
              }
              placeholder="drone-01"
            />
          </label>
          <label className="field">
            <span>Callsign</span>
            <input
              value={setupDrone?.callsign ?? ''}
              onChange={(event) =>
                updateRequiredSetupDrone((drone) => ({
                  ...drone,
                  callsign: event.target.value,
                }))
              }
              placeholder="Alpha"
            />
          </label>
          <label className="field">
            <span>Transport</span>
            <select
              value={setupDrone?.transport.type ?? 'http'}
              onChange={(event) =>
                updateRequiredSetupDrone((drone) => ({
                  ...drone,
                  transport: {
                    ...drone.transport,
                    type: event.target.value as TransportKind,
                  },
                }))
              }
            >
              {setupTransportOptions.map((transport) => (
                <option key={transport} value={transport}>
                  {transport}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Companion endpoint</span>
            <input
              value={setupDrone?.transport.endpoint ?? ''}
              onChange={(event) =>
                updateRequiredSetupDrone((drone) => {
                  const endpoint = event.target.value;
                  const currentTelemetryEndpoint =
                    drone.endpoints?.find((entry) => {
                      const protocol = endpointProtocol(entry);
                      return protocol === 'ws' || protocol === 'wss';
                    }) ?? buildTelemetryEndpoint(endpoint);
                  return {
                    ...drone,
                    transport: {
                      ...drone.transport,
                      endpoint,
                    },
                    endpoints: [endpoint, currentTelemetryEndpoint].filter((entry) => entry.trim()),
                  };
                })
              }
              placeholder="http://192.168.1.140:8000"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="field">
            <span>Telemetry endpoint</span>
            <input
              value={setupTelemetryEndpoint}
              onChange={(event) => updateRequiredSetupTelemetryEndpoint(event.target.value)}
              placeholder="ws://192.168.1.140:8000/ws/telemetry"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="field">
            <span>Api Key</span>
            <input
              value={setupDrone?.transport.api_key ?? ''}
              onChange={(event) =>
                updateRequiredSetupDrone((drone) => ({
                  ...drone,
                  transport: {
                    ...drone.transport,
                    api_key: event.target.value,
                  },
                }))
              }
              placeholder="companion API key"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
        </div>

        <div className="settings-actions">
          <button type="button" className="secondary-button" onClick={handleSaveRequiredSetup} disabled={settingsSaving || settingsLoading}>
            {settingsSaving ? 'Saving...' : 'Save setup'}
          </button>
          <button type="button" className="ghost-button" onClick={handleLogout} disabled={settingsSaving || settingsLoading}>
            Sign out
          </button>
        </div>
      </div>
    </div>
  ) : null;

  if (!userAuthenticated) {
    return (
      <div className="app-shell login-shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">GS</div>
            <div>
              <span className="eyebrow">Pixhawk companion</span>
              <h1>Ground Station</h1>
            </div>
          </div>

          {settingsPanel}
        </aside>

        <main className="content login-content">
          <header className="hero login-hero">
            <div>
              <span className="eyebrow">Field operations cockpit</span>
              <h2>Mission control for spraying, mapping, and fleet awareness.</h2>
              <p>Sign in to load the user profile that owns drone connections, API keys, authority tokens, and operational panels.</p>
            </div>
          </header>
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside key={`sidebar-${uiRevision}`} className="sidebar">
        <div className="brand">
          <div className="brand-mark">GS</div>
          <div>
            <span className="eyebrow">Pixhawk companion</span>
            <h1>Ground Station</h1>
          </div>
        </div>

        <section className="sidebar-panel sidebar-accordion">
          <div className="sidebar-panel-head">
            <div>
              <span className="panel-label">Drones</span>
              <h3>Current swarm member</h3>
            </div>
            <button type="button" className="ghost-button" onClick={() => toggleSidebarSection('drones')}>
              {sidebarSections.drones ? 'Collapse' : 'Expand'}
            </button>
          </div>
          {sidebarSections.drones ? (
            <div className="stack">
              <label className="field">
                <span>Selected drone</span>
                <select
                  value={activeDroneId ?? ''}
                  onChange={(event) => selectDraftActiveDrone(event.target.value)}
                >
                  {fleetConfig.drones.map((drone) => (
                    <option key={drone.drone_id} value={drone.drone_id}>
                      {drone.callsign ?? drone.drone_id}
                    </option>
                  ))}
                </select>
              </label>
              <StatusChip label="Drone" value={activeSidebarDrone?.callsign ?? activeSidebarDrone?.drone_id ?? 'none'} tone="neutral" />
              <StatusChip label="Transport" value={activeSidebarDrone?.transport.type ?? 'unknown'} tone="neutral" />
            </div>
          ) : null}
        </section>

        <section className="sidebar-panel sidebar-accordion">
          <div className="sidebar-panel-head">
            <div>
              <span className="panel-label">Mission</span>
              <h3>Route readiness</h3>
            </div>
            <button type="button" className="ghost-button" onClick={() => toggleSidebarSection('mission')}>
              {sidebarSections.mission ? 'Collapse' : 'Expand'}
            </button>
          </div>
          {sidebarSections.mission ? (
            <div className="mini-list">
              <div>
                <strong>{mission?.waypoint_count ?? waypoints.length}</strong>
                <span>Waypoints</span>
              </div>
              <div>
                <strong>{mission?.completed ?? 0}</strong>
                <span>Completed</span>
              </div>
              <div>
                <strong>{formatMeters(mission?.total_distance_m)}</strong>
                <span>Route length</span>
              </div>
            </div>
          ) : null}
        </section>

        <section className="sidebar-panel sidebar-accordion">
          <div className="sidebar-panel-head">
            <div>
              <span className="panel-label">Connection</span>
              <h3>Link state</h3>
            </div>
            <button type="button" className="ghost-button" onClick={() => toggleSidebarSection('connection')}>
              {sidebarSections.connection ? 'Collapse' : 'Expand'}
            </button>
          </div>
          {sidebarSections.connection ? (
            <div className="stack">
              <StatusChip label="State" value={connectionState} tone={connectionTone} />
              <StatusChip label="Telemetry" value={telemetryStream.state} tone={telemetryTone} />
              <StatusChip label="Source" value={sourceLabel} tone="neutral" />
              <StatusChip label="API" value={getBaseUrl(companionBaseUrl)} tone="neutral" />
              <StatusChip label="Route" value={routeMessage} tone="neutral" />
              <StatusChip label="Authority" value={authorityStatus} tone="neutral" />
            </div>
          ) : null}
        </section>

        <section className="sidebar-panel sidebar-accordion">
          <div className="sidebar-panel-head">
            <div>
              <span className="panel-label">Shell parity</span>
              <h3>Runtime shell</h3>
            </div>
            <button type="button" className="ghost-button" onClick={() => toggleSidebarSection('shell')}>
              {sidebarSections.shell ? 'Collapse' : 'Expand'}
            </button>
          </div>
          {sidebarSections.shell ? <ShellStatusPanel shellContext={shellContext} runtimeConfig={runtimeConfig} /> : null}
        </section>

        {settingsPanel}
      </aside>

      <main key={`content-${uiRevision}`} className="content">
        <header className="hero">
          <div>
            <span className="eyebrow">Field operations cockpit</span>
            <h2>Mission control for spraying, mapping, and fleet awareness.</h2>
            <p>
              A cockpit-style shell for the Pixhawk companion with a real map, live telemetry stream, and draft mission tools.
            </p>
          </div>
        </header>

        <section className="dashboard-grid">
          <div className="map-panel">
            <div className="panel-head">
              <div>
                <span className="panel-label">Map stage</span>
                <h3>Live field view</h3>
              </div>
              <div className="map-head-actions">
                <StatusChip
                  label="Mode"
                  value={vehicle?.mode ?? 'unknown'}
                  tone={vehicle?.armed ? 'warn' : 'neutral'}
                />
                <StatusChip label="GeoTIFF" value={geotiffStatus} tone={imageryOverlayUrl ? 'good' : 'neutral'} />
                <button type="button" className="secondary-button" onClick={openPlannerScreen}>
                  Open mission editor
                </button>
                <button type="button" className="secondary-button" onClick={triggerGeoTiffPicker}>
                  Load GeoTIFF
                </button>
                <button type="button" className="ghost-button" onClick={clearAerialOverlay} disabled={!imageryOverlayUrl}>
                  Clear overlay
                </button>
                <input
                  ref={geotiffInputRef}
                  className="visually-hidden"
                  type="file"
                  accept=".tif,.tiff,image/tiff,image/x-tiff"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = '';
                    if (file) {
                      void loadGeoTiffFromFile(file);
                    }
                  }}
                />
              </div>
            </div>

            <FieldMap
              center={mapCenter}
              boundary={boundaryDraft}
              waypoints={waypoints}
              breadcrumb={EMPTY_BREADCRUMB}
              surveyPreview={surveyPreview}
              coverage={coverageOverlay}
              vehicle={
                vehicle?.location?.latitude !== undefined && vehicle.location.longitude !== undefined
                ? {
                      latitude: vehicle.location.latitude,
                      longitude: vehicle.location.longitude,
                      altitude: vehicle.location.altitude,
                      heading: vehicle.heading,
                }
                  : undefined
              }
              aerialOverlay={aerialOverlay}
              fleet={fleetMarkers}
              mode={missionMode}
              followViewport={false}
              onMapClick={handleMapClick}
              onBoundaryChange={setBoundaryPoints}
              onWaypointsChange={setWaypointPoints}
              activeDroneId={activeDroneId}
              onSelectDrone={selectDraftActiveDrone}
            />

            <div className="map-footer">
              <StatusChip label="Boundary" value={`${boundaryDraft.length} pts`} tone="neutral" />
              <StatusChip label="Survey" value={`${surveyPreview.length} lines`} tone="neutral" />
              <StatusChip label="Breadcrumb" value={`${breadcrumb.length} pts`} tone="neutral" />
              <StatusChip label="GeoTIFF" value={geotiffAssetId ?? 'none'} tone={geotiffAssetId ? 'good' : 'neutral'} />
            </div>
          </div>

          <div className="summary-column">
            <section className="summary-card">
              <div className="panel-head">
                <div>
                  <span className="panel-label">Telemetry</span>
                  <h3>Current flight state</h3>
                </div>
                <StatusChip label="Link" value={telemetryStream.state} tone={telemetryTone} />
              </div>

              <div className="metric-grid">
                <MetricCard title="Speed" value={telemetry?.ground_speed !== undefined ? `${telemetry.ground_speed.toFixed(1)} m/s` : '--'} detail="Ground speed" accent="teal" />
                <MetricCard title="Battery" value={formatPercent(vehicle?.battery?.level_percent)} detail={vehicle?.battery?.voltage ? `${vehicle.battery.voltage.toFixed(1)} V` : undefined} accent="amber" />
                <MetricCard title="GPS" value={vehicle?.gps?.satellite_count ? `${vehicle.gps.satellite_count}` : '--'} detail="Satellites" accent="blue" />
                <MetricCard title="Altitude" value={formatMeters(vehicle?.location?.altitude)} detail="Relative" accent="red" />
              </div>
            </section>

            <TelemetryCharts
              points={telemetryPoints}
              latestLabel={telemetryStream.lastMessageAt ? `last update ${new Date(telemetryStream.lastMessageAt).toLocaleTimeString()}` : telemetryStream.state}
            />
          </div>
        </section>

        {screen === 'cockpit' ? (
          <section className="bottom-grid">
            <FleetPanel drones={fleetMarkers} activeDroneId={activeDroneId} onSelectDrone={selectDraftActiveDrone} />
            <section className="summary-card">
              <div className="panel-head">
                <div>
                  <span className="panel-label">Planner</span>
                  <h3>Flight path tools</h3>
                </div>
                <button type="button" className="secondary-button" onClick={() => setScreen('planner')}>
                  Open planner
                </button>
              </div>
              <p className="hint">
                Boundary and route editing now lives on the planner screen so the cockpit stays focused on telemetry and map tracking.
              </p>
            </section>
          </section>
        ) : (
          <section className="bottom-grid">
            <FlightPathPlannerScreen
              fleet={fleetConfig}
              selectedDroneId={activeDroneId}
              onSelectedDroneChange={selectDraftActiveDrone}
              boundary={boundaryDraft}
              waypoints={waypoints}
              obstacles={plannerObstacles}
              parameters={flightPathParameters}
              routeName={routeDraft.name}
              mode={plannerMode}
              onModeChange={setPlannerMode}
              onBoundaryChange={setBoundaryPoints}
              onWaypointsChange={setWaypointPoints}
              onObstaclesChange={setPlannerObstacles}
              onRouteNameChange={(name) => setRouteDraft((current) => ({ ...current, name, updated_at: new Date().toISOString() }))}
              onParametersChange={setFlightPathParameters}
              onGeneratePath={generateFlightPath}
              onSaveRoute={saveRoute}
              onSaveParameters={saveFlightPathParameters}
              onLoadBoundary={loadRouteFromCompanion}
              routeStatus={routeMessage}
              missionHint="Draw or import a boundary, add obstacles, then auto-optimize the route."
              vehicle={
                telemetry?.location?.latitude !== undefined && telemetry.location.longitude !== undefined
                  ? {
                      latitude: telemetry.location.latitude,
                      longitude: telemetry.location.longitude,
                      altitude: telemetry.location.altitude,
                      heading: telemetry.heading,
                    }
                  : undefined
              }
              breadcrumb={telemetryStream.samples as any}
              surveyPreview={surveyPreview}
              coverage={plannerCoverage}
              activeDroneId={activeDroneId}
              onSelectDrone={selectDraftActiveDrone}
              onSaveMission={saveRoute}
              onUploadMission={uploadRouteToCompanion}
            />
          </section>
        )}

        <section className="bottom-grid">
          <section className="summary-card">
            <div className="panel-head">
              <div>
                <span className="panel-label">Safety</span>
                <h3>Geofences and compliance</h3>
              </div>
              <StatusChip label="Geofences" value={`${safety?.geofences?.length ?? 0}`} tone="neutral" />
            </div>

            <div className="stack">
              <div className="pill-row">
                <span className="pill">Remote ID {safety?.remote_id ? 'configured' : 'missing'}</span>
                <span className="pill">Waivers {safety?.waivers ? 'available' : 'none'}</span>
                <span className="pill">Landing zones ready</span>
              </div>
              <div className="list-card">
                {(safety?.geofences ?? []).map((zone) => (
                  <div className="list-row" key={zone.name}>
                    <div>
                      <strong>{zone.name}</strong>
                      <span>{zone.type ?? 'zone'}</span>
                    </div>
                    <span>{zone.enabled ? 'enabled' : 'disabled'}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="summary-card">
            <div className="panel-head">
              <div>
                <span className="panel-label">Navigation</span>
                <h3>Obstacle and terrain config</h3>
              </div>
              <StatusChip
                label="Terrain"
                value={statusSnapshot.navigation?.terrain_following?.enabled ? 'on' : 'off'}
                tone={statusSnapshot.navigation?.terrain_following?.enabled ? 'good' : 'neutral'}
              />
            </div>

            <div className="config-grid">
              <div>
                <span className="metric-title">Obstacle avoidance</span>
                <strong>{String(statusSnapshot.navigation?.obstacle_avoidance?.enabled ?? false)}</strong>
              </div>
              <div>
                <span className="metric-title">Terrain source</span>
                <strong>{String(statusSnapshot.navigation?.terrain_following?.source ?? '--')}</strong>
              </div>
              <div>
                <span className="metric-title">Sensor count</span>
                <strong>{statusSnapshot.navigation?.distance_sensors?.length ?? 0}</strong>
              </div>
              <div>
                <span className="metric-title">Target AGL</span>
                <strong>{String(statusSnapshot.navigation?.terrain_following?.target_agl_meters ?? '--')}</strong>
              </div>
            </div>
          </section>

          <section className="summary-card">
            <div className="panel-head">
              <div>
                <span className="panel-label">Weather and vision</span>
                <h3>Preflight briefing and obstacle scan</h3>
              </div>
              <div className="stack" style={{ alignItems: 'flex-end' }}>
                <StatusChip
                  label="Weather"
                  value={weatherBriefing ? (weatherReady ? 'go' : 'hold') : 'unavailable'}
                  tone={weatherTone}
                />
                <StatusChip
                  label="Vision"
                  value={edgeAiResult ? (edgeAiResult.obstacle_risk ? 'obstacle' : 'clear') : 'idle'}
                  tone={edgeAiTone}
                />
              </div>
            </div>

            <div className="stack">
              <div className="config-grid">
                <div>
                  <span className="metric-title">METAR station</span>
                  <strong>{weather?.station_id ?? weatherBriefing?.station_id ?? '--'}</strong>
                </div>
                <div>
                  <span className="metric-title">Flight category</span>
                  <strong>{weatherBriefing?.metar?.flight_category ?? '--'}</strong>
                </div>
                <div>
                  <span className="metric-title">Visibility</span>
                  <strong>{formatOptionalNumber(weatherBriefing?.metar?.visibility_sm, 2, ' SM')}</strong>
                </div>
                <div>
                  <span className="metric-title">Ceiling</span>
                  <strong>{weatherBriefing?.metar?.ceiling_ft ? `${weatherBriefing.metar.ceiling_ft} ft` : '--'}</strong>
                </div>
                <div>
                  <span className="metric-title">Wind</span>
                  <strong>
                    {weatherBriefing?.metar?.wind?.speed_kt !== undefined
                      ? `${weatherBriefing.metar.wind.speed_kt} kt`
                      : '--'}
                  </strong>
                </div>
                <div>
                  <span className="metric-title">Last update</span>
                  <strong>{formatAge(weatherBriefing?.updated_at)}</strong>
                </div>
              </div>

              <div className="list-card">
                <div className="list-row">
                  <div>
                    <strong>Weather blockers</strong>
                    <span>{weatherBriefing?.blocking_reasons?.length ? weatherBriefing.blocking_reasons.join(' ') : 'None reported'}</span>
                  </div>
                  <span>{weatherBriefing?.blocking_reasons?.length ? weatherBriefing.blocking_reasons.length : 0}</span>
                </div>
                <div className="list-row">
                  <div>
                    <strong>Vision backend</strong>
                    <span>{edgeAi?.backend ?? '--'}</span>
                  </div>
                  <span>{edgeAi?.configured ? 'configured' : 'not set'}</span>
                </div>
                <div className="list-row">
                  <div>
                    <strong>Obstacle detections</strong>
                    <span>
                      {edgeAiResult?.obstacle_detections?.length
                        ? edgeAiResult.obstacle_detections.map((detection) => detection.label).filter(Boolean).join(', ')
                        : edgeAiResult
                          ? 'No obstacle detections'
                          : 'No scan yet'}
                    </span>
                  </div>
                  <span>
                    {edgeAiResult
                      ? `${edgeAiResult.obstacle_detections?.length ?? 0} / ${edgeAiResult.detections?.length ?? 0}`
                      : '--'}
                  </span>
                </div>
              </div>
            </div>
          </section>

          <section className="summary-card">
            <div className="panel-head">
              <div>
                <span className="panel-label">Variable rate</span>
                <h3>Prescription map and flow control</h3>
              </div>
              <div className="stack" style={{ alignItems: 'flex-end' }}>
                <StatusChip
                  label="Control"
                  value={prescriptionStatus?.enabled === false ? 'disabled' : prescriptionStatus?.configured ? 'live' : 'idle'}
                  tone={prescriptionStatus?.configured ? 'good' : prescriptionStatus?.enabled === false ? 'neutral' : 'warn'}
                />
                <button type="button" className="secondary-button" onClick={triggerPrescriptionPicker}>
                  Import map
                </button>
                <input
                  ref={prescriptionInputRef}
                  className="visually-hidden"
                  type="file"
                  accept=".csv,.geojson,.json,application/json,text/csv,application/geo+json"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = '';
                    if (file) {
                      void importPrescriptionFile(file);
                    }
                  }}
                />
              </div>
            </div>

            <div className="stack">
              <p className="hint">{prescriptionMessage}</p>
              <div className="config-grid">
                <div>
                  <span className="metric-title">Active map</span>
                  <strong>{prescriptionStatus?.active_map?.name ?? prescriptionStatus?.active_map?.map_id ?? '--'}</strong>
                </div>
                <div>
                  <span className="metric-title">Current zone</span>
                  <strong>{prescriptionStatus?.current_zone?.label ?? '--'}</strong>
                </div>
                <div>
                  <span className="metric-title">Target rate</span>
                  <strong>
                    {prescriptionStatus?.target_rate_liters_per_hectare !== undefined && prescriptionStatus.target_rate_liters_per_hectare !== null
                      ? `${prescriptionStatus.target_rate_liters_per_hectare.toFixed(1)} L/ha`
                      : '--'}
                  </strong>
                </div>
                <div>
                  <span className="metric-title">Target flow</span>
                  <strong>
                    {prescriptionStatus?.current_flow_rate_liters_per_minute !== undefined && prescriptionStatus.current_flow_rate_liters_per_minute !== null
                      ? `${prescriptionStatus.current_flow_rate_liters_per_minute.toFixed(1)} L/min`
                      : '--'}
                  </strong>
                </div>
                <div>
                  <span className="metric-title">Ground speed</span>
                  <strong>{formatOptionalNumber(prescriptionStatus?.ground_speed_mps, 1, ' m/s')}</strong>
                </div>
                <div>
                  <span className="metric-title">Duty cycle</span>
                  <strong>{formatPercent(prescriptionDutyCyclePercent)}</strong>
                </div>
              </div>

              <div className="list-card">
                <div className="list-row">
                  <div>
                    <strong>Map status</strong>
                    <span>{prescriptionStatus?.configured ? 'Prescription active' : 'No active prescription'}</span>
                  </div>
                  <span>{prescriptionStatus?.swath_width_m ? `${prescriptionStatus.swath_width_m.toFixed(1)} m` : '--'}</span>
                </div>
                <div className="list-row">
                  <div>
                    <strong>Matched zone</strong>
                    <span>
                      {prescriptionStatus?.current_zone?.label
                        ? `${prescriptionStatus.current_zone.label} (${prescriptionStatus.current_zone.priority ?? 0})`
                        : 'No zone match'}
                    </span>
                  </div>
                  <span>{prescriptionStatus?.current_zone?.target_rate_lpha !== undefined ? `${prescriptionStatus.current_zone.target_rate_lpha} L/ha` : '--'}</span>
                </div>
                <div className="list-row">
                  <div>
                    <strong>GPS sync</strong>
                    <span>{prescriptionStatus?.speed_sync_enabled ? 'enabled' : 'disabled'}</span>
                  </div>
                  <span>{formatOptionalNumber(prescriptionStatus?.effective_ground_speed_mps, 1, ' m/s')}</span>
                </div>
              </div>
            </div>
          </section>

          <CalibrationHistoryPanel
            calibrationStatus={calibrationStatus}
            message={calibrationMessage}
            onSaveBaseStation={saveBaseStationWorkflow}
            onRunPpk={processPpkWorkflow}
          />

        <FarmTimelinePanel
          farmStatus={farmStatus}
          message={farmMessage}
          onExportIsoxml={exportIsoxmlWorkflow}
          onSyncAgLeader={syncAgLeaderWorkflow}
          onGenerateReport={generateFarmReportWorkflow}
        />

        <FlightLogTimelinePanel
          flightLogSync={statusSnapshot.flight_log_sync}
          bundles={flightLogBundles}
          message={flightLogMessage}
          onReplay={replayFlightLogBundleWorkflow}
          onRefresh={refreshFlightLogHistory}
        />

        <SwarmConfigEditor
          companionBaseUrl={companionBaseUrl}
          apiKey={companionApiKey || undefined}
          ensureControlToken={ensureControlToken}
          coordination={swarmCoordination}
        />
        </section>
      </main>
      {requiredSetupModal}
    </div>
  );
}

export default App;
