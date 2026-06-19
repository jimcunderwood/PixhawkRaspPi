import type {
  GroundStationLoginRequest,
  GroundStationSessionState,
  GroundStationUserSettings,
} from '../types/settings';

type RequestOptions = {
  baseUrl?: string;
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
    },
    credentials: 'include',
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
    },
    credentials: 'include',
    body: JSON.stringify(body ?? {}),
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

export async function loadSession(baseUrl?: string): Promise<GroundStationSessionState | undefined> {
  try {
    const payload = await requestJson<{ data?: GroundStationSessionState }>('/api/settings/session', { baseUrl });
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function login(
  request: GroundStationLoginRequest,
  baseUrl?: string,
): Promise<GroundStationSessionState | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: GroundStationSessionState }>(
      '/api/settings/session',
      request,
      { baseUrl },
      'POST',
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function logout(baseUrl?: string): Promise<void> {
  await requestJsonWithBody('/api/settings/session', {}, { baseUrl }, 'DELETE');
}

export async function loadUserSettings(baseUrl?: string): Promise<GroundStationUserSettings | undefined> {
  try {
    const payload = await requestJson<{ data?: GroundStationUserSettings }>('/api/settings/profile', { baseUrl });
    return extractData(payload);
  } catch {
    return undefined;
  }
}

export async function saveUserSettings(
  settings: GroundStationUserSettings,
  baseUrl?: string,
): Promise<GroundStationUserSettings | undefined> {
  try {
    const payload = await requestJsonWithBody<{ data?: GroundStationUserSettings }>(
      '/api/settings/profile',
      settings,
      { baseUrl },
      'PUT',
    );
    return extractData(payload);
  } catch {
    return undefined;
  }
}
