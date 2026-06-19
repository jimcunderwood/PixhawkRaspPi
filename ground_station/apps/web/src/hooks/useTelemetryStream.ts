import { useEffect, useRef, useState } from 'react';
import type { TelemetrySeriesPoint, TelemetrySnapshot, TelemetryStreamState } from '../types';
import { buildWebSocketUrl } from '../../../../shared/api/companion';
import { appendTelemetrySample, normalizeTelemetryPayload } from '../../../../shared/telemetry/stream';

type UseTelemetryStreamResult = {
  state: TelemetryStreamState;
  latest?: TelemetrySnapshot;
  samples: TelemetrySeriesPoint[];
  lastMessageAt?: number;
};

function makeId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function useTelemetryStream(
  apiKey?: string,
  companionBaseUrl?: string,
  seedSample?: TelemetrySnapshot,
): UseTelemetryStreamResult {
  const [state, setState] = useState<TelemetryStreamState>('offline');
  const [latest, setLatest] = useState<TelemetrySnapshot | undefined>(seedSample);
  const [samples, setSamples] = useState<TelemetrySeriesPoint[]>(() =>
    seedSample ? [{ ...seedSample, id: makeId() }] : [],
  );
  const [lastMessageAt, setLastMessageAt] = useState<number | undefined>(undefined);
  const reconnectRef = useRef<number>(0);

  useEffect(() => {
    if (seedSample && samples.length === 0) {
      setLatest(seedSample);
      setSamples([{ ...seedSample, id: makeId() }]);
    }
  }, [seedSample, samples.length]);

  useEffect(() => {
    if (!companionBaseUrl) {
      setState('offline');
      return () => {
        // no websocket connection to maintain
      };
    }

    let alive = true;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;
    reconnectRef.current = 0;

    function scheduleReconnect() {
      if (!alive) {
        return;
      }

      const attempt = reconnectRef.current;
      const delay = Math.min(1000 * 2 ** attempt, 10000);
      reconnectRef.current += 1;
      setState(attempt === 0 ? 'offline' : 'reconnecting');
      reconnectTimer = window.setTimeout(connect, delay);
    }

    function handleMessage(event: MessageEvent) {
      setLastMessageAt(Date.now());
      try {
        const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
        const telemetry = normalizeTelemetryPayload(parsed);
        if (telemetry) {
          const sampleId = makeId();
          setLatest(telemetry);
          setSamples((current) => appendTelemetrySample(current, telemetry, sampleId));
        }
      } catch {
        if (typeof event.data === 'string') {
          const sample = { timestamp: Date.now() / 1000 } as TelemetrySnapshot;
          setLatest(sample);
          setSamples((current) => appendTelemetrySample(current, sample, makeId()));
        }
      }
    }

    function connect() {
      if (!alive) {
        return;
      }

      setState(reconnectRef.current === 0 ? 'connecting' : 'reconnecting');

      try {
        socket = new WebSocket(
          buildWebSocketUrl(companionBaseUrl, '/ws/telemetry', apiKey),
        );
      } catch {
        scheduleReconnect();
        return;
      }

      socket.onopen = () => {
        reconnectRef.current = 0;
        setState('streaming');
      };
      socket.onmessage = handleMessage;
      socket.onerror = () => {
        try {
          socket?.close();
        } catch {
          scheduleReconnect();
        }
      };
      socket.onclose = () => {
        if (alive) {
          scheduleReconnect();
        }
      };
    }

    connect();

    return () => {
      alive = false;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
      }
      try {
        socket?.close();
      } catch {
        // ignore
      }
    };
  }, [apiKey, companionBaseUrl]);

  return {
    state,
    latest,
    samples,
    lastMessageAt,
  };
}
