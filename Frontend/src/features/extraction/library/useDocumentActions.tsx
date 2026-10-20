import { useState } from 'react'
import type { ReactNode } from 'react'

import { useDeleteDocument, useUpdateDocument } from '@/features/extraction/api/hooks'
import type { DocumentOut } from '@/features/extraction/api/types'
import type { DocumentAction } from './DocumentActions'
import { DeleteDocumentDialog, MoveDocumentDialog } from './DocumentDialogs'
import { FolderNameDialog } from './FolderDialogs'

/** One place that owns the rename / move / delete dialogs for documents. */
export function useDocumentActions(options: { onDeleted?: (document: DocumentOut) => void } = {}) {
  const [active, setActive] = useState<{ action: DocumentAction; document: DocumentOut } | null>(null)
  const update = useUpdateDocument()
  const remove = useDeleteDocument()
  const close = () => setActive(null)

  let dialog: ReactNode = null
  if (active?.action === 'rename') {
    const d = active.document
    dialog = (
      <FolderNameDialog
        title="Rename document"
        label="Document name"
        initialName={d.filename}
        submitLabel="Rename"
        onSubmit={(name) => update.mutateAsync({ id: d.id, filename: name })}
        onClose={close}
      />
    )
  } else if (active?.action === 'move') {
    const d = active.document
    dialog = (
      <MoveDocumentDialog
        documentName={d.filename}
        currentFolderId={d.folder_id}
        onMove={(folderId) => update.mutateAsync({ id: d.id, folderId })}
        onClose={close}
      />
    )
  } else if (active?.action === 'delete') {
    const d = active.document
    dialog = (
      <DeleteDocumentDialog
        documentName={d.filename}
        verified={d.status === 'verified'}
        onConfirm={async () => {
          await remove.mutateAsync(d.id)
          options.onDeleted?.(d)
        }}
        onClose={close}
      />
    )
  }

  return { open: (action: DocumentAction, document: DocumentOut) => setActive({ action, document }), dialog }
}
