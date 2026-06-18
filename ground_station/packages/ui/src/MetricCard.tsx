type MetricCardProps = {
  title: string;
  value: string;
  detail?: string;
  accent?: 'amber' | 'teal' | 'red' | 'blue';
};

export function MetricCard({
  title,
  value,
  detail,
  accent = 'amber',
}: MetricCardProps) {
  return (
    <section className={`metric metric-${accent}`}>
      <span className="metric-title">{title}</span>
      <strong className="metric-value">{value}</strong>
      {detail ? <span className="metric-detail">{detail}</span> : null}
    </section>
  );
}
