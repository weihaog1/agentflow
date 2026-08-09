import { describe, expect, it } from 'vitest';
import { getDemoRun, runDemoWorkflow } from './demo';

describe('demo workflow contract', () => {
  it('fails with an evidence gap when selected documents exclude the fixture source', async () => {
    const run = await runDemoWorkflow({
      workflow: 'question',
      question: "What are Northstar's deletion timelines and exceptions?",
      documentIds: ['atlas-service-proposal'],
      topK: 8,
    });

    expect(run).toMatchObject({ status: 'evidence_gap', verified: false, citations: [] });
    expect(run.evidenceGap).toContain('northstar-retention-schedule');
  });

  it('fails closed when retrieval depth cannot support the committed comparison', async () => {
    const run = await runDemoWorkflow({
      workflow: 'compare',
      focus: 'Compare Atlas and Beacon on cost, availability, and resilience.',
      documentIds: ['atlas-service-proposal', 'beacon-service-proposal'],
      topK: 4,
    });

    expect(run.status).toBe('evidence_gap');
    expect(run.evidenceGap).toContain('retrieval depth 4');
  });

  it('honors brief audience and maximum points in a supported fixture', async () => {
    const run = await runDemoWorkflow({
      workflow: 'brief',
      objective: 'Summarize Q3 performance, decisions, risks, owners, and next milestones.',
      audience: 'Audit committee',
      maxPoints: 2,
      documentIds: ['q3-operating-review'],
      topK: 4,
    });

    expect(run).toMatchObject({ status: 'completed', verified: true });
    expect(run.answer).toContain('Audience: Audit committee.');
    expect(run.answer.match(/^•/gm)).toHaveLength(2);
    expect(run.citations).toHaveLength(2);
    expect(run.steps.find((step) => step.name === 'retrieve')?.detail).toEqual({
      requested_top_k: 4,
      selected_document_ids: ['q3-operating-review'],
    });
  });

  it('rejects unknown snapshot run identifiers', () => {
    expect(() => getDemoRun('demo-run-missing')).toThrow(/not part of the committed snapshot/i);
  });
});
