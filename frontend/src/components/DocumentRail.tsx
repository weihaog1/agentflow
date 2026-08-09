import type { ConnectionMode, DocumentRecord } from '../types';
import { formatBytes, statusLabel } from '../lib/format';
import { Icon } from './Icon';
import { SectionHeading } from './SectionHeading';
import { UploadPanel } from './UploadPanel';

interface DocumentRailProps {
  mode: ConnectionMode;
  documents: DocumentRecord[];
  corpusRevision: number | string | null;
  selectedIds: string[];
  isUploading: boolean;
  onSelectionChange: (documentId: string, selected: boolean) => void;
  onSelectAll: () => void;
  onUpload: (file: File) => Promise<void>;
}

const stageProgress: Record<DocumentRecord['status'], number> = {
  uploading: 6,
  pending: 10,
  processing: 18,
  queued: 14,
  retrying: 20,
  downloading: 24,
  parsing: 42,
  chunking: 58,
  embedding: 76,
  indexing: 90,
  ready: 100,
  failed: 100,
  unknown: 0,
};

export function DocumentRail({
  mode,
  documents,
  corpusRevision,
  selectedIds,
  isUploading,
  onSelectionChange,
  onSelectAll,
  onUpload,
}: DocumentRailProps) {
  const readyDocuments = documents.filter((document) => document.status === 'ready');
  const allReadySelected =
    readyDocuments.length > 0 && readyDocuments.every((document) => selectedIds.includes(document.id));

  return (
    <aside className="document-rail" aria-label="Evidence corpus">
      <SectionHeading
        index="01"
        title="Corpus"
        note={`${documents.length} documents · revision ${corpusRevision ?? 'pending'}`}
      />

      <UploadPanel mode={mode} isUploading={isUploading} onUpload={onUpload} />

      <div className="document-list__toolbar">
        <span>Evidence scope</span>
        <button type="button" onClick={onSelectAll} disabled={readyDocuments.length === 0}>
          {allReadySelected ? 'Clear' : 'Select ready'}
        </button>
      </div>

      {mode === 'checking' ? (
        <div className="document-skeletons" aria-label="Loading documents" aria-busy="true">
          {[0, 1, 2, 3].map((item) => <span key={item} />)}
        </div>
      ) : documents.length === 0 ? (
        <div className="rail-empty">
          <Icon name="document" size={24} />
          <strong>No evidence indexed</strong>
          <p>Upload the first source document to open the workbench.</p>
        </div>
      ) : (
        <ol className="document-list">
          {documents.map((document, index) => {
            const isReady = document.status === 'ready';
            const checked = selectedIds.includes(document.id);
            const job = document.ingestionJob;
            const progressLabel = job
              ? `${statusLabel(job.stage)} stage, ${job.status}${job.maxAttempts > 0 ? `, attempt ${job.attempt} of ${job.maxAttempts}` : ''}`
              : `${statusLabel(document.status)} progress`;
            return (
              <li key={document.id} className="document-item" data-status={document.status}>
                <label className="document-item__main">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!isReady}
                    onChange={(event) => onSelectionChange(document.id, event.target.checked)}
                  />
                  <span className="document-item__check" aria-hidden="true">
                    {checked ? <Icon name="check" size={12} /> : String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="document-item__copy">
                    <strong title={document.title}>{document.title}</strong>
                    <small title={document.fileName}>{document.fileName}</small>
                  </span>
                </label>
                <div className="document-item__meta">
                  <span className="status-mark" data-status={document.status}>
                    <i aria-hidden="true" />
                    {job?.status === 'retrying'
                      ? `Retrying ${job.attempt}/${job.maxAttempts}`
                      : statusLabel(document.status)}
                  </span>
                  {job && job.stage !== 'ready' && job.stage !== 'failed'
                    ? <span>{statusLabel(job.stage)} stage</span>
                    : null}
                  <span>{formatBytes(document.sizeBytes)}</span>
                  {document.version !== null ? <span>v{document.version}</span> : null}
                </div>
                {!isReady ? (
                  <div className="document-progress" aria-label={progressLabel}>
                    <span style={{ width: `${stageProgress[document.status]}%` }} />
                  </div>
                ) : null}
                {document.error ? <p className="document-item__error">{document.error}</p> : null}
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}
