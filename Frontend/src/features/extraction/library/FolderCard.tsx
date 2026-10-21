import { Folder, Inbox, Pencil, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'
import type { FolderOut } from '@/features/extraction/api/types'
import { pluralize } from '@/features/extraction/format'

interface FolderCardProps {
  folder: FolderOut
  onRename: (folder: FolderOut) => void
  onDelete: (folder: FolderOut) => void
}

export function FolderCard({ folder, onRename, onDelete }: FolderCardProps) {
  const items = folder.folder_count + folder.document_count
  return (
    <div className="group relative flex items-center gap-3 rounded-(--radius) border border-line-light bg-surface p-3.5 transition hover:border-line hover:shadow-(--shadow-md)">
      <Link to={extractionPaths.folder(folder.id)} className="flex min-w-0 flex-1 items-center gap-3 outline-none after:absolute after:inset-0 after:rounded-(--radius) focus-visible:after:ring-2 focus-visible:after:ring-primary">
        <Folder size={22} strokeWidth={1.5} className="shrink-0 fill-surface-muted text-ink-muted" aria-hidden />
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-ink-h">{folder.name}</span>
          <span className="block text-xs text-ink-muted">{pluralize(items, 'item')}</span>
        </span>
      </Link>
      <div className="relative z-10 flex gap-0.5 opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
        <button
          type="button"
          aria-label={`Rename ${folder.name}`}
          onClick={() => onRename(folder)}
          className="rounded-full p-1.5 text-ink-soft hover:bg-surface-muted hover:text-ink-h"
        >
          <Pencil size={15} />
        </button>
        <button
          type="button"
          aria-label={`Delete ${folder.name}`}
          onClick={() => onDelete(folder)}
          className="rounded-full p-1.5 text-ink-soft hover:bg-danger/10 hover:text-danger"
        >
          <Trash2 size={15} />
        </button>
      </div>
    </div>
  )
}

/** The Unfiled view as a card: documents in no folder. Not a real folder, so
 * it cannot be renamed or deleted. */
export function UnfiledCard({ count }: { count: number | undefined }) {
  return (
    <Link
      to={extractionPaths.unfiled}
      className="flex items-center gap-3 rounded-(--radius) border border-dashed border-line bg-surface/60 p-3.5 transition hover:border-ink-soft hover:bg-surface hover:shadow-(--shadow-md) focus-visible:outline-2 focus-visible:outline-primary"
    >
      <Inbox size={22} strokeWidth={1.5} className="shrink-0 text-ink-muted" aria-hidden />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink-h">Unfiled</span>
        <span className="block text-xs text-ink-muted">
          {count === undefined ? 'Documents in no folder' : `${pluralize(count, 'document')} in no folder`}
        </span>
      </span>
    </Link>
  )
}
