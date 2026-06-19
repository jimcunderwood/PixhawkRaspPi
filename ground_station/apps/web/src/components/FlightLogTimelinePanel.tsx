import type { FlightLogSyncHistoryEntry, FlightLogSyncStatus } from '../../../../shared/types/base';
import { StatusChip } from '../../../../packages/ui/src';

type FlightLogTimelinePanelProps = {
  flightLogSync?: FlightLogSyncStatus;
  bundles?: FlightLogSyncHistoryEntry[];
  message: string;
  onReplay: (bundle?: FlightLogSyncHistoryEntry) => Promise<void> | void;
  onRefresh: () => Promise<void> | void;
};

function formatAge(timestamp?: number | null) {
  if (!timestamp) {
    return '--';
  }

  const ageSeconds = Math.max(0, (Date.now() / 1000) - timestamp);
  if (ageSeconds < 60) {
    return `${Math.round(ageSeconds)}s ago`;
  }
  if (ageSeconds < 3600) {
    return `${Math.round(ageSeconds / 60)}m ago`;
  }
  return `${Math.round(ageSeconds / 3600)}h ago`;
}

export function FlightLogTimelinePanel({
  flightLogSync,
  bundles = [],
  message,
  onReplay,
  onRefresh,
}: FlightLogTimelinePanelProps) {
  const latestBundle = bundles[0];

  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">Observability</span>
          <h3>Flight log sync history</h3>
        </div>
        <StatusChip
          label="Sync"
          value={flightLogSync?.running ? 'running' : flightLogSync?.status ?? 'idle'}
          tone={flightLogSync?.running ? 'warn' : 'neutral'}
        />
      </div>

      <div className="stack">
        <p className="hint">{message}</p>
        <div className="config-grid">
          <div>
            <span className="metric-title">Base directory</span>
            <strong>{flightLogSync?.base_directory ?? '--'}</strong>
          </div>
          <div>
            <span className="metric-title">Latest bundle</span>
            <strong>{latestBundle?.name ?? 'none'}</strong>
          </div>
          <div>
            <span className="metric-title">Bundles</span>
            <strong>{bundles.length}</strong>
          </div>
          <div>
            <span className="metric-title">Last update</span>
            <strong>{formatAge(flightLogSync?.updated_at)}</strong>
          </div>
        </div>

        <div className="list-card">
          <div className="list-row">
            <div>
              <strong>Latest archive</strong>
              <span>{latestBundle?.archive_path ?? 'No archives yet'}</span>
            </div>
            <span>{latestBundle?.reason ?? '--'}</span>
          </div>
          {bundles.slice(0, 5).map((bundle) => (
            <div className="list-row" key={bundle.archive_path ?? bundle.name}>
              <div>
                <strong>{bundle.name ?? 'Flight log bundle'}</strong>
                <span>
                  {bundle.session ?? '--'} {bundle.pixhawk_file_count ? `· ${bundle.pixhawk_file_count} Pixhawk files` : ''}
                </span>
              </div>
              <span>{formatAge(bundle.updated_at)}</span>
            </div>
          ))}
        </div>

        <div className="editor-actions">
          <button type="button" className="secondary-button" onClick={() => void onReplay(latestBundle)}>
            Replay latest
          </button>
          <button type="button" className="ghost-button" onClick={() => void onRefresh()}>
            Refresh history
          </button>
        </div>
      </div>
    </section>
  );
}
