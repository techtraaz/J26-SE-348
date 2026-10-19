import { CircleAlert, CircleCheck, FileText, X } from 'lucide-react'

import { ProgressBar } from '@/features/extraction/components/ProgressBar'
import { formatBytes, pluralize } from '@/features/extraction/format'
import { countByStatus } from './uploadQueueState'
import type { UploadItem } from './uploadQueueState'

interface UploadQueueProps {
  items: UploadItem[]
  onDismiss: (id: string) => void
  onClearFinished: () => void
}

function Row({ item, onDismiss }: { item: UploadItem; onDismiss: (id: string) => void }) {
  return (
    <li className="flex items-start gap-3 px-4 py-2.5">
      <FileText size={18} className="mt-0.5 shrink-0 text-slate-400" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm text-slate-800" title={item.name}>
            {item.name}
          </span>
          <span className="shrink-0 text-xs text-slate-400">{formatBytes(item.size)}</span>
        </div>
        {item.status === 'uploading' && (
          <div className="mt-1.5">
            <ProgressBar value={item.progress} label={`Uploading ${item.name}`} />
          </div>
        )}
        {item.status === 'done' && (
          <p className="mt-0.5 flex items-center gap-1 text-xs text-green-700">
            <CircleCheck size={13} aria-hidden /> Uploaded. Extraction runs in the background.
          </p>
        )}
        {item.status === 'error' && (
          <p className="mt-0.5 flex items-start gap-1 text-xs text-red-700">
            <CircleAlert size={13} className="mt-px shrink-0" aria-hidden /> {item.error}
          </p>
        )}
      </div>
      {item.status !== 'uploading' && (
        <button
          type="button"
          aria-label={`Dismiss ${item.name}`}
          onClick={() => onDismiss(item.id)}
          className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <X size={16} />
        </button>
      )}
    </li>
  )
}

export function UploadQueue({ items, onDismiss, onClearFinished }: UploadQueueProps) {
  if (items.length === 0) return null
  const counts = countByStatus(items)
  const title =
    counts.uploading > 0
      ? `Uploading ${pluralize(counts.uploading, 'file')}`
      : counts.error > 0
        ? `${pluralize(counts.error, 'upload')} failed`
        : 'Uploads complete'

  return (
    <section
      aria-label="Uploads"
      className="fixed bottom-4 right-4 z-40 w-96 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl bg-white shadow-xl ring-1 ring-slate-200"
    >
      <header className="flex items-center justify-between bg-slate-900 px-4 py-2.5 text-sm text-white">
        <span className="font-medium">{title}</span>
        {counts.uploading === 0 && (
          <button type="button" onClick={onClearFinished} className="text-xs text-slate-300 hover:text-white">
            Clear all
          </button>
        )}
      </header>
      <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto">
        {items.map((item) => (
          <Row key={item.id} item={item} onDismiss={onDismiss} />
        ))}
      </ul>
    </section>
  )
}
