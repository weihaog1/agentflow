import { useRef, useState } from 'react';
import type { ConnectionMode } from '../types';
import { Icon } from './Icon';

interface UploadPanelProps {
  mode: ConnectionMode;
  isUploading: boolean;
  onUpload: (file: File) => Promise<void>;
}

export function UploadPanel({ mode, isUploading, onUpload }: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState('PDF, DOCX, Markdown, or text');
  const unavailable = mode !== 'live';

  const chooseFile = () => {
    if (!unavailable) inputRef.current?.click();
  };

  const submitFile = async (file: File | undefined) => {
    if (!file || unavailable) return;
    setMessage(`Uploading and tracking ${file.name}`);
    try {
      await onUpload(file);
      setMessage(`${file.name} accepted. Check its corpus status.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Upload failed');
    } finally {
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div className="upload-block">
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept=".pdf,.docx,.md,.markdown,.txt,application/pdf,text/markdown,text/plain"
        disabled={unavailable || isUploading}
        aria-label="Choose a document to upload"
        onChange={(event) => void submitFile(event.target.files?.[0])}
      />
      <button
        className="upload-target"
        type="button"
        disabled={unavailable || isUploading}
        data-dragging={dragging}
        aria-describedby="upload-status"
        onClick={chooseFile}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!unavailable) setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void submitFile(event.dataTransfer.files[0]);
        }}
      >
        <span className="upload-target__icon"><Icon name="upload" size={18} /></span>
        <span className="upload-target__copy">
          <strong>{isUploading ? 'Tracking ingestion' : 'Add evidence'}</strong>
          <small>
            {unavailable ? 'Live API required for uploads' : 'Drop one file or browse'}
          </small>
        </span>
      </button>
      <p id="upload-status" className="upload-status" aria-live="polite">
        {mode === 'demo' ? 'Snapshot is read-only. No file leaves this browser.' : message}
      </p>
    </div>
  );
}
