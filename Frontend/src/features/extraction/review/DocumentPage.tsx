import { ArrowLeft, CircleAlert, RotateCw } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'
import { useDocument, useExtraction, useRetryDocument } from '@/features/extraction/api/hooks'
import { errorMessage } from '@/features/extraction/api/errors'
import { Button } from '@/features/extraction/components/Button'
import { EmptyState } from '@/features/extraction/components/EmptyState'
import { formatDuration, pluralize } from '@/features/extraction/format'
import { DocumentProgress } from '../library/DocumentProgress'
import { StatusChip } from '../library/StatusChip'

/** Placeholder for the review workspace (milestone M4). For now it shows the
 * document's status and a first look at the extracted regions, so the whole
 * upload -> extract -> read path can be seen working end to end. */
export function DocumentPage() {
  const { documentId = '' } = useParams()
  const document = useDocument(documentId)
  const ready = document.data?.status === 'needs_review' || document.data?.status === 'verified'
  const extraction = useExtraction(documentId, ready)
  const retry = useRetryDocument()

  if (document.isPending) return <p className="px-8 py-6 text-sm text-slate-500">Loading…</p>
  if (document.isError) {
    return (
      <div className="px-8 py-6">
        <EmptyState
          icon={<CircleAlert size={22} />}
          title="Document not found"
          description={errorMessage(document.error)}
          action={
            <Link to={extractionPaths.library} className="text-sm font-medium text-indigo-600 hover:underline">
              Back to documents
            </Link>
          }
        />
      </div>
    )
  }

  const doc = document.data
  const run = doc.latest_run
  const regions = extraction.data?.regions ?? []

  return (
    <div className="mx-auto max-w-4xl px-8 py-6">
      <Link
        to={doc.folder_id ? extractionPaths.folder(doc.folder_id) : extractionPaths.library}
        className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900"
      >
        <ArrowLeft size={15} aria-hidden /> Back to library
      </Link>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900">{doc.filename}</h1>
        <StatusChip status={doc.status} />
      </div>

      <dl className="mb-6 grid grid-cols-2 gap-4 rounded-xl bg-white p-4 text-sm ring-1 ring-slate-200 sm:grid-cols-4">
        <div>
          <dt className="text-xs text-slate-500">Pages</dt>
          <dd className="font-medium text-slate-900">{doc.page_count ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Engine</dt>
          <dd className="font-medium text-slate-900">{run?.engine ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Extraction time</dt>
          <dd className="font-medium text-slate-900">{run?.elapsed_ms ? formatDuration(run.elapsed_ms) : '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Data source</dt>
          <dd className="font-medium capitalize text-slate-900">{doc.source}</dd>
        </div>
      </dl>

      <DocumentProgress document={doc} />

      {doc.status === 'failed' && (
        <div role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800 ring-1 ring-red-200">
          <p className="font-medium">Extraction failed</p>
          <p className="mt-1">{doc.error_message}</p>
          <Button className="mt-3" disabled={retry.isPending} onClick={() => retry.mutate(doc.id)}>
            <RotateCw size={14} aria-hidden /> Retry
          </Button>
        </div>
      )}

      {ready && (
        <section aria-label="Extracted text">
          <h2 className="mb-1 text-sm font-semibold text-slate-900">
            Extracted text ({pluralize(regions.length, 'region')})
          </h2>
          <p className="mb-3 text-sm text-slate-500">
            The editable review workspace with the page image and boxes arrives in the next milestone.
            Confidence is the engine&apos;s raw score, shown as reported.
          </p>
          <div className="overflow-hidden rounded-xl bg-white ring-1 ring-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="w-14 px-4 py-2 font-medium">Page</th>
                  <th scope="col" className="px-4 py-2 font-medium">Text</th>
                  <th scope="col" className="w-28 px-4 py-2 font-medium">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {regions.slice(0, 25).map((region) => (
                  <tr key={region.id}>
                    <td className="px-4 py-2 text-slate-500">{region.page_number}</td>
                    <td className="px-4 py-2 text-slate-900">{region.text}</td>
                    <td className="px-4 py-2 tabular-nums text-slate-600">
                      {region.confidence === null ? '—' : region.confidence.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {regions.length > 25 && (
              <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
                Showing the first 25 of {regions.length} regions.
              </p>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
