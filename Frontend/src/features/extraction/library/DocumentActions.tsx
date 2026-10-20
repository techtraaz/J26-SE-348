import clsx from 'clsx'
import { Ellipsis, FolderInput, Pencil, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import type { DocumentOut } from '@/features/extraction/api/types'

export type DocumentAction = 'rename' | 'move' | 'delete'

/** The ⋯ menu on a document: rename, move, delete. */
export function DocumentMenu({ document, onAction, className }: {
  document: Pick<DocumentOut, 'filename'>
  onAction: (action: DocumentAction) => void
  className?: string
}) {
  // Where the menu opens, in window coordinates. Fixed positioning, because the
  // document table scrolls sideways and would clip a menu placed inside it.
  const [at, setAt] = useState<{ top: number; right: number } | null>(null)
  const open = at !== null
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setAt(null)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAt(null)
    }
    const onMove = () => setAt(null) // the menu would no longer sit under its button
    window.addEventListener('mousedown', onPointer)
    window.addEventListener('keydown', onKey)
    window.addEventListener('resize', onMove)
    window.addEventListener('scroll', onMove, true)
    return () => {
      window.removeEventListener('mousedown', onPointer)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', onMove)
      window.removeEventListener('scroll', onMove, true)
    }
  }, [open])

  const item = (action: DocumentAction, icon: ReactNode, label: string, danger = false) => (
    <button
      type="button"
      role="menuitem"
      onClick={() => {
        setAt(null)
        onAction(action)
      }}
      className={clsx(
        'flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] hover:bg-surface-muted',
        danger ? 'text-danger' : 'text-ink-h',
      )}
    >
      {icon} {label}
    </button>
  )

  return (
    <div ref={root} className={clsx('relative', className)}>
      <button
        type="button"
        aria-label={`Actions for ${document.filename}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(event) => {
          event.preventDefault() // inside a link card: do not open the document
          const rect = event.currentTarget.getBoundingClientRect()
          setAt(open ? null : { top: rect.bottom + 4, right: window.innerWidth - rect.right })
        }}
        className="flex size-8 items-center justify-center rounded-full text-ink-muted hover:bg-surface-muted hover:text-ink-h"
      >
        <Ellipsis size={17} />
      </button>
      {at && (
        <div
          role="menu"
          style={{ top: at.top, right: at.right }}
          className="fixed z-50 w-44 overflow-hidden rounded-(--radius) border border-line-light bg-surface py-1 shadow-(--shadow-lg)"
        >
          {item('rename', <Pencil size={14} aria-hidden />, 'Rename')}
          {item('move', <FolderInput size={14} aria-hidden />, 'Move to…')}
          {item('delete', <Trash2 size={14} aria-hidden />, 'Delete', true)}
        </div>
      )}
    </div>
  )
}
