import { StatusChip } from '../../../../packages/ui/src';
import type { RuntimeConfig } from '../runtimeConfig';
import type { ShellContext } from '../lib/shell';

type ShellStatusPanelProps = {
  shellContext: ShellContext;
  runtimeConfig?: RuntimeConfig;
};

export function ShellStatusPanel({
  shellContext,
  runtimeConfig,
}: ShellStatusPanelProps) {
  return (
    <div className="stack">
      <StatusChip label="Shell" value={shellContext.label} tone="good" />
      <StatusChip label="Mode" value={shellContext.detail} tone="neutral" />
      <StatusChip
        label="Runtime"
        value={runtimeConfig?.shellLabel ?? 'auto-detected'}
        tone={runtimeConfig?.shellLabel ? 'good' : 'neutral'}
      />
      <p className="hint">
        The same shared dashboard code powers web, Electron desktop, and Capacitor mobile shells.
      </p>
    </div>
  );
}
