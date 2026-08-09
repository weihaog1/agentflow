export type ConnectionMode = 'checking' | 'live' | 'demo';

export type WorkflowKind = 'question' | 'compare' | 'brief';

export type DocumentStatus =
  | 'uploading'
  | 'pending'
  | 'processing'
  | 'queued'
  | 'retrying'
  | 'downloading'
  | 'parsing'
  | 'chunking'
  | 'embedding'
  | 'indexing'
  | 'ready'
  | 'failed'
  | 'unknown';

export type JobStatus =
  | 'pending'
  | 'running'
  | 'retrying'
  | 'completed'
  | 'failed'
  | 'unknown';

export type IngestionStage =
  | 'pending'
  | 'downloading'
  | 'parsing'
  | 'chunking'
  | 'embedding'
  | 'indexing'
  | 'ready'
  | 'failed'
  | 'unknown';

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export interface IngestionJob {
  id: string;
  workspaceId: string;
  documentId: string;
  documentVersionId: string;
  status: JobStatus;
  stage: IngestionStage;
  attempt: number;
  maxAttempts: number;
  nextAttemptAt: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
}

export interface DocumentRecord {
  id: string;
  title: string;
  fileName: string;
  status: DocumentStatus;
  mimeType: string | null;
  sizeBytes: number | null;
  chunkCount: number | null;
  pageCount: number | null;
  version: number | string | null;
  createdAt: string;
  updatedAt: string;
  error: string | null;
  ingestionJob?: IngestionJob | null;
}

export interface DocumentCollection {
  documents: DocumentRecord[];
  corpusRevision: number | string | null;
}

export type CitationLocator =
  | string
  | { [key: string]: JsonValue }
  | null;

export interface Citation {
  id: string;
  chunkId: string;
  documentId: string;
  documentVersionId: string | null;
  documentTitle: string;
  chunkOrdinal: number | null;
  quote: string;
  locator: CitationLocator;
  score: number | null;
}

export type RunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'evidence_gap'
  | 'unknown';

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'unknown';

export interface RunStep {
  name: string;
  status: StepStatus;
  reportedStatus: string | null;
  latencyMs: number | null;
  detail: JsonValue | null;
}

export interface RunMetrics {
  totalLatencyMs: number | null;
  retrievalLatencyMs: number | null;
  reasoningLatencyMs: number | null;
  citationCoverage: number | null;
  tokens: number | null;
  evidenceCount: number | null;
}

export interface WorkflowRun {
  id: string;
  workflow: WorkflowKind;
  status: RunStatus;
  reportedStatus: string | null;
  corpusRevision: number | string | null;
  cached: boolean;
  verified: boolean;
  answer: string;
  citations: Citation[];
  evidenceGap: string | null;
  metrics: RunMetrics;
  steps: RunStep[];
  createdAt: string;
  completedAt: string | null;
}

export interface RunSummary {
  id: string;
  workflow: WorkflowKind;
  status: RunStatus;
  reportedStatus: string | null;
  cached: boolean;
  citationCount: number;
  totalLatencyMs: number | null;
  createdAt: string;
}

export interface UploadReceipt {
  document: DocumentRecord;
  jobId: string | null;
  job: IngestionJob | null;
}

export interface BaseWorkflowInput {
  documentIds: string[];
  topK: number;
}

export interface QuestionInput extends BaseWorkflowInput {
  workflow: 'question';
  question: string;
}

export interface CompareInput extends BaseWorkflowInput {
  workflow: 'compare';
  focus: string;
}

export interface BriefInput extends BaseWorkflowInput {
  workflow: 'brief';
  objective: string;
  audience: string;
  maxPoints: number;
}

export type WorkflowInput = QuestionInput | CompareInput | BriefInput;
