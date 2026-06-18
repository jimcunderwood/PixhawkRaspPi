import type { LatLngPoint, MissionWaypoint } from '../types/base';
import { buildWebSocketUrl, getCompanionBaseLabel, loadCompanionSnapshot } from './companion';

type RequestOptions = {
  apiKey?: string;
  controlToken?: string;
  baseUrl?: string;
};

type StatusResponse<T> = {
  status?: string;
  message?: string;
  data?: T;
};

export type ControlAuthorityStatus = {
  client_id?: string;
  operator?: string;
  token?: string;
  expires_at?: number;
  lease_seconds?: number;
  active?: boolean;
};

function buildUrl(baseUrl: string | undefined, path: string): string {
  if (!baseUrl) {
    return path;
  }

  return new URL(path, baseUrl).toString();
}

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(buildUrl(options.baseUrl, path), {
    method: 'GET',
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

async function requestJsonWithBody<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {},
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE' = 'POST',
): Promise<T> {
  const response = await fetch(buildUrl(options.baseUrl, path), {
    method,
    headers: {
      'content-type': 'application/json',
      ...(options.apiKey ? { 'x-api-key': options.apiKey } : {}),
      ...(options.controlToken ? { 'x-control-token': options.controlToken } : {}),
    },
    body: JSON.stringify(body ?? {}),
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export type CompanionMissionState = {
  waypoints: Array<{
    location?: LatLngPoint;
    label?: string;
    altitude_frame?: string;
    sequence?: number;
  }>;
  statistics?: Record<string, unknown>;
  execution?: Record<string, unknown>;
};

export type CompanionFieldBoundary = {
  name?: string;
  altitude?: number;
  vertices?: Array<LatLngPoint>;
};

export async function loadMissionState(baseUrl?: string, apiKey?: string): Promise<CompanionMissionState | undefined> {
  try {
    const payload = await requestJson<StatusResponse<CompanionMissionState>>('/api/mission/waypoints', {
      baseUrl,
      apiKey,
    });
    return payload.data;
  } catch {
    return undefined;
  }
}

export async function loadFieldBoundaries(baseUrl?: string, apiKey?: string): Promise<CompanionFieldBoundary[]> {
  try {
    const payload = await requestJson<StatusResponse<CompanionFieldBoundary[]>>('/api/field-boundaries', {
      baseUrl,
      apiKey,
    });
    return payload.data ?? [];
  } catch {
    return [];
  }
}

export async function clearCompanionMission(baseUrl?: string, apiKey?: string, controlToken?: string): Promise<void> {
  await requestJsonWithBody('/api/mission/clear', {}, { baseUrl, apiKey, controlToken }, 'POST');
}

export async function uploadMissionWaypoint(
  point: LatLngPoint,
  altitudeFrame: string,
  baseUrl?: string,
  apiKey?: string,
  controlToken?: string,
): Promise<void> {
  await requestJsonWithBody(
    '/api/mission/add-waypoint',
    {
      location: point,
      altitude_frame: altitudeFrame,
    },
    { baseUrl, apiKey, controlToken },
    'POST',
  );
}

export async function uploadFieldBoundary(
  name: string,
  vertices: LatLngPoint[],
  altitude?: number,
  baseUrl?: string,
  apiKey?: string,
  controlToken?: string,
): Promise<void> {
  await requestJsonWithBody(
    '/api/field-boundaries',
    {
      name,
      vertices,
      altitude,
    },
    { baseUrl, apiKey, controlToken },
    'POST',
  );
}

export async function uploadMissionToPixhawk(baseUrl?: string, apiKey?: string, controlToken?: string): Promise<void> {
  await requestJsonWithBody('/api/mission/pixhawk/upload', {}, { baseUrl, apiKey, controlToken }, 'POST');
}

export function buildCompanionWsLabel(baseUrl?: string): string {
  return getCompanionBaseLabel(baseUrl);
}

export function buildTelemetryStreamUrl(baseUrl: string | undefined, apiKey?: string): string {
  return buildWebSocketUrl(baseUrl, '/ws/telemetry', apiKey);
}

export async function acquireControlAuthority(
  baseUrl?: string,
  apiKey?: string,
  clientId = 'ground-station-web',
  operator = 'ground-station',
  leaseSeconds = 30,
  force = false,
): Promise<ControlAuthorityStatus | undefined> {
  try {
    const payload = await requestJsonWithBody<StatusResponse<ControlAuthorityStatus>>(
      '/api/control/authority',
      {
        client_id: clientId,
        operator,
        lease_seconds: leaseSeconds,
        force,
      },
      { baseUrl, apiKey },
      'POST',
    );
    return payload.data;
  } catch {
    return undefined;
  }
}
