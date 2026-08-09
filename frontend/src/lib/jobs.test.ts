import { describe, expect, it, vi } from 'vitest';
import type { IngestionJob } from '../types';
import { pollIngestionJob } from './jobs';

function job(status: IngestionJob['status'], stage: IngestionJob['stage']): IngestionJob {
  return {
    id: 'job-1',
    workspaceId: 'default',
    documentId: 'doc-1',
    documentVersionId: 'version-1',
    status,
    stage,
    attempt: status === 'retrying' ? 2 : 1,
    maxAttempts: 4,
    nextAttemptAt: null,
    errorCode: null,
    errorMessage: null,
    createdAt: '2026-08-09T12:00:00Z',
    updatedAt: '2026-08-09T12:00:01Z',
    completedAt: status === 'completed' ? '2026-08-09T12:00:02Z' : null,
  };
}

describe('pollIngestionJob', () => {
  it('reports retrying and processing stages before the terminal job', async () => {
    const updates: IngestionJob[] = [];
    const client = {
      getJob: vi.fn()
        .mockResolvedValueOnce(job('running', 'parsing'))
        .mockResolvedValueOnce(job('retrying', 'embedding'))
        .mockResolvedValueOnce(job('completed', 'ready')),
    };

    const result = await pollIngestionJob(client, 'default', 'job-1', {
      intervalMs: 0,
      maxPolls: 3,
      onUpdate: (update) => updates.push(update),
    });

    expect(client.getJob).toHaveBeenCalledWith('default', 'job-1', undefined);
    expect(updates.map((update) => [update.status, update.stage])).toEqual([
      ['running', 'parsing'],
      ['retrying', 'embedding'],
      ['completed', 'ready'],
    ]);
    expect(result.status).toBe('completed');
  });

  it('stops after the configured polling bound without inventing a failure', async () => {
    const running = job('running', 'chunking');
    const client = { getJob: vi.fn().mockResolvedValue(running) };

    await expect(pollIngestionJob(client, 'default', 'job-1', {
      intervalMs: 0,
      maxPolls: 2,
    })).rejects.toMatchObject({
      name: 'IngestionPollTimeoutError',
      lastJob: running,
    });
    expect(client.getJob).toHaveBeenCalledTimes(2);
  });
});
