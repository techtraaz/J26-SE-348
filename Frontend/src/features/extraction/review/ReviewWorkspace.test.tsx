import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { DraftLine, PageOut } from '@/features/extraction/api/types'
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
  line('c', 2, 2, 'Thank you', [30, 60, 150, 90], { confidence: null }),
]

function renderWorkspace() {
  return render(<ReviewWorkspace documentId="doc-1" pages={PAGES} lines={LINES} />)
}

const box = (text: string) => screen.getByRole('button', { name: `Line: ${text}` })
const row = (text: string) => screen.getByText(text, { selector: 'span' }).closest('button')!

describe('ReviewWorkspace', () => {
  it('draws each box in the page pixels the engine reported', () => {
    renderWorkspace()

    const overlay = screen.getByLabelText('Line boxes')
    expect(overlay).toHaveAttribute('viewBox', '0 0 200 100') // = the OCR-space page size
    const rect = box('TOTAL 42.00')
    expect([rect.getAttribute('x'), rect.getAttribute('y'), rect.getAttribute('width'), rect.getAttribute('height')])
      .toEqual(['10', '20', '100', '20'])
    // Only page 1's boxes are drawn.
    expect(within(overlay).getAllByRole('button')).toHaveLength(2)
  })

  it('sizes the page to its pixels times the zoom, so image and boxes scale together', async () => {
    renderWorkspace()
    const page = screen.getByAltText('Page 1').parentElement!
    expect(page).toHaveStyle({ width: '200px', height: '100px' }) // no width to fit in jsdom: 100%

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))

    expect(screen.getByLabelText('Zoom level')).toHaveTextContent('125%')
    expect(page).toHaveStyle({ width: '250px', height: '125px' })
  })

  it('selects the line when its box is clicked, and the box when its line is clicked', async () => {
    renderWorkspace()

    await userEvent.click(box('TOTAL 42.00'))
    expect(row('TOTAL 42.00')).toHaveAttribute('aria-current', 'true')
    expect(box('TOTAL 42.00')).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(row('VAT 6.30'))
    expect(box('VAT 6.30')).toHaveAttribute('aria-pressed', 'true')
    expect(box('TOTAL 42.00')).toHaveAttribute('aria-pressed', 'false')
  })

  it('opens the right page when a line on another page is selected', async () => {
    renderWorkspace()

    await userEvent.click(row('Thank you'))

    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Line boxes')).toHaveAttribute('viewBox', '0 0 300 150')
    expect(box('Thank you')).toHaveAttribute('aria-pressed', 'true')
  })

  it('pages through the document', async () => {
    renderWorkspace()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))

    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
    expect(screen.getByAltText('Page 2')).toHaveAttribute('src', 'http://127.0.0.1:8000/api/v1/documents/doc-1/pages/2/image')
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  })

  it('lists lines in reading order with their raw confidence, grouped by page', () => {
    renderWorkspace()

    expect(screen.getByRole('region', { name: 'Page 1' })).toHaveTextContent('TOTAL 42.00')
    expect(screen.getByRole('region', { name: 'Page 2' })).toHaveTextContent('Thank you')
    expect(row('TOTAL 42.00')).toHaveTextContent('0.97')
    expect(row('Thank you')).toHaveTextContent('—') // no score
    expect(screen.getByText('VAT 6.30', { selector: 'span' })).toHaveClass('line-through') // deleted
  })
})
