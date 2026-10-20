import { FileImage, FileText, Folder, Inbox, RotateCw } from 'lucide-react'
import { Link } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'
import type { DocumentOut } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import { formatRelativeTime, pluralize } from '@/features/extraction/format'
import { DocumentMenu } from './DocumentActions'
import type { DocumentAction } from './DocumentActions'
import { DocumentProgress } from './DocumentProgress'
import { StatusChip } from './StatusChip'

export function FileIcon({ mime, size = 20 }: { mime: string; size?: number }) {
  const Icon = mime === 'application/pdf' ? FileText : FileImage
  return <Icon size={size} className="shrink-0 text-ink-soft" aria-hidden />
}

interface DocumentListProps {
  documents: DocumentOut[]
  onRetry: (id: string) => void
  retrying: boolean
  onAction: (action: DocumentAction, document: DocumentOut) => void
  showFolder?: boolean // All documents: say where each one is filed
}

export function DocumentList({ documents, onRetry, retrying, onAction, showFolder = false }: DocumentListProps) {
  return (
    // Narrow screens scroll the table sideways rather than squeezing the name away.
    <div className="overflow-x-auto rounded-lg border border-line-light bg-surface">
      <table className="w-full min-w-[34rem] text-left text-sm">
        <thead className="border-b border-line-light text-xs text-ink-muted">
          <tr>
            {/* Fixed widths for the short columns; the name takes the rest. */}
            <th scope="col" className="px-5 py-3 font-medium">Name</th>
            {showFolder && <th scope="col" className="hidden w-44 px-4 py-3 font-medium lg:table-cell">Folder</th>}
            <th scope="col" className="w-44 px-4 py-3 font-medium">Status</th>
            <th scope="col" className="hidden w-24 px-4 py-3 font-medium sm:table-cell">Pages</th>
            <th scope="col" className="hidden w-28 px-4 py-3 font-medium md:table-cell">Uploaded</th>
            <th scope="col" className="w-36 px-5 py-3"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-light">
          {documents.map((doc) => (
            <tr key={doc.id} className="hover:bg-canvas/60">
              <td className="max-w-0 px-5 py-3.5">
                <div className="flex items-center gap-3">
                  <FileIcon mime={doc.mime} />
                  <div className="min-w-0 flex-1">
                    <Link
                      to={extractionPaths.document(doc.id)}
                      className="block truncate font-medium text-ink-h hover:underline underline-offset-2"
                      title={doc.filename}
                    >
                      {doc.filename}
                    </Link>
                    {doc.status === 'failed' && doc.error_message && (
                      <p className="mt-0.5 truncate text-xs text-danger" title={doc.error_message}>
                        {doc.error_message}
                      </p>
                    )}
                  </div>
                </div>
              </td>
              {showFolder && (
                <td className="hidden max-w-0 px-4 py-3.5 lg:table-cell">
                  <FolderLink document={doc} />
                </td>
              )}
              <td className="px-4 py-3.5">
                <StatusChip status={doc.status} />
                <DocumentProgress document={doc} />
              </td>
              <td className="hidden px-4 py-3.5 text-ink sm:table-cell">
                {doc.page_count ? pluralize(doc.page_count, 'page') : '—'}
              </td>
              <td className="hidden px-4 py-3.5 text-ink-muted md:table-cell">
                {formatRelativeTime(doc.created_at)}
              </td>
              <td className="px-5 py-3.5">
                <div className="flex items-center justify-end gap-1">
                  {doc.status === 'failed' && (
                    <Button size="sm" disabled={retrying} onClick={() => onRetry(doc.id)}>
                      <RotateCw size={14} aria-hidden /> Retry
                    </Button>
                  )}
                  <DocumentMenu document={doc} onAction={(action) => onAction(action, doc)} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Where a document is filed: its folder, or Unfiled. */
export function FolderLink({ document }: { document: DocumentOut }) {
  return document.folder_id ? (
    <Link
      to={extractionPaths.folder(document.folder_id)}
      className="flex min-w-0 items-center gap-1.5 text-ink hover:text-ink-h hover:underline underline-offset-2"
      title={document.folder_name ?? undefined}
    >
      <Folder size={14} strokeWidth={1.5} className="shrink-0 text-ink-soft" aria-hidden />
      <span className="truncate">{document.folder_name}</span>
    </Link>
  ) : (
    <Link to={extractionPaths.unfiled} className="flex items-center gap-1.5 text-ink-soft hover:text-ink-h">
      <Inbox size={14} className="shrink-0" aria-hidden /> Unfiled
    </Link>
  )
}
