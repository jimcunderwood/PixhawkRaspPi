import { useEffect, useMemo, useState } from 'react';
import { FieldMap } from './components/FieldMap';
import { FleetPanel } from './components/FleetPanel';
import { MissionEditor } from './components/MissionEditor';
import { TelemetryCharts } from './components/TelemetryCharts';
import { mockSnapshot } from './data/mockState';
import { useTelemetryStream } from './hooks/useTelemetryStream';
import { getBaseUrl, loadCompanionSnapshot } from './lib/companionClient';
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

function App() {
  const companionBaseUrl = import.meta.env.VITE_COMPANION_BASE_URL?.trim() || undefined;
  const routeStorageKey = 'ground-station.route-draft.v1';
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
  const [activeDroneId, setActiveDroneId] = useState(mockFleetConfig.drones[0]?.drone_id);
  const [fleetConfig] = useState(mockFleetConfig);
  const [controlToken, setControlToken] = useState('');
  const [authorityStatus, setAuthorityStatus] = useState('not requested');

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
          telemetry: live.telemetry ?? mockSnapshot.telemetry,
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
  }, [apiKey]);

  useEffect(() => {
    saveStoredDraft(routeStorageKey, routeDraft);
  }, [routeDraft, routeStorageKey]);

  const telemetryStream = useTelemetryStream(apiKey || undefined, statusSnapshot.telemetry ?? mockSnapshot.telemetry);
  const telemetry = telemetryStream.latest ?? statusSnapshot.telemetry ?? mockSnapshot.telemetry;
  const vehicle = statusSnapshot.vehicle ?? mockSnapshot.vehicle;
  const readiness = statusSnapshot.readiness ?? mockSnapshot.readiness;
  const safety = statusSnapshot.safety ?? mockSnapshot.safety;
  const mission = statusSnapshot.mission ?? mockSnapshot.mission;

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

  const mapCenter: [number, number] = [boundaryCenter.latitude, boundaryCenter.longitude];
  const surveyPreview = useMemo(() => buildSurveyPreview(boundaryDraft), [boundaryDraft]);
  const breadcrumb = telemetryStream.samples;
  const activeDrone = fleetConfig.drones.find((drone) => drone.drone_id === activeDroneId) ?? fleetConfig.drones[0];
  const fleetMarkers = useMemo(
    () =>
      fleetConfig.drones.map((drone, index) => {
        const position =
          index === 0 && vehicle?.location?.latitude !== undefined && vehicle.location.longitude !== undefined
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
          active: drone.drone_id === activeDroneId,
          position,
        };
      }),
    [activeDroneId, fleetConfig.drones, mapCenter, vehicle?.heading, vehicle?.location?.altitude, vehicle?.location?.latitude, vehicle?.location?.longitude],
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

      await clearCompanionMission(companionBaseUrl, apiKey || undefined, tokenToUse || undefined);
      if (routeDraft.boundary.length >= 3) {
        await uploadFieldBoundary(
          routeDraft.name,
          routeDraft.boundary,
          routeDraft.boundary[0]?.altitude,
          companionBaseUrl,
          apiKey || undefined,
          tokenToUse || undefined,
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
          tokenToUse || undefined,
        );
      }
      await uploadMissionToPixhawk(companionBaseUrl, apiKey || undefined, tokenToUse || undefined);
      setRouteMessage(`Uploaded ${routeDraft.waypoints.length} waypoints to companion`);
    } catch (error) {
      setRouteMessage(`Upload failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
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
              <StatusChip
                label="Mode"
                value={vehicle?.mode ?? 'unknown'}
                tone={vehicle?.armed ? 'warn' : 'neutral'}
              />
            </div>

            <FieldMap
              center={mapCenter}
              boundary={boundaryDraft}
              waypoints={waypoints}
              breadcrumb={breadcrumb}
              surveyPreview={surveyPreview}
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
              fleet={fleetMarkers}
              mode={missionMode}
              followViewport={missionMode === 'view'}
              onMapClick={handleMapClick}
              activeDroneId={activeDrone?.drone_id}
              onSelectDrone={setActiveDroneId}
            />

            <div className="map-footer">
              <StatusChip label="Boundary" value={`${boundaryDraft.length} pts`} tone="neutral" />
              <StatusChip label="Survey" value={`${surveyPreview.length} lines`} tone="neutral" />
              <StatusChip label="Breadcrumb" value={`${breadcrumb.length} pts`} tone="neutral" />
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
        </section>
      </main>
    </div>
  );
}

export default App;
