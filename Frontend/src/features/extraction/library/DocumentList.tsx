import { FileImage, FileText, RotateCw } from 'lucide-react'
import { Link } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'
import type { DocumentOut } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import { formatRelativeTime, pluralize } from '@/features/extraction/format'
import { DocumentProgress } from './DocumentProgress'
import { StatusChip } from './StatusChip'

export function FileIcon({ mime, size = 20 }: { mime: string; size?: number }) {
  const Icon = mime === 'application/pdf' ? FileText : FileImage
  return <Icon size={size} className="shrink-0 text-slate-400" aria-hidden />
}

interface DocumentListProps {
  documents: DocumentOut[]
  onRetry: (id: string) => void
  retrying: boolean
}

export function DocumentList({ documents, onRetry, retrying }: DocumentListProps) {
  return (
    <div className="overflow-hidden rounded-xl bg-white ring-1 ring-slate-200">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-4 py-2.5 font-medium">Name</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
            <th scope="col" className="hidden px-4 py-2.5 font-medium sm:table-cell">Pages</th>
            <th scope="col" className="hidden px-4 py-2.5 font-medium md:table-cell">Uploaded</th>
            <th scope="col" className="w-24 px-4 py-2.5"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {documents.map((doc) => (
            <tr key={doc.id} className="hover:bg-slate-50">
              <td className="max-w-0 px-4 py-3">
                <div className="flex items-center gap-3">
                  <FileIcon mime={doc.mime} />
                  <div className="min-w-0">
                    <Link
                      to={extractionPaths.document(doc.id)}
                      className="block truncate font-medium text-slate-900 hover:text-indigo-700"
                      title={doc.filename}
                    >
                      {doc.filename}
                    </Link>
                    {doc.status === 'failed' && doc.error_message && (
                      <p className="truncate text-xs text-red-600" title={doc.error_message}>
                        {doc.error_message}
                      </p>
                    )}
                  </div>
                </div>
              </td>
              <td className="px-4 py-3">
                <StatusChip status={doc.status} />
                <DocumentProgress document={doc} />
              </td>
              <td className="hidden px-4 py-3 text-slate-600 sm:table-cell">
                {doc.page_count ? pluralize(doc.page_count, 'page') : '—'}
              </td>
              <td className="hidden px-4 py-3 text-slate-500 md:table-cell">
                {formatRelativeTime(doc.created_at)}
              </td>
              <td className="px-4 py-3 text-right">
                {doc.status === 'failed' && (
                  <Button size="sm" disabled={retrying} onClick={() => onRetry(doc.id)}>
                    <RotateCw size={14} aria-hidden /> Retry
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
