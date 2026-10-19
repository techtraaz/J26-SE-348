import clsx from 'clsx'
import { useEffect, useRef } from 'react'

import type { DraftLine } from '@/features/extraction/api/types'
import { pluralize } from '@/features/extraction/format'

interface LineListProps {
  lines: DraftLine[] // all pages, in reading order
  selectedId: string | null
  onSelect: (lineId: string) => void
}

/** The document's lines in reading order, grouped by page. */
export function LineList({ lines, selectedId, onSelect }: LineListProps) {
  const listRef = useRef<HTMLDivElement>(null)

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

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line-light bg-surface">
      <div className="flex items-baseline justify-between border-b border-line-light px-4 py-3">
        <h3 className="text-[15px] font-semibold text-ink-h">Lines</h3>
        <span className="text-xs text-ink-muted">{pluralize(lines.length, 'line')}</span>
      </div>
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
                .map((line) => {
                  const selected = line.line_id === selectedId
                  return (
                    <li key={line.line_id}>
                      <button
                        type="button"
                        data-line-id={line.line_id}
                        aria-current={selected || undefined}
                        onClick={() => onSelect(line.line_id)}
                        className={clsx(
                          'flex w-full items-baseline gap-3 border-l-2 px-4 py-2 text-left text-sm transition-colors',
                          selected
                            ? 'border-primary bg-surface-muted'
                            : 'border-transparent hover:bg-canvas/60',
                          line.human_action === 'deleted' && 'opacity-50',
                        )}
                      >
                        <span
                          className={clsx(
                            'min-w-0 flex-1 wrap-break-word text-ink-h',
                            line.human_action === 'deleted' && 'line-through',
                          )}
                        >
                          {line.text || <span className="italic text-ink-soft">(empty)</span>}
                        </span>
                        <span className="shrink-0 text-xs tabular-nums text-ink-soft" title="The engine's raw score">
                          {line.confidence == null ? '—' : line.confidence.toFixed(2)}
                        </span>
                      </button>
                    </li>
                  )
                })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
