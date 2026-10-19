import clsx from 'clsx'
import { BadgeCheck, CircleAlert, CloudCheck, LoaderCircle, Redo2, Undo2 } from 'lucide-react'
import { useEffect, useReducer, useRef, useState } from 'react'

import { pageImageUrl } from '@/features/extraction/api/client'
import { errorMessage } from '@/features/extraction/api/errors'
import { useConfirmDocument } from '@/features/extraction/api/hooks'
import type { PageOut, ReviewDraft } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import { ConfirmDialog } from './ConfirmDialog'
import { LineList } from './LineList'
import { PageViewer } from './PageViewer'
import { initReview, neighbour, newLine, nextFlagged, reviewReducer } from './reviewState'
import { useDisplayThreshold } from './useDisplayThreshold'
import { useDraftAutosave } from './useDraftAutosave'
import type { SaveStatus } from './useDraftAutosave'

interface ReviewWorkspaceProps {
  documentId: string
  pages: PageOut[]
  draft: ReviewDraft // read once: the workspace owns the working copy afterwards
  readOnly: boolean
  onReload: () => void
  onConfirmed: () => void // the document is now verified: the page reloads it
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
  onConfirmed,
  autosaveDelayMs,
}: ReviewWorkspaceProps) {
  const [state, dispatch] = useReducer(reviewReducer, draft.lines, initReview)
  const [pageNumber, setPageNumber] = useState(pages[0]?.page_number ?? 1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [marked, setMarked] = useState<Set<string>>(() => new Set())
  const [drawing, setDrawing] = useState(false)
  const [threshold, setThreshold] = useDisplayThreshold()
  const { lines } = state
  const page = pages.find((p) => p.page_number === pageNumber) ?? pages[0]
  const markedIds = lines.filter((l) => marked.has(l.line_id)).map((l) => l.line_id)

  const { status, version } = useDraftAutosave({
    documentId,
    basedOnRunId: draft.based_on_run_id,
    initialVersion: draft.version,
    lines,
    revision: state.revision,
    enabled: !readOnly,
    delayMs: autosaveDelayMs,
  })
  const locked = readOnly || status.kind === 'conflict'

  // Confirmation is tied to a saved draft version, so it waits for autosave.
  const [confirming, setConfirming] = useState(false)
  const confirm = useConfirmDocument(documentId)
  const canConfirm = !locked && status.kind === 'saved' && !editingId
  const submitConfirm = () =>
    confirm.mutate(version, {
      onSuccess: () => {
        setConfirming(false)
        onConfirmed()
      },
    })

  const select = (lineId: string | null) => {
    const line = lines.find((l) => l.line_id === lineId)
    if (!line) return
    setSelectedId(line.line_id)
    setPageNumber(line.page) // a line on another page opens that page
  }

  /** A box drawn on the page becomes a new line; type its text straight away. */
  const addBox = (box: number[]) => {
    if (!page) return
    const line = newLine(page.page_number, box)
    dispatch({ type: 'addLine', line })
    setDrawing(false)
    setSelectedId(line.line_id)
    setEditingId(line.line_id)
  }

  /** Cancelling the text of a box just drawn removes it again. */
  const cancelEdit = (lineId: string) => {
    const line = lines.find((l) => l.line_id === lineId)
    if (line && line.region_id === null && line.text === '') dispatch({ type: 'discardAdded', id: lineId })
    setEditingId(null)
  }

  const toggleMark = (lineId: string) =>
    setMarked((current) => {
      const next = new Set(current)
      if (!next.delete(lineId)) next.add(lineId)
      return next
    })

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
    else if (key === 'escape' && drawing) setDrawing(false)
    else if (key === 'escape' && markedIds.length > 0) setMarked(new Set())
    else if (key === 'b' && !locked) setDrawing((d) => !d)
    else if (markedIds.length > 0 && !locked) return handleBulkKey(key)
    else return handleLineKey(key)
    return true
  }

  /** With lines marked, A and Del act on all of them (one undo step). */
  function handleBulkKey(key: string): boolean {
    if (key === 'a') {
      dispatch({ type: 'accept', ids: markedIds })
    } else if (key === 'delete' || key === 'backspace') {
      const allDeleted = lines.filter((l) => marked.has(l.line_id)).every((l) => l.human_action === 'deleted')
      dispatch({ type: allDeleted ? 'restore' : 'delete', ids: markedIds })
    } else {
      return handleLineKey(key) // other keys still work on the selected line
    }
    setMarked(new Set())
    return true
  }

  /** Keys that act on the selected line. */
  function handleLineKey(key: string): boolean {
    const line = lines.find((l) => l.line_id === selectedId)
    if (!line || locked) return false
    const ids = [line.line_id]
    if (key === 'a') {
      dispatch({ type: 'accept', ids })
      select(neighbour(lines, line.line_id, 1)) // accept and move on
    } else if ((key === 'enter' || key === 'e') && line.human_action !== 'deleted') {
      setEditingId(line.line_id)
    } else if (key === 'delete' || key === 'backspace') {
      dispatch({ type: line.human_action === 'deleted' ? 'restore' : 'delete', ids })
    } else if (key === 'x') {
      toggleMark(line.line_id)
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
      if (confirming) return // the dialog is open: no edits behind it
      if (handleKey(event)) event.preventDefault()
    }
  })

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keys.current(event)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!page) return <p className="text-sm text-ink-muted">This document has no pages.</p>

  return (
    // On large screens the workspace fills the window below the page header,
    // and each pane scrolls inside itself.
    // A verified document has the page's verified banner instead of this toolbar.
    <div className={clsx('flex flex-col gap-3', readOnly ? 'lg:h-[calc(100vh-28rem)] lg:min-h-104' : 'lg:h-[calc(100vh-23rem)] lg:min-h-128')}>
      <div className={clsx('flex flex-wrap items-center justify-between gap-2', readOnly && 'sr-only')}>
        {readOnly ? (
          <p className="text-[13px] text-ink-muted">Read only. Reopen the document to make changes.</p>
        ) : (
          <SaveIndicator status={status} />
        )}
        {!readOnly && (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" disabled={locked || state.past.length === 0} onClick={() => dispatch({ type: 'undo' })}>
              <Undo2 size={14} aria-hidden /> Undo
            </Button>
            <Button variant="ghost" size="sm" disabled={locked || state.future.length === 0} onClick={() => dispatch({ type: 'redo' })}>
              <Redo2 size={14} aria-hidden /> Redo
            </Button>
            <Button
              variant="primary"
              size="sm"
              className="ml-2"
              disabled={!canConfirm}
              title={canConfirm ? 'Save a verified version for auditing' : 'Waiting for your changes to be saved'}
              onClick={() => {
                confirm.reset()
                setConfirming(true)
              }}
            >
              <BadgeCheck size={15} aria-hidden /> Confirm document
            </Button>
          </div>
        )}
      </div>

      {confirming && (
        <ConfirmDialog
          lines={lines}
          threshold={threshold}
          pending={confirm.isPending}
          error={confirm.error ? errorMessage(confirm.error) : null}
          onConfirm={submitConfirm}
          onCheckFirst={() => {
            setConfirming(false)
            select(nextFlagged(lines, selectedId, threshold))
          }}
          onClose={() => setConfirming(false)}
        />
      )}

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
            editable={!locked}
            drawing={drawing && !locked}
            onDrawingChange={setDrawing}
            onAddBox={addBox}
            onMoveBox={(id, box) => dispatch({ type: 'moveBox', id, box })}
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
            onEditCancel={cancelEdit}
            dispatch={dispatch}
            threshold={threshold}
            onThresholdChange={setThreshold}
            readOnly={locked}
            marked={marked}
            onMarkedChange={setMarked}
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
