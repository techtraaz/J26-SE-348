import clsx from 'clsx'
import { Check, CircleCheck, Pencil, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Dispatch } from 'react'

import type { DraftLine } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import { isFlagged, isReviewed } from './reviewState'
import type { ReviewAction } from './reviewState'

interface LineListProps {
  lines: DraftLine[] // all pages, in reading order
  selectedId: string | null
  onSelect: (lineId: string) => void
  editingId: string | null
  onEditingChange: (lineId: string | null) => void
  onEditDone: (lineId: string) => void // after Enter: move on
  onEditCancel: (lineId: string) => void
  dispatch: Dispatch<ReviewAction>
  threshold: number
  onThresholdChange: (value: number) => void
  readOnly: boolean
  marked: ReadonlySet<string> // lines picked for a bulk action
  onMarkedChange: (marked: Set<string>) => void
}

/** The document's lines in reading order, grouped by page, with the review
 * actions on the selected line and bulk actions on marked lines. */
export function LineList({
  lines,
  selectedId,
  onSelect,
  editingId,
  onEditingChange,
  onEditDone,
  onEditCancel,
  dispatch,
  threshold,
  onThresholdChange,
  readOnly,
  marked,
  onMarkedChange,
}: LineListProps) {
  const listRef = useRef<HTMLDivElement>(null)
  const anchor = useRef<string | null>(null) // where a Shift-click range starts

  /** Ctrl/Cmd-click toggles a line; Shift-click marks the range from the last one. */
  const mark = (lineId: string, range: boolean) => {
    const next = new Set(marked)
    const from = lines.findIndex((l) => l.line_id === anchor.current)
    const to = lines.findIndex((l) => l.line_id === lineId)
    if (range && from !== -1) {
      for (const l of lines.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(l.line_id)
    } else if (next.has(lineId)) {
      next.delete(lineId)
    } else {
      next.add(lineId)
    }
    anchor.current = lineId
    onMarkedChange(next)
  }

  const markedLines = lines.filter((l) => marked.has(l.line_id))
  const ids = markedLines.map((l) => l.line_id)
  const counts = {
    accept: markedLines.filter((l) => l.human_action === 'untouched').length,
    delete: markedLines.filter((l) => l.human_action !== 'deleted').length,
    restore: markedLines.filter((l) => l.human_action === 'deleted').length,
  }
  const bulk = (type: 'accept' | 'delete' | 'restore') => {
    dispatch({ type, ids })
    onMarkedChange(new Set())
  }
  const allMarked = lines.length > 0 && markedLines.length === lines.length

  // Keep the selected line visible when it was picked on the page image. Only
  // the list scrolls: scrollIntoView would also scroll the window.
  useEffect(() => {
    const list = listRef.current
    const row = selectedId ? list?.querySelector<HTMLElement>(`[data-line-id="${selectedId}"]`) : null
    if (!list || !row) return
    const top = row.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop
    const stickyHeader = 32 // the page heading above the rows
    if (top - stickyHeader < list.scrollTop) list.scrollTop = top - stickyHeader
    else if (top + row.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = top + row.offsetHeight - list.clientHeight
  }, [selectedId])

  const pages = [...new Set(lines.map((l) => l.page))]
  const reviewed = lines.filter(isReviewed).length
  const flagged = lines.filter((l) => isFlagged(l, threshold) && !isReviewed(l)).length

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line-light bg-surface">
      <div className="space-y-2.5 border-b border-line-light px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-[15px] font-semibold text-ink-h">Lines</h3>
          <span className="text-xs text-ink-muted tabular-nums">
            {reviewed} of {lines.length} reviewed
          </span>
        </div>
        <label className="flex items-center gap-2.5 text-xs text-ink-muted">
          <span className="shrink-0">Highlight below</span>
          <input
            type="range"
            min={0.5}
            max={1}
            step={0.01}
            value={threshold}
            onChange={(event) => onThresholdChange(Number(event.target.value))}
            aria-label="Low-confidence highlight threshold"
            className="h-1 min-w-0 flex-1 accent-warning"
          />
          <span className="w-8 shrink-0 text-right tabular-nums text-ink">{threshold.toFixed(2)}</span>
        </label>
        <p className="text-xs text-ink-soft">
          {flagged > 0 ? `${flagged} low-confidence line${flagged === 1 ? '' : 's'} to check` : 'No low-confidence lines left'}
          {' · '}scores are the engine&apos;s raw values, not probabilities
        </p>
      </div>

      {!readOnly && lines.length > 0 && (
        <div className="flex min-h-12 items-center gap-2 border-b border-line-light bg-canvas/50 px-4 py-2">
          <input
            type="checkbox"
            aria-label="Mark all lines"
            checked={allMarked}
            ref={(el) => {
              if (el) el.indeterminate = markedLines.length > 0 && !allMarked
            }}
            onChange={() => onMarkedChange(allMarked ? new Set() : new Set(lines.map((l) => l.line_id)))}
            className="size-3.5 accent-primary"
          />
          {markedLines.length === 0 ? (
            <>
              <span className="text-xs text-ink-muted">Mark lines for a bulk action</span>
              <button
                type="button"
                onClick={() => onMarkedChange(new Set(lines.filter((l) => !isReviewed(l)).map((l) => l.line_id)))}
                className="ml-auto text-xs font-medium text-ink underline-offset-2 hover:underline"
              >
                Mark unreviewed
              </button>
            </>
          ) : (
            <>
            <span className="shrink-0 text-xs font-medium text-ink-h">{markedLines.length} marked</span>
            <div role="toolbar" aria-label="Bulk actions" className="ml-auto flex shrink-0 items-center gap-1">
              <Button size="sm" disabled={counts.accept === 0} onClick={() => bulk('accept')}>
                <Check size={14} aria-hidden /> Accept{counts.accept ? ` ${counts.accept}` : ''}
              </Button>
              {counts.restore > 0 && (
                <Button size="sm" onClick={() => bulk('restore')}>
                  <RotateCcw size={13} aria-hidden /> Restore {counts.restore}
                </Button>
              )}
              <Button size="sm" variant="ghost" disabled={counts.delete === 0} onClick={() => bulk('delete')}>
                <Trash2 size={13} aria-hidden /> Delete{counts.delete ? ` ${counts.delete}` : ''}
              </Button>
              <Button size="sm" variant="ghost" aria-label="Clear marks" className="px-2" onClick={() => onMarkedChange(new Set())}>
                <X size={14} aria-hidden />
              </Button>
            </div>
            </>
          )}
        </div>
      )}

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
        {lines.length === 0 && <p className="px-4 py-6 text-sm text-ink-muted">No text was found on this document.</p>}
        {pages.map((page) => (
          <section key={page} aria-label={`Page ${page}`}>
            {pages.length > 1 && (
              <h4 className="sticky top-0 z-10 border-b border-line-light bg-surface px-4 py-1.5 text-xs font-medium text-ink-muted">
                Page {page}
              </h4>
            )}
            <ul>
              {lines
                .filter((l) => l.page === page)
                .map((line) => (
                  <LineRow
                    key={line.line_id}
                    line={line}
                    selected={line.line_id === selectedId}
                    editing={line.line_id === editingId}
                    flagged={isFlagged(line, threshold)}
                    readOnly={readOnly}
                    marked={marked.has(line.line_id)}
                    onMark={(range) => mark(line.line_id, range)}
                    onSelect={() => {
                      anchor.current = line.line_id
                      onSelect(line.line_id)
                    }}
                    onEdit={() => onEditingChange(line.line_id)}
                    onCommit={(text, moveOn) => {
                      dispatch({ type: 'editText', id: line.line_id, text })
                      onEditingChange(null)
                      if (moveOn) onEditDone(line.line_id)
                    }}
                    onCancel={() => onEditCancel(line.line_id)}
                    dispatch={dispatch}
                  />
                ))}
            </ul>
          </section>
        ))}
      </div>

      {!readOnly && (
        <p className="border-t border-line-light px-4 py-2 text-[11px] leading-relaxed text-ink-soft">
          <Key>↑</Key> <Key>↓</Key> move · <Key>N</Key> next to check · <Key>A</Key> accept · <Key>Enter</Key> edit ·{' '}
          <Key>Del</Key> delete · <Key>X</Key> mark (Shift/Ctrl+click) · <Key>B</Key> add box · <Key>Ctrl</Key>+<Key>Z</Key> undo
        </p>
      )}
    </div>
  )
}

function Key({ children }: { children: string }) {
  return <kbd className="rounded border border-line bg-surface-muted px-1 font-sans text-[10px] text-ink-muted">{children}</kbd>
}

interface LineRowProps {
  line: DraftLine
  selected: boolean
  editing: boolean
  flagged: boolean
  readOnly: boolean
  marked: boolean
  onMark: (range: boolean) => void
  onSelect: () => void
  onEdit: () => void
  onCommit: (text: string, moveOn: boolean) => void
  onCancel: () => void
  dispatch: Dispatch<ReviewAction>
}

function LineRow({
  line,
  selected,
  editing,
  flagged,
  readOnly,
  marked,
  onMark,
  onSelect,
  onEdit,
  onCommit,
  onCancel,
  dispatch,
}: LineRowProps) {
  const deleted = line.human_action === 'deleted'
  const needsCheck = flagged && !isReviewed(line)
  const ids = [line.line_id]

  return (
    <li
      data-line-id={line.line_id}
      className={clsx(
        'flex flex-wrap border-l-2 transition-colors',
        selected ? 'border-primary bg-surface-muted' : needsCheck ? 'border-warning/70' : 'border-transparent',
        marked && !selected && 'bg-info/8',
      )}
    >
      {!readOnly && (
        <input
          type="checkbox"
          aria-label={`Mark ${line.text || 'empty line'}`}
          checked={marked}
          // onClick, not onChange: only the click event says whether Shift was held.
          onClick={(event) => onMark(event.shiftKey)}
          onChange={() => {}}
          className="ml-3 mt-2.5 size-3.5 shrink-0 accent-primary"
        />
      )}
      {editing ? (
        <div className="min-w-0 flex-1">
          <EditBox initial={line.text} onCommit={onCommit} onCancel={onCancel} />
        </div>
      ) : (
        <button
          type="button"
          aria-current={selected || undefined}
          onClick={(event) => {
            if (!readOnly && (event.ctrlKey || event.metaKey || event.shiftKey)) onMark(event.shiftKey)
            else onSelect()
          }}
          onDoubleClick={readOnly ? undefined : onEdit}
          className={clsx(
            'flex min-w-0 flex-1 items-baseline gap-2.5 py-2 pr-4 text-left text-sm',
            readOnly ? 'pl-4' : 'pl-2.5',
            !selected && 'hover:bg-canvas/60',
          )}
        >
          <ActionIcon action={line.human_action} />
          <span
            className={clsx(
              'min-w-0 flex-1 wrap-break-word text-ink-h',
              deleted && 'text-ink-soft line-through',
            )}
          >
            {line.text || <span className="italic text-ink-soft">(empty)</span>}
          </span>
          <span
            className={clsx('shrink-0 text-xs tabular-nums', needsCheck ? 'font-medium text-warning' : 'text-ink-soft')}
            title="The engine's raw score"
          >
            {line.confidence == null ? '—' : line.confidence.toFixed(2)}
          </span>
        </button>
      )}

      {selected && !editing && !readOnly && (
        <div className="flex w-full flex-wrap gap-1.5 pb-2.5 pl-15 pr-4">
          <Button size="sm" onClick={onEdit} disabled={deleted}>
            <Pencil size={13} aria-hidden /> Edit
          </Button>
          {line.human_action === 'untouched' && (
            <Button size="sm" onClick={() => dispatch({ type: 'accept', ids })}>
              <Check size={14} aria-hidden /> Accept
            </Button>
          )}
          {deleted ? (
            <Button size="sm" onClick={() => dispatch({ type: 'restore', ids })}>
              <RotateCcw size={13} aria-hidden /> Restore
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => dispatch({ type: 'delete', ids })}>
              <Trash2 size={13} aria-hidden /> Delete
            </Button>
          )}
        </div>
      )}
    </li>
  )
}

/** What the reviewer did to a line, as a small icon (empty for untouched). */
function ActionIcon({ action }: { action: DraftLine['human_action'] }) {
  const common = { size: 14, className: 'shrink-0 translate-y-0.5' }
  switch (action) {
    case 'accepted':
      return <CircleCheck {...common} className={clsx(common.className, 'text-success')} aria-label="Accepted" />
    case 'edited':
      return <Pencil {...common} className={clsx(common.className, 'text-info')} aria-label="Edited" />
    case 'added':
      return <Plus {...common} className={clsx(common.className, 'text-info')} aria-label="Added" />
    case 'deleted':
      return <Trash2 {...common} className={clsx(common.className, 'text-ink-soft')} aria-label="Deleted" />
    default:
      return <span className="w-3.5 shrink-0" aria-hidden />
  }
}

function EditBox({
  initial,
  onCommit,
  onCancel,
}: {
  initial: string
  onCommit: (text: string, moveOn: boolean) => void
  onCancel: () => void
}) {
  const [text, setText] = useState(initial)
  const done = useRef(false) // Enter/Escape already handled; ignore the blur that follows
  const finish = (commit: boolean, moveOn = false) => {
    if (done.current) return
    done.current = true
    if (commit) onCommit(text, moveOn)
    else onCancel()
  }
  return (
    <div className="px-4 py-2 pl-10">
      <textarea
        autoFocus
        aria-label="Line text"
        value={text}
        rows={Math.min(4, Math.max(1, Math.ceil(text.length / 38)))}
        onChange={(event) => setText(event.target.value)}
        onFocus={(event) => event.currentTarget.select()}
        onBlur={() => finish(true)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            finish(true, true)
          } else if (event.key === 'Escape') {
            event.preventDefault()
            finish(false)
          }
        }}
        className="block w-full resize-none rounded-(--radius) border border-ink-muted bg-surface px-2.5 py-1.5 text-sm text-ink-h outline-none ring-4 ring-primary/10"
      />
      <p className="mt-1 text-[11px] text-ink-soft">Enter to save · Shift+Enter for a new line · Esc to cancel</p>
    </div>
  )
}
