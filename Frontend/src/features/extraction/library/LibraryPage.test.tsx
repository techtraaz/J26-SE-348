import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LibraryPage } from './LibraryPage'

const NOW = '2026-10-17T10:00:00Z'

function doc(id: string, filename: string, status: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    folder_id: null,
    filename,
    mime: 'application/pdf',
    sha256: 'x'.repeat(64),
    status,
    page_count: status === 'needs_review' ? 3 : null,
    source: 'demo',
    error_code: null,
    error_message: null,
    created_at: NOW,
    updated_at: NOW,
    latest_run: null,
    ...extra,
  }
}

const FOLDER = {
  id: 'f1',
  parent_id: null,
  name: 'Invoices 2026',
  created_at: NOW,
  folder_count: 0,
  document_count: 2,
}

function mockApi(documents: unknown[], opts: { documentsStatus?: number } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === 'string' ? input : input.url)
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

      if (url.pathname === '/api/v1/folders') return json({ items: [FOLDER] })
      if (url.pathname === '/api/v1/documents') {
        if (opts.documentsStatus && opts.documentsStatus >= 400) {
          return json({ error: { code: 'server_down', message: 'The database is unavailable.' } }, opts.documentsStatus)
        }
        return json({ items: documents, total: documents.length, limit: 200, offset: 0 })
      }
      return json({ error: { code: 'not_found', message: 'Not found.' } }, 404)
    }),
  )
}

function renderLibrary(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<LibraryPage />} />
          <Route path="/folders/:folderId" element={<LibraryPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('LibraryPage', () => {
  it('shows folders, documents and status chips', async () => {
    mockApi([doc('1', 'invoice-001.pdf', 'needs_review'), doc('2', 'receipt.png', 'failed', { error_message: 'The file could not be read as an image.' })])
    renderLibrary()

    expect(await screen.findByText('invoice-001.pdf')).toBeInTheDocument()
    expect(screen.getByText('Invoices 2026')).toBeInTheDocument()
    expect(screen.getByText('The file could not be read as an image.')).toBeInTheDocument()
    expect(screen.getAllByText('Needs review').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument() // failed rows can be retried
  })

  it('shows extraction progress for a document being processed', async () => {
    mockApi([
      doc('1', 'big-scan.pdf', 'processing', {
        latest_run: { id: 'r', status: 'running', pipeline_mode: 'ocr_only', engine: null, pages_total: 12, pages_done: 4, elapsed_ms: null, started_at: NOW, finished_at: null },
      }),
    ])
    renderLibrary()

    expect(await screen.findByText('4 of 12 pages')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: /big-scan\.pdf/ })).toHaveAttribute('aria-valuenow', '33')
  })

  it('filters documents by status with the pills', async () => {
    mockApi([doc('1', 'a.pdf', 'needs_review'), doc('2', 'b.pdf', 'verified')])
    renderLibrary()
    await screen.findByText('a.pdf')

    await userEvent.click(screen.getByRole('button', { name: /^Verified/ }))

    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument()
    expect(screen.getByText('b.pdf')).toBeInTheDocument()
  })

  it('shows an empty state with an upload action when there are no documents', async () => {
    mockApi([])
    renderLibrary()

    expect(await screen.findByText('No documents here yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /upload documents/i })).toBeInTheDocument()
  })

  it('shows the API error message and lets the user try again', async () => {
    mockApi([], { documentsStatus: 500 })
    renderLibrary()

    expect(await screen.findByText('Could not load documents')).toBeInTheDocument()
    expect(screen.getByText('The database is unavailable.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('switches between list and grid and remembers the choice', async () => {
    mockApi([doc('1', 'a.pdf', 'needs_review')])
    renderLibrary()
    await screen.findByText('a.pdf')
    expect(screen.getByRole('table')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'grid view' }))

    await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument())
    expect(localStorage.getItem('auditmind.library.view')).toBe('grid')
  })

  it('searches across all documents and hides folders while searching', async () => {
    mockApi([doc('1', 'invoice-001.pdf', 'needs_review')])
    renderLibrary('/?q=invoice')

    expect(await screen.findByText('Results for “invoice”')).toBeInTheDocument()
    expect(await screen.findByText('invoice-001.pdf')).toBeInTheDocument()
    expect(screen.queryByText('Invoices 2026')).not.toBeInTheDocument()
  })
})
