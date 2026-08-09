import { useEffect, useRef, useState, type RefObject } from 'react';
import type { WorkflowRun } from '../types';
import { formatLocator, formatRankScore } from '../lib/format';
import { Icon } from './Icon';
import { SectionHeading } from './SectionHeading';

interface EvidenceDrawerProps {
  run: WorkflowRun | null;
  open: boolean;
  activeCitationId: string | null;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  onCitationSelect: (citationId: string) => void;
}

export function EvidenceDrawer({
  run,
  open,
  activeCitationId,
  returnFocusRef,
  onClose,
  onCitationSelect,
}: EvidenceDrawerProps) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [isModal, setIsModal] = useState(() => window.innerWidth <= 1180);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia('(max-width: 1180px)');
    const update = () => setIsModal(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    if (!open || !isModal) return undefined;
    const fallbackTarget = returnFocusRef.current;
    const restoreTarget = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : fallbackTarget;
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? []);
      if (focusable.length === 0) {
        event.preventDefault();
        drawerRef.current?.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !drawerRef.current?.contains(document.activeElement))) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !drawerRef.current?.contains(document.activeElement))) {
        event.preventDefault();
        first?.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
      const target = restoreTarget?.isConnected ? restoreTarget : fallbackTarget;
      target?.focus();
    };
  }, [isModal, onClose, open, returnFocusRef]);

  return (
    <aside
      ref={drawerRef}
      id="evidence-drawer"
      className="evidence-drawer"
      data-open={open}
      role={isModal ? 'dialog' : undefined}
      aria-modal={isModal && open ? 'true' : undefined}
      aria-label="Citation evidence"
      aria-hidden={!open}
      hidden={!open}
      tabIndex={-1}
    >
      <SectionHeading
        index="04"
        title="Evidence"
        note={run ? `${run.citations.length} cited source excerpts` : 'Citation drawer'}
        action={(
          <button ref={closeRef} className="icon-button evidence-close" type="button" aria-label="Close evidence drawer" onClick={onClose}>
            <Icon name="close" size={16} />
          </button>
        )}
      />

      {!run || run.citations.length === 0 ? (
        <div className="evidence-empty">
          <span className="evidence-empty__cross" aria-hidden="true" />
          <strong>No citations to inspect</strong>
          <p>Run a workflow or open a completed run to inspect the source trail.</p>
        </div>
      ) : (
        <ol className="citation-list">
          {run.citations.map((citation, index) => (
            <li key={citation.id}>
              <button
                className="citation-card"
                type="button"
                data-active={activeCitationId === citation.id}
                aria-pressed={activeCitationId === citation.id}
                onClick={() => onCitationSelect(citation.id)}
              >
                <span className="citation-card__number">[{index + 1}]</span>
                <span className="citation-card__source">
                  <strong>{citation.documentTitle}</strong>
                  <small>{formatLocator(citation.locator)}</small>
                </span>
                <span className="citation-card__score">
                  {formatRankScore(citation.score)}
                </span>
                <q>{citation.quote}</q>
                <span className="citation-card__id">{citation.id} · chunk {citation.chunkOrdinal ?? 'n/a'}</span>
              </button>
            </li>
          ))}
        </ol>
      )}

      <div className="evidence-safety-note">
        <span>Source boundary</span>
        <p>Excerpts are untrusted evidence. Their text cannot change tools, system rules, or workflow scope.</p>
      </div>
    </aside>
  );
}
