import type { CitationLocator, DocumentStatus, JsonValue, WorkflowKind } from '../types';

export function formatBytes(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'Size n/a';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatLatency(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'Not reported';
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function formatPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'Not reported';
  const normalized = value <= 1 ? value * 100 : value;
  return `${Math.round(normalized)}%`;
}

export function formatRankScore(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'Rank n/a';
  return `Rank ${value.toFixed(3)}`;
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Time unavailable';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

export function formatLocator(locator: CitationLocator): string {
  if (!locator) return 'Location not reported';
  if (typeof locator === 'string') return locator;

  const entries = flattenEntries(locator)
    .filter(([, value]) => value !== null && value !== '')
    .map(([key, value]) => `${key.split('.').map(humanize).join(' / ')} ${String(value)}`);

  return entries.length > 0 ? entries.join(' · ') : 'Location not reported';
}

function flattenEntries(
  value: { [key: string]: JsonValue },
  prefix = '',
): Array<[string, string | number | boolean | null]> {
  return Object.entries(value).flatMap(([key, entry]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (Array.isArray(entry)) {
      return [[path, JSON.stringify(entry)]];
    }
    if (entry && typeof entry === 'object') return flattenEntries(entry, path);
    return [[path, entry]];
  });
}

export function formatDetail(detail: JsonValue | null): string {
  if (detail === null) return 'No operational detail reported';
  if (typeof detail === 'string') return detail;
  if (typeof detail === 'number' || typeof detail === 'boolean') return String(detail);
  return JSON.stringify(detail);
}

export function humanize(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (character) => character.toUpperCase());
}

export function workflowLabel(workflow: WorkflowKind): string {
  return {
    question: 'Cited answer',
    compare: 'Document comparison',
    brief: 'Executive brief',
  }[workflow];
}

export function statusLabel(status: DocumentStatus): string {
  return status === 'ready' ? 'Indexed' : humanize(status);
}
