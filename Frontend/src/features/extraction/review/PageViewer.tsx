import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Maximize2, TriangleAlert, ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

import type { DraftLine, PageOut } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import { boxRect, fitWidthScale, scrollToShow, sizeMatches, stepScale } from './geometry'
import { isFlagged, isReviewed } from './reviewState'

const PADDING = 16 // around the page inside the viewport

type BoxState = 'check' | 'reviewed' | 'untouched'

// Amber: low confidence, nobody has looked yet. Green: reviewed. Blue: the rest.
const BOX_STYLE: Record<BoxState, string> = {
  check: 'fill-warning/15 stroke-warning [stroke-width:1.75] hover:fill-warning/25',
  reviewed: 'fill-success/5 stroke-success/60 [stroke-width:1.25] hover:fill-success/15',
  untouched: 'fill-info/5 stroke-info/70 [stroke-width:1.25] hover:fill-info/15',
}

function boxState(line: DraftLine, threshold: number): BoxState {
  if (isReviewed(line)) return 'reviewed'
  return isFlagged(line, threshold) ? 'check' : 'untouched'
}

interface PageViewerProps {
  page: PageOut
  pageCount: number
  imageUrl: string
  lines: DraftLine[] // this page's lines
  selectedId: string | null
  threshold: number // display only (D4)
  onSelect: (lineId: string) => void
  onPageChange: (pageNumber: number) => void
}

/** One page image with its line boxes drawn on top. The SVG's viewBox is the
 * page's OCR-space size, so each box is drawn in the engine's own pixels and
 * scales with the image (see geometry.ts). */
export function PageViewer({
  page,
  pageCount,
  imageUrl,
  lines,
  selectedId,
  threshold,
  onSelect,
  onPageChange,
}: PageViewerProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [viewportWidth, setViewportWidth] = useState(0)
  // null = fit to width (follows resizes); a number = the reviewer's zoom.
  const [zoom, setZoom] = useState<number | null>(null)
  const [mismatch, setMismatch] = useState(false)
  const scale = zoom ?? fitWidthScale(page, viewportWidth, PADDING)

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    setViewportWidth(viewport.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setViewportWidth(viewport.clientWidth))
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [])

  // Ctrl + wheel zooms (a non-passive listener, so the browser's page zoom is prevented).
  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return
      event.preventDefault()
      setZoom((z) => stepScale(z ?? fitWidthScale(page, viewport.clientWidth, PADDING), event.deltaY < 0 ? 1 : -1))
    }
    viewport.addEventListener('wheel', onWheel, { passive: false })
    return () => viewport.removeEventListener('wheel', onWheel)
  }, [page])

  // Bring the selected line's box into view when it is off screen.
  useEffect(() => {
    const viewport = viewportRef.current
    const line = lines.find((l) => l.line_id === selectedId)
    if (!viewport || !line) return
    const target = scrollToShow(line.box, scale, {
      scrollLeft: viewport.scrollLeft - PADDING,
      scrollTop: viewport.scrollTop - PADDING,
      width: viewport.clientWidth,
      height: viewport.clientHeight,
    })
    if (target) viewport.scrollTo?.({ left: target.left, top: target.top, behavior: 'smooth' })
  }, [selectedId, lines, scale])

  // Drag the page to pan (clicks on boxes still select).
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as Element).closest('[data-line-box]')) return
    const viewport = event.currentTarget
    drag.current = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop }
    viewport.setPointerCapture?.(event.pointerId)
  }
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    event.currentTarget.scrollLeft = drag.current.left - (event.clientX - drag.current.x)
    event.currentTarget.scrollTop = drag.current.top - (event.clientY - drag.current.y)
  }
  const endDrag = () => {
    drag.current = null
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line-light bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-light px-3 py-2">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            aria-label="Previous page"
            disabled={page.page_number <= 1}
            onClick={() => onPageChange(page.page_number - 1)}
          >
            <ChevronLeft size={16} />
          </Button>
          <span className="min-w-20 text-center text-xs text-ink-muted tabular-nums">
            Page {page.page_number} of {pageCount}
          </span>
          <Button
            variant="ghost"
            size="sm"
            aria-label="Next page"
            disabled={page.page_number >= pageCount}
            onClick={() => onPageChange(page.page_number + 1)}
          >
            <ChevronRight size={16} />
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" aria-label="Zoom out" onClick={() => setZoom(stepScale(scale, -1))}>
            <ZoomOut size={16} />
          </Button>
          <span className="min-w-12 text-center text-xs text-ink-muted tabular-nums" aria-label="Zoom level">
            {Math.round(scale * 100)}%
          </span>
          <Button variant="ghost" size="sm" aria-label="Zoom in" onClick={() => setZoom(stepScale(scale, 1))}>
            <ZoomIn size={16} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label="Fit to width"
            aria-pressed={zoom === null}
            onClick={() => setZoom(null)}
          >
            <Maximize2 size={15} />
          </Button>
        </div>
      </div>

      {mismatch && (
        <p role="alert" className="flex items-center gap-2 border-b border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <TriangleAlert size={14} aria-hidden /> This image is not the size the boxes were measured on, so boxes may be misplaced.
        </p>
      )}

      <div
        ref={viewportRef}
        data-testid="page-viewport"
        className="relative min-h-0 flex-1 cursor-grab overflow-auto bg-surface-muted active:cursor-grabbing"
        style={{ padding: PADDING }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div
          className="relative mx-auto bg-surface shadow-(--shadow-md)"
          style={{ width: page.width * scale, height: page.height * scale }}
        >
          <img
            key={imageUrl}
            src={imageUrl}
            alt={`Page ${page.page_number}`}
            draggable={false}
            className="pointer-events-none block size-full select-none"
            onLoad={(event) =>
              setMismatch(
                !sizeMatches(
                  { width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight },
                  page,
                ),
              )
            }
          />
          <svg
            viewBox={`0 0 ${page.width} ${page.height}`}
            preserveAspectRatio="none"
            className="absolute inset-0 size-full"
            aria-label="Line boxes"
          >
            {lines.map((line) => {
              const r = boxRect(line.box)
              const selected = line.line_id === selectedId
              return (
                <rect
                  key={line.line_id}
                  data-line-box
                  x={r.x}
                  y={r.y}
                  width={r.width}
                  height={r.height}
                  role="button"
                  aria-label={`Line: ${line.text}`}
                  aria-pressed={selected}
                  vectorEffect="non-scaling-stroke"
                  onClick={() => onSelect(line.line_id)}
                  data-state={boxState(line, threshold)}
                  className={clsx(
                    'cursor-pointer transition-[fill,stroke]',
                    selected ? 'fill-primary/15 stroke-primary [stroke-width:2.5]' : BOX_STYLE[boxState(line, threshold)],
                    line.human_action === 'deleted' && '[stroke-dasharray:4_3] opacity-50',
                  )}
                />
              )
            })}
          </svg>
        </div>
      </div>
    </div>
  )
}
