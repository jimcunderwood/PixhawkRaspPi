import type {
  CompanionSnapshot,
  CalibrationStatus,
  EdgeAiStatus,
  FleetStatus,
  FarmIntegrationStatus,
  FlightLogSyncStatus,
  FlightLogSyncHistoryEntry,
  HealthResponse,
  MissionStats,
  NavigationStatus,
  PrescriptionMap,
  PrescriptionStatus,
  ReadinessStatus,
  SafetyStatus,
  WeatherStatus,
  TelemetrySnapshot,
  SwarmCoordinationStatus,
  VehicleStatus,
} from '../types/base';

type RequestOptions = {
  apiKey?: string;
  controlToken?: string;
  baseUrl?: string;
};

export type CameraSessionSummary = {
  session: string;
  latest_photo?: {
    session?: string;
    filename?: string;
    captured_at?: number;
  };
  photo_count?: number;
  captured_at?: number;
};

export type OrthomosaicPreviewRequest = {
  session?: string;
  filenames?: string[];
  limit?: number;
  tile_scale?: number;
  columns?: number;
};

export type GeoTiffBounds = {
  north: number;
  south: number;
  east: number;
  west: number;
};

export type GeoTiffUploadResponse = {
  asset_id: string;
  name?: string;
  source_filename?: string;
  bounds?: GeoTiffBounds;
  source_width_px?: number;
  source_height_px?: number;
  preview_width_px?: number;
  preview_height_px?: number;
  preview_url?: string;
};

function buildUrl(baseUrl: string | undefined, path: string): string {
  if (!baseUrl) {
    return path;
  }

  return new URL(path, baseUrl).toString();
}

export function buildWebSocketUrl(baseUrl: string | undefined, path: string, apiKey?: string): string {
  if (!baseUrl) {
    const locationHref = globalThis.location?.href;
    if (!locationHref) {
      return path;
    }

    const url = new URL(path, locationHref);
    url.protocol = globalThis.location?.protocol === 'https:' ? 'wss:' : 'ws:';
    if (apiKey) {
      url.searchParams.set('api_key', apiKey);
    }
    return url.toString();
  }

  const url = new URL(baseUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = path;
  url.search = '';
  if (apiKey) {
    url.searchParams.set('api_key', apiKey);
  }
  return url.toString();
}

export function getCompanionBaseLabel(baseUrl?: string): string {
  return baseUrl?.trim() || 'same-origin';
}

async function requestJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(buildUrl(options.baseUrl, path), {
    headers: {
      'content-type': 'application/json',
      ...(options.apiKey ? { 'x-api-key': options.apiKey } : {}),
      ...(options.controlToken ? { 'x-control-token': options.controlToken } : {}),
    },
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

async function requestBlob(
  path: string,
  options: RequestOptions = {},
  body?: unknown,
  method: 'GET' | 'POST' = 'GET',
): Promise<Blob> {
  const response = await fetch(buildUrl(options.baseUrl, path), {
    method,
    headers: {
      ...(body ? { 'content-type': 'application/json' } : {}),
      ...(options.apiKey ? { 'x-api-key': options.apiKey } : {}),
      ...(options.controlToken ? { 'x-control-token': options.controlToken } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.blob();
}

async function requestJsonWithBody<T>(
  path: string,
  body: BodyInit,
  options: RequestOptions = {},
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE' = 'POST',
  headers: Record<string, string> = {},
): Promise<T> {
  const response = await fetch(buildUrl(options.baseUrl, path), {
    method,
    headers: {
      ...headers,
      ...(options.apiKey ? { 'x-api-key': options.apiKey } : {}),
      ...(options.controlToken ? { 'x-control-token': options.controlToken } : {}),
    },
    body,
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

function extractData<T>(payload: { data?: T } | T): T {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data?: T }).data as T;
  }

  return payload as T;
}

export async function loadCompanionSnapshot(
  apiKey?: string,
  baseUrl?: string,
): Promise<CompanionSnapshot> {
  const [health, vehicle, readiness, safety, mission, navigation, weather, edgeAi, telemetry, fleet, prescription, calibration, farm, flightLogSync, swarmCoordination] = await Promise.allSettled([
    requestJson<HealthResponse>('/health', { apiKey, baseUrl }),
    requestJson<{ data?: VehicleStatus }>('/api/vehicle/status', { apiKey, baseUrl }),
    requestJson<{ data?: ReadinessStatus }>('/readiness', { apiKey, baseUrl }),
    requestJson<{ data?: SafetyStatus }>('/api/safety/status', { apiKey, baseUrl }),
    requestJson<{ data?: MissionStats }>('/api/mission/stats', { apiKey, baseUrl }),
    requestJson<{ data?: NavigationStatus }>('/api/navigation/config', { apiKey, baseUrl }),
    requestJson<{ data?: WeatherStatus }>('/api/weather/status', { apiKey, baseUrl }),
    requestJson<{ data?: EdgeAiStatus }>('/api/vision/obstacles/status', { apiKey, baseUrl }),
    requestJson<{ data?: TelemetrySnapshot }>('/api/telemetry/current', { apiKey, baseUrl }),
    requestJson<{ data?: FleetStatus }>('/api/fleet/status', { apiKey, baseUrl }),
    requestJson<{ data?: PrescriptionStatus }>('/api/payload/prescription/status', { apiKey, baseUrl }),
    requestJson<{ data?: CalibrationStatus }>('/api/calibration/status', { apiKey, baseUrl }),
    requestJson<{ data?: FarmIntegrationStatus }>('/api/farm/status', { apiKey, baseUrl }),
    requestJson<{ data?: FlightLogSyncStatus }>('/api/log-sync/status', { apiKey, baseUrl }),
    requestJson<{ data?: SwarmCoordinationStatus }>('/api/swarm/coordination', { apiKey, baseUrl }),
  ]);

  return {
    health: health.status === 'fulfilled' ? health.value : undefined,
    vehicle: vehicle.status === 'fulfilled' ? extractData(vehicle.value) : undefined,
    readiness: readiness.status === 'fulfilled' ? extractData(readiness.value) : undefined,
    safety: safety.status === 'fulfilled' ? extractData(safety.value) : undefined,
    mission: mission.status === 'fulfilled' ? extractData(mission.value) : undefined,
    navigation: navigation.status === 'fulfilled' ? extractData(navigation.value) : undefined,
    weather: weather.status === 'fulfilled' ? extractData(weather.value) : undefined,
    edge_ai: edgeAi.status === 'fulfilled' ? extractData(edgeAi.value) : undefined,
    telemetry: telemetry.status === 'fulfilled' ? extractData(telemetry.value) : undefined,
    fleet: fleet.status === 'fulfilled' ? extractData(fleet.value) : undefined,
    prescription: prescription.status === 'fulfilled' ? extractData(prescription.value) : undefined,
    calibration: calibration.status === 'fulfilled' ? extractData(calibration.value) : undefined,
    farm: farm.status === 'fulfilled' ? extractData(farm.value) : undefined,
    flight_log_sync: flightLogSync.status === 'fulfilled' ? extractData(flightLogSync.value) : undefined,
    swarm_coordination: swarmCoordination.status === 'fulfilled' ? extractData(swarmCoordination.value) : undefined,
  };
}

export async function loadFlightLogSyncHistory(
  apiKey?: string,
  baseUrl?: string,
): Promise<FlightLogSyncHistoryEntry[]> {
  try {
    const payload = await requestJson<{ data?: { bundles?: FlightLogSyncHistoryEntry[] } }>('/api/log-sync/history', {
      apiKey,
      baseUrl,
    });
    return payload.data?.bundles ?? [];
  } catch {
    return [];
  }
}

export async function replayFlightLogSyncBundle(
  archivePath: string,
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
  upload = false,
): Promise<FlightLogSyncHistoryEntry | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: FlightLogSyncHistoryEntry }>(
      '/api/log-sync/replay',
      JSON.stringify({ archive_path: archivePath, upload }),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function loadFleetStatus(apiKey?: string, baseUrl?: string): Promise<FleetStatus | undefined> {
  try {
    const payload = await requestJson<{ data?: FleetStatus }>('/api/fleet/status', { apiKey, baseUrl });
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function loadPrescriptionStatus(
  apiKey?: string,
  baseUrl?: string,
): Promise<PrescriptionStatus | undefined> {
  try {
    const payload = await requestJson<{ data?: PrescriptionStatus }>('/api/payload/prescription/status', {
      apiKey,
      baseUrl,
    });
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function loadPrescriptionMaps(
  apiKey?: string,
  baseUrl?: string,
): Promise<PrescriptionMap[]> {
  try {
    const payload = await requestJson<{ data?: { maps?: PrescriptionMap[] } }>('/api/payload/prescription/maps', {
      apiKey,
      baseUrl,
    });
    return payload.data?.maps ?? [];
  } catch {
    return [];
  }
}

export async function importPrescriptionMap(
  request: {
    name: string;
    payload_text: string;
    source_format?: string;
    activate?: boolean;
  },
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<PrescriptionMap | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: PrescriptionMap }>(
      '/api/payload/prescription/maps',
      JSON.stringify(request),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function activatePrescriptionMap(
  mapId: string,
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<PrescriptionMap | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: PrescriptionMap }>(
      '/api/payload/prescription/maps/activate',
      JSON.stringify({ map_id: mapId }),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function saveBaseStation(
  request: {
    station_id?: string;
    name: string;
    latitude?: number;
    longitude?: number;
    altitude_m?: number;
    antenna_height_m?: number;
    correction_port?: string;
    correction_baudrate?: number;
    mount_type?: string;
    notes?: string;
    activate?: boolean;
  },
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<Record<string, unknown> | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: Record<string, unknown> }>(
      '/api/calibration/rtk/base-stations',
      JSON.stringify(request),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function processPpkJob(
  request: {
    job_id?: string;
    session?: string;
    base_station_id?: string;
    telemetry_window_seconds?: number;
    source_label?: string;
    notes?: string;
    telemetry_history?: Array<Record<string, unknown>>;
  },
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<Record<string, unknown> | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: Record<string, unknown> }>(
      '/api/calibration/ppk/process',
      JSON.stringify(request),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function exportIsoxml(
  session?: string,
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<Record<string, unknown> | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: Record<string, unknown> }>(
      '/api/farm/integrations/isoxml/export',
      JSON.stringify({ session, report_format: 'isoxml' }),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function syncAgLeader(
  session?: string,
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<Record<string, unknown> | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: Record<string, unknown> }>(
      '/api/farm/integrations/agleader/sync',
      JSON.stringify({ session, report_format: 'agleader' }),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function generateFarmReport(
  session?: string,
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<Record<string, unknown> | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: Record<string, unknown> }>(
      '/api/farm/reports/automated',
      JSON.stringify({ session, report_format: 'json' }),
      { apiKey, controlToken, baseUrl },
      'POST',
      { 'content-type': 'application/json' },
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function loadCameraSessions(
  apiKey?: string,
  baseUrl?: string,
): Promise<CameraSessionSummary[]> {
  try {
    const payload = await requestJson<{ data?: { sessions?: CameraSessionSummary[] } }>('/api/payload/camera/sessions', {
      apiKey,
      baseUrl,
    });
    return payload.data?.sessions ?? [];
  } catch {
    return [];
  }
}

export async function loadOrthomosaicPreview(
  request: OrthomosaicPreviewRequest,
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<Blob> {
  return requestBlob(
    '/api/mapping/orthomosaic/preview',
    { apiKey, controlToken, baseUrl },
    request,
    'POST',
  );
}

export async function uploadGeoTiffPreview(
  file: Blob,
  bounds: GeoTiffBounds,
  options: {
    apiKey?: string;
    controlToken?: string;
    baseUrl?: string;
    filename?: string;
    name?: string;
    maxPreviewSize?: number;
  } = {},
): Promise<GeoTiffUploadResponse> {
  const url = new URL(buildUrl(options.baseUrl, '/api/mapping/geotiff/upload'), globalThis.location?.href);
  url.searchParams.set('north', String(bounds.north));
  url.searchParams.set('south', String(bounds.south));
  url.searchParams.set('east', String(bounds.east));
  url.searchParams.set('west', String(bounds.west));
  if (options.filename) {
    url.searchParams.set('filename', options.filename);
  }
  if (options.name) {
    url.searchParams.set('name', options.name);
  }
  if (options.maxPreviewSize) {
    url.searchParams.set('max_preview_size', String(options.maxPreviewSize));
  }

  return requestJsonWithBody<{
    data?: GeoTiffUploadResponse;
  }>(
    url.pathname + url.search,
    file,
    { apiKey: options.apiKey, controlToken: options.controlToken, baseUrl: options.baseUrl },
    'POST',
    { 'content-type': file.type || 'image/tiff' },
  ).then((payload) => payload.data as GeoTiffUploadResponse);
}

export async function loadGeoTiffPreview(
  assetId: string,
  apiKey?: string,
  controlToken?: string,
  baseUrl?: string,
): Promise<Blob> {
  return requestBlob(
    `/api/mapping/geotiff/${assetId}/preview`,
    { apiKey, controlToken, baseUrl },
  );
}
