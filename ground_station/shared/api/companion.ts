import type {
  CompanionSnapshot,
  HealthResponse,
  MissionStats,
  NavigationStatus,
  ReadinessStatus,
  SafetyStatus,
  TelemetrySnapshot,
  VehicleStatus,
} from '../types/base';

type RequestOptions = {
  apiKey?: string;
  controlToken?: string;
  baseUrl?: string;
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
  const [health, vehicle, readiness, safety, mission, navigation, telemetry] = await Promise.allSettled([
    requestJson<HealthResponse>('/health', { apiKey, baseUrl }),
    requestJson<{ data?: VehicleStatus }>('/api/vehicle/status', { apiKey, baseUrl }),
    requestJson<{ data?: ReadinessStatus }>('/api/readiness', { apiKey, baseUrl }),
    requestJson<{ data?: SafetyStatus }>('/api/safety/status', { apiKey, baseUrl }),
    requestJson<{ data?: MissionStats }>('/api/mission/stats', { apiKey, baseUrl }),
    requestJson<{ data?: NavigationStatus }>('/api/navigation/config', { apiKey, baseUrl }),
    requestJson<{ data?: TelemetrySnapshot }>('/api/telemetry/current', { apiKey, baseUrl }),
  ]);

  return {
    health: health.status === 'fulfilled' ? health.value : undefined,
    vehicle: vehicle.status === 'fulfilled' ? extractData(vehicle.value) : undefined,
    readiness: readiness.status === 'fulfilled' ? extractData(readiness.value) : undefined,
    safety: safety.status === 'fulfilled' ? extractData(safety.value) : undefined,
    mission: mission.status === 'fulfilled' ? extractData(mission.value) : undefined,
    navigation: navigation.status === 'fulfilled' ? extractData(navigation.value) : undefined,
    telemetry: telemetry.status === 'fulfilled' ? extractData(telemetry.value) : undefined,
  };
}
