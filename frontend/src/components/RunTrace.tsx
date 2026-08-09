import type { WorkflowRun } from '../types';
import { formatDetail, formatLatency, humanize } from '../lib/format';
import { Icon } from './Icon';

interface RunTraceProps {
  run: WorkflowRun | null;
}

export function RunTrace({ run }: RunTraceProps) {
  return (
    <details className="trace-panel" open={Boolean(run)}>
      <summary>
        <span className="trace-panel__title">
          <span>05</span>
          <strong>Run trace</strong>
          <small>Bounded operational stages</small>
        </span>
        <span className="trace-panel__summary">
          {run ? `${run.steps.length} reported steps` : 'No active run'}
          <Icon name="chevron" size={15} />
        </span>
      </summary>

      {!run ? (
        <p className="trace-empty">A completed run will expose its operational trace here. Hidden reasoning is never recorded.</p>
      ) : run.steps.length === 0 ? (
        <p className="trace-empty">This API response did not include detailed stage telemetry.</p>
      ) : (
        <ol className="trace-list">
          {run.steps.map((step, index) => (
            <li key={`${step.name}-${index}`} data-status={step.status}>
              <span className="trace-node" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
              <span className="trace-step">
                <strong>{humanize(step.name)}</strong>
                <small>{formatDetail(step.detail)}</small>
              </span>
              <span className="trace-status">{step.status}</span>
              <span className="trace-latency">{formatLatency(step.latencyMs)}</span>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}
