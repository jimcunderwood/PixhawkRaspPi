import { useEffect, useMemo, useRef, useState } from 'react';
import { FieldMap } from './components/FieldMap';
import { CalibrationHistoryPanel } from './components/CalibrationHistoryPanel';
import { FleetPanel } from './components/FleetPanel';
import { FarmTimelinePanel } from './components/FarmTimelinePanel';
import { MissionEditor } from './components/MissionEditor';
import { SwarmConfigEditor } from './components/SwarmConfigEditor';
import { TelemetryCharts } from './components/TelemetryCharts';
import { mockSnapshot } from './data/mockState';
import { useTelemetryStream } from './hooks/useTelemetryStream';
import {
  exportIsoxml,
  generateFarmReport,
  importPrescriptionMap,
  getBaseUrl,
  loadCompanionSnapshot,
  loadGeoTiffPreview,
  processPpkJob,
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
import type { DroneFleetEntry } from '../../../shared/types/fleet';
import {
  appendDraftWaypoint,
  createMissionRouteDraft,
  loadStoredDraft,
  saveStoredDraft,
  serializeMissionRouteExport,
  updateDraftBoundary,
  updateDraftWaypoints,
} from '../../../shared/mission/routes';
import { buildSurveyPreview, computePolygonCenter } from '../../../shared/mission/planning';
import type {
  CompanionSnapshot,
  ConnectionState,
  LatLngPoint,
  MissionEditorMode,
  MissionWaypoint,
} from './types';
import type { PpkJobStatus } from '../../../shared/types/base';

type AppProps = {
  companionBaseUrl?: string;
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

function formatOptionalNumber(value?: number, digits = 1, suffix = '') {
  if (value === undefined || Number.isNaN(value)) {
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

function App({ companionBaseUrl }: AppProps) {
  const routeStorageKey = 'ground-station.route-draft.v1';
  const geotiffInputRef = useRef<HTMLInputElement | null>(null);
  const prescriptionInputRef = useRef<HTMLInputElement | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [statusSnapshot, setStatusSnapshot] = useState<CompanionSnapshot>(mockSnapshot);
  const [connectionState, setConnectionState] = useState<ConnectionState>('unknown');
  const [sourceLabel, setSourceLabel] = useState('mock data');
  const [refreshing, setRefreshing] = useState(true);
  const [missionMode, setMissionMode] = useState<MissionEditorMode>('view');
  const [routeDraft, setRouteDraft] = useState(() =>
    loadStoredDraft(routeStorageKey) ?? createMissionRouteDraft('Draft route'),
  );
  const [routeMessage, setRouteMessage] = useState('Ready');
  const [imageryOverlayUrl, setImageryOverlayUrl] = useState<string | undefined>();
  const [imageryStatus, setImageryStatus] = useState('no overlay loaded');
  const [geotiffAssetId, setGeotiffAssetId] = useState<string | undefined>();
  const [geotiffStatus, setGeotiffStatus] = useState('no GeoTIFF loaded');
  const [geotiffBounds, setGeotiffBounds] = useState<[[number, number], [number, number]] | undefined>();
  const [activeDroneId, setActiveDroneId] = useState(mockFleetConfig.drones[0]?.drone_id);
  const [fleetConfig] = useState(mockFleetConfig);
  const [controlToken, setControlToken] = useState('');
  const [authorityStatus, setAuthorityStatus] = useState('not requested');
  const [prescriptionMessage, setPrescriptionMessage] = useState('no prescription loaded');
  const [calibrationMessage, setCalibrationMessage] = useState('no base station configured');
  const [farmMessage, setFarmMessage] = useState('farm integrations idle');
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

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      setRefreshing(true);
      try {
        const live = await loadCompanionSnapshot(
          apiKey || undefined,
          companionBaseUrl,
        );
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
          swarm_coordination: live.swarm_coordination ?? mockSnapshot.swarm_coordination,
        } as CompanionSnapshot;

        setStatusSnapshot(merged);
        setConnectionState(normalizeConnectionState(merged));
        setSourceLabel(apiKey ? 'companion api' : 'local mock + api fallback');
      } catch {
        if (!cancelled) {
          setStatusSnapshot(mockSnapshot);
          setConnectionState('unknown');
          setSourceLabel('mock data');
        }
      } finally {
        if (!cancelled) {
          setRefreshing(false);
        }
      }
    }

    void refresh();

    const timer = window.setInterval(() => {
      void refresh();
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [apiKey, companionBaseUrl]);

  useEffect(() => {
    saveStoredDraft(routeStorageKey, routeDraft);
  }, [routeDraft, routeStorageKey]);

  useEffect(() => {
    return () => {
      if (imageryOverlayUrl) {
        URL.revokeObjectURL(imageryOverlayUrl);
      }
    };
  }, [imageryOverlayUrl]);

  const telemetryStream = useTelemetryStream(
    apiKey || undefined,
    companionBaseUrl,
    statusSnapshot.telemetry ?? mockSnapshot.telemetry,
  );
  const telemetry = telemetryStream.latest ?? statusSnapshot.telemetry ?? mockSnapshot.telemetry;
  const vehicle = statusSnapshot.vehicle ?? mockSnapshot.vehicle;
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

  const boundaryCenter = useMemo<LatLngPoint | undefined>(() => {
    const boundaryCenterPoint = computePolygonCenter(boundaryDraft);
    if (boundaryCenterPoint) {
      return boundaryCenterPoint;
    }

    return vehicle?.location
      ? {
          latitude: vehicle.location.latitude ?? 40.1123,
          longitude: vehicle.location.longitude ?? -74.2129,
          altitude: vehicle.location.altitude,
        }
      : { latitude: 40.1123, longitude: -74.2129 };
  }, [boundaryDraft, vehicle?.location]);

  const mapCenter: [number, number] =
    missionMode === 'view' && vehicle?.location?.latitude !== undefined && vehicle.location.longitude !== undefined
      ? [vehicle.location.latitude, vehicle.location.longitude]
      : [boundaryCenter.latitude, boundaryCenter.longitude];
  const surveyPreview = useMemo(() => buildSurveyPreview(boundaryDraft), [boundaryDraft]);
  const breadcrumb = telemetryStream.samples;
  const fleetSource: FleetMarker[] = (fleetStatus?.drones?.length ? fleetStatus.drones : fleetConfig.drones) as FleetMarker[];
  const coverageOverlay = useMemo(
    () => [
      ...surveyPreview.flatMap((segment, segmentIndex) =>
        segment.map((point, pointIndex) => ({
          ...point,
          intensity: 0.08 + Math.min((segmentIndex + pointIndex) * 0.008, 0.14),
          radius: 18 + ((segmentIndex + pointIndex) % 4) * 4,
          label: pointIndex === 0 ? 'planned pass' : undefined,
        })),
      ),
      ...breadcrumb.slice(-40).map((sample, index) => ({
        latitude: sample.location?.latitude ?? mapCenter[0],
        longitude: sample.location?.longitude ?? mapCenter[1],
        intensity: 0.1 + Math.min(index * 0.005, 0.16),
        radius: 22 + (index % 3) * 3,
        label: index === breadcrumb.length - 1 ? 'live track' : undefined,
      })),
    ],
    [breadcrumb, mapCenter, surveyPreview],
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
      fleetSource.map((drone, index) => {
        const livePosition = drone.position;
        const position =
          livePosition?.latitude !== undefined && livePosition.longitude !== undefined
            ? {
                latitude: livePosition.latitude,
                longitude: livePosition.longitude,
                altitude: livePosition.altitude,
                heading: livePosition.heading,
              }
            : index === 0 && vehicle?.location?.latitude !== undefined && vehicle.location.longitude !== undefined
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
          ...drone,
          active: drone.drone_id === activeDroneId || drone.drone_id === fleetStatus?.self_drone_id,
          position,
        };
      }),
    [activeDroneId, fleetSource, fleetStatus?.self_drone_id, mapCenter, vehicle?.heading, vehicle?.location?.altitude, vehicle?.location?.latitude, vehicle?.location?.longitude],
  );
  const activeDrone = fleetMarkers.find((drone) => drone.drone_id === activeDroneId) ?? fleetMarkers[0];

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

  function saveRoute() {
    saveStoredDraft(routeStorageKey, routeDraft);
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
        apiKey || undefined,
        `gs-${routeStorageKey}`,
        'ground-station',
      );
      tokenToUse = authority?.token ?? '';
      if (tokenToUse) {
        setControlToken(tokenToUse);
      }
      setAuthorityStatus(authority?.active ? 'authority acquired' : 'authority request sent');
    }
    if (!tokenToUse) {
      setRouteMessage(`${statusLabel} requires control authority`);
    }
    return tokenToUse;
  }

  async function loadRouteFromCompanion() {
    try {
      const [missionState, boundaries] = await Promise.all([
        loadMissionState(companionBaseUrl, apiKey || undefined),
        loadFieldBoundaries(companionBaseUrl, apiKey || undefined),
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

      await clearCompanionMission(companionBaseUrl, apiKey || undefined, tokenToUse);
      if (routeDraft.boundary.length >= 3) {
        await uploadFieldBoundary(
          routeDraft.name,
          routeDraft.boundary,
          routeDraft.boundary[0]?.altitude,
          companionBaseUrl,
          apiKey || undefined,
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
          apiKey || undefined,
          tokenToUse,
        );
      }
      await uploadMissionToPixhawk(companionBaseUrl, apiKey || undefined, tokenToUse);
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
        apiKey || undefined,
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
        apiKey || undefined,
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
        apiKey || undefined,
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

      const exported = await exportIsoxml(routeDraft.name, apiKey || undefined, tokenToUse, companionBaseUrl);
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

      const result = await syncAgLeader(routeDraft.name, apiKey || undefined, tokenToUse, companionBaseUrl);
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

      const result = await generateFarmReport(routeDraft.name, apiKey || undefined, tokenToUse, companionBaseUrl);
      const reportPayload = result as { report_path?: string } | undefined;
      setFarmMessage(`report ${reportPayload?.report_path ? 'saved' : 'ready'}`);
    } catch (error) {
      setFarmMessage(`report failed: ${error instanceof Error ? error.message : 'unknown error'}`);
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
        apiKey: apiKey || undefined,
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
        apiKey || undefined,
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

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">GS</div>
          <div>
            <span className="eyebrow">Pixhawk companion</span>
            <h1>Ground Station</h1>
          </div>
        </div>

        <div className="sidebar-panel">
          <span className="panel-label">Connection</span>
          <div className="stack">
            <StatusChip label="State" value={connectionState} tone={connectionTone} />
            <StatusChip label="Telemetry" value={telemetryStream.state} tone={telemetryTone} />
            <StatusChip label="Source" value={sourceLabel} tone="neutral" />
            <StatusChip label="API" value={getBaseUrl(companionBaseUrl)} tone="neutral" />
            <StatusChip label="Route" value={routeMessage} tone="neutral" />
            <StatusChip label="Authority" value={authorityStatus} tone="neutral" />
          </div>
        </div>

        <div className="sidebar-panel">
          <span className="panel-label">Session</span>
          <label className="field">
            <span>API key</span>
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="x-api-key"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="field">
            <span>Control token</span>
            <input
              value={controlToken}
              onChange={(event) => setControlToken(event.target.value)}
              placeholder="x-control-token"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <button
            type="button"
            className="secondary-button"
            onClick={async () => {
              const authority = await acquireControlAuthority(
                companionBaseUrl,
                apiKey || undefined,
                `gs-${routeStorageKey}`,
                'ground-station',
              );
              if (authority?.token) {
                setControlToken(authority.token);
              }
              setAuthorityStatus(authority?.active ? 'authority acquired' : 'authority request sent');
            }}
          >
            Acquire authority
          </button>
          <p className="hint">Connects to `/ws/telemetry` and the REST snapshot endpoints when configured.</p>
        </div>

        <div className="sidebar-panel">
          <span className="panel-label">Mission</span>
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
        </div>
      </aside>

      <main className="content">
        <header className="hero">
          <div>
            <span className="eyebrow">Field operations cockpit</span>
            <h2>Mission control for spraying, mapping, and fleet awareness.</h2>
            <p>
              A cockpit-style shell for the Pixhawk companion with a real map, live telemetry stream, and draft mission tools.
            </p>
          </div>
          <div className="hero-actions">
            <button className="primary-button" type="button" onClick={uploadRouteToCompanion}>
              Upload mission
            </button>
            <button className="secondary-button" type="button" disabled={refreshing} onClick={saveRoute}>
              {refreshing ? 'Syncing...' : 'Save route'}
            </button>
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
              breadcrumb={breadcrumb}
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
              followViewport={missionMode === 'view'}
              onMapClick={handleMapClick}
              onBoundaryChange={setBoundaryPoints}
              onWaypointsChange={setWaypointPoints}
              activeDroneId={activeDrone?.drone_id}
              onSelectDrone={setActiveDroneId}
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

        <section className="bottom-grid">
          <MissionEditor
            mode={missionMode}
            boundary={boundaryDraft}
            waypoints={waypoints}
            onModeChange={setMissionMode}
            onClearBoundary={clearBoundary}
            onClearWaypoints={clearWaypoints}
            onUndoBoundaryPoint={removeLastBoundaryPoint}
            onUndoWaypoint={removeLastWaypoint}
            routeName={routeDraft.name}
            onRouteNameChange={(name) => setRouteDraft((current) => ({ ...current, name, updated_at: new Date().toISOString() }))}
            onSaveRoute={saveRoute}
            onUploadRoute={uploadRouteToCompanion}
            onDownloadRoute={downloadRoute}
            onLoadRoute={loadRouteFromCompanion}
            routeStatus={routeMessage}
          />

          <FleetPanel
            drones={fleetMarkers}
            activeDroneId={activeDrone?.drone_id}
            onSelectDrone={setActiveDroneId}
          />
        </section>

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

          <SwarmConfigEditor
            companionBaseUrl={companionBaseUrl}
            apiKey={apiKey || undefined}
            ensureControlToken={ensureControlToken}
            coordination={swarmCoordination}
          />
        </section>
      </main>
    </div>
  );
}

export default App;
