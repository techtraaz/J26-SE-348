import { UploadCloud } from 'lucide-react'

/** Shown over the page while files are dragged onto it. */
export function DropOverlay({ folderName }: { folderName: string }) {
  return (
    <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center bg-indigo-600/10 backdrop-blur-[1px]">
      <div className="flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed border-indigo-500 bg-white/90 px-12 py-10 shadow-lg">
        <UploadCloud size={36} className="text-indigo-600" aria-hidden />
        <p className="text-base font-semibold text-slate-900">Drop files to upload</p>
        <p className="text-sm text-slate-500">They will be added to {folderName}</p>
      </div>
    </div>
  )
}
