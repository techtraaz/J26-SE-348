import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LibraryPage } from './LibraryPage'

const NOW = '2026-10-17T10:00:00Z'

function doc(id: string, filename: string, status: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    folder_id: null,
    folder_name: null,
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

const filed = (id: string, filename: string, status = 'needs_review') =>
  doc(id, filename, status, { folder_id: 'f1', folder_name: 'Invoices 2026' })

/** Fake API: lists like the real one (folder, unfiled, status, limit) and records changes. */
function mockApi(documents: ReturnType<typeof doc>[], opts: { documentsStatus?: number } = {}) {
  const changes: { method: string; path: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const request = typeof input === 'string' ? new Request(input) : input
      const url = new URL(request.url)
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

      if (request.method === 'PATCH' || request.method === 'DELETE') {
        const body = request.method === 'PATCH' ? await request.json() : null
        changes.push({ method: request.method, path: url.pathname, body })
        if (request.method === 'DELETE') return new Response(null, { status: 204 })
        return json({ ...documents.find((d) => url.pathname.endsWith(d.id)), ...body })
      }
      if (url.pathname === '/api/v1/folders') {
        return json({ items: url.searchParams.get('parent_id') ? [] : [FOLDER] })
      }
      if (url.pathname === '/api/v1/folders/f1') {
        return json({ ...FOLDER, breadcrumbs: [{ id: 'f1', name: 'Invoices 2026' }] })
      }
      if (url.pathname === '/api/v1/documents') {
        if (opts.documentsStatus && opts.documentsStatus >= 400) {
          return json({ error: { code: 'server_down', message: 'The database is unavailable.' } }, opts.documentsStatus)
        }
        const p = url.searchParams
        let items = documents
        if (p.get('folder_id')) items = items.filter((d) => d.folder_id === p.get('folder_id'))
        else if (p.get('root_only') === 'true') items = items.filter((d) => d.folder_id === null)
        if (p.get('status')) items = items.filter((d) => d.status === p.get('status'))
        const limit = Number(p.get('limit') ?? 50)
        return json({ items: items.slice(0, limit), total: items.length, limit, offset: 0 })
      }
      return json({ error: { code: 'not_found', message: 'Not found.' } }, 404)
    }),
  )
  return changes
}

function renderLibrary(path = '/documents') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/documents" element={<LibraryPage view="all" />} />
          <Route path="/documents/folders" element={<LibraryPage view="folders" />} />
          <Route path="/documents/folders/:folderId" element={<LibraryPage view="folders" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const menu = (filename: string) => screen.getByRole('button', { name: `Actions for ${filename}` })

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('All documents', () => {
  it('lists every document with its folder, status and actions', async () => {
    mockApi([
      filed('1', 'invoice-001.pdf'),
      doc('2', 'receipt.png', 'failed', { error_message: 'The file could not be read as an image.' }),
    ])
    renderLibrary()

    expect(await screen.findByText('invoice-001.pdf')).toBeInTheDocument()
    const rows = screen.getAllByRole('row')
    expect(within(rows[1]).getByRole('link', { name: 'Invoices 2026' })).toHaveAttribute('href', '/documents/folders/f1')
    expect(within(rows[2]).getByRole('link', { name: 'Unfiled' })).toHaveAttribute('href', '/documents/folders/unfiled')
    expect(screen.getByText('The file could not be read as an image.')).toBeInTheDocument()
    expect(screen.getAllByText('Needs review').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(menu('invoice-001.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /new folder/i })).not.toBeInTheDocument() // folders live in their tab
  })

  it('marks the active tab', async () => {
    mockApi([])
    renderLibrary()

    expect(await screen.findByRole('link', { name: 'All documents' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Folders' })).not.toHaveAttribute('aria-current')
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
    mockApi([filed('1', 'a.pdf')])
    renderLibrary()
    await screen.findByText('a.pdf')
    expect(screen.getByRole('table')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'grid view' }))

    await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument())
    expect(localStorage.getItem('auditmind.library.view')).toBe('grid')
    expect(screen.getByRole('link', { name: 'Invoices 2026' })).toBeInTheDocument() // folder on the card
    expect(menu('a.pdf')).toBeInTheDocument()
  })

  it('searches across all documents', async () => {
    mockApi([filed('1', 'invoice-001.pdf')])
    renderLibrary('/documents?q=invoice')

    expect(await screen.findByText('Results for “invoice”')).toBeInTheDocument()
    expect(await screen.findByText('invoice-001.pdf')).toBeInTheDocument()
  })
})

describe('Folders', () => {
  it('shows Unfiled first with its count, then the folders, and no document list', async () => {
    mockApi([filed('1', 'march.pdf'), doc('2', 'loose-a.pdf', 'needs_review'), doc('3', 'loose-b.pdf', 'verified')])
    renderLibrary('/documents/folders')

    const unfiled = await screen.findByRole('link', { name: /Unfiled/ })
    expect(unfiled).toHaveAttribute('href', '/documents/folders/unfiled')
    expect(await within(unfiled).findByText('2 documents in no folder')).toBeInTheDocument()
    expect(screen.getByText('Invoices 2026')).toBeInTheDocument()
    expect(screen.queryByText('loose-a.pdf')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /new folder/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Folders' })).toHaveAttribute('aria-current', 'page')
  })

  it('lists the documents in no folder under Unfiled', async () => {
    mockApi([filed('1', 'march.pdf'), doc('2', 'loose.pdf', 'needs_review')])
    renderLibrary('/documents/folders/unfiled')

    expect(await screen.findByText('loose.pdf')).toBeInTheDocument()
    expect(screen.queryByText('march.pdf')).not.toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('FoldersUnfiled')
    expect(screen.queryByRole('button', { name: /new folder/i })).not.toBeInTheDocument() // not a real folder
  })

  it('says so when nothing is unfiled', async () => {
    mockApi([filed('1', 'march.pdf')])
    renderLibrary('/documents/folders/unfiled')

    expect(await screen.findByText('Nothing unfiled: every document is in a folder')).toBeInTheDocument()
  })

  it('shows a folder with its breadcrumb and documents', async () => {
    mockApi([filed('1', 'march.pdf'), doc('2', 'loose.pdf', 'needs_review')])
    renderLibrary('/documents/folders/f1')

    expect(await screen.findByText('march.pdf')).toBeInTheDocument()
    expect(screen.queryByText('loose.pdf')).not.toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(crumbs).getByRole('link', { name: 'Folders' })).toHaveAttribute('href', '/documents/folders')
    expect(await within(crumbs).findByText('Invoices 2026')).toHaveAttribute('aria-current', 'page')
  })
})

describe('Document actions', () => {
  it('renames a document', async () => {
    const changes = mockApi([doc('1', 'IMG_0042.pdf', 'needs_review')])
    renderLibrary()

    await userEvent.click(await screen.findByRole('button', { name: 'Actions for IMG_0042.pdf' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Rename' }))
    const name = screen.getByRole('textbox', { name: 'Document name' })
    await userEvent.clear(name)
    await userEvent.type(name, 'March invoice.pdf{Enter}')

    await waitFor(() => expect(changes).toEqual([{ method: 'PATCH', path: '/api/v1/documents/1', body: { filename: 'March invoice.pdf' } }]))
  })

  it('moves a document into a folder', async () => {
    const changes = mockApi([doc('1', 'loose.pdf', 'needs_review')])
    renderLibrary()

    await userEvent.click(await screen.findByRole('button', { name: 'Actions for loose.pdf' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Move to…' }))
    const dialog = screen.getByRole('dialog', { name: 'Move document' })
    expect(within(dialog).getByRole('button', { name: 'Already here' })).toBeDisabled() // it is unfiled
    await userEvent.click(await within(dialog).findByRole('button', { name: /Invoices 2026/ }))
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Move to Invoices 2026' }))

    await waitFor(() => expect(changes).toEqual([{ method: 'PATCH', path: '/api/v1/documents/1', body: { folder_id: 'f1' } }]))
  })

  it('moves a document out of its folder to Unfiled', async () => {
    const changes = mockApi([filed('1', 'march.pdf')])
    renderLibrary()

    await userEvent.click(await screen.findByRole('button', { name: 'Actions for march.pdf' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Move to…' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move to Unfiled' }))

    await waitFor(() => expect(changes).toEqual([{ method: 'PATCH', path: '/api/v1/documents/1', body: { folder_id: null } }]))
  })

  it('deletes a document after asking', async () => {
    const changes = mockApi([doc('1', 'wrong-upload.pdf', 'needs_review')])
    renderLibrary()

    await userEvent.click(await screen.findByRole('button', { name: 'Actions for wrong-upload.pdf' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('This cannot be undone.')
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(changes).toEqual([{ method: 'DELETE', path: '/api/v1/documents/1', body: null }]))
  })

  it('explains why a verified document is kept instead of deleting it', async () => {
    const changes = mockApi([doc('1', 'audited.pdf', 'verified')])
    renderLibrary()

    await userEvent.click(await screen.findByRole('button', { name: 'Actions for audited.pdf' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))

    const dialog = screen.getByRole('dialog', { name: 'Kept for the audit trail' })
    expect(within(dialog).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    expect(changes).toEqual([])
  })
})
