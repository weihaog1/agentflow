import type { IngestionJob } from '../types';

export interface IngestionJobClient {
  getJob: (
    workspaceId: string,
    jobId: string,
    signal?: AbortSignal,
  ) => Promise<IngestionJob>;
}

interface PollOptions {
  signal?: AbortSignal;
  intervalMs?: number;
  maxPolls?: number;
  onUpdate?: (job: IngestionJob) => void;
}

export class IngestionPollTimeoutError extends Error {
  readonly lastJob: IngestionJob | null;

  constructor(lastJob: IngestionJob | null) {
    super('Ingestion tracking reached its bounded polling limit. The worker may still be processing the document.');
    this.name = 'IngestionPollTimeoutError';
    this.lastJob = lastJob;
  }
}

export async function pollIngestionJob(
  client: IngestionJobClient,
  workspaceId: string,
  jobId: string,
  options: PollOptions = {},
): Promise<IngestionJob> {
  const intervalMs = options.intervalMs ?? 1_000;
  const maxPolls = options.maxPolls ?? 90;
  let lastJob: IngestionJob | null = null;

  for (let poll = 0; poll < maxPolls; poll += 1) {
    if (options.signal?.aborted) throw abortError();
    lastJob = await client.getJob(workspaceId, jobId, options.signal);
    options.onUpdate?.(lastJob);

    if (
      lastJob.status === 'completed' ||
      lastJob.status === 'failed' ||
      lastJob.status === 'unknown'
    ) {
      return lastJob;
    }

    if (poll < maxPolls - 1) await wait(intervalMs, options.signal);
  }

  throw new IngestionPollTimeoutError(lastJob);
}

function wait(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }

    const handleAbort = () => {
      globalThis.clearTimeout(timer);
      reject(abortError());
    };
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener('abort', handleAbort);
      resolve();
    }, delayMs);
    signal?.addEventListener('abort', handleAbort, { once: true });
  });
}

function abortError(): DOMException {
  return new DOMException('Ingestion tracking was cancelled.', 'AbortError');
}
