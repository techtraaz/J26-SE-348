import { BadgeCheck, Download, PencilLine } from 'lucide-react'

import { exportUrl } from '@/features/extraction/api/client'
import { errorMessage } from '@/features/extraction/api/errors'
import { useReopenDocument, useVerifiedRecord } from '@/features/extraction/api/hooks'
import { Button } from '@/features/extraction/components/Button'
import { pluralize } from '@/features/extraction/format'

/** A verified document: its version, downloads, and the way back to review. */
export function VerifiedBanner({ documentId, onReopened }: { documentId: string; onReopened: () => void }) {
  const record = useVerifiedRecord(documentId, true)
  const reopen = useReopenDocument(documentId)

  const confirmedAt = record.data
    ? new Date(record.data.confirmed_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    : null
  const linkClass =
    'inline-flex h-8 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-xs font-medium text-ink-h hover:bg-surface-muted'

  return (
    <div
      role="status"
      className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-success/30 bg-success/8 px-4 py-3"
    >
      <BadgeCheck size={20} className="shrink-0 text-success" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {record.data ? (
          <>
            <p className="font-medium text-ink-h">Verified, version {record.data.version}</p>
            <p className="text-[13px] text-ink-muted">
              Confirmed {confirmedAt} · {pluralize(record.data.lines.length, 'line')} · ready for Component 03
            </p>
          </>
        ) : (
          <p className="text-ink-muted">{record.isError ? errorMessage(record.error) : 'Loading the verified version…'}</p>
        )}
        {reopen.isError && <p className="mt-1 text-[13px] text-danger">{errorMessage(reopen.error)}</p>}
      </div>
      {record.data && (
        <div className="flex flex-wrap items-center gap-2">
          <a className={linkClass} href={exportUrl(documentId, record.data.version, 'json')} download>
            <Download size={13} aria-hidden /> JSON
          </a>
          <a className={linkClass} href={exportUrl(documentId, record.data.version, 'csv')} download>
            <Download size={13} aria-hidden /> CSV
          </a>
          <Button size="sm" disabled={reopen.isPending} onClick={() => reopen.mutate(undefined, { onSuccess: onReopened })}>
            <PencilLine size={14} aria-hidden /> Reopen for edits
          </Button>
        </div>
      )}
    </div>
  )
}
