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
/** Confirm requests seen by the fake API (cleared before each test). */
const confirms: { version: number }[] = []

/** Fake API: records each saved body; answers with the next version, or with `failWith`. */
function mockSaves(failWith?: { status: number; code: string; message: string }) {
  const saved: { version: number; lines: Partial<DraftLine>[] }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const body = await input.json()
      const json = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } })
      if (new URL(input.url).pathname.endsWith('/confirm')) {
        confirms.push(body)
        if (failWith) return json({ error: { code: failWith.code, message: failWith.message } }, failWith.status)
        return json({ document_id: 'doc-1', version: 1, based_on_run_id: 'run-1', confirmed_by: null,
                      confirmed_at: '2026-10-20T09:00:00Z', lines: [] }, 201)
      }
      saved.push(body)
      if (failWith) return json({ error: { code: failWith.code, message: failWith.message } }, failWith.status)
      return json(draft(body.lines.map((l: DraftLine) => ({ ...LINES.find((x) => x.line_id === l.line_id)!, ...l })), body.version + 1))
    }),
  )
  return saved
}

function renderWorkspace(props: Partial<Parameters<typeof ReviewWorkspace>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onReload = vi.fn()
  const onConfirmed = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <ReviewWorkspace documentId="doc-1" pages={PAGES} draft={draft()} readOnly={false} onReload={onReload}
                       onConfirmed={onConfirmed} autosaveDelayMs={0} {...props} />
    </QueryClientProvider>,
  )
  return { onReload, onConfirmed }
}

const box = (text: string) => screen.getByRole('button', { name: `Line: ${text}` })
const row = (text: string) => screen.getByText(text, { selector: 'span' }).closest('li')!
const rowButton = (text: string) => within(row(text)).getAllByRole('button')[0]

beforeEach(() => {
  localStorage.clear()
  confirms.length = 0
})
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

    expect(screen.getByText(/Reopen the document to make changes/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })
})

/** jsdom has no layout: put page 1 (200x100) on screen at (0, 0), scale 1. */
function placePage() {
  const svg = screen.getByLabelText('Line boxes')
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => ({}) })
  return svg
}

function drag(start: Element, from: [number, number], to: [number, number], over: Element = start) {
  fireEvent.pointerDown(start, { button: 0, pointerId: 1, clientX: from[0], clientY: from[1] })
  fireEvent.pointerMove(over, { pointerId: 1, clientX: to[0], clientY: to[1] })
  fireEvent.pointerUp(over, { pointerId: 1, clientX: to[0], clientY: to[1] })
}

describe('box editing', () => {
  it('draws a box for missed text, types its text, and places it in reading order', async () => {
    const saved = mockSaves()
    renderWorkspace()
    const svg = placePage()

    await userEvent.click(screen.getByRole('button', { name: /add box/i }))
    drag(svg, [20, 42], [120, 48])
    await userEvent.type(screen.getByRole('textbox', { name: 'Line text' }), 'Discount 1.00{Enter}')

    await waitFor(() => expect(saved.at(-1)?.lines).toHaveLength(5))
    const added = saved.at(-1)!.lines[1] // between TOTAL (y 20-40) and VAT (y 50-70)
    expect(added).toMatchObject({ region_id: null, text: 'Discount 1.00', box: [20, 42, 120, 48], human_action: 'added', sequence: 1 })
    expect(screen.getByRole('button', { name: 'Line: Discount 1.00' })).toBeInTheDocument()
  })

  it('removes a box again when its text is cancelled while empty', async () => {
    const saved = mockSaves()
    renderWorkspace()
    const svg = placePage()

    await userEvent.keyboard('b') // draw mode from the keyboard
    drag(svg, [20, 42], [120, 48])
    await userEvent.keyboard('{Escape}')

    expect(screen.getAllByRole('button', { name: /^Line: / })).toHaveLength(2)
    await waitFor(() => expect(saved.at(-1)?.lines ?? LINES).toHaveLength(4))
  })

  it('moves the selected box by dragging it', async () => {
    const saved = mockSaves()
    renderWorkspace()
    placePage()
    await userEvent.click(box('TOTAL 42.00'))

    drag(box('TOTAL 42.00'), [50, 30], [60, 35], screen.getByLabelText('Line boxes'))

    await waitFor(() => expect(saved.at(-1)?.lines[0]).toMatchObject({ box: [20, 25, 120, 45], human_action: 'edited' }))
  })

  it('resizes the selected box from a corner handle', async () => {
    const saved = mockSaves()
    renderWorkspace()
    placePage()
    await userEvent.click(box('TOTAL 42.00'))

    drag(screen.getByLabelText('Resize from the se corner'), [110, 40], [130, 50], screen.getByLabelText('Line boxes'))

    await waitFor(() => expect(saved.at(-1)?.lines[0].box).toEqual([10, 20, 130, 50]))
  })

  it('does not move a box on a plain click', async () => {
    const saved = mockSaves()
    renderWorkspace()
    placePage()
    await userEvent.click(box('TOTAL 42.00'))

    drag(box('TOTAL 42.00'), [50, 30], [51, 31], screen.getByLabelText('Line boxes')) // under 3px

    expect(box('TOTAL 42.00')).toHaveAttribute('x', '10')
    expect(saved).toHaveLength(0)
  })
})

describe('bulk actions', () => {
  it('accepts marked lines together in one save and one undo step', async () => {
    const saved = mockSaves()
    renderWorkspace()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Mark TOTAL 42.00' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Mark Thank you' }))
    expect(screen.getByText('2 marked')).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('toolbar', { name: 'Bulk actions' })).getByRole('button', { name: /accept 2/i }))

    await waitFor(() => expect(saved).toHaveLength(1))
    expect(saved[0].lines.map((l) => l.human_action)).toEqual(['accepted', 'deleted', 'untouched', 'accepted'])
    expect(screen.queryByText('2 marked')).not.toBeInTheDocument() // marks cleared

    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(saved.at(-1)?.lines.map((l) => l.human_action)).toEqual(['untouched', 'deleted', 'untouched', 'untouched']))
  })

  it('marks every unreviewed line and deletes them, counting only lines it will change', async () => {
    const saved = mockSaves()
    renderWorkspace()

    await userEvent.click(screen.getByRole('button', { name: 'Mark unreviewed' }))
    const bar = screen.getByRole('toolbar', { name: 'Bulk actions' })
    expect(screen.getByText('3 marked')).toBeInTheDocument() // VAT is already deleted
    await userEvent.click(within(bar).getByRole('button', { name: /delete 3/i }))

    await waitFor(() => expect(saved.at(-1)?.lines.every((l) => l.human_action === 'deleted')).toBe(true))
  })

  it('marks a range with Shift-click and acts on it from the keyboard', async () => {
    const saved = mockSaves()
    renderWorkspace()
    const user = userEvent.setup() // one session, so the held Shift key carries into the click

    await user.click(rowButton('TOTAL 42.00'))
    await user.keyboard('{Shift>}')
    await user.click(rowButton('RÉPORTING'))
    await user.keyboard('{/Shift}')
    expect(screen.getByText('3 marked')).toBeInTheDocument()

    await user.keyboard('a') // accepts the marked lines, not just the selected one
    await waitFor(() => expect(saved.at(-1)?.lines.map((l) => l.human_action)).toEqual(['accepted', 'deleted', 'accepted', 'untouched']))
  })

  it('marks the selected line with X, and clears marks with Escape', async () => {
    renderWorkspace()
    await userEvent.click(rowButton('TOTAL 42.00'))

    await userEvent.keyboard('x')
    expect(screen.getByRole('checkbox', { name: 'Mark TOTAL 42.00' })).toBeChecked()

    await userEvent.keyboard('{Escape}')
    expect(screen.getByRole('checkbox', { name: 'Mark TOTAL 42.00' })).not.toBeChecked()
  })
})

describe('confirming', () => {
  const confirmButton = () => screen.getByRole('button', { name: /confirm document/i })

  it('waits for unsaved changes before it can confirm', async () => {
    mockSaves()
    renderWorkspace({ autosaveDelayMs: 50 })
    expect(confirmButton()).toBeEnabled() // nothing to save yet

    await userEvent.click(rowButton('TOTAL 42.00'))
    await userEvent.keyboard('{Delete}')
    expect(confirmButton()).toBeDisabled()

    await waitFor(() => expect(confirmButton()).toBeEnabled())
  })

  it('says what confirming will do, then confirms the saved version', async () => {
    mockSaves()
    const { onConfirmed } = renderWorkspace()

    await userEvent.click(confirmButton())
    const dialog = screen.getByRole('dialog', { name: 'Confirm document' })
    expect(dialog).toHaveTextContent('Your review: 1 deleted (left out).')
    expect(dialog).toHaveTextContent('3 lines you have not reviewed will be marked accepted.')
    expect(dialog).toHaveTextContent('1 of them is below the highlight threshold (0.90).')

    await userEvent.click(within(dialog).getByRole('button', { name: 'Accept 3 and confirm' }))

    await waitFor(() => expect(onConfirmed).toHaveBeenCalled())
    expect(confirms).toEqual([{ version: 0 }])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('offers to check the low-confidence lines first', async () => {
    renderWorkspace()

    await userEvent.click(confirmButton())
    await userEvent.click(screen.getByRole('button', { name: /check them first/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(rowButton('RÉPORTING')).toHaveAttribute('aria-current', 'true')
  })

  it('shows why a confirmation was refused and stays open', async () => {
    mockSaves({ status: 409, code: 'draft_conflict', message: 'This draft changed since you opened it.' })
    const { onConfirmed } = renderWorkspace()

    await userEvent.click(confirmButton())
    await userEvent.click(screen.getByRole('button', { name: /and confirm/i }))

    expect(await screen.findByText('This draft changed since you opened it.')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(onConfirmed).not.toHaveBeenCalled()
  })

  it('ignores review shortcuts while the dialog is open', async () => {
    renderWorkspace()
    await userEvent.click(rowButton('TOTAL 42.00'))

    await userEvent.click(confirmButton())
    await userEvent.keyboard('{Delete}')

    expect(screen.getByText('TOTAL 42.00', { selector: 'span' })).not.toHaveClass('line-through')
  })

  it('has no confirm button on a verified document', () => {
    renderWorkspace({ readOnly: true })

    expect(screen.queryByRole('button', { name: /confirm document/i })).not.toBeInTheDocument()
    expect(screen.getByText(/Reopen the document to make changes/)).toBeInTheDocument()
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
