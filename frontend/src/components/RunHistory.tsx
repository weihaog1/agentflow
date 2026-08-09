import type { RunSummary } from '../types';
import { formatDate, formatLatency, workflowLabel } from '../lib/format';
import { Icon } from './Icon';
import { SectionHeading } from './SectionHeading';

interface RunHistoryProps {
  runs: RunSummary[];
  loadError: string | null;
  activeRunId: string | null;
  isLoadingRun: boolean;
  onSelectRun: (runId: string) => void;
}

export function RunHistory({ runs, loadError, activeRunId, isLoadingRun, onSelectRun }: RunHistoryProps) {
  return (
    <section className="history-panel" aria-labelledby="run-history-title">
      <SectionHeading
        id="run-history-title"
        index="06"
        title="Run ledger"
        note="Recent immutable workflow records"
      />
      {loadError ? <p className="history-warning" role="status">{loadError}</p> : null}
      {runs.length === 0 ? (
        <p className="history-empty">
          {loadError ? 'Document work remains available while the run ledger reconnects.' : 'No completed runs in this workspace.'}
        </p>
      ) : (
        <div className="history-table" role="table" aria-label="Recent workflow runs">
          <div className="history-row history-head" role="row">
            <span role="columnheader">Workflow</span>
            <span role="columnheader">Created</span>
            <span role="columnheader">Cache</span>
            <span role="columnheader">Latency</span>
            <span aria-hidden="true" />
          </div>
          {runs.map((run) => (
            <button
              className="history-row"
              type="button"
              role="row"
              key={run.id}
              aria-label={`Open ${workflowLabel(run.workflow)} run from ${formatDate(run.createdAt)}`}
              aria-current={activeRunId === run.id ? 'true' : undefined}
              disabled={isLoadingRun}
              onClick={() => onSelectRun(run.id)}
            >
              <span role="cell">
                <i data-workflow={run.workflow} aria-hidden="true" />
                <strong>{workflowLabel(run.workflow)}</strong>
                <small>{run.id} · {run.status === 'unknown' ? 'status unknown' : run.status.replace('_', ' ')}</small>
              </span>
              <span role="cell">{formatDate(run.createdAt)}</span>
              <span role="cell">{run.cached ? 'Hit' : 'Miss'}</span>
              <span role="cell">{formatLatency(run.totalLatencyMs)}</span>
              <span role="cell"><Icon name="arrow" size={14} /></span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
