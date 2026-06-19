export type RuntimeConfig = {
  companionBaseUrl?: string;
  shellLabel?: string;
};

declare global {
  interface Window {
    __GROUND_STATION_RUNTIME_CONFIG__?: RuntimeConfig;
  }
}

function normalizeUrl(value?: string | null): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  const injected = globalThis.window?.__GROUND_STATION_RUNTIME_CONFIG__;
  if (injected) {
    return {
      companionBaseUrl: normalizeUrl(injected.companionBaseUrl),
      shellLabel: normalizeUrl(injected.shellLabel),
    };
  }

  try {
    const response = await fetch('/runtime-config.json', { cache: 'no-store' });
    if (response.ok) {
      const payload = (await response.json()) as RuntimeConfig;
      return {
        companionBaseUrl: normalizeUrl(payload.companionBaseUrl),
        shellLabel: normalizeUrl(payload.shellLabel),
      };
    }
  } catch {
    // fall back to build-time defaults
  }

  return {};
}

export function resolveCompanionBaseUrl(runtimeConfig?: RuntimeConfig): string | undefined {
  return (
    normalizeUrl(runtimeConfig?.companionBaseUrl) ||
    normalizeUrl(import.meta.env.VITE_COMPANION_BASE_URL) ||
    undefined
  );
}
