import { ProgressBar } from '@/features/extraction/components/ProgressBar'
import type { DocumentOut } from '@/features/extraction/api/types'

/** Extraction progress for a queued or processing document. */
export function DocumentProgress({ document }: { document: DocumentOut }) {
  const run = document.latest_run
  if (document.status === 'uploaded') {
    return <span className="text-xs text-slate-500">Waiting in queue</span>
  }
  if (document.status !== 'processing') return null

  const total = run?.pages_total ?? null
  const done = run?.pages_done ?? 0
  return (
    <div className="mt-1.5 w-40">
      <ProgressBar
        value={total ? done / total : undefined}
        label={`Extraction progress for ${document.filename}`}
      />
      <span className="mt-0.5 block text-xs text-slate-500">
        {total ? `${done} of ${total} pages` : 'Preparing pages…'}
      </span>
    </div>
  )
}
