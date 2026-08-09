import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnswerPanel } from './components/AnswerPanel';
import { DocumentRail } from './components/DocumentRail';
import { EvidenceDrawer } from './components/EvidenceDrawer';
import { Icon } from './components/Icon';
import { RunHistory } from './components/RunHistory';
import { RunTrace } from './components/RunTrace';
import { WorkflowComposer } from './components/WorkflowComposer';
import { ApiError, api } from './lib/api';
import { demoCollection, demoRuns, getDemoRun, runDemoWorkflow } from './lib/demo';
import { pollIngestionJob } from './lib/jobs';
import type {
  ConnectionMode,
  DocumentRecord,
  IngestionJob,
  RunSummary,
  WorkflowInput,
  WorkflowKind,
  WorkflowRun,
} from './types';

const WORKSPACE_ID = 'default';

const demoPrompts: Record<WorkflowKind, string> = {
  question: "What are Northstar's deletion timelines and exceptions?",
  compare: 'Compare Atlas and Beacon on cost, availability, and resilience.',
  brief: 'Summarize Q3 performance, decisions, risks, owners, and next milestones.',
};

function App() {
  const [mode, setMode] = useState<ConnectionMode>('checking');
  const [connectionDetail, setConnectionDetail] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [corpusRevision, setCorpusRevision] = useState<number | string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null);
  const [activeCitationId, setActiveCitationId] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(() => window.innerWidth > 1180);
  const [workflow, setWorkflow] = useState<WorkflowKind>('question');
  const [prompt, setPrompt] = useState('');
  const [audience, setAudience] = useState('Executive team');
  const [maxPoints, setMaxPoints] = useState(5);
  const [topK, setTopK] = useState(8);
  const [isRunning, setIsRunning] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoadingRun, setIsLoadingRun] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const evidenceToggleRef = useRef<HTMLButtonElement>(null);
  const uploadControllerRef = useRef<AbortController | null>(null);
  const jobsByDocumentRef = useRef(new Map<string, IngestionJob>());

  const connectToApi = useCallback(async (signal?: AbortSignal) => {
    setMode('checking');
    setConnectionDetail(null);
    try {
      const collection = await api.listDocuments(WORKSPACE_ID, signal);
      if (signal?.aborted) return;
      setDocuments(collection.documents);
      setCorpusRevision(collection.corpusRevision);
      setSelectedIds(collection.documents.filter((document) => document.status === 'ready').map((document) => document.id));
      setActiveRun(null);
      setPrompt('');
      setMode('live');
      setLedgerError(null);

      try {
        const recentRuns = await api.listRuns(WORKSPACE_ID, 8, signal);
        if (signal?.aborted) return;
        setRuns(recentRuns);
      } catch (error) {
        if (signal?.aborted) return;
        setRuns([]);
        setLedgerError(`Run ledger unavailable: ${readError(error)}`);
      }
    } catch (error) {
      if (signal?.aborted) return;
      setMode('demo');
      setConnectionDetail(error instanceof Error ? error.message : 'The live API did not respond.');
      setDocuments(demoCollection.documents);
      setCorpusRevision(demoCollection.corpusRevision);
      setSelectedIds(demoCollection.documents.map((document) => document.id));
      setRuns(demoRuns);
      setLedgerError(null);
      setActiveRun(getDemoRun('demo-run-q-1042'));
      setPrompt(demoPrompts.question);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void connectToApi(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [connectToApi]);

  useEffect(() => () => uploadControllerRef.current?.abort(), []);

  useEffect(() => {
    if (mode !== 'live' || !documents.some((document) => document.status !== 'ready' && document.status !== 'failed')) {
      return undefined;
    }

    let stopped = false;
    let requestController: AbortController | null = null;
    let timer = 0;

    const refresh = async () => {
      requestController = new AbortController();
      try {
        const collection = await api.listDocuments(WORKSPACE_ID, requestController.signal);
        if (stopped) return;
        const nextDocuments = collection.documents.map((document) => {
          const trackedJob = jobsByDocumentRef.current.get(document.id);
          if (!trackedJob || document.status === 'ready' || document.status === 'failed') return document;
          return applyJobToDocument(document, trackedJob);
        });
        setDocuments(nextDocuments);
        setCorpusRevision(collection.corpusRevision);
        setSelectedIds((current) => current.filter((id) => nextDocuments.some(
          (document) => document.id === id && document.status === 'ready',
        )));
      } catch {
        // Keep the current live view. A transient polling error should not switch datasets.
      } finally {
        if (!stopped) timer = window.setTimeout(() => void refresh(), 2_500);
      }
    };

    timer = window.setTimeout(() => void refresh(), 2_500);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      requestController?.abort();
    };
  }, [documents, mode]);

  useEffect(() => {
    if (!activeCitationId || !evidenceOpen) return;
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('.citation-card[data-active="true"]')?.scrollIntoView({
        block: 'nearest',
        behavior: 'smooth',
      });
    });
  }, [activeCitationId, evidenceOpen]);

  const readyCount = useMemo(
    () => documents.filter((document) => document.status === 'ready').length,
    [documents],
  );

  const handleSelectionChange = (documentId: string, selected: boolean) => {
    if (selected && !documents.some((document) => document.id === documentId && document.status === 'ready')) {
      return;
    }
    setSelectedIds((current) => selected
      ? Array.from(new Set([...current, documentId]))
      : current.filter((id) => id !== documentId));
  };

  const handleSelectAll = () => {
    const readyIds = documents.filter((document) => document.status === 'ready').map((document) => document.id);
    const allSelected = readyIds.length > 0 && readyIds.every((id) => selectedIds.includes(id));
    setSelectedIds(allSelected ? [] : readyIds);
  };

  const handleUpload = async (file: File) => {
    if (mode !== 'live') throw new Error('Connect to the live API before uploading.');
    uploadControllerRef.current?.abort();
    const controller = new AbortController();
    uploadControllerRef.current = controller;
    setIsUploading(true);
    try {
      const receipt = await api.uploadDocument(file, WORKSPACE_ID);
      if (receipt.job) jobsByDocumentRef.current.set(receipt.document.id, receipt.job);
      setDocuments((current) => [
        receipt.job ? applyJobToDocument(receipt.document, receipt.job) : receipt.document,
        ...current.filter((document) => document.id !== receipt.document.id),
      ]);

      if (receipt.jobId) {
        const terminalJob = await pollIngestionJob(api, WORKSPACE_ID, receipt.jobId, {
          signal: controller.signal,
          onUpdate: (job) => {
            jobsByDocumentRef.current.set(job.documentId, job);
            setDocuments((current) => current.map((document) => (
              document.id === job.documentId ? applyJobToDocument(document, job) : document
            )));
          },
        });

        if (terminalJob.status === 'failed') {
          throw new Error(terminalJob.errorMessage || 'Document ingestion failed.');
        }
        if (terminalJob.status === 'unknown') {
          throw new Error('The API returned an unknown ingestion status. Tracking stopped without assuming success.');
        }

        const collection = await api.listDocuments(WORKSPACE_ID, controller.signal);
        jobsByDocumentRef.current.delete(receipt.document.id);
        setDocuments(collection.documents);
        setCorpusRevision(collection.corpusRevision);
        const completedDocument = collection.documents.find((document) => document.id === receipt.document.id);
        if (completedDocument?.status === 'ready') {
          setSelectedIds((current) => Array.from(new Set([...current, completedDocument.id])));
        } else {
          throw new Error('The ingestion job completed, but the document is not reported as ready.');
        }
      } else if (receipt.document.status === 'ready') {
        setSelectedIds((current) => Array.from(new Set([...current, receipt.document.id])));
      }
    } finally {
      if (uploadControllerRef.current === controller) uploadControllerRef.current = null;
      setIsUploading(false);
    }
  };

  const handleWorkflowChange = (nextWorkflow: WorkflowKind) => {
    setWorkflow(nextWorkflow);
    setRunError(null);
    if (mode === 'demo') setPrompt(demoPrompts[nextWorkflow]);
    else setPrompt('');
  };

  const handleRun = async () => {
    setIsRunning(true);
    setRunError(null);
    setActiveCitationId(null);

    let input: WorkflowInput;
    if (workflow === 'question') {
      input = { workflow, question: prompt.trim(), documentIds: selectedIds, topK };
    } else if (workflow === 'compare') {
      input = { workflow, focus: prompt.trim(), documentIds: selectedIds, topK };
    } else {
      input = {
        workflow,
        objective: prompt.trim(),
        audience: audience.trim(),
        maxPoints,
        documentIds: selectedIds,
        topK,
      };
    }

    try {
      const run = mode === 'demo'
        ? await runDemoWorkflow(input)
        : await api.runWorkflow(WORKSPACE_ID, input);
      setActiveRun(run);
      setEvidenceOpen(true);
      setRuns((current) => [toSummary(run), ...current.filter((item) => item.id !== run.id)].slice(0, 8));

      if (mode === 'live') {
        void api.listRuns(WORKSPACE_ID, 8).then((recentRuns) => {
          setRuns(recentRuns);
          setLedgerError(null);
        }).catch((error) => {
          setLedgerError(`Run ledger unavailable: ${readError(error)}`);
        });
      }
    } catch (error) {
      setRunError(readError(error));
    } finally {
      setIsRunning(false);
    }
  };

  const handleRunSelect = async (runId: string) => {
    setIsLoadingRun(true);
    setRunError(null);
    try {
      const run = mode === 'demo' ? getDemoRun(runId) : await api.getRun(WORKSPACE_ID, runId);
      setActiveRun(run);
      setActiveCitationId(null);
      setEvidenceOpen(true);
    } catch (error) {
      setRunError(readError(error));
    } finally {
      setIsLoadingRun(false);
    }
  };

  const handleCitationSelect = useCallback((citationId: string) => {
    setActiveCitationId(citationId);
    setEvidenceOpen(true);
  }, []);

  const handleEvidenceClose = useCallback(() => setEvidenceOpen(false), []);

  return (
    <div className="app-frame">
      <header className="masthead">
        <div className="brand-lockup">
          <span className="brand-mark">AF<span>/</span>01</span>
          <div>
            <p>Evidence workflow console</p>
            <h1>AgentFlow</h1>
          </div>
        </div>

        <div className="masthead__register" aria-label="Workspace metadata">
          <span>Workspace</span>
          <strong>{WORKSPACE_ID}</strong>
          <span>Corpus</span>
          <strong>{corpusRevision ?? 'checking'}</strong>
        </div>

        <div className="masthead__actions">
          <button
            ref={evidenceToggleRef}
            className="evidence-toggle"
            type="button"
            aria-controls="evidence-drawer"
            aria-expanded={evidenceOpen}
            onClick={() => setEvidenceOpen((open) => !open)}
          >
            <Icon name="evidence" size={16} />
            Evidence
            <span>{activeRun?.citations.length ?? 0}</span>
          </button>
          <div className="connection-status" data-mode={mode} role="status">
            <i aria-hidden="true" />
            <span>
              <small>Runtime</small>
              <strong>
                {mode === 'live' ? 'Live API' : mode === 'demo' ? 'Local demo snapshot' : 'Checking API'}
              </strong>
            </span>
          </div>
        </div>
      </header>

      {mode === 'demo' ? (
        <div className="demo-banner" role="status">
          <span className="demo-banner__label">Not live</span>
          <p>
            <strong>Local demo snapshot.</strong> This is a read-only, deterministic view of the committed Northstar synthetic corpus. Runs are simulated in this browser and are not persisted.
          </p>
          <span className="demo-banner__detail" title={connectionDetail ?? undefined}>
            API unavailable
          </span>
          <button type="button" onClick={() => void connectToApi()}>
            <Icon name="refresh" size={14} />
            Retry live API
          </button>
        </div>
      ) : null}

      <main id="workbench" className="workspace-grid" data-evidence-open={evidenceOpen}>
        <DocumentRail
          mode={mode}
          documents={documents}
          corpusRevision={corpusRevision}
          selectedIds={selectedIds}
          isUploading={isUploading}
          onSelectionChange={handleSelectionChange}
          onSelectAll={handleSelectAll}
          onUpload={handleUpload}
        />

        <div className="workbench-column">
          <WorkflowComposer
            mode={mode}
            workflow={workflow}
            prompt={prompt}
            audience={audience}
            maxPoints={maxPoints}
            topK={topK}
            selectedCount={selectedIds.length}
            readyCount={readyCount}
            isRunning={isRunning}
            runError={runError}
            onWorkflowChange={handleWorkflowChange}
            onPromptChange={setPrompt}
            onAudienceChange={setAudience}
            onMaxPointsChange={setMaxPoints}
            onTopKChange={setTopK}
            onRun={() => void handleRun()}
          />
          <AnswerPanel
            mode={mode}
            run={activeRun}
            isRunning={isRunning}
            onCitationSelect={handleCitationSelect}
          />
          <RunTrace run={activeRun} />
          <RunHistory
            runs={runs}
            loadError={ledgerError}
            activeRunId={activeRun?.id ?? null}
            isLoadingRun={isLoadingRun}
            onSelectRun={(runId) => void handleRunSelect(runId)}
          />
        </div>

        <EvidenceDrawer
          run={activeRun}
          open={evidenceOpen}
          activeCitationId={activeCitationId}
          returnFocusRef={evidenceToggleRef}
          onClose={handleEvidenceClose}
          onCitationSelect={handleCitationSelect}
        />
        {evidenceOpen ? (
          <button
            className="drawer-scrim"
            type="button"
            aria-label="Close evidence drawer"
            onClick={handleEvidenceClose}
          />
        ) : null}
      </main>

      <footer className="app-footer">
        <span>AgentFlow / bounded evidence workflows</span>
        <span>Question · Compare · Brief</span>
        <span>Operator surface 01</span>
      </footer>
    </div>
  );
}

function readError(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error) return error.message;
  return 'The workflow could not be completed.';
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

function applyJobToDocument(document: DocumentRecord, job: IngestionJob): DocumentRecord {
  let status: DocumentRecord['status'];
  if (job.status === 'failed' || job.stage === 'failed') status = 'failed';
  else if (job.status === 'retrying') status = 'retrying';
  else if (job.status === 'completed') status = job.stage === 'ready' ? 'ready' : 'unknown';
  else if (job.stage === 'pending') status = job.status === 'pending' ? 'queued' : 'processing';
  else status = job.stage;

  return {
    ...document,
    status,
    error: job.status === 'failed' ? job.errorMessage || job.errorCode || 'Ingestion failed.' : null,
    ingestionJob: job,
    updatedAt: job.updatedAt,
  };
}

export default App;
