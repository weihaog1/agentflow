import type { ConnectionMode, WorkflowKind } from '../types';
import { workflowLabel } from '../lib/format';
import { Icon } from './Icon';
import { SectionHeading } from './SectionHeading';

interface WorkflowComposerProps {
  mode: ConnectionMode;
  workflow: WorkflowKind;
  prompt: string;
  audience: string;
  maxPoints: number;
  topK: number;
  selectedCount: number;
  readyCount: number;
  isRunning: boolean;
  runError: string | null;
  onWorkflowChange: (workflow: WorkflowKind) => void;
  onPromptChange: (value: string) => void;
  onAudienceChange: (value: string) => void;
  onMaxPointsChange: (value: number) => void;
  onTopKChange: (value: number) => void;
  onRun: () => void;
}

const workflows: Array<{
  id: WorkflowKind;
  short: string;
  description: string;
}> = [
  { id: 'question', short: 'Ask', description: 'Answer one question with verified citations' },
  { id: 'compare', short: 'Compare', description: 'Contrast selected documents against one focus' },
  { id: 'brief', short: 'Brief', description: 'Turn evidence into a decision-ready summary' },
];

const promptLabels: Record<WorkflowKind, string> = {
  question: 'Question to answer',
  compare: 'Comparison focus',
  brief: 'Brief objective',
};

const placeholders: Record<WorkflowKind, string> = {
  question: 'Ask a specific question that the selected evidence can answer.',
  compare: 'What tradeoffs, obligations, or terms should be compared?',
  brief: 'What decision should this brief help the audience make?',
};

export function WorkflowComposer({
  mode,
  workflow,
  prompt,
  audience,
  maxPoints,
  topK,
  selectedCount,
  readyCount,
  isRunning,
  runError,
  onWorkflowChange,
  onPromptChange,
  onAudienceChange,
  onMaxPointsChange,
  onTopKChange,
  onRun,
}: WorkflowComposerProps) {
  const compareNeedsDocuments = workflow === 'compare' && selectedCount < 2;
  const missingPrompt = workflow !== 'brief' && prompt.trim().length === 0;
  const nothingReady = readyCount === 0;
  const disabled = isRunning || compareNeedsDocuments || missingPrompt || nothingReady || mode === 'checking';

  let scopeLabel = `${selectedCount} selected`;
  if (selectedCount === 0 && workflow !== 'compare') scopeLabel = `All ${readyCount} ready documents`;

  return (
    <section className="composer-panel" aria-labelledby="compose-title">
      <SectionHeading
        id="compose-title"
        index="02"
        title="Compose"
        note="Choose one bounded evidence workflow"
        action={<span className="scope-count">{scopeLabel}</span>}
      />

      <div className="workflow-tabs" role="tablist" aria-label="Workflow" aria-orientation="horizontal">
        {workflows.map((item, index) => (
          <button
            key={item.id}
            id={`workflow-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={workflow === item.id}
            aria-controls="workflow-composer"
            tabIndex={workflow === item.id ? 0 : -1}
            onClick={() => onWorkflowChange(item.id)}
            onKeyDown={(event) => {
              let targetIndex: number;
              if (event.key === 'ArrowRight') targetIndex = (index + 1) % workflows.length;
              else if (event.key === 'ArrowLeft') targetIndex = (index - 1 + workflows.length) % workflows.length;
              else if (event.key === 'Home') targetIndex = 0;
              else if (event.key === 'End') targetIndex = workflows.length - 1;
              else return;

              event.preventDefault();
              const target = workflows[targetIndex];
              if (!target) return;
              onWorkflowChange(target.id);
              document.getElementById(`workflow-tab-${target.id}`)?.focus();
            }}
          >
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{item.short}</strong>
            <small>{item.description}</small>
          </button>
        ))}
      </div>

      <form
        id="workflow-composer"
        className="composer-form"
        role="tabpanel"
        aria-labelledby={`workflow-tab-${workflow}`}
        onSubmit={(event) => {
          event.preventDefault();
          if (!disabled) onRun();
        }}
      >
        <label className="prompt-field">
          <span className="field-label">
            {promptLabels[workflow]}
            {workflow === 'brief' ? <small>Optional</small> : null}
          </span>
          <textarea
            value={prompt}
            rows={4}
            placeholder={placeholders[workflow]}
            disabled={isRunning}
            aria-describedby="composer-guidance"
            onChange={(event) => onPromptChange(event.target.value)}
          />
          <span className="prompt-field__rule" aria-hidden="true" />
        </label>

        {workflow === 'brief' ? (
          <div className="brief-options">
            <label>
              <span className="field-label">Audience</span>
              <input
                type="text"
                value={audience}
                placeholder="Executive team"
                disabled={isRunning}
                onChange={(event) => onAudienceChange(event.target.value)}
              />
            </label>
            <label>
              <span className="field-label">Maximum points</span>
              <select
                value={maxPoints}
                disabled={isRunning}
                onChange={(event) => onMaxPointsChange(Number(event.target.value))}
              >
                {[4, 5, 6, 8].map((count) => <option key={count} value={count}>{count}</option>)}
              </select>
            </label>
          </div>
        ) : null}

        <div className="composer-controls">
          <div id="composer-guidance" className="composer-guidance">
            {compareNeedsDocuments ? (
              <span className="validation-note">Select at least two ready documents to compare.</span>
            ) : (
              <span>Source text is treated as evidence, never as workflow instructions.</span>
            )}
            {runError ? <span className="validation-note" role="alert">{runError}</span> : null}
          </div>

          <label className="depth-control">
            <span>Retrieval depth</span>
            <select
              value={topK}
              disabled={isRunning}
              aria-label="Retrieval depth"
              onChange={(event) => onTopKChange(Number(event.target.value))}
            >
              <option value={4}>4 chunks</option>
              <option value={6}>6 chunks</option>
              <option value={8}>8 chunks</option>
              <option value={12}>12 chunks</option>
            </select>
          </label>

          <button className="run-button" type="submit" disabled={disabled}>
            <span className="run-button__icon"><Icon name="run" size={17} /></span>
            <span>
              <small>{mode === 'demo' ? 'Run snapshot simulation' : 'Start verified workflow'}</small>
              <strong>{isRunning ? 'Working through evidence' : workflowLabel(workflow)}</strong>
            </span>
            <Icon name="arrow" size={18} />
          </button>
        </div>
      </form>
    </section>
  );
}
