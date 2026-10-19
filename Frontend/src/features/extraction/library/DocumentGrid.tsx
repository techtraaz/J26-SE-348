import { useState } from 'react'
import { Link } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'
import { pageImageUrl } from '@/features/extraction/api/client'
import type { DocumentOut } from '@/features/extraction/api/types'
import { formatRelativeTime } from '@/features/extraction/format'
import { DocumentProgress } from './DocumentProgress'
import { FileIcon } from './DocumentList'
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

export function DocumentGrid({ documents }: { documents: DocumentOut[] }) {
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {documents.map((doc) => (
        <li key={doc.id}>
          <Link
            to={extractionPaths.document(doc.id)}
            className="block overflow-hidden rounded-xl bg-white ring-1 ring-slate-200 transition hover:ring-indigo-300 hover:shadow-sm"
          >
            <div className="aspect-[4/3] overflow-hidden border-b border-slate-100 bg-slate-100">
              <Thumbnail document={doc} />
            </div>
            <div className="space-y-1.5 p-3">
              <p className="truncate text-sm font-medium text-slate-900" title={doc.filename}>
                {doc.filename}
              </p>
              <div className="flex items-center justify-between gap-2">
                <StatusChip status={doc.status} />
                <span className="text-xs text-slate-400">{formatRelativeTime(doc.created_at)}</span>
              </div>
              <DocumentProgress document={doc} />
              {doc.status === 'failed' && doc.error_message && (
                <p className="line-clamp-2 text-xs text-red-600">{doc.error_message}</p>
              )}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  )
}
