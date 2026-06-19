import type { TelemetrySeriesPoint, TelemetrySnapshot } from '../types/base';

type TelemetryEnvelope = {
  data?: TelemetrySnapshot | { telemetry?: TelemetrySnapshot };
  telemetry?: TelemetrySnapshot;
  sample?: TelemetrySnapshot;
  current?: TelemetrySnapshot;
  snapshot?: TelemetrySnapshot;
};

function isTelemetrySnapshot(value: unknown): value is TelemetrySnapshot {
  return (
    !!value &&
    typeof value === 'object' &&
    ('timestamp' in value || 'ground_speed' in value || 'battery' in value)
  );
}

export function normalizeTelemetryPayload(payload: unknown): TelemetrySnapshot | undefined {
  if (!payload || typeof payload !== 'object') {
    return undefined;
  }

  const candidate = payload as TelemetryEnvelope;

  if (isTelemetrySnapshot(candidate)) {
    return candidate;
  }

  if (candidate.data && typeof candidate.data === 'object') {
    if ('telemetry' in candidate.data && candidate.data.telemetry) {
      return candidate.data.telemetry;
    }

    return candidate.data as TelemetrySnapshot;
  }

  return candidate.telemetry ?? candidate.sample ?? candidate.current ?? candidate.snapshot;
}

export function appendTelemetrySample(
  current: TelemetrySeriesPoint[],
  sample: TelemetrySnapshot,
  sampleId: string,
  maxSamples = 120,
): TelemetrySeriesPoint[] {
  return [...current.slice(-(maxSamples - 1)), { ...sample, id: sampleId }];
}

export function getTelemetryBreadcrumb(
  samples: TelemetrySeriesPoint[],
): Array<[number, number]> {
  return samples.reduce<Array<[number, number]>>((acc, point) => {
    const latitude = point.location?.latitude;
    const longitude = point.location?.longitude;
    if (latitude === undefined || longitude === undefined) {
      return acc;
    }

    acc.push([latitude, longitude]);
    return acc;
  }, []);
}
