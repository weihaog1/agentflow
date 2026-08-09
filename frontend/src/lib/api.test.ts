import { describe, expect, it, vi } from 'vitest';
import { AgentFlowApi, ApiError } from './api';

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('AgentFlowApi', () => {
  it('loads and normalizes the document collection contract', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      corpus_revision: 'rev-9',
      documents: [
        {
          document_id: 'doc-1',
          title: 'Security Standard',
          filename: 'security.md',
          status: 'ready',
          mime_type: 'text/markdown',
          size_bytes: 640,
          chunk_count: 4,
          version_number: 3,
          created_at: '2026-08-09T12:00:00Z',
        },
      ],
    }));
    vi.stubGlobal('fetch', fetchMock);

    const client = new AgentFlowApi('/api/v1');
    const collection = await client.listDocuments('default');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/documents?workspace_id=default',
      expect.objectContaining({ headers: expect.objectContaining({ Accept: 'application/json' }) }),
    );
    expect(collection.corpusRevision).toBe('rev-9');
    expect(collection.documents[0]).toMatchObject({
      id: 'doc-1',
      fileName: 'security.md',
      status: 'ready',
      version: 3,
    });
  });

  it('sends the comparison workflow using the planned FastAPI schema', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      run_id: 'run-7',
      workflow: 'compare',
      status: 'completed',
      verified: true,
      corpus_revision: 4,
      cached: false,
      result: { comparison: 'Atlas is more resilient [1].' },
      citations: [],
      metrics: { total_latency_ms: 120 },
      steps: [],
      created_at: '2026-08-09T12:00:00Z',
    }));
    vi.stubGlobal('fetch', fetchMock);

    const client = new AgentFlowApi('/api/v1');
    const run = await client.runWorkflow('default', {
      workflow: 'compare',
      documentIds: ['atlas', 'beacon'],
      focus: 'Compare resilience',
      topK: 6,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/workflows/compare',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          workspace_id: 'default',
          document_ids: ['atlas', 'beacon'],
          focus: 'Compare resilience',
          top_k: 6,
        }),
      }),
    );
    expect(run).toMatchObject({ id: 'run-7', workflow: 'compare', answer: 'Atlas is more resilient [1].' });
    expect(run.verified).toBe(true);
  });

  it('uploads one document as multipart form data', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      document: {
        id: 'doc-upload',
        title: 'Review',
        filename: 'review.md',
        status: 'pending',
        created_at: '2026-08-09T12:00:00Z',
      },
      job: { id: 'job-1' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const client = new AgentFlowApi('/api/v1');
    const file = new File(['synthetic'], 'review.md', { type: 'text/markdown' });
    const receipt = await client.uploadDocument(file, 'default');
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/documents');
    expect(request.method).toBe('POST');
    expect(request.body).toBeInstanceOf(FormData);
    expect((request.body as FormData).get('workspace_id')).toBe('default');
    expect((request.body as FormData).get('file')).toBe(file);
    expect(receipt.jobId).toBe('job-1');
  });

  it('includes workspace binding on document, job, and run detail routes', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/documents/')) {
        return Promise.resolve(jsonResponse({
          id: 'doc-1',
          workspace_id: 'workspace/a',
          title: 'Bound document',
          filename: 'bound.md',
          status: 'ready',
          created_at: '2026-08-09T12:00:00Z',
        }));
      }
      if (url.includes('/jobs/')) {
        return Promise.resolve(jsonResponse({
          id: 'job-1',
          workspace_id: 'workspace/a',
          document_id: 'doc-1',
          document_version_id: 'version-1',
          status: 'retrying',
          stage: 'embedding',
          attempt: 2,
          max_attempts: 4,
          created_at: '2026-08-09T12:00:00Z',
          updated_at: '2026-08-09T12:01:00Z',
        }));
      }
      return Promise.resolve(jsonResponse({
        run_id: 'run-1',
        workflow: 'question',
        status: 'completed',
        verified: true,
        result: { answer: 'Bound answer.' },
        citations: [{
          citation_id: 'cite-1',
          chunk_id: 'chunk-1',
          document_id: 'doc-1',
          document_version_id: 'version-1',
          document_title: 'Bound document',
          chunk_ordinal: 1,
          quote: 'Bound answer.',
          locator: {},
          score: 1,
        }],
        metrics: {},
        steps: [],
        created_at: '2026-08-09T12:00:00Z',
      }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const client = new AgentFlowApi('/api/v1');

    await client.getDocument('workspace/a', 'doc-1');
    const job = await client.getJob('workspace/a', 'job-1');
    await client.getRun('workspace/a', 'run-1');

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/documents/doc-1?workspace_id=workspace%2Fa',
      '/api/v1/jobs/job-1?workspace_id=workspace%2Fa',
      '/api/v1/runs/run-1?workspace_id=workspace%2Fa',
    ]);
    expect(job).toMatchObject({ status: 'retrying', stage: 'embedding', attempt: 2, maxAttempts: 4 });
  });

  it('fails closed on unknown statuses and preserves structured evidence telemetry', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      run_id: 'run-unknown',
      workflow: 'question',
      status: 'published',
      verified: true,
      result: { answer: 'Do not present this as verified.' },
      citations: [{
        citation_id: 'cite-1',
        chunk_id: 'chunk-1',
        document_id: 'doc-1',
        document_version_id: 'version-1',
        document_title: 'Nested source',
        chunk_ordinal: 2,
        quote: 'Nested source text.',
        locator: { page: 4, region: { section: 'Controls', box: [1, 2, 3, 4] } },
        score: 0.91,
      }],
      metrics: {},
      steps: [{
        name: 'verify',
        status: 'accepted',
        latency_ms: 5,
        detail: { checks: { quote_match: true }, failures: [] },
      }],
      created_at: '2026-08-09T12:00:00Z',
    }));
    vi.stubGlobal('fetch', fetchMock);

    const run = await new AgentFlowApi('/api/v1').getRun('default', 'run-unknown');

    expect(run).toMatchObject({
      status: 'unknown',
      reportedStatus: 'published',
      verified: false,
      steps: [{
        status: 'unknown',
        reportedStatus: 'accepted',
        detail: { checks: { quote_match: true }, failures: [] },
      }],
      citations: [{ locator: { page: 4, region: { section: 'Controls', box: [1, 2, 3, 4] } } }],
    });
  });

  it('does not infer verification from a completed status and citations alone', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      run_id: 'run-without-verification',
      workflow: 'question',
      status: 'completed',
      result: { answer: 'A completed result.' },
      citations: [{
        citation_id: 'cite-1',
        chunk_id: 'chunk-1',
        document_id: 'doc-1',
        document_version_id: 'version-1',
        document_title: 'Source',
        chunk_ordinal: 0,
        quote: 'A completed result.',
        locator: {},
        score: 1,
      }],
      metrics: {},
      steps: [],
      created_at: '2026-08-09T12:00:00Z',
    })));

    const run = await new AgentFlowApi('/api/v1').getRun('default', 'run-without-verification');
    expect(run.status).toBe('completed');
    expect(run.verified).toBe(false);
  });

  it('normalizes the structured backend error envelope without discarding its code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      error: {
        code: 'WORKSPACE_MISMATCH',
        message: 'Document not found in this workspace.',
        details: { document_id: 'doc-1' },
        request_id: 'request-7',
      },
    }, 404)));

    try {
      await new AgentFlowApi('/api/v1').getDocument('default', 'doc-1');
      throw new Error('Expected the request to fail.');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({
        name: 'ApiError',
        status: 404,
        code: 'WORKSPACE_MISMATCH',
        detail: 'Document not found in this workspace.',
        details: { document_id: 'doc-1' },
        requestId: 'request-7',
      });
    }
  });

  it('bounds a request that never returns', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
    }));
    vi.stubGlobal('fetch', fetchMock);
    const request = new AgentFlowApi('/api/v1', 25).listDocuments('default');
    const rejection = request.catch((error: unknown) => error);

    await vi.advanceTimersByTimeAsync(25);
    await expect(rejection).resolves.toMatchObject({ code: 'REQUEST_TIMEOUT' });
    vi.useRealTimers();
  });
});
