import type { FarmIntegrationStatus } from '../../../../shared/types/base';
import { StatusChip } from '../../../../packages/ui/src';

type FarmTimelinePanelProps = {
  farmStatus?: FarmIntegrationStatus;
  message: string;
  onExportIsoxml: () => void;
  onSyncAgLeader: () => void;
  onGenerateReport: () => void;
};

function formatAge(timestamp?: number) {
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

function buildTimelineItems(farmStatus?: FarmIntegrationStatus) {
  const isoxmlExports = (farmStatus?.recent_isoxml_exports ?? []) as Array<{
    name?: string;
    path?: string;
    updated_at?: number;
  }>;
  const reports = (farmStatus?.recent_reports ?? []) as Array<{
    name?: string;
    path?: string;
    updated_at?: number;
  }>;
  const items = [
    ...isoxmlExports.map((item) => ({
      kind: 'ISOXML',
      name: item.name ?? item.path ?? 'ISOXML export',
      updated_at: item.updated_at,
      detail: item.path,
    })),
    ...reports.map((item) => ({
      kind: 'Report',
      name: item.name ?? item.path ?? 'Farm report',
      updated_at: item.updated_at,
      detail: item.path,
    })),
  ];

  return items.sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0)).slice(0, 6);
}

export function FarmTimelinePanel({
  farmStatus,
  message,
  onExportIsoxml,
  onSyncAgLeader,
  onGenerateReport,
}: FarmTimelinePanelProps) {
  const timelineItems = buildTimelineItems(farmStatus);

  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">Farm management</span>
          <h3>ISOXML and report timeline</h3>
        </div>
        <StatusChip
          label="Reports"
          value={farmStatus?.agleader_configured ? 'connected' : 'local'}
          tone={farmStatus?.agleader_configured ? 'good' : 'warn'}
        />
      </div>

      <div className="stack">
        <p className="hint">{message}</p>
        <div className="editor-actions">
          <button type="button" className="secondary-button" onClick={onExportIsoxml}>
            Export ISOXML
          </button>
          <button type="button" className="secondary-button" onClick={onSyncAgLeader}>
            Sync agLeader
          </button>
          <button type="button" className="secondary-button" onClick={onGenerateReport}>
            Automated report
          </button>
        </div>

        <div className="config-grid">
          <div>
            <span className="metric-title">ISOXML output</span>
            <strong>{farmStatus?.isoxml_output_directory ?? '--'}</strong>
          </div>
          <div>
            <span className="metric-title">Report output</span>
            <strong>{farmStatus?.report_output_directory ?? '--'}</strong>
          </div>
          <div>
            <span className="metric-title">Latest ISOXML</span>
            <strong>{(farmStatus?.latest_isoxml_export as { name?: string } | undefined)?.name ?? 'none'}</strong>
          </div>
          <div>
            <span className="metric-title">Latest report</span>
            <strong>{(farmStatus?.latest_report as { name?: string } | undefined)?.name ?? 'none'}</strong>
          </div>
        </div>

        <div className="list-card">
          <div className="list-row">
            <div>
              <strong>Timeline</strong>
              <span>{timelineItems.length ? `${timelineItems.length} recent outputs` : 'No outputs yet'}</span>
            </div>
            <span>{farmStatus?.configured ? 'ready' : 'idle'}</span>
          </div>
          {timelineItems.map((item, index) => (
            <div className="list-row" key={`${item.kind}-${item.name}-${index}`}>
              <div>
                <strong>{item.kind}</strong>
                <span>{item.detail ?? item.name}</span>
              </div>
              <span>{formatAge(item.updated_at)}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
