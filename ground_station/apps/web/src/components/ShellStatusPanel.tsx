import { StatusChip } from '../../../../packages/ui/src';
import type { RuntimeConfig } from '../runtimeConfig';
import type { ShellContext } from '../lib/shell';

type ShellStatusPanelProps = {
  shellContext: ShellContext;
  runtimeConfig?: RuntimeConfig;
  companionBaseUrl?: string;
};

export function ShellStatusPanel({
  shellContext,
  runtimeConfig,
  companionBaseUrl,
}: ShellStatusPanelProps) {
  return (
    <section className="sidebar-panel">
      <span className="panel-label">Shell parity</span>
      <div className="stack">
        <StatusChip label="Shell" value={shellContext.label} tone="good" />
        <StatusChip label="Mode" value={shellContext.detail} tone="neutral" />
        <StatusChip
          label="Runtime"
          value={runtimeConfig?.shellLabel ?? 'auto-detected'}
          tone={runtimeConfig?.shellLabel ? 'good' : 'neutral'}
        />
        <StatusChip label="Companion" value={companionBaseUrl?.trim() || 'same-origin'} tone="neutral" />
        <p className="hint">
          The same shared dashboard code powers web, Electron desktop, and Capacitor mobile shells.
        </p>
      </div>
    </section>
  );
}
