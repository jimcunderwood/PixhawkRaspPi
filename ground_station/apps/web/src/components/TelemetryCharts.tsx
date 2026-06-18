import type { TelemetrySeriesPoint } from '../types';

function getValue(point: TelemetrySeriesPoint, key: 'ground_speed' | 'battery' | 'altitude') {
  if (key === 'ground_speed') {
    return point.ground_speed ?? 0;
  }

  if (key === 'battery') {
    return point.battery?.level_percent ?? 0;
  }

  return point.location?.altitude ?? 0;
}

function Sparkline({
  points,
  color,
  valueKey,
}: {
  points: TelemetrySeriesPoint[];
  color: string;
  valueKey: 'ground_speed' | 'battery' | 'altitude';
}) {
  const values = points.map((point) => getValue(point, valueKey));
  const width = 320;
  const height = 110;
  const padded = 10;
  const numericValues = values.length ? values : [0];
  const min = Math.min(...numericValues);
  const max = Math.max(...numericValues);
  const range = max - min || 1;
  const step = values.length > 1 ? (width - padded * 2) / (values.length - 1) : width / 2;
  const coords = numericValues.map((value, index) => {
    const x = padded + step * index;
    const y = height - padded - ((value - min) / range) * (height - padded * 2);
    return `${x},${y}`;
  });

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="sparkline" aria-hidden="true">
      <defs>
        <linearGradient id={`spark-${valueKey}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.42" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline fill="none" stroke={color} strokeWidth="3" points={coords.join(' ')} strokeLinecap="round" strokeLinejoin="round" />
      <path
        d={`M ${coords.join(' L ')} L ${width - padded},${height - padded} L ${padded},${height - padded} Z`}
        fill={`url(#spark-${valueKey})`}
      />
    </svg>
  );
}

export function TelemetryCharts({
  points,
  latestLabel,
}: {
  points: TelemetrySeriesPoint[];
  latestLabel: string;
}) {
  const latest = points.length ? points[points.length - 1] : undefined;

  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">Telemetry</span>
          <h3>Live stream and charts</h3>
        </div>
        <span className="pill">{latestLabel}</span>
      </div>

      <div className="chart-grid">
        <article className="chart-card">
          <div className="chart-head">
            <span>Ground speed</span>
            <strong>{latest?.ground_speed?.toFixed(1) ?? '--'} m/s</strong>
          </div>
          <Sparkline points={points} color="#2fd6c4" valueKey="ground_speed" />
        </article>

        <article className="chart-card">
          <div className="chart-head">
            <span>Battery</span>
            <strong>{latest?.battery?.level_percent !== undefined ? `${Math.round(latest.battery.level_percent)}%` : '--'}</strong>
          </div>
          <Sparkline points={points} color="#ffb000" valueKey="battery" />
        </article>

        <article className="chart-card">
          <div className="chart-head">
            <span>Altitude</span>
            <strong>{latest?.location?.altitude?.toFixed(1) ?? '--'} m</strong>
          </div>
          <Sparkline points={points} color="#6ea8fe" valueKey="altitude" />
        </article>
      </div>
    </section>
  );
}
