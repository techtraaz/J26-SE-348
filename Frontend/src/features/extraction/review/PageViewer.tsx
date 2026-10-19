import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Maximize2, SquareDashedMousePointer, TriangleAlert, ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

import type { DraftLine, PageOut } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import {
  boxFromPoints,
  boxRect,
  fitWidthScale,
  moveBox,
  resizeBox,
  scrollToShow,
  sizeMatches,
  stepScale,
  toPagePoint,
} from './geometry'
import type { Corner } from './geometry'
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
  editable: boolean
  drawing: boolean // "Add box" mode: dragging on the page draws a new line's box
  onDrawingChange: (drawing: boolean) => void
  onAddBox: (box: number[]) => void
  onMoveBox: (lineId: string, box: number[]) => void
}

type Point = { x: number; y: number }
type Gesture =
  | { kind: 'draw'; start: Point }
  | { kind: 'move'; id: string; start: Point; box: number[]; moved: boolean }
  | { kind: 'resize'; id: string; corner: Corner; box: number[] }

const CORNERS: { corner: Corner; cursor: string }[] = [
  { corner: 'nw', cursor: 'cursor-nwse-resize' },
  { corner: 'ne', cursor: 'cursor-nesw-resize' },
  { corner: 'sw', cursor: 'cursor-nesw-resize' },
  { corner: 'se', cursor: 'cursor-nwse-resize' },
]
const HANDLE_PX = 9 // on screen, at any zoom
const MOVE_THRESHOLD_PX = 3 // a smaller drag is a click

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
  editable,
  drawing,
  onDrawingChange,
  onAddBox,
  onMoveBox,
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

  // ---- box editing (M4.4): a preview follows the pointer; one change is
  // recorded on release, so a drag is one undo step and one save.
  const svgRef = useRef<SVGSVGElement>(null)
  const gesture = useRef<Gesture | null>(null)
  const [preview, setPreview] = useState<{ id: string | null; box: number[] } | null>(null)
  const selected = lines.find((l) => l.line_id === selectedId && l.human_action !== 'deleted')

  const pagePoint = (event: ReactPointerEvent): Point =>
    toPagePoint(event.clientX, event.clientY, svgRef.current!.getBoundingClientRect(), page)

  const onSvgPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!editable || event.button !== 0) return
    const target = event.target as Element
    const corner = target.getAttribute('data-handle') as Corner | null
    const point = pagePoint(event)
    if (drawing) {
      gesture.current = { kind: 'draw', start: point }
    } else if (corner && selected) {
      gesture.current = { kind: 'resize', id: selected.line_id, corner, box: [...selected.box] }
    } else if (selected && target.getAttribute('data-line-id') === selected.line_id) {
      gesture.current = { kind: 'move', id: selected.line_id, start: point, box: [...selected.box], moved: false }
    } else {
      return // a click on another box selects it; elsewhere the viewport pans
    }
    event.stopPropagation()
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  const onSvgPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const g = gesture.current
    if (!g) return
    const point = pagePoint(event)
    if (g.kind === 'draw') {
      setPreview({ id: null, box: boxFromPoints(g.start, point, page) ?? [g.start.x, g.start.y, g.start.x, g.start.y] })
    } else if (g.kind === 'resize') {
      setPreview({ id: g.id, box: resizeBox(g.box, g.corner, point, page) })
    } else {
      const dx = point.x - g.start.x
      const dy = point.y - g.start.y
      if (!g.moved && Math.hypot(dx, dy) * scale < MOVE_THRESHOLD_PX) return
      g.moved = true
      setPreview({ id: g.id, box: moveBox(g.box, dx, dy, page) })
    }
  }

  const onSvgPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    const g = gesture.current
    gesture.current = null
    setPreview(null)
    if (!g) return
    const point = pagePoint(event)
    if (g.kind === 'draw') {
      const box = boxFromPoints(g.start, point, page)
      if (box) onAddBox(box)
    } else if (g.kind === 'resize') {
      onMoveBox(g.id, resizeBox(g.box, g.corner, point, page))
    } else if (g.moved) {
      onMoveBox(g.id, moveBox(g.box, point.x - g.start.x, point.y - g.start.y, page))
    }
  }

  const cancelGesture = () => {
    gesture.current = null
    setPreview(null)
  }

  // Drag the page to pan (clicks on boxes still select).
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || drawing || (event.target as Element).closest('[data-line-box]')) return
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
          {editable && (
            <Button
              variant={drawing ? 'primary' : 'ghost'}
              size="sm"
              aria-pressed={drawing}
              title="Draw a box around text the engine missed (B)"
              onClick={() => onDrawingChange(!drawing)}
              className="mr-1"
            >
              <SquareDashedMousePointer size={15} aria-hidden /> {drawing ? 'Drawing… (Esc)' : 'Add box'}
            </Button>
          )}
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
        className={clsx(
          'relative min-h-0 flex-1 overflow-auto bg-surface-muted',
          drawing ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing',
        )}
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
            ref={svgRef}
            viewBox={`0 0 ${page.width} ${page.height}`}
            preserveAspectRatio="none"
            className={clsx('absolute inset-0 size-full touch-none', drawing && 'cursor-crosshair')}
            aria-label="Line boxes"
            onPointerDown={onSvgPointerDown}
            onPointerMove={onSvgPointerMove}
            onPointerUp={onSvgPointerUp}
            onPointerCancel={cancelGesture}
          >
            {lines.map((line) => {
              const r = boxRect(preview?.id === line.line_id ? preview.box : line.box)
              const selected = line.line_id === selectedId
              const movable = editable && selected && !drawing && line.human_action !== 'deleted'
              return (
                <rect
                  key={line.line_id}
                  data-line-box
                  data-line-id={line.line_id}
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
                    movable ? 'cursor-move' : drawing ? 'pointer-events-none' : 'cursor-pointer',
                    'transition-[fill,stroke]',
                    selected ? 'fill-primary/15 stroke-primary [stroke-width:2.5]' : BOX_STYLE[boxState(line, threshold)],
                    line.human_action === 'deleted' && '[stroke-dasharray:4_3] opacity-50',
                  )}
                />
              )
            })}

            {/* Resize handles on the selected box, a constant size on screen. */}
            {editable && !drawing && selected && (() => {
              const r = boxRect(preview?.id === selected.line_id ? preview.box : selected.box)
              const size = HANDLE_PX / scale
              const at: Record<Corner, Point> = {
                nw: { x: r.x, y: r.y },
                ne: { x: r.x + r.width, y: r.y },
                sw: { x: r.x, y: r.y + r.height },
                se: { x: r.x + r.width, y: r.y + r.height },
              }
              return CORNERS.map(({ corner, cursor }) => (
                <rect
                  key={corner}
                  data-line-box
                  data-handle={corner}
                  aria-label={`Resize from the ${corner} corner`}
                  x={at[corner].x - size / 2}
                  y={at[corner].y - size / 2}
                  width={size}
                  height={size}
                  vectorEffect="non-scaling-stroke"
                  className={clsx(cursor, 'fill-surface stroke-primary [stroke-width:1.5]')}
                />
              ))
            })()}

            {/* The box being drawn. */}
            {preview && preview.id === null && (
              <rect
                {...boxRect(preview.box)}
                vectorEffect="non-scaling-stroke"
                className="pointer-events-none fill-primary/10 stroke-primary [stroke-dasharray:5_3] [stroke-width:1.5]"
              />
            )}
          </svg>
        </div>
      </div>
    </div>
  )
}
