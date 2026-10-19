import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DraftLine, PageOut, ReviewDraft } from '@/features/extraction/api/types'
import { ReviewWorkspace } from './ReviewWorkspace'

const PAGES: PageOut[] = [
  { page_number: 1, width: 200, height: 100, dpi: null, image_url: '/p1' },
  { page_number: 2, width: 300, height: 150, dpi: null, image_url: '/p2' },
]

function line(id: string, page: number, sequence: number, text: string, box: number[], extra: Partial<DraftLine> = {}): DraftLine {
  return {
    line_id: id, region_id: id, page, sequence, text, box, human_action: 'untouched',
    confidence: 0.97, provenance: 'paddleocr', escalated: null, ...extra,
  }
}

const LINES = [
  line('a', 1, 0, 'TOTAL 42.00', [10, 20, 110, 40]),
  line('b', 1, 1, 'VAT 6.30', [10, 50, 90, 70], { human_action: 'deleted' }),
  line('c', 2, 2, 'RÉPORTING', [30, 60, 150, 90], { confidence: 0.41 }),
  line('d', 2, 3, 'Thank you', [30, 100, 150, 120], { confidence: null }),
]

function draft(lines = LINES, version = 0): ReviewDraft {
  return { document_id: 'doc-1', based_on_run_id: 'run-1', version, updated_at: null, lines }
}

/** Fake API: records each saved body; answers with the next version, or with `failWith`. */
function mockSaves(failWith?: { status: number; code: string; message: string }) {
  const saved: { version: number; lines: Partial<DraftLine>[] }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const body = await input.json()
      saved.push(body)
      const json = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } })
      if (failWith) return json({ error: { code: failWith.code, message: failWith.message } }, failWith.status)
      return json(draft(body.lines.map((l: DraftLine) => ({ ...LINES.find((x) => x.line_id === l.line_id)!, ...l })), body.version + 1))
    }),
  )
  return saved
}

function renderWorkspace(props: Partial<Parameters<typeof ReviewWorkspace>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onReload = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <ReviewWorkspace documentId="doc-1" pages={PAGES} draft={draft()} readOnly={false} onReload={onReload} autosaveDelayMs={0} {...props} />
    </QueryClientProvider>,
  )
  return { onReload }
}

const box = (text: string) => screen.getByRole('button', { name: `Line: ${text}` })
const row = (text: string) => screen.getByText(text, { selector: 'span' }).closest('li')!
const rowButton = (text: string) => within(row(text)).getAllByRole('button')[0]

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('viewer', () => {
  it('draws each box in the page pixels the engine reported', () => {
    renderWorkspace()

    const overlay = screen.getByLabelText('Line boxes')
    expect(overlay).toHaveAttribute('viewBox', '0 0 200 100') // = the OCR-space page size
    const rect = box('TOTAL 42.00')
    expect([rect.getAttribute('x'), rect.getAttribute('y'), rect.getAttribute('width'), rect.getAttribute('height')])
      .toEqual(['10', '20', '100', '20'])
    expect(within(overlay).getAllByRole('button')).toHaveLength(2) // page 1 only
  })

  it('sizes the page to its pixels times the zoom, so image and boxes scale together', async () => {
    renderWorkspace()
    const page = screen.getByAltText('Page 1').parentElement!
    expect(page).toHaveStyle({ width: '200px', height: '100px' })

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))

    expect(screen.getByLabelText('Zoom level')).toHaveTextContent('125%')
    expect(page).toHaveStyle({ width: '250px', height: '125px' })
  })

  it('selects the line from its box and the box from its line', async () => {
    renderWorkspace()

    await userEvent.click(box('TOTAL 42.00'))
    expect(rowButton('TOTAL 42.00')).toHaveAttribute('aria-current', 'true')

    await userEvent.click(rowButton('VAT 6.30'))
    expect(box('VAT 6.30')).toHaveAttribute('aria-pressed', 'true')
    expect(box('TOTAL 42.00')).toHaveAttribute('aria-pressed', 'false')
  })

  it('opens the right page for a line on another page, and pages through', async () => {
    renderWorkspace()

    await userEvent.click(rowButton('Thank you'))
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
    expect(box('Thank you')).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(screen.getByAltText('Page 1')).toHaveAttribute('src', 'http://127.0.0.1:8000/api/v1/documents/doc-1/pages/1/image')
  })
})

describe('low-confidence highlight', () => {
  it('marks scored lines below the threshold, never lines without a score', async () => {
    renderWorkspace()
    await userEvent.click(rowButton('RÉPORTING')) // to page 2

    expect(box('RÉPORTING')).toHaveAttribute('data-state', 'check')
    expect(box('Thank you')).toHaveAttribute('data-state', 'untouched')
    expect(screen.getByText(/1 low-confidence line to check/)).toBeInTheDocument()
  })

  it('follows the slider and remembers it in this browser', async () => {
    renderWorkspace()
    const slider = screen.getByRole('slider', { name: 'Low-confidence highlight threshold' })
    expect(slider).toHaveValue('0.9')

    // jsdom does not move range inputs with keys: set the value as a drag would.
    fireEvent.change(slider, { target: { value: '0.98' } })

    // Now TOTAL 42.00 (0.97) is below it too; the deleted line is already reviewed.
    expect(screen.getByText(/2 low-confidence lines to check/)).toBeInTheDocument()
    expect(box('TOTAL 42.00')).toHaveAttribute('data-state', 'check')
    expect(localStorage.getItem('nomos.review.threshold')).toBe('0.98')

    fireEvent.change(slider, { target: { value: '0.4' } }) // below the range: clamped to 0.5
    expect(screen.getByText(/1 low-confidence line to check/)).toBeInTheDocument()
  })
})

describe('editing and autosave', () => {
  it('edits a line, saves it with the draft version, and moves on', async () => {
    const saved = mockSaves()
    renderWorkspace()

    await userEvent.click(rowButton('TOTAL 42.00'))
    await userEvent.click(within(row('TOTAL 42.00')).getByRole('button', { name: /edit/i }))
    const input = screen.getByRole('textbox', { name: 'Line text' })
    await userEvent.clear(input)
    await userEvent.type(input, 'TOTAL 42.50{Enter}')

    await waitFor(() => expect(saved).toHaveLength(1))
    expect(saved[0].version).toBe(0)
    expect(saved[0].lines[0]).toMatchObject({ line_id: 'a', text: 'TOTAL 42.50', human_action: 'edited' })
    expect(saved[0].lines[0]).not.toHaveProperty('confidence') // machine fields never sent
    expect(await screen.findByText('All changes saved')).toBeInTheDocument()
    expect(rowButton('VAT 6.30')).toHaveAttribute('aria-current', 'true') // Enter moved on
  })

  it('bases the next save on the version the server returned', async () => {
    const saved = mockSaves()
    renderWorkspace()

    await userEvent.click(rowButton('TOTAL 42.00'))
    await userEvent.click(within(row('TOTAL 42.00')).getByRole('button', { name: 'Accept' }))
    await waitFor(() => expect(saved).toHaveLength(1))
    await screen.findByText('All changes saved')
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))

    await waitFor(() => expect(saved).toHaveLength(2))
    expect(saved.map((s) => s.version)).toEqual([0, 1])
    expect(saved[1].lines[0].human_action).toBe('untouched') // undo is saved too
  })

  it('deletes and restores a line without removing it', async () => {
    const saved = mockSaves()
    renderWorkspace()

    await userEvent.click(rowButton('VAT 6.30'))
    await userEvent.click(within(row('VAT 6.30')).getByRole('button', { name: 'Restore' }))
    await waitFor(() => expect(saved).toHaveLength(1))
    expect(saved[0].lines).toHaveLength(4)
    expect(saved[0].lines[1]).toMatchObject({ line_id: 'b', human_action: 'untouched' })
  })

  it('pauses editing and offers a reload when the draft changed elsewhere', async () => {
    mockSaves({ status: 409, code: 'draft_conflict', message: 'This draft was changed elsewhere.' })
    const { onReload } = renderWorkspace()

    await userEvent.click(rowButton('TOTAL 42.00'))
    await userEvent.click(within(row('TOTAL 42.00')).getByRole('button', { name: 'Accept' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This draft was changed elsewhere.')
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument() // locked
    await userEvent.click(within(alert).getByRole('button', { name: /reload/i }))
    expect(onReload).toHaveBeenCalled()
  })

  it('shows a verified document without editing controls', async () => {
    renderWorkspace({ readOnly: true })

    await userEvent.click(rowButton('TOTAL 42.00'))

    expect(screen.getByText(/This document is verified/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })
})

describe('keyboard flow', () => {
  it('moves, jumps to the next line to check, accepts and moves on', async () => {
    const saved = mockSaves()
    renderWorkspace()

    await userEvent.keyboard('{ArrowDown}')
    expect(rowButton('TOTAL 42.00')).toHaveAttribute('aria-current', 'true')

    await userEvent.keyboard('n') // the only low-confidence line nobody reviewed
    expect(rowButton('RÉPORTING')).toHaveAttribute('aria-current', 'true')
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()

    await userEvent.keyboard('a')
    expect(rowButton('Thank you')).toHaveAttribute('aria-current', 'true')
    await waitFor(() => expect(saved.at(-1)?.lines[2].human_action).toBe('accepted'))
  })

  it('edits with Enter, cancels with Escape, deletes with Delete and undoes with Ctrl+Z', async () => {
    mockSaves()
    renderWorkspace()
    await userEvent.click(rowButton('TOTAL 42.00'))

    await userEvent.keyboard('{Enter}')
    await userEvent.keyboard('changed{Escape}')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.getByText('TOTAL 42.00', { selector: 'span' })).toBeInTheDocument() // unchanged

    await userEvent.keyboard('{Delete}')
    expect(screen.getByText('TOTAL 42.00', { selector: 'span' })).toHaveClass('line-through')

    await userEvent.keyboard('{Control>}z{/Control}')
    expect(screen.getByText('TOTAL 42.00', { selector: 'span' })).not.toHaveClass('line-through')
  })
})
