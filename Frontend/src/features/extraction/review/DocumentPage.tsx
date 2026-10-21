import { ArrowLeft, CircleAlert, RotateCw } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { extractionPaths } from '@/features/extraction/paths'
import { useDocument, useRetryDocument, useReviewDraft } from '@/features/extraction/api/hooks'
import { errorMessage } from '@/features/extraction/api/errors'
import { Button } from '@/features/extraction/components/Button'
import { EmptyState } from '@/features/extraction/components/EmptyState'
import { formatDuration, pluralize } from '@/features/extraction/format'
import { DocumentMenu } from '../library/DocumentActions'
import { FolderLink } from '../library/DocumentList'
import { DocumentProgress } from '../library/DocumentProgress'
import { StatusChip } from '../library/StatusChip'
import { useDocumentActions } from '../library/useDocumentActions'
import { ReviewWorkspace } from './ReviewWorkspace'
import { VerifiedBanner } from './VerifiedBanner'

/** A document: its status while extraction runs, then the review workspace. */
export function DocumentPage() {
  const { documentId = '' } = useParams()
  const document = useDocument(documentId)
  const ready = document.data?.status === 'needs_review' || document.data?.status === 'verified'
  const draft = useReviewDraft(documentId, ready)
  const retry = useRetryDocument()
  const navigate = useNavigate()
  // Deleted: back to where it was filed (the document page no longer exists).
  const actions = useDocumentActions({
    onDeleted: (d) => navigate(d.folder_id ? extractionPaths.folder(d.folder_id) : extractionPaths.unfiled),
  })
  const [reloads, setReloads] = useState(0)
  // After a conflict, a confirmation or a reopen: fetch the document and its
  // draft again, then rebuild the workspace from them (fresh draft version).
  const reload = () =>
    void Promise.all([document.refetch(), draft.refetch()]).then(() => setReloads((n) => n + 1))

  if (document.isPending) return <p className="px-8 pb-12 text-sm text-ink-muted">Loading…</p>
  if (document.isError) {
    return (
      <div className="px-8 pb-12">
        <EmptyState
          icon={<CircleAlert size={22} />}
          title="Document not found"
          description={errorMessage(document.error)}
          action={
            <Link to={extractionPaths.library} className="text-sm font-medium text-ink-h underline-offset-2 hover:underline">
              Back to documents
            </Link>
          }
        />
      </div>
    )
  }

  const doc = document.data
  const run = doc.latest_run
  const details = [
    doc.page_count ? pluralize(doc.page_count, 'page') : null,
    run?.engine,
    run?.elapsed_ms ? formatDuration(run.elapsed_ms) : null,
    doc.source === 'research' ? 'Research data' : 'Demo data',
  ].filter(Boolean)

  return (
    <div className="px-8 pb-12">
      <Link
        to={doc.folder_id ? extractionPaths.folder(doc.folder_id) : extractionPaths.library}
        className="mb-3 inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink-h"
      >
        <ArrowLeft size={15} aria-hidden /> Back to library
      </Link>

      <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="min-w-0 truncate text-xl font-medium text-ink-h">{doc.filename}</h2>
        <StatusChip status={doc.status} />
        <DocumentMenu document={doc} onAction={(action) => actions.open(action, doc)} />
        <span className="text-[13px]"><FolderLink document={doc} /></span>
        <p className="w-full text-[13px] text-ink-muted">
          {details.join(' · ')}
          {run?.engine === 'replay' && (
            // Development engine (D14): one saved result served for every upload.
            <span className="text-info"> · Replay result from a sample document: boxes fit only that sample</span>
          )}
        </p>
      </div>

      {actions.dialog}
      <DocumentProgress document={doc} />

      {doc.status === 'failed' && (
        <div role="alert" className="max-w-2xl rounded-lg border border-danger/30 bg-danger/8 p-4 text-sm text-danger">
          <p className="font-medium">Extraction failed</p>
          <p className="mt-1">{doc.error_message}</p>
          <Button className="mt-3" disabled={retry.isPending} onClick={() => retry.mutate(doc.id)}>
            <RotateCw size={14} aria-hidden /> Retry
          </Button>
        </div>
      )}

      {ready && draft.isPending && <p className="text-sm text-ink-muted">Loading the review…</p>}
      {ready && draft.isError && (
        <EmptyState
          icon={<CircleAlert size={22} />}
          title="Could not load the review"
          description={errorMessage(draft.error)}
          action={<Button onClick={() => void draft.refetch()}>Try again</Button>}
        />
      )}
      {doc.status === 'verified' && <VerifiedBanner documentId={doc.id} onReopened={reload} />}

      {ready && draft.isSuccess && (
        <ReviewWorkspace
          // A new key after a reload rebuilds the working copy from the server.
          key={`${doc.id}:${reloads}`}
          documentId={doc.id}
          pages={doc.pages}
          draft={draft.data}
          readOnly={doc.status === 'verified'}
          onReload={reload}
          onConfirmed={reload}
        />
      )}
    </div>
  )
}
