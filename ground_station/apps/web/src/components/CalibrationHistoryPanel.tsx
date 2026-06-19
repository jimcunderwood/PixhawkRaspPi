import { useMemo, useState } from 'react';
import type { CalibrationStatus, PpkJobStatus } from '../../../../shared/types/base';
import { StatusChip } from '../../../../packages/ui/src';

type CalibrationHistoryPanelProps = {
  calibrationStatus?: CalibrationStatus;
  message: string;
  onSaveBaseStation: () => void;
  onRunPpk: (job?: PpkJobStatus) => Promise<void> | void;
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

function formatNumber(value?: number | null, digits = 2, suffix = '') {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '--';
  }

  return `${value.toFixed(digits)}${suffix}`;
}

export function CalibrationHistoryPanel({
  calibrationStatus,
  message,
  onSaveBaseStation,
  onRunPpk,
}: CalibrationHistoryPanelProps) {
  const jobs = calibrationStatus?.recent_jobs ?? [];
  const [selectedJobId, setSelectedJobId] = useState<string | undefined>(jobs[0]?.job_id);

  const selectedJob = useMemo(
    () => jobs.find((job) => job.job_id === selectedJobId) ?? jobs[0],
    [jobs, selectedJobId],
  );

  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">RTK / PPK</span>
          <h3>Calibration history and rerun queue</h3>
        </div>
        <StatusChip
          label="Calibration"
          value={calibrationStatus?.active_base_station?.name ?? 'unconfigured'}
          tone={calibrationStatus?.active_base_station ? 'good' : 'warn'}
        />
      </div>

      <div className="stack">
        <p className="hint">{message}</p>
        <div className="config-grid">
          <div>
            <span className="metric-title">Base stations</span>
            <strong>{calibrationStatus?.base_station_count ?? 0}</strong>
          </div>
          <div>
            <span className="metric-title">Recent jobs</span>
            <strong>{jobs.length}</strong>
          </div>
          <div>
            <span className="metric-title">RTK</span>
            <strong>{calibrationStatus?.rtk_enabled ? 'ready' : 'idle'}</strong>
          </div>
          <div>
            <span className="metric-title">PPK</span>
            <strong>{calibrationStatus?.ppk_enabled ? 'ready' : 'idle'}</strong>
          </div>
        </div>

        <div className="editor-actions">
          <button type="button" className="secondary-button" onClick={onSaveBaseStation}>
            Save base station
          </button>
          <button type="button" className="secondary-button" onClick={() => void onRunPpk(selectedJob)}>
            Rerun selected PPK
          </button>
        </div>

        <div className="list-card">
          <div className="list-row">
            <div>
              <strong>Active base station</strong>
              <span>{calibrationStatus?.active_base_station?.name ?? 'None selected'}</span>
            </div>
            <span>{calibrationStatus?.active_base_station?.station_id ?? '--'}</span>
          </div>
          <div className="list-row">
            <div>
              <strong>Latest PPK job</strong>
              <span>{calibrationStatus?.last_job?.status ?? 'No job yet'}</span>
            </div>
            <span>
              {((calibrationStatus?.last_job?.quality as { estimated_position_error_m?: number } | undefined)?.estimated_position_error_m) !== undefined
                ? formatNumber(
                    (calibrationStatus?.last_job?.quality as { estimated_position_error_m?: number } | undefined)?.estimated_position_error_m,
                    2,
                    ' m',
                  )
                : '--'}
            </span>
          </div>
        </div>

        <div className="list-card">
          {jobs.slice(0, 6).map((job) => {
            const request = (job.request as { telemetry_window_seconds?: number } | undefined) ?? {};
            const summary = (job.summary as { sample_count?: number } | undefined) ?? {};

            return (
              <button
                key={job.job_id ?? `${job.session ?? 'job'}-${job.updated_at ?? 'new'}`}
                type="button"
                className={`fleet-row ${selectedJob?.job_id === job.job_id ? 'fleet-row-active' : ''}`}
                onClick={() => setSelectedJobId(job.job_id)}
              >
                <div>
                  <strong>{job.session ?? job.job_id ?? 'PPK job'}</strong>
                  <span>
                    {typeof summary.sample_count === 'number'
                      ? `${summary.sample_count} samples`
                      : `window ${request.telemetry_window_seconds ?? job.telemetry_window_seconds ?? 600}s`}
                  </span>
                </div>
                <span>
                  {formatAge(job.updated_at)}
                </span>
              </button>
            );
          })}
        </div>

        {selectedJob ? (
          <div className="list-card">
            <div className="list-row">
              <div>
                <strong>Selected job</strong>
                <span>{selectedJob.job_id ?? 'unknown job'}</span>
              </div>
              <span>{selectedJob.status ?? 'unknown'}</span>
            </div>
            <div className="list-row">
              <div>
                <strong>Request</strong>
                <span>{(selectedJob.request as { source_label?: string } | undefined)?.source_label ?? selectedJob.source_label ?? 'telemetry history'}</span>
              </div>
              <span>{selectedJob.base_station?.name ?? selectedJob.base_station_id ?? '--'}</span>
            </div>
            <div className="list-row">
              <div>
                <strong>Summary</strong>
                <span>{(selectedJob.summary as { sample_count?: number } | undefined)?.sample_count !== undefined ? `${(selectedJob.summary as { sample_count?: number } | undefined)?.sample_count} samples` : 'no samples'}</span>
              </div>
              <span>
                {((selectedJob.quality as { estimated_position_error_m?: number } | undefined)?.estimated_position_error_m) !== undefined
                  ? `${formatNumber((selectedJob.quality as { estimated_position_error_m?: number } | undefined)?.estimated_position_error_m, 2, ' m')}`
                  : '--'}
              </span>
            </div>
            <div className="editor-actions">
              <button type="button" className="ghost-button" onClick={() => void onRunPpk(selectedJob)}>
                Rerun this job
              </button>
              <button type="button" className="ghost-button" onClick={() => setSelectedJobId(undefined)}>
                Clear selection
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
