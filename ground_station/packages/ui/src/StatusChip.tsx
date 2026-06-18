type StatusChipProps = {
  label: string;
  value: string;
  tone?: 'good' | 'warn' | 'bad' | 'neutral';
};

export function StatusChip({ label, value, tone = 'neutral' }: StatusChipProps) {
  return (
    <div className={`chip chip-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
