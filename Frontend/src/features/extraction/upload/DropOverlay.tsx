import { UploadCloud } from 'lucide-react'

/** Shown over the page while files are dragged onto it. */
export function DropOverlay({ folderName }: { folderName: string }) {
  return (
    <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center bg-primary/10 backdrop-blur-[2px]">
      <div className="flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed border-ink-muted bg-surface px-12 py-10 shadow-(--shadow-lg)">
        <UploadCloud size={36} strokeWidth={1.5} className="text-ink-muted" aria-hidden />
        <p className="text-[15px] font-medium text-ink-h">Drop files to upload</p>
        <p className="text-[13px] text-ink-muted">They will be added to {folderName}</p>
      </div>
    </div>
  )
}
