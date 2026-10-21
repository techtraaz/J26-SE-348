import { ChevronRight, Folder, Inbox } from 'lucide-react'
import { useState } from 'react'

import { errorMessage } from '@/features/extraction/api/errors'
import { useFolder, useFolders } from '@/features/extraction/api/hooks'
import { Button } from '@/features/extraction/components/Button'
import { Modal } from '@/features/extraction/components/Modal'

interface MoveDialogProps {
  documentName: string
  currentFolderId: string | null
  onMove: (folderId: string | null) => Promise<unknown>
  onClose: () => void
}

/** Browse to a folder and move the document there; at the top level, "here" is Unfiled. */
export function MoveDocumentDialog({ documentName, currentFolderId, onMove, onClose }: MoveDialogProps) {
  const [at, setAt] = useState<string | null>(null)
  const folder = useFolder(at ?? undefined)
  const folders = useFolders(at)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const here = at === null ? 'Unfiled' : (folder.data?.name ?? '…')
  const move = async () => {
    setPending(true)
    setError(null)
    try {
      await onMove(at)
      onClose()
    } catch (e) {
      setError(errorMessage(e))
      setPending(false)
    }
  }

  return (
    <Modal title="Move document" onClose={onClose}>
      <p className="mb-3 truncate text-sm text-ink-muted">“{documentName}”</p>
      <nav aria-label="Folder" className="mb-2 flex flex-wrap items-center gap-1 text-[13px]">
        <button type="button" onClick={() => setAt(null)} className={at ? 'text-ink-muted hover:text-ink-h' : 'font-medium text-ink-h'}>
          Folders
        </button>
        {(folder.data?.breadcrumbs ?? []).map((crumb, i, list) => (
          <span key={crumb.id} className="flex items-center gap-1">
            <ChevronRight size={14} className="text-ink-soft" aria-hidden />
            <button type="button" onClick={() => setAt(crumb.id)}
                    className={i === list.length - 1 ? 'font-medium text-ink-h' : 'text-ink-muted hover:text-ink-h'}>
              {crumb.name}
            </button>
          </span>
        ))}
      </nav>

      <ul className="max-h-64 divide-y divide-line-light overflow-y-auto rounded-lg border border-line-light">
        {(folders.data?.items ?? []).map((f) => (
          <li key={f.id}>
            <button type="button" onClick={() => setAt(f.id)}
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-sm hover:bg-canvas/60">
              <Folder size={16} strokeWidth={1.5} className="shrink-0 fill-surface-muted text-ink-muted" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-ink-h">{f.name}</span>
              <ChevronRight size={15} className="text-ink-soft" aria-hidden />
            </button>
          </li>
        ))}
        {folders.isSuccess && folders.data.items.length === 0 && (
          <li className="px-3.5 py-2.5 text-[13px] text-ink-muted">
            {at === null ? 'No folders yet. Create one in the Folders tab.' : 'No folders inside.'}
          </li>
        )}
      </ul>
      {at === null && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-soft">
          <Inbox size={13} aria-hidden /> At the top level, the document goes to Unfiled (in no folder).
        </p>
      )}

      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={pending || at === currentFolderId} onClick={move}>
          {at === currentFolderId ? 'Already here' : `Move to ${here}`}
        </Button>
      </div>
    </Modal>
  )
}

interface DeleteDialogProps {
  documentName: string
  verified: boolean
  onConfirm: () => Promise<unknown>
  onClose: () => void
}

/** Delete a document; a verified one is explained, not offered (the server refuses it too). */
export function DeleteDocumentDialog({ documentName, verified, onConfirm, onClose }: DeleteDialogProps) {
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const confirm = async () => {
    setPending(true)
    setError(null)
    try {
      await onConfirm()
      onClose()
    } catch (e) {
      setError(errorMessage(e))
      setPending(false)
    }
  }

  return (
    <Modal title={verified ? 'Kept for the audit trail' : 'Delete document'} onClose={onClose}>
      {verified ? (
        <p className="text-sm text-ink">
          <span className="font-medium text-ink-h">“{documentName}”</span> has verified versions that audits may
          refer to, so it cannot be deleted. You can move or rename it.
        </p>
      ) : (
        <p className="text-sm text-ink">
          Delete <span className="font-medium text-ink-h">“{documentName}”</span>? Its file, extraction and review
          are deleted too. This cannot be undone.
        </p>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>{verified ? 'Close' : 'Cancel'}</Button>
        {!verified && (
          <Button variant="danger" disabled={pending} onClick={confirm}>
            Delete
          </Button>
        )}
      </div>
    </Modal>
  )
}
