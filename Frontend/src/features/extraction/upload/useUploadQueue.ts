import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useReducer, useRef } from 'react'

import { uploadDocument } from '@/features/extraction/api/client'
import { errorMessage } from '@/features/extraction/api/errors'
import { queryKeys } from '@/features/extraction/api/hooks'
import { newUploadItem, uploadReducer } from './uploadQueueState'

const MAX_PARALLEL = 2

interface Job {
  id: string
  file: File
  folderId: string | null
}

let nextId = 0
const makeId = () => `upload-${Date.now()}-${nextId++}`

/** Uploads files a couple at a time into `folderId` and tracks their progress.
 * Extraction continues in the background after each upload is accepted; the
 * library list picks that up through its own polling. */
export function useUploadQueue(folderId: string | null) {
  const queryClient = useQueryClient()
  const [items, dispatch] = useReducer(uploadReducer, [])
  const pending = useRef<Job[]>([])
  const running = useRef(0)

  const pump = useCallback(
    function run() {
      while (running.current < MAX_PARALLEL && pending.current.length > 0) {
        const job = pending.current.shift()!
        running.current++
        uploadDocument(job.file, {
          folderId: job.folderId,
          onProgress: (progress) => dispatch({ type: 'progress', id: job.id, progress }),
        })
          .then((document) => {
            dispatch({ type: 'done', id: job.id, documentId: document.id })
            void queryClient.invalidateQueries({ queryKey: queryKeys.allDocuments })
            void queryClient.invalidateQueries({ queryKey: queryKeys.allFolders })
          })
          .catch((error: unknown) =>
            dispatch({ type: 'error', id: job.id, message: errorMessage(error) }),
          )
          .finally(() => {
            running.current--
            run()
          })
      }
    },
    [queryClient],
  )

  const addFiles = useCallback(
    (files: File[]) => {
      const jobs = files.map((file) => ({ id: makeId(), file, folderId }))
      dispatch({ type: 'add', items: jobs.map((j) => newUploadItem(j.file, j.id)) })
      pending.current.push(...jobs)
      pump()
    },
    [folderId, pump],
  )

  /** Files rejected before upload (wrong type, too large): shown as errors. */
  const addRejected = useCallback((rejected: { file: File; message: string }[]) => {
    dispatch({
      type: 'add',
      items: rejected.map(({ file, message }) => ({
        ...newUploadItem(file, makeId()),
        status: 'error' as const,
        error: message,
      })),
    })
  }, [])

  return {
    items,
    addFiles,
    addRejected,
    dismiss: (id: string) => dispatch({ type: 'dismiss', id }),
    clearFinished: () => dispatch({ type: 'clearFinished' }),
  }
}
