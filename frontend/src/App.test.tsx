import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from './App';

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('AgentFlow operator interface', () => {
  it('falls back to a clearly labeled, read-only snapshot when the API is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);

    expect(await screen.findByText('Not live')).toBeInTheDocument();
    expect(screen.getByText('Northstar Security Standard')).toBeInTheDocument();
    expect(screen.getByText(/read-only, deterministic view/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add evidence/i })).toBeDisabled();
  });

  it('runs the deterministic snapshot workflow and opens its first citation', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);
    await screen.findByText('Not live');

    await user.click(screen.getByRole('button', { name: /run snapshot simulation.*cited answer/i }));
    expect(screen.getByText('Building an evidence-backed artifact')).toBeInTheDocument();
    expect(await screen.findByText(/At contract end, source files enter a 30-day recovery window/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /open citation 1 from northstar retention schedule/i }));
    expect(document.querySelector('.citation-card[data-active="true"]')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('dialog', { name: 'Citation evidence' })).toHaveAttribute('aria-hidden', 'false');
  });

  it('renders live workspace state when the API responds', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/documents')) {
        return Promise.resolve(jsonResponse({
          corpus_revision: 2,
          documents: [{
            id: 'live-doc',
            title: 'Live Security File',
            filename: 'live.md',
            status: 'ready',
            mime_type: 'text/markdown',
            size_bytes: 128,
            version: 1,
            created_at: '2026-08-09T12:00:00Z',
          }],
        }));
      }
      return Promise.resolve(jsonResponse({ runs: [] }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    expect(await screen.findByText('Live API')).toBeInTheDocument();
    expect(screen.getByText('Live Security File')).toBeInTheDocument();
    expect(screen.queryByText('Not live')).not.toBeInTheDocument();
  });

  it('requires two ready documents for comparison', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);
    await screen.findByText('Not live');

    await user.click(screen.getByRole('tab', { name: /compare/i }));
    const checkboxes = screen.getAllByRole('checkbox');
    checkboxes.slice(1).forEach((checkbox) => fireEvent.click(checkbox));

    await waitFor(() => {
      expect(screen.getByText(/select at least two ready documents/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /run snapshot simulation.*document comparison/i })).toBeDisabled();
  });

  it('does not substitute a canned demo answer for a changed prompt', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);
    await screen.findByText('Not live');

    const prompt = screen.getByRole('textbox', { name: /question to answer/i });
    await user.clear(prompt);
    await user.type(prompt, 'What is the unsupported control policy?');
    await user.click(screen.getByRole('button', { name: /run snapshot simulation.*cited answer/i }));

    expect(await screen.findByText(/did not produce an answer/i)).toBeInTheDocument();
    expect(screen.getAllByText(/supports only/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/evidence gap/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/At contract end, source files enter/i)).not.toBeInTheDocument();
  });

  it('supports arrow, Home, and End navigation across workflow tabs', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);
    await screen.findByText('Not live');

    const ask = screen.getByRole('tab', { name: /ask/i });
    ask.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: /compare/i })).toHaveFocus();
    expect(screen.getByRole('tab', { name: /compare/i })).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: /brief/i })).toHaveFocus();
    await user.keyboard('{Home}');
    expect(ask).toHaveFocus();
  });

  it('contains mobile dialog focus, closes on Escape, and restores its trigger', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);
    await screen.findByText('Not live');

    const trigger = screen.getByRole('button', { name: /^Evidence4$/i });
    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Citation evidence' });
    const close = within(dialog).getByRole('button', { name: /close evidence drawer/i });
    await waitFor(() => expect(close).toHaveFocus());

    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Citation evidence' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('keeps the live corpus usable when only the run ledger fails', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes('/documents')) {
        return Promise.resolve(jsonResponse({
          items: [{
            id: 'live-doc',
            title: 'Live Security File',
            filename: 'live.md',
            status: 'ready',
            media_type: 'text/markdown',
            created_at: '2026-08-09T12:00:00Z',
            updated_at: '2026-08-09T12:00:00Z',
          }],
        }));
      }
      return Promise.resolve(new Response(JSON.stringify({
        error: { code: 'LEDGER_DOWN', message: 'Run storage is unavailable.', details: {}, request_id: 'req-1' },
      }), { status: 503, headers: { 'Content-Type': 'application/json' } }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    expect(await screen.findByText('Live API')).toBeInTheDocument();
    expect(screen.getByText('Live Security File')).toBeInTheDocument();
    expect(screen.getByText(/run ledger unavailable: run storage is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText('Not live')).not.toBeInTheDocument();
  });

  it('selects only ready documents from the live corpus', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => Promise.resolve(jsonResponse(
      String(input).includes('/documents')
        ? {
            items: [
              { id: 'ready-doc', title: 'Ready', filename: 'ready.md', status: 'ready', created_at: '2026-08-09T12:00:00Z' },
              { id: 'busy-doc', title: 'Processing', filename: 'busy.md', status: 'processing', created_at: '2026-08-09T12:00:00Z' },
            ],
          }
        : { items: [] },
    )));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await screen.findByText('Live API');
    const ready = screen.getByRole('checkbox', { name: /Readyready.md/i });
    const processing = screen.getByRole('checkbox', { name: /Processingbusy.md/i });
    expect(ready).toBeChecked();
    expect(processing).not.toBeChecked();
    expect(processing).toBeDisabled();
    expect(screen.getByText('1 selected')).toBeInTheDocument();
  });
});
