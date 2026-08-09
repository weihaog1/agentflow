import type {
  Citation,
  DocumentCollection,
  RunSummary,
  WorkflowInput,
  WorkflowRun,
} from '../types';

const snapshotTime = '2026-08-09T16:28:00.000Z';

const fixturePrompts = {
  question: "What are Northstar's deletion timelines and exceptions?",
  compare: 'Compare Atlas and Beacon on cost, availability, and resilience.',
  brief: 'Summarize Q3 performance, decisions, risks, owners, and next milestones.',
} as const;

export const demoCollection: DocumentCollection = {
  corpusRevision: '2026-08-09.1',
  documents: [
    {
      id: 'northstar-security-standard',
      title: 'Northstar Security Standard',
      fileName: 'northstar-security-standard.md',
      status: 'ready',
      mimeType: 'text/markdown',
      sizeBytes: 1_315,
      chunkCount: 6,
      pageCount: null,
      version: 3,
      createdAt: '2026-08-09T15:14:00.000Z',
      updatedAt: '2026-08-09T15:14:18.000Z',
      error: null,
    },
    {
      id: 'northstar-retention-schedule',
      title: 'Northstar Retention Schedule',
      fileName: 'northstar-retention-schedule.md',
      status: 'ready',
      mimeType: 'text/markdown',
      sizeBytes: 1_049,
      chunkCount: 5,
      pageCount: null,
      version: 2,
      createdAt: '2026-08-09T15:16:00.000Z',
      updatedAt: '2026-08-09T15:16:16.000Z',
      error: null,
    },
    {
      id: 'atlas-service-proposal',
      title: 'Atlas Service Proposal',
      fileName: 'atlas-service-proposal.md',
      status: 'ready',
      mimeType: 'text/markdown',
      sizeBytes: 1_044,
      chunkCount: 6,
      pageCount: null,
      version: 1,
      createdAt: '2026-08-09T15:18:00.000Z',
      updatedAt: '2026-08-09T15:18:14.000Z',
      error: null,
    },
    {
      id: 'beacon-service-proposal',
      title: 'Beacon Service Proposal',
      fileName: 'beacon-service-proposal.md',
      status: 'ready',
      mimeType: 'text/markdown',
      sizeBytes: 1_064,
      chunkCount: 6,
      pageCount: null,
      version: 1,
      createdAt: '2026-08-09T15:20:00.000Z',
      updatedAt: '2026-08-09T15:20:15.000Z',
      error: null,
    },
    {
      id: 'q3-operating-review',
      title: 'Q3 Operating Review',
      fileName: 'q3-operating-review.md',
      status: 'ready',
      mimeType: 'text/markdown',
      sizeBytes: 1_175,
      chunkCount: 5,
      pageCount: null,
      version: 4,
      createdAt: '2026-08-09T15:22:00.000Z',
      updatedAt: '2026-08-09T15:22:17.000Z',
      error: null,
    },
  ],
};

const retentionCitations: Citation[] = [
  citation(
    'RET-01',
    'northstar-retention-schedule',
    'Northstar Retention Schedule',
    1,
    'Source files remain available for the active contract term. When a contract ends, source files enter a 30-day recovery window and are then queued for deletion.',
    'Active customer content',
    0.97,
  ),
  citation(
    'RET-02',
    'northstar-retention-schedule',
    'Northstar Retention Schedule',
    3,
    'An approved deletion request bypasses the normal recovery window. Northstar completes deletion from active systems within 14 calendar days. Encrypted backups expire through normal rotation within 35 days.',
    'Deletion requests',
    0.96,
  ),
  citation(
    'RET-03',
    'northstar-retention-schedule',
    'Northstar Retention Schedule',
    2,
    'Extracted text, chunks, embeddings, and generated workflow artifacts are deleted within 90 days after contract termination unless a shorter written schedule applies.',
    'Derived workflow data',
    0.93,
  ),
  citation(
    'RET-04',
    'northstar-retention-schedule',
    'Northstar Retention Schedule',
    4,
    'Security logs follow the 400-day period in the Northstar Security Standard. Operational application logs are retained for 30 days. A documented legal hold pauses deletion only for the records named in the hold.',
    'Logs and legal holds',
    0.9,
  ),
];

const comparisonCitations: Citation[] = [
  citation(
    'ATL-01',
    'atlas-service-proposal',
    'Atlas Service Proposal',
    1,
    'The annual subscription is $125,000 for up to 250 named operators. Standard implementation is included. The proposed initial term is 24 months.',
    'Commercial terms',
    0.96,
  ),
  citation(
    'BCN-01',
    'beacon-service-proposal',
    'Beacon Service Proposal',
    1,
    'The annual subscription is $98,000 for up to 250 named operators. A separate $18,000 implementation fee applies. The proposed initial term is 12 months.',
    'Commercial terms',
    0.95,
  ),
  citation(
    'ATL-02',
    'atlas-service-proposal',
    'Atlas Service Proposal',
    2,
    'Atlas commits to 99.95 percent monthly service availability. Planned maintenance is excluded only when Atlas gives seven days of notice, and the exclusion is limited to four hours per month.',
    'Availability',
    0.94,
  ),
  citation(
    'BCN-02',
    'beacon-service-proposal',
    'Beacon Service Proposal',
    2,
    'Beacon commits to 99.9 percent monthly service availability. Planned maintenance is excluded when Beacon gives three days of notice, with an exclusion limit of eight hours per month.',
    'Availability',
    0.93,
  ),
  citation(
    'ATL-03',
    'atlas-service-proposal',
    'Atlas Service Proposal',
    4,
    'The proposed deployment stores customer content only in the United States. The disaster recovery target is a four-hour recovery time objective and a one-hour recovery point objective.',
    'Resilience and location',
    0.91,
  ),
  citation(
    'BCN-03',
    'beacon-service-proposal',
    'Beacon Service Proposal',
    4,
    'The customer may select United States or European Union storage. The disaster recovery target is an eight-hour recovery time objective and a four-hour recovery point objective.',
    'Resilience and location',
    0.9,
  ),
];

const reviewCitations: Citation[] = [
  citation(
    'Q3-01',
    'q3-operating-review',
    'Q3 Operating Review',
    1,
    'The ingestion pilot processed 18,400 documents, compared with the quarterly target of 20,000. Citation review passed for 96 percent of sampled answers, above the 95 percent quality gate. Median ingestion latency was 7.8 minutes, compared with the 6-minute target.',
    'Progress',
    0.98,
  ),
  citation(
    'Q3-02',
    'q3-operating-review',
    'Q3 Operating Review',
    2,
    'The team approved a two-week extension for the ingestion latency work. The vendor decision remains open until Legal completes the availability and retention comparison. The team kept the September 15 operator pilot date.',
    'Decisions',
    0.95,
  ),
  citation(
    'Q3-03',
    'q3-operating-review',
    'Q3 Operating Review',
    3,
    'The largest delivery risk is delayed access to the final source archive. The owner is Priya Shah, and the mitigation deadline is August 20. A second risk is a capacity shortfall during reindexing; the owner is Mateo Ruiz, and the mitigation is a load test by August 14.',
    'Risks',
    0.94,
  ),
  citation(
    'Q3-04',
    'q3-operating-review',
    'Q3 Operating Review',
    4,
    'The reindexing load test is due August 14. Source archive access is due August 20. Operator training begins September 8, and the operator pilot begins September 15.',
    'Next milestones',
    0.92,
  ),
];

const trace = [
  { name: 'normalize', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 7, detail: 'Input normalized' },
  { name: 'cache_lookup', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 5, detail: 'Verified cache miss' },
  { name: 'retrieve', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 184, detail: '8 evidence chunks retrieved' },
  { name: 'reason', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 722, detail: 'Bounded answer artifact created' },
  { name: 'verify', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 43, detail: 'Citations verified' },
  { name: 'cache_write', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 6, detail: 'Verified result cached' },
];

const questionRun: WorkflowRun = createRun({
  id: 'demo-run-q-1042',
  workflow: 'question',
  answer:
    'At contract end, source files enter a 30-day recovery window before deletion is queued [1]. An approved deletion request bypasses that window: active systems are cleared within 14 calendar days, while encrypted backups expire within 35 days [2].\n\nDerived workflow data, including chunks, embeddings, and generated artifacts, is deleted within 90 days unless a shorter schedule applies [3]. Legal holds pause deletion only for the records named in the hold, and security logs remain subject to the separate 400-day retention period [4].',
  citations: retentionCitations,
  totalLatencyMs: 967,
});

const compareRun: WorkflowRun = createRun({
  id: 'demo-run-c-1038',
  workflow: 'compare',
  cached: true,
  answer:
    'Atlas costs $125,000 annually with implementation included and proposes a 24-month term [1]. Beacon costs $98,000 annually plus an $18,000 implementation fee, with a shorter 12-month term [2].\n\nAtlas offers the stronger availability commitment at 99.95 percent, seven days notice for planned maintenance, and a four-hour monthly exclusion cap [3]. Beacon offers 99.9 percent, three days notice, and an eight-hour exclusion cap [4].\n\nAtlas has the stronger recovery targets at four-hour RTO and one-hour RPO, but supports only United States storage [5]. Beacon allows United States or European Union storage, with weaker eight-hour RTO and four-hour RPO targets [6].',
  citations: comparisonCitations,
  totalLatencyMs: 24,
});

const briefRun: WorkflowRun = createRun({
  id: 'demo-run-b-1034',
  workflow: 'brief',
  answer:
    '• Performance: 18,400 documents were processed against a 20,000 target. Citation review cleared the quality gate at 96 percent, while 7.8-minute median ingestion latency missed the 6-minute target [1].\n• Decision: the team approved a two-week latency extension, left the vendor choice open pending Legal review, and kept the September 15 pilot date [2].\n• Risks: Priya Shah owns source archive access due August 20. Mateo Ruiz owns the reindexing load test due August 14 [3].\n• Next: begin operator training September 8, then launch the pilot September 15 [4].',
  citations: reviewCitations,
  totalLatencyMs: 1_214,
});

export const demoRuns: RunSummary[] = [
  toSummary(questionRun),
  toSummary(compareRun),
  toSummary(briefRun),
];

export async function runDemoWorkflow(input: WorkflowInput): Promise<WorkflowRun> {
  await new Promise((resolve) => window.setTimeout(resolve, 520));
  const base = {
    question: questionRun,
    compare: compareRun,
    brief: briefRun,
  }[input.workflow];
  const selectedIds = input.documentIds.length > 0
    ? input.documentIds
    : demoCollection.documents.map((document) => document.id);
  const requiredDocuments = {
    question: ['northstar-retention-schedule'],
    compare: ['atlas-service-proposal', 'beacon-service-proposal'],
    brief: ['q3-operating-review'],
  }[input.workflow];
  const prompt = input.workflow === 'question'
    ? input.question
    : input.workflow === 'compare'
      ? input.focus
      : input.objective;
  const issues: string[] = [];

  if (prompt.trim() !== fixturePrompts[input.workflow]) {
    issues.push(`this committed fixture supports only: "${fixturePrompts[input.workflow]}"`);
  }
  const missingDocuments = requiredDocuments.filter((documentId) => !selectedIds.includes(documentId));
  if (missingDocuments.length > 0) {
    issues.push(`the selected scope excludes ${missingDocuments.join(', ')}`);
  }

  const answerLines = input.workflow === 'brief'
    ? base.answer.split('\n').slice(0, input.maxPoints)
    : base.answer.split('\n');
  const neededCitations = input.workflow === 'brief'
    ? base.citations.slice(0, answerLines.length)
    : base.citations;
  if (input.topK < neededCitations.length) {
    issues.push(`retrieval depth ${input.topK} is below the ${neededCitations.length} excerpts required by this fixture`);
  }

  if (issues.length > 0) return createEvidenceGap(input, issues);

  const answer = input.workflow === 'brief'
    ? `Audience: ${input.audience.trim() || 'Not specified'}.\n${answerLines.join('\n')}`
    : base.answer;
  return {
    ...base,
    answer,
    citations: neededCitations,
    metrics: {
      ...base.metrics,
      evidenceCount: neededCitations.length,
      citationCoverage: neededCitations.length > 0 ? 1 : 0,
    },
    steps: base.steps.map((step) => step.name === 'retrieve'
      ? {
          ...step,
          detail: {
            requested_top_k: input.topK,
            selected_document_ids: selectedIds,
          },
        }
      : step),
    createdAt: new Date().toISOString(),
  };
}

export function getDemoRun(runId: string): WorkflowRun {
  const run = [questionRun, compareRun, briefRun].find((item) => item.id === runId);
  if (!run) throw new Error(`Demo run ${runId} is not part of the committed snapshot.`);
  return run;
}

function createEvidenceGap(input: WorkflowInput, issues: string[]): WorkflowRun {
  return {
    id: `demo-gap-${input.workflow}`,
    workflow: input.workflow,
    status: 'evidence_gap',
    reportedStatus: 'evidence_gap',
    corpusRevision: demoCollection.corpusRevision,
    cached: false,
    verified: false,
    answer: 'The local snapshot did not produce an answer because the requested scope does not match its committed fixture.',
    citations: [],
    evidenceGap: `No simulated result was substituted. ${issues.join('; ')}.`,
    metrics: {
      totalLatencyMs: 12,
      retrievalLatencyMs: 0,
      reasoningLatencyMs: 0,
      citationCoverage: 0,
      tokens: 0,
      evidenceCount: 0,
    },
    steps: [
      {
        name: 'normalize',
        status: 'completed',
        reportedStatus: 'completed',
        latencyMs: 4,
        detail: {
          requested_top_k: input.topK,
          selected_document_ids: input.documentIds,
        },
      },
      {
        name: 'fixture_guard',
        status: 'failed',
        reportedStatus: 'failed',
        latencyMs: 8,
        detail: { reasons: issues },
      },
    ],
    createdAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
  };
}

function citation(
  id: string,
  documentId: string,
  documentTitle: string,
  chunkOrdinal: number,
  quote: string,
  section: string,
  score: number,
): Citation {
  return {
    id,
    chunkId: `${documentId}-chunk-${chunkOrdinal}`,
    documentId,
    documentVersionId: `${documentId}-version`,
    documentTitle,
    chunkOrdinal,
    quote,
    locator: { section },
    score,
  };
}

function createRun(input: {
  id: string;
  workflow: WorkflowRun['workflow'];
  answer: string;
  citations: Citation[];
  totalLatencyMs: number;
  cached?: boolean;
}): WorkflowRun {
  const cached = input.cached ?? false;
  const steps = cached
    ? [
        { name: 'normalize', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 6, detail: 'Input normalized' },
        { name: 'cache_lookup', status: 'completed' as const, reportedStatus: 'completed', latencyMs: 18, detail: 'Verified cache hit' },
        { name: 'retrieve', status: 'skipped' as const, reportedStatus: 'skipped', latencyMs: 0, detail: 'Cached evidence reused' },
        { name: 'reason', status: 'skipped' as const, reportedStatus: 'skipped', latencyMs: 0, detail: 'Cached artifact reused' },
        { name: 'verify', status: 'skipped' as const, reportedStatus: 'skipped', latencyMs: 0, detail: 'Previously verified result' },
      ]
    : trace;

  return {
    id: input.id,
    workflow: input.workflow,
    status: 'completed',
    reportedStatus: 'completed',
    corpusRevision: demoCollection.corpusRevision,
    cached,
    verified: true,
    answer: input.answer,
    citations: input.citations,
    evidenceGap: null,
    metrics: {
      totalLatencyMs: input.totalLatencyMs,
      retrievalLatencyMs: cached ? 0 : 184,
      reasoningLatencyMs: cached ? 0 : input.totalLatencyMs - 245,
      citationCoverage: 1,
      tokens: input.workflow === 'brief' ? 1_416 : 1_184,
      evidenceCount: input.citations.length,
    },
    steps,
    createdAt: snapshotTime,
    completedAt: snapshotTime,
  };
}

function toSummary(run: WorkflowRun): RunSummary {
  return {
    id: run.id,
    workflow: run.workflow,
    status: run.status,
    reportedStatus: run.reportedStatus,
    cached: run.cached,
    citationCount: run.citations.length,
    totalLatencyMs: run.metrics.totalLatencyMs,
    createdAt: run.createdAt,
  };
}
