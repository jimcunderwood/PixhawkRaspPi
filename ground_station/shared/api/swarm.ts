import type {
  SwarmConfig,
  SwarmFusionState,
  SwarmSeparationAlert,
  SwarmStatus,
  SwarmTelemetryMessage,
} from '../types/swarm';

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

function buildUrl(baseUrl: string | undefined, path: string): string {
  if (!baseUrl) {
    return path;
  }

  return new URL(path, baseUrl).toString();
}

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
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

export async function loadSwarmConfig(baseUrl?: string, apiKey?: string): Promise<SwarmConfig | undefined> {
  try {
    const payload = await requestJson<StatusResponse<SwarmConfig>>('/api/swarm/config', {
      baseUrl,
      apiKey,
    });
    return payload.data;
  } catch {
    return undefined;
  }
}

export async function saveSwarmConfig(
  config: SwarmConfig,
  baseUrl?: string,
  apiKey?: string,
  controlToken?: string,
): Promise<SwarmConfig | undefined> {
  try {
    const payload = await requestJsonWithBody<StatusResponse<SwarmConfig>>(
      '/api/swarm/config',
      config,
      { baseUrl, apiKey, controlToken },
      'PUT',
    );
    return payload.data;
  } catch {
    return undefined;
  }
}

export async function loadSwarmStatus(baseUrl?: string, apiKey?: string): Promise<SwarmStatus | undefined> {
  try {
    const payload = await requestJson<StatusResponse<SwarmStatus>>('/api/swarm/status', {
      baseUrl,
      apiKey,
    });
    return payload.data;
  } catch {
    return undefined;
  }
}

export async function loadSwarmTelemetry(
  baseUrl?: string,
  apiKey?: string,
): Promise<SwarmTelemetryMessage[]> {
  try {
    const payload = await requestJson<StatusResponse<{ samples?: SwarmTelemetryMessage[] }>>('/api/swarm/telemetry', {
      baseUrl,
      apiKey,
    });
    return payload.data?.samples ?? [];
  } catch {
    return [];
  }
}

export async function loadSwarmAlerts(
  baseUrl?: string,
  apiKey?: string,
): Promise<SwarmSeparationAlert[]> {
  try {
    const payload = await requestJson<StatusResponse<{ alerts?: SwarmSeparationAlert[] }>>('/api/swarm/alerts', {
      baseUrl,
      apiKey,
    });
    return payload.data?.alerts ?? [];
  } catch {
    return [];
  }
}

export async function loadSwarmFusionState(
  baseUrl?: string,
  apiKey?: string,
): Promise<SwarmFusionState | undefined> {
  try {
    const payload = await requestJson<StatusResponse<SwarmFusionState>>('/api/swarm/fusion', {
      baseUrl,
      apiKey,
    });
    return payload.data;
  } catch {
    return undefined;
  }
}
