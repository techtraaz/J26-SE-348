import { useState } from 'react'
import { Link } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'
import { pageImageUrl } from '@/features/extraction/api/client'
import type { DocumentOut } from '@/features/extraction/api/types'
import { formatRelativeTime } from '@/features/extraction/format'
import { DocumentProgress } from './DocumentProgress'
import { DocumentMenu } from './DocumentActions'
import type { DocumentAction } from './DocumentActions'
import { FileIcon, FolderLink } from './DocumentList'
import { StatusChip } from './StatusChip'

function Thumbnail({ document }: { document: DocumentOut }) {
  const [broken, setBroken] = useState(false)
  const ready = document.status === 'needs_review' || document.status === 'verified'

  if (ready && !broken) {
    return (
      <img
        src={pageImageUrl(document.id, 1)}
        alt=""
        loading="lazy"
        onError={() => setBroken(true)}
        className="size-full object-cover object-top"
      />
    )
  }
  return (
    <div className="flex size-full items-center justify-center">
      <FileIcon mime={document.mime} size={36} />
    </div>
  )
}

interface DocumentGridProps {
  documents: DocumentOut[]
  onAction: (action: DocumentAction, document: DocumentOut) => void
  showFolder?: boolean // All documents: say where each one is filed
}

export function DocumentGrid({ documents, onAction, showFolder = false }: DocumentGridProps) {
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
      {documents.map((doc) => (
        <li key={doc.id} className="relative">
          {/* Beside the link, not inside it: a button may not sit in a link. */}
          <DocumentMenu
            document={doc}
            onAction={(action) => onAction(action, doc)}
            className="absolute right-2 top-2 z-10 rounded-full bg-surface/90 shadow-(--shadow-sm)"
          />
          <Link
            to={extractionPaths.document(doc.id)}
            className="block overflow-hidden rounded-lg border border-line-light bg-surface transition hover:border-line hover:shadow-(--shadow-md)"
          >
            <div className="aspect-4/3 overflow-hidden border-b border-line-light bg-surface-muted">
              <Thumbnail document={doc} />
            </div>
            <div className="space-y-1.5 p-3">
              <p className="truncate text-sm font-medium text-ink-h" title={doc.filename}>
                {doc.filename}
              </p>
              <div className="flex items-center justify-between gap-2">
                <StatusChip status={doc.status} />
                <span className="text-xs text-ink-soft">{formatRelativeTime(doc.created_at)}</span>
              </div>
              <DocumentProgress document={doc} />
              {doc.status === 'failed' && doc.error_message && (
                <p className="line-clamp-2 text-xs text-danger">{doc.error_message}</p>
              )}
            </div>
          </Link>
          {showFolder && (
            <div className="mt-1.5 px-1 text-xs">
              <FolderLink document={doc} />
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
