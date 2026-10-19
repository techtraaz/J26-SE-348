import { Folder, Pencil, Trash2 } from 'lucide-react'
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
    <div className="group relative flex items-center gap-3 rounded-xl bg-white p-3.5 ring-1 ring-slate-200 transition hover:ring-indigo-300 hover:shadow-sm">
      <Link to={extractionPaths.folder(folder.id)} className="flex min-w-0 flex-1 items-center gap-3 outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-indigo-600">
        <Folder size={22} className="shrink-0 fill-indigo-100 text-indigo-500" aria-hidden />
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-slate-900">{folder.name}</span>
          <span className="block text-xs text-slate-500">{pluralize(items, 'item')}</span>
        </span>
      </Link>
      <div className="relative z-10 flex gap-0.5 opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
        <button
          type="button"
          aria-label={`Rename ${folder.name}`}
          onClick={() => onRename(folder)}
          className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <Pencil size={15} />
        </button>
        <button
          type="button"
          aria-label={`Delete ${folder.name}`}
          onClick={() => onDelete(folder)}
          className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
        >
          <Trash2 size={15} />
        </button>
      </div>
    </div>
  )
}
