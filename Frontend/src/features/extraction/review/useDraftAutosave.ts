import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, call } from '@/features/extraction/api/client'
import { ApiError, errorMessage } from '@/features/extraction/api/errors'
import { queryKeys } from '@/features/extraction/api/hooks'
import type { DraftLine } from '@/features/extraction/api/types'
import { editableLines } from './reviewState'

export type SaveStatus =
  | { kind: 'saved' }
  | { kind: 'unsaved' }
  | { kind: 'saving' }
  | { kind: 'retrying'; message: string } // network or server trouble; tries again
  | { kind: 'conflict'; message: string } // the server refused this version; reload needed

// The server will not take this draft as it is: saving again cannot help.
const STOPPING_CODES = new Set(['draft_conflict', 'run_changed', 'document_verified'])

interface Options {
  documentId: string
  basedOnRunId: string
  initialVersion: number
  lines: DraftLine[]
  revision: number // from reviewState: changes with every edit, undo and redo
  enabled: boolean
  delayMs?: number
  retryMs?: number
}

/** Saves the draft shortly after the reviewer stops changing it. One save at a
 * time, each based on the version the last one returned (optimistic
 * concurrency on the server); changes made during a save are saved next. A
 * conflict stops saving instead of overwriting someone else's work. */
export function useDraftAutosave({
  documentId,
  basedOnRunId,
  initialVersion,
  lines,
  revision,
  enabled,
  delayMs = 800,
  retryMs = 5000,
}: Options): { status: SaveStatus; version: number } {
  const queryClient = useQueryClient()
  const [savedRevision, setSavedRevision] = useState(0)
  // The server's draft version after the last save: what confirmation is based on.
  const [savedVersion, setSavedVersion] = useState(initialVersion)
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState<SaveStatus | null>(null)

  // Refs for the async save: the latest state without re-creating timers.
  const latest = useRef({ lines, revision })
  const version = useRef(initialVersion)
  const savedRef = useRef(0)
  const inFlight = useRef(false)
  const stopped = useRef(false)
  const retryTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // save() re-schedules itself (after a save that changes overtook, and on retry)
  // through this ref, which always holds the latest save.
  const saveAgain = useRef<() => void>(() => {})

  const save = useCallback(async () => {
    if (inFlight.current || stopped.current) return
    const { lines: toSave, revision: target } = latest.current
    if (target === savedRef.current) return
    inFlight.current = true
    setSaving(true)
    clearTimeout(retryTimer.current)
    try {
      const draft = await call(
        api.PUT('/api/v1/documents/{document_id}/review', {
          params: { path: { document_id: documentId } },
          body: { version: version.current, based_on_run_id: basedOnRunId, lines: editableLines(toSave) },
        }),
      )
      version.current = draft.version
      setSavedVersion(draft.version)
      savedRef.current = target
      setSavedRevision(target)
      setProblem(null)
      queryClient.setQueryData(queryKeys.review(documentId), draft)
      inFlight.current = false
      setSaving(false)
      if (latest.current.revision !== target) saveAgain.current() // changed while saving
    } catch (error) {
      inFlight.current = false
      setSaving(false)
      if (error instanceof ApiError && STOPPING_CODES.has(error.code)) {
        stopped.current = true
        setProblem({ kind: 'conflict', message: error.message })
        return
      }
      setProblem({ kind: 'retrying', message: errorMessage(error) })
      retryTimer.current = setTimeout(() => saveAgain.current(), retryMs)
    }
  }, [documentId, basedOnRunId, queryClient, retryMs])

  useEffect(() => {
    saveAgain.current = () => void save()
  }, [save])

  // Debounce: save once the reviewer pauses.
  useEffect(() => {
    latest.current = { lines, revision }
    if (!enabled || revision === savedRef.current) return
    const timer = setTimeout(() => void save(), delayMs)
    return () => clearTimeout(timer)
  }, [lines, revision, enabled, delayMs, save])

  // Leaving the page: save what is pending rather than drop it.
  useEffect(
    () => () => {
      clearTimeout(retryTimer.current)
      if (enabled && latest.current.revision !== savedRef.current) void save()
    },
    [enabled, save],
  )

  const status: SaveStatus =
    problem?.kind === 'conflict'
      ? problem
      : saving
        ? { kind: 'saving' }
        : problem ?? (revision !== savedRevision ? { kind: 'unsaved' } : { kind: 'saved' })

  // Closing the tab with unsaved work asks first.
  const pending = enabled && status.kind !== 'saved'
  useEffect(() => {
    if (!pending) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [pending])

  return { status, version: savedVersion }
}
