import clsx from 'clsx'
import { CircleAlert, CloudCheck, LoaderCircle, Redo2, Undo2 } from 'lucide-react'
import { useEffect, useReducer, useRef, useState } from 'react'

import { pageImageUrl } from '@/features/extraction/api/client'
import type { PageOut, ReviewDraft } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import { LineList } from './LineList'
import { PageViewer } from './PageViewer'
import { initReview, neighbour, nextFlagged, reviewReducer } from './reviewState'
import { useDisplayThreshold } from './useDisplayThreshold'
import { useDraftAutosave } from './useDraftAutosave'
import type { SaveStatus } from './useDraftAutosave'

interface ReviewWorkspaceProps {
  documentId: string
  pages: PageOut[]
  draft: ReviewDraft // read once: the workspace owns the working copy afterwards
  readOnly: boolean
  onReload: () => void
  autosaveDelayMs?: number
}

/** Split pane: the page with its boxes on the left, the lines on the right.
 * Selecting a box selects its line and vice versa; edits autosave. */
export function ReviewWorkspace({
  documentId,
  pages,
  draft,
  readOnly,
  onReload,
  autosaveDelayMs,
}: ReviewWorkspaceProps) {
  const [state, dispatch] = useReducer(reviewReducer, draft.lines, initReview)
  const [pageNumber, setPageNumber] = useState(pages[0]?.page_number ?? 1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [threshold, setThreshold] = useDisplayThreshold()
  const { lines } = state

  const status = useDraftAutosave({
    documentId,
    basedOnRunId: draft.based_on_run_id,
    initialVersion: draft.version,
    lines,
    revision: state.revision,
    enabled: !readOnly,
    delayMs: autosaveDelayMs,
  })
  const locked = readOnly || status.kind === 'conflict'

  const select = (lineId: string | null) => {
    const line = lines.find((l) => l.line_id === lineId)
    if (!line) return
    setSelectedId(line.line_id)
    setPageNumber(line.page) // a line on another page opens that page
  }

  /** Returns true when the key was a review shortcut. */
  function handleKey(event: KeyboardEvent): boolean {
    const key = event.key.toLowerCase()
    if (event.ctrlKey || event.metaKey) {
      if (locked) return false
      if (key === 'z') dispatch({ type: event.shiftKey ? 'redo' : 'undo' })
      else if (key === 'y') dispatch({ type: 'redo' })
      else return false
      return true
    }
    if (event.altKey) return false

    if (key === 'arrowdown' || key === 'j') select(neighbour(lines, selectedId, 1))
    else if (key === 'arrowup' || key === 'k') select(neighbour(lines, selectedId, -1))
    else if (key === 'n') select(nextFlagged(lines, selectedId, threshold))
    else return handleLineKey(key)
    return true
  }

  /** Keys that act on the selected line. */
  function handleLineKey(key: string): boolean {
    const line = lines.find((l) => l.line_id === selectedId)
    if (!line || locked) return false
    if (key === 'a') {
      dispatch({ type: 'accept', id: line.line_id })
      select(neighbour(lines, line.line_id, 1)) // accept and move on
    } else if ((key === 'enter' || key === 'e') && line.human_action !== 'deleted') {
      setEditingId(line.line_id)
    } else if (key === 'delete' || key === 'backspace') {
      dispatch({ type: line.human_action === 'deleted' ? 'restore' : 'delete', id: line.line_id })
    } else {
      return false
    }
    return true
  }
  // Keyboard flow (UC4). Ignored while typing; the textarea handles its own keys.
  const keys = useRef<(event: KeyboardEvent) => void>(() => {})
  useEffect(() => {
    keys.current = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (handleKey(event)) event.preventDefault()
    }
  })

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keys.current(event)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const page = pages.find((p) => p.page_number === pageNumber) ?? pages[0]
  if (!page) return <p className="text-sm text-ink-muted">This document has no pages.</p>

  return (
    // On large screens the workspace fills the window below the page header,
    // and each pane scrolls inside itself.
    <div className="flex flex-col gap-3 lg:h-[calc(100vh-23rem)] lg:min-h-128">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {readOnly ? (
          <p className="text-[13px] text-ink-muted">This document is verified. Reopening it for edits comes with confirmation.</p>
        ) : (
          <SaveIndicator status={status} />
        )}
        {!readOnly && (
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" disabled={locked || state.past.length === 0} onClick={() => dispatch({ type: 'undo' })}>
              <Undo2 size={14} aria-hidden /> Undo
            </Button>
            <Button variant="ghost" size="sm" disabled={locked || state.future.length === 0} onClick={() => dispatch({ type: 'redo' })}>
              <Redo2 size={14} aria-hidden /> Redo
            </Button>
          </div>
        )}
      </div>

      {status.kind === 'conflict' && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger/8 px-4 py-2.5 text-sm text-danger">
          <span>
            <span className="font-medium">Not saved.</span> {status.message} Edits are paused so nothing is overwritten.
          </span>
          <Button size="sm" onClick={onReload}>Reload the latest draft</Button>
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_23rem]">
        <div className="h-[65vh] min-h-0 lg:h-auto">
          <PageViewer
            page={page}
            pageCount={pages.length}
            imageUrl={pageImageUrl(documentId, page.page_number)}
            lines={lines.filter((l) => l.page === page.page_number)}
            selectedId={selectedId}
            threshold={threshold}
            onSelect={select}
            onPageChange={setPageNumber}
          />
        </div>
        <div className="h-[60vh] min-h-0 lg:h-auto">
          <LineList
            lines={lines}
            selectedId={selectedId}
            onSelect={select}
            editingId={locked ? null : editingId}
            onEditingChange={setEditingId}
            onEditDone={(id) => select(neighbour(lines, id, 1) ?? id)}
            dispatch={dispatch}
            threshold={threshold}
            onThresholdChange={setThreshold}
            readOnly={locked}
          />
        </div>
      </div>
    </div>
  )
}

function SaveIndicator({ status }: { status: SaveStatus }) {
  const base = 'flex items-center gap-1.5 text-[13px]'
  switch (status.kind) {
    case 'saving':
      return (
        <p className={clsx(base, 'text-ink-muted')} role="status">
          <LoaderCircle size={14} className="animate-spin" aria-hidden /> Saving…
        </p>
      )
    case 'unsaved':
      return <p className={clsx(base, 'text-ink-muted')} role="status">Unsaved changes</p>
    case 'retrying':
      return (
        <p className={clsx(base, 'text-warning')} role="status">
          <CircleAlert size={14} aria-hidden /> Not saved yet: {status.message} Retrying…
        </p>
      )
    case 'conflict':
      return (
        <p className={clsx(base, 'text-danger')} role="status">
          <CircleAlert size={14} aria-hidden /> Not saved
        </p>
      )
    default:
      return (
        <p className={clsx(base, 'text-ink-muted')} role="status">
          <CloudCheck size={14} className="text-success" aria-hidden /> All changes saved
        </p>
      )
  }
}
