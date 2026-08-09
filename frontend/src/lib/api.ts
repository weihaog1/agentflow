import type {
  Citation,
  DocumentCollection,
  DocumentRecord,
  DocumentStatus,
  IngestionJob,
  IngestionStage,
  JobStatus,
  JsonValue,
  RunMetrics,
  RunStatus,
  RunStep,
  RunSummary,
  StepStatus,
  UploadReceipt,
  WorkflowInput,
  WorkflowKind,
  WorkflowRun,
} from '../types';

const DEFAULT_API_BASE = '/api/v1';
const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;

type JsonRecord = Record<string, unknown>;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly code: string | null;
  readonly details: JsonValue | null;
  readonly requestId: string | null;

  constructor(
    status: number,
    detail: string,
    code: string | null = null,
    details: JsonValue | null = null,
    requestId: string | null = null,
  ) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export class AgentFlowApi {
  readonly baseUrl: string;
  readonly requestTimeoutMs: number;

  constructor(
    baseUrl = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE,
    requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  ) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.requestTimeoutMs = requestTimeoutMs;
  }

  async listDocuments(workspaceId: string, signal?: AbortSignal): Promise<DocumentCollection> {
    const payload = await this.request<unknown>(
      `/documents?workspace_id=${encodeURIComponent(workspaceId)}`,
      { signal },
    );
    const record = asRecord(payload);
    const rawDocuments = Array.isArray(payload)
      ? payload
      : arrayFrom(record, 'documents', 'items');

    return {
      documents: rawDocuments.map((document) => normalizeDocument(document)),
      corpusRevision: scalarFrom(record, 'corpus_revision', 'revision'),
    };
  }

  async uploadDocument(
    file: File,
    workspaceId: string,
    title?: string,
  ): Promise<UploadReceipt> {
    const body = new FormData();
    body.set('file', file);
    body.set('workspace_id', workspaceId);
    if (title?.trim()) body.set('title', title.trim());

    const payload = asRecord(
      await this.request<unknown>('/documents', { method: 'POST', body }),
    );
    const documentPayload = payload.document ?? payload;
    const version = asRecord(payload.version);
    const job = asRecord(payload.job);
    const normalizedJob = Object.keys(job).length > 0 ? normalizeJob(job) : null;

    return {
      document: normalizeDocument(documentPayload, version, normalizedJob),
      jobId: normalizedJob?.id ?? (stringFrom(payload, 'job_id') || null),
      job: normalizedJob,
    };
  }

  async getDocument(
    workspaceId: string,
    documentId: string,
    signal?: AbortSignal,
  ): Promise<DocumentRecord> {
    const payload = await this.request<unknown>(
      `/documents/${encodeURIComponent(documentId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
      { signal },
    );
    return normalizeDocument(payload);
  }

  async getJob(
    workspaceId: string,
    jobId: string,
    signal?: AbortSignal,
  ): Promise<IngestionJob> {
    const payload = await this.request<unknown>(
      `/jobs/${encodeURIComponent(jobId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
      { signal },
    );
    return normalizeJob(payload);
  }

  async runWorkflow(
    workspaceId: string,
    input: WorkflowInput,
  ): Promise<WorkflowRun> {
    const { workflow, documentIds, topK } = input;
    let requestBody: JsonRecord;

    if (input.workflow === 'question') {
      requestBody = {
        workspace_id: workspaceId,
        question: input.question,
        document_ids: documentIds.length > 0 ? documentIds : undefined,
        top_k: topK,
      };
    } else if (input.workflow === 'compare') {
      requestBody = {
        workspace_id: workspaceId,
        document_ids: documentIds,
        focus: input.focus || undefined,
        top_k: topK,
      };
    } else {
      requestBody = {
        workspace_id: workspaceId,
        document_ids: documentIds.length > 0 ? documentIds : undefined,
        objective: input.objective || undefined,
        audience: input.audience || undefined,
        max_points: input.maxPoints,
        top_k: topK,
      };
    }

    const payload = await this.request<unknown>(`/workflows/${workflow}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });
    return normalizeRun(payload);
  }

  async listRuns(workspaceId: string, limit = 8, signal?: AbortSignal): Promise<RunSummary[]> {
    const payload = await this.request<unknown>(
      `/runs?workspace_id=${encodeURIComponent(workspaceId)}&limit=${limit}`,
      { signal },
    );
    const record = asRecord(payload);
    const rawRuns = Array.isArray(payload) ? payload : arrayFrom(record, 'runs', 'items');
    return rawRuns.map(normalizeRunSummary);
  }

  async getRun(
    workspaceId: string,
    runId: string,
    signal?: AbortSignal,
  ): Promise<WorkflowRun> {
    const payload = await this.request<unknown>(
      `/runs/${encodeURIComponent(runId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
      { signal },
    );
    return normalizeRun(payload);
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    let timedOut = false;
    const externalSignal = init.signal;
    const abortFromCaller = () => controller.abort(externalSignal?.reason);
    if (externalSignal?.aborted) abortFromCaller();
    else externalSignal?.addEventListener('abort', abortFromCaller, { once: true });
    const timeout = globalThis.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, this.requestTimeoutMs);

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          ...init.headers,
        },
      });

      if (!response.ok) {
        const error = await readErrorPayload(response);
        if (timedOut) {
          throw new ApiError(0, 'The AgentFlow API request timed out.', 'REQUEST_TIMEOUT');
        }
        throw new ApiError(
          response.status,
          error.message,
          error.code,
          error.details,
          error.requestId,
        );
      }

      if (response.status === 204) return undefined as T;
      return await response.json() as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (timedOut) {
        throw new ApiError(0, 'The AgentFlow API request timed out.', 'REQUEST_TIMEOUT');
      }
      if (externalSignal?.aborted) {
        throw new ApiError(0, 'The AgentFlow API request was cancelled.', 'REQUEST_CANCELLED');
      }
      if (error instanceof SyntaxError) {
        throw new ApiError(0, 'The AgentFlow API returned invalid JSON.', 'INVALID_RESPONSE');
      }
      throw new ApiError(0, 'The AgentFlow API could not be reached.', 'NETWORK_ERROR');
    } finally {
      globalThis.clearTimeout(timeout);
      externalSignal?.removeEventListener('abort', abortFromCaller);
    }
  }
}

async function readErrorPayload(response: Response): Promise<{
  message: string;
  code: string | null;
  details: JsonValue | null;
  requestId: string | null;
}> {
  try {
    const payload = asRecord(await response.json());
    const envelope = asRecord(payload.error);
    const message = stringFrom(envelope, 'message');
    if (message) {
      return {
        message,
        code: stringFrom(envelope, 'code') || null,
        details: normalizeJsonValue(envelope.details),
        requestId: stringFrom(envelope, 'request_id') || null,
      };
    }

    const detail = payload.detail;
    if (typeof detail === 'string') {
      return { message: detail, code: null, details: null, requestId: null };
    }
    if (Array.isArray(detail)) {
      const validationMessage = detail
        .map((item) => stringFrom(asRecord(item), 'msg', 'message'))
        .filter(Boolean)
        .join(', ');
      if (validationMessage) {
        return {
          message: validationMessage,
          code: 'VALIDATION_ERROR',
          details: normalizeJsonValue(detail),
          requestId: null,
        };
      }
    }
  } catch {
    // The response may not contain JSON.
  }
  return {
    message: `Request failed with status ${response.status}.`,
    code: null,
    details: null,
    requestId: null,
  };
}

function normalizeDocument(
  value: unknown,
  versionValue: unknown = null,
  ingestionJob: IngestionJob | null = null,
): DocumentRecord {
  const record = asRecord(value);
  const version = asRecord(versionValue);
  const status = normalizeDocumentStatus(stringFrom(record, 'status', 'ingestion_status'));
  const createdAt = stringFrom(record, 'created_at', 'createdAt') || new Date(0).toISOString();

  return {
    id: stringFrom(record, 'id', 'document_id') || crypto.randomUUID(),
    title:
      stringFrom(record, 'title', 'display_name', 'filename', 'file_name') ||
      'Untitled document',
    fileName: stringFrom(record, 'filename', 'file_name', 'title') || 'Untitled document',
    status,
    mimeType: stringFrom(record, 'mime_type', 'media_type', 'content_type') || stringFrom(version, 'media_type') || null,
    sizeBytes: numberFrom(record, 'size_bytes', 'byte_size') ?? numberFrom(version, 'size_bytes'),
    chunkCount: numberFrom(record, 'chunk_count', 'chunks'),
    pageCount: numberFrom(record, 'page_count', 'pages'),
    version: scalarFrom(record, 'version', 'version_number') ?? scalarFrom(version, 'version_number'),
    createdAt,
    updatedAt: stringFrom(record, 'updated_at', 'updatedAt') || createdAt,
    error: stringFrom(record, 'error', 'failure_reason') || null,
    ingestionJob,
  };
}

function normalizeJob(value: unknown): IngestionJob {
  const record = asRecord(value);
  return {
    id: stringFrom(record, 'id', 'job_id') || crypto.randomUUID(),
    workspaceId: stringFrom(record, 'workspace_id'),
    documentId: stringFrom(record, 'document_id'),
    documentVersionId: stringFrom(record, 'document_version_id'),
    status: normalizeJobStatus(stringFrom(record, 'status')),
    stage: normalizeIngestionStage(stringFrom(record, 'stage')),
    attempt: numberFrom(record, 'attempt') ?? 0,
    maxAttempts: numberFrom(record, 'max_attempts') ?? 0,
    nextAttemptAt: stringFrom(record, 'next_attempt_at') || null,
    errorCode: stringFrom(record, 'error_code') || null,
    errorMessage: stringFrom(record, 'error_message') || null,
    createdAt: stringFrom(record, 'created_at') || new Date(0).toISOString(),
    updatedAt: stringFrom(record, 'updated_at') || new Date(0).toISOString(),
    completedAt: stringFrom(record, 'completed_at') || null,
  };
}

function normalizeRun(value: unknown): WorkflowRun {
  const record = asRecord(value);
  const citations = arrayFrom(record, 'citations').map(normalizeCitation);
  const metrics = normalizeMetrics(record.metrics);
  const result = record.result;
  const runId = stringFrom(record, 'run_id', 'id') || crypto.randomUUID();
  const createdAt = stringFrom(record, 'created_at') || new Date().toISOString();
  const reportedStatus = stringFrom(record, 'status') || null;
  const status = normalizeRunStatus(reportedStatus ?? '');

  return {
    id: runId,
    workflow: normalizeWorkflow(stringFrom(record, 'workflow', 'workflow_type')),
    status,
    reportedStatus,
    corpusRevision: scalarFrom(record, 'corpus_revision'),
    cached: Boolean(record.cached ?? record.cache_hit),
    verified: record.verified === true && status === 'completed',
    answer: extractAnswer(result),
    citations,
    evidenceGap: extractEvidenceGap(record.evidence_gap),
    metrics: {
      ...metrics,
      evidenceCount: metrics.evidenceCount ?? citations.length,
    },
    steps: arrayFrom(record, 'steps', 'trace').map(normalizeStep),
    createdAt,
    completedAt: stringFrom(record, 'completed_at') || null,
  };
}

function normalizeRunSummary(value: unknown): RunSummary {
  const record = asRecord(value);
  const metrics = normalizeMetrics(record.metrics);
  const citations = arrayFrom(record, 'citations');
  const reportedStatus = stringFrom(record, 'status') || null;

  return {
    id: stringFrom(record, 'run_id', 'id') || crypto.randomUUID(),
    workflow: normalizeWorkflow(stringFrom(record, 'workflow', 'workflow_type')),
    status: normalizeRunStatus(reportedStatus ?? ''),
    reportedStatus,
    cached: Boolean(record.cached ?? record.cache_hit),
    citationCount:
      numberFrom(record, 'citation_count') ?? citations.length,
    totalLatencyMs:
      numberFrom(record, 'total_latency_ms', 'latency_ms') ?? metrics.totalLatencyMs,
    createdAt: stringFrom(record, 'created_at') || new Date(0).toISOString(),
  };
}

function normalizeCitation(value: unknown): Citation {
  const record = asRecord(value);
  return {
    id: stringFrom(record, 'citation_id', 'id') || crypto.randomUUID(),
    chunkId: stringFrom(record, 'chunk_id') || 'unknown-chunk',
    documentId: stringFrom(record, 'document_id') || 'unknown-document',
    documentVersionId: stringFrom(record, 'document_version_id') || null,
    documentTitle:
      stringFrom(record, 'document_title', 'title', 'document_name') || 'Untitled document',
    chunkOrdinal: numberFrom(record, 'chunk_ordinal', 'ordinal'),
    quote: stringFrom(record, 'quote', 'excerpt', 'text') || 'Excerpt unavailable.',
    locator: normalizeLocator(record.locator),
    score: numberFrom(record, 'score', 'relevance_score'),
  };
}

function normalizeMetrics(value: unknown): RunMetrics {
  const record = asRecord(value);
  return {
    totalLatencyMs: numberFrom(record, 'total_latency_ms', 'latency_ms'),
    retrievalLatencyMs: numberFrom(record, 'retrieval_latency_ms'),
    reasoningLatencyMs: numberFrom(record, 'reasoning_latency_ms', 'generation_latency_ms'),
    citationCoverage: numberFrom(record, 'citation_coverage'),
    tokens: numberFrom(record, 'tokens', 'token_count', 'total_tokens'),
    evidenceCount: numberFrom(record, 'evidence_count'),
  };
}

function normalizeStep(value: unknown): RunStep {
  const record = asRecord(value);
  const reportedStatus = stringFrom(record, 'status') || null;
  return {
    name: stringFrom(record, 'name', 'step') || 'unknown_step',
    status: normalizeStepStatus(reportedStatus ?? ''),
    reportedStatus,
    latencyMs: numberFrom(record, 'latency_ms'),
    detail: normalizeJsonValue(record.detail ?? record.summary),
  };
}

function extractAnswer(value: unknown): string {
  if (typeof value === 'string') return value;
  const record = asRecord(value);
  const direct = stringFrom(record, 'answer', 'summary', 'brief', 'comparison', 'text');
  if (direct) return direct;

  const points = record.points;
  if (Array.isArray(points)) {
    return points
      .map((point) => (typeof point === 'string' ? point : stringFrom(asRecord(point), 'text', 'claim')))
      .filter(Boolean)
      .map((point) => `• ${point}`)
      .join('\n');
  }
  return 'The run completed, but no displayable result was returned.';
}

function extractEvidenceGap(value: unknown): string | null {
  if (typeof value === 'string') return value;
  const record = asRecord(value);
  return stringFrom(record, 'message', 'detail', 'reason') || null;
}

function normalizeLocator(value: unknown): Citation['locator'] {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return normalizeJsonValue(value) as Citation['locator'];
}

function normalizeWorkflow(value: string): WorkflowKind {
  if (value === 'compare' || value === 'comparison') return 'compare';
  if (value === 'brief' || value === 'executive_brief') return 'brief';
  return 'question';
}

function normalizeDocumentStatus(value: string): DocumentStatus {
  const allowed: DocumentStatus[] = [
    'uploading',
    'pending',
    'processing',
    'queued',
    'retrying',
    'downloading',
    'parsing',
    'chunking',
    'embedding',
    'indexing',
    'ready',
    'failed',
    'unknown',
  ];
  return allowed.includes(value as DocumentStatus) ? (value as DocumentStatus) : 'unknown';
}

function normalizeRunStatus(value: string): RunStatus {
  const allowed: RunStatus[] = ['queued', 'running', 'completed', 'failed', 'evidence_gap'];
  return allowed.includes(value as RunStatus) ? (value as RunStatus) : 'unknown';
}

function normalizeStepStatus(value: string): StepStatus {
  const allowed: StepStatus[] = ['pending', 'running', 'completed', 'failed', 'skipped'];
  return allowed.includes(value as StepStatus) ? (value as StepStatus) : 'unknown';
}

function normalizeJobStatus(value: string): JobStatus {
  const allowed: JobStatus[] = ['pending', 'running', 'retrying', 'completed', 'failed'];
  return allowed.includes(value as JobStatus) ? (value as JobStatus) : 'unknown';
}

function normalizeIngestionStage(value: string): IngestionStage {
  const allowed: IngestionStage[] = [
    'pending',
    'downloading',
    'parsing',
    'chunking',
    'embedding',
    'indexing',
    'ready',
    'failed',
  ];
  return allowed.includes(value as IngestionStage) ? (value as IngestionStage) : 'unknown';
}

function normalizeJsonValue(value: unknown, depth = 0): JsonValue | null {
  if (value === null) return null;
  if (typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (depth >= 12) return '[nested value omitted]';
  if (Array.isArray(value)) {
    return value.map((entry) => normalizeJsonValue(entry, depth + 1));
  }
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, normalizeJsonValue(entry, depth + 1)]),
    );
  }
  return null;
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function arrayFrom(record: JsonRecord, ...keys: string[]): unknown[] {
  for (const key of keys) {
    if (Array.isArray(record[key])) return record[key];
  }
  return [];
}

function stringFrom(record: JsonRecord, ...keys: string[]): string {
  for (const key of keys) {
    if (typeof record[key] === 'string') return record[key];
  }
  return '';
}

function numberFrom(record: JsonRecord, ...keys: string[]): number | null {
  for (const key of keys) {
    if (typeof record[key] === 'number' && Number.isFinite(record[key])) return record[key];
  }
  return null;
}

function scalarFrom(record: JsonRecord, ...keys: string[]): number | string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' || typeof value === 'string') return value;
  }
  return null;
}

export const api = new AgentFlowApi();
