import { useState } from 'react'
import type { FormEvent } from 'react'

import { errorMessage } from '@/features/extraction/api/errors'
import { Button } from '@/features/extraction/components/Button'
import { Modal } from '@/features/extraction/components/Modal'

interface NameDialogProps {
  title: string
  initialName?: string
  submitLabel: string
  onSubmit: (name: string) => Promise<unknown>
  onClose: () => void
}

/** Create or rename a folder. Server errors (e.g. a duplicate name) are shown
 * inline so the user can fix the name without losing the dialog. */
export function FolderNameDialog({ title, initialName = '', submitLabel, onSubmit, onClose }: NameDialogProps) {
  const [name, setName] = useState(initialName)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Enter a name.')
      return
    }
    setPending(true)
    setError(null)
    try {
      await onSubmit(trimmed)
      onClose()
    } catch (e) {
      setError(errorMessage(e))
      setPending(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit}>
        <label htmlFor="folder-name" className="mb-1.5 block text-[13px] font-medium text-ink">
          Folder name
        </label>
        <input
          id="folder-name"
          autoFocus
          value={name}
          maxLength={255}
          onChange={(event) => setName(event.target.value)}
          className="h-10 w-full rounded-(--radius) border border-line bg-input px-3 text-sm text-ink-h focus:border-ink-muted focus:bg-surface focus:outline-none focus:ring-4 focus:ring-primary/10"
        />
        {error && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {error}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={pending}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

interface DeleteDialogProps {
  folderName: string
  onConfirm: () => Promise<unknown>
  onClose: () => void
}

export function DeleteFolderDialog({ folderName, onConfirm, onClose }: DeleteDialogProps) {
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
    <Modal title="Delete folder" onClose={onClose}>
      <p className="text-sm text-ink">
        Delete the folder <span className="font-medium text-ink-h">“{folderName}”</span>? Only empty
        folders can be deleted.
      </p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={pending} onClick={confirm}>
          Delete
        </Button>
      </div>
    </Modal>
  )
}
