import { useState } from 'react';
import type { Citation, ConnectionMode, WorkflowRun } from '../types';
import { formatLatency, formatPercent, workflowLabel } from '../lib/format';
import { Icon } from './Icon';
import { SectionHeading } from './SectionHeading';

interface AnswerPanelProps {
  mode: ConnectionMode;
  run: WorkflowRun | null;
  isRunning: boolean;
  onCitationSelect: (citationId: string) => void;
}

export function AnswerPanel({ mode, run, isRunning, onCitationSelect }: AnswerPanelProps) {
  const [copied, setCopied] = useState(false);

  const copyAnswer = async () => {
    if (!run) return;
    await navigator.clipboard?.writeText(run.answer);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_600);
  };

  return (
    <section className="answer-panel" aria-labelledby="answer-title" aria-busy={isRunning}>
      <SectionHeading
        id="answer-title"
        index="03"
        title="Finding"
        note={run ? `${workflowLabel(run.workflow)} · run ${run.id}` : 'Evidence-backed output appears here'}
        action={run ? (
          <button className="text-action" type="button" onClick={() => void copyAnswer()}>
            <Icon name={copied ? 'check' : 'copy'} size={14} />
            {copied ? 'Copied' : 'Copy result'}
          </button>
        ) : null}
      />

      {isRunning ? (
        <div className="answer-loading" role="status">
          <div className="answer-loading__signal"><span /><span /><span /></div>
          <strong>Building an evidence-backed artifact</strong>
          <p>Retrieval, bounded reasoning, and citation verification run in sequence.</p>
          <div className="answer-loading__lines"><i /><i /><i /><i /></div>
        </div>
      ) : !run ? (
        <div className="answer-empty">
          <div className="answer-empty__folio">A</div>
          <div>
            <strong>No finding selected</strong>
            <p>Scope the corpus, choose a workflow, and run it. Every supported claim should lead back to source evidence.</p>
          </div>
        </div>
      ) : (
        <>
          <div className="answer-meta">
            <span className="answer-state" data-status={run.status}>
              <i aria-hidden="true" />
              {verificationLabel(run)}
            </span>
            <span>{mode === 'demo' ? 'Synthetic snapshot result' : 'Live API result'}</span>
            <span>Corpus revision {run.corpusRevision ?? 'not reported'}</span>
          </div>

          {run.evidenceGap ? (
            <div className="evidence-gap" role="status">
              <strong>Evidence gap</strong>
              <p>{run.evidenceGap}</p>
            </div>
          ) : null}

          <article className="answer-copy">
            {run.answer.split('\n').filter(Boolean).map((paragraph, index) => (
              <p key={`${paragraph.slice(0, 24)}-${index}`} data-bullet={paragraph.startsWith('•')}>
                <CitedLine
                  text={paragraph.replace(/^•\s*/, '')}
                  citations={run.citations}
                  onCitationSelect={onCitationSelect}
                />
              </p>
            ))}
          </article>

          <dl className="metric-strip">
            <div>
              <dt>Response cache</dt>
              <dd data-signal={run.cached && run.verified ? 'positive' : 'neutral'}>
                {run.cached ? (run.verified ? 'Verified hit' : 'Hit, unverified') : 'Miss'}
              </dd>
            </div>
            <div>
              <dt>Total latency</dt>
              <dd>{formatLatency(run.metrics.totalLatencyMs)}</dd>
            </div>
            <div>
              <dt>Citations</dt>
              <dd>{run.citations.length}</dd>
            </div>
            <div>
              <dt>Coverage</dt>
              <dd>{formatPercent(run.metrics.citationCoverage)}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}

function verificationLabel(run: WorkflowRun): string {
  if (run.verified) return 'Citation verified';
  if (run.status === 'completed') return 'Verification not confirmed';
  if (run.status === 'unknown') return 'Contract status unknown';
  return run.status.replace('_', ' ');
}

function CitedLine({
  text,
  citations,
  onCitationSelect,
}: {
  text: string;
  citations: Citation[];
  onCitationSelect: (citationId: string) => void;
}) {
  const parts = text.split(/(\[[A-Za-z0-9_-]+\])/g);
  return parts.map((part, index) => {
    const match = part.match(/^\[([A-Za-z0-9_-]+)\]$/);
    if (!match) return part;

    const reference = match[1] ?? '';
    const numericIndex = Number(reference);
    const citation = Number.isInteger(numericIndex) && numericIndex > 0
      ? citations[numericIndex - 1]
      : citations.find((item) => item.id === reference);
    if (!citation) return part;
    const citationNumber = citations.indexOf(citation) + 1;

    return (
      <button
        key={`${citation.id}-${index}`}
        className="inline-citation"
        type="button"
        aria-label={`Open citation ${citationNumber} from ${citation.documentTitle}`}
        onClick={() => onCitationSelect(citation.id)}
      >
        {citationNumber}
      </button>
    );
  });
}
