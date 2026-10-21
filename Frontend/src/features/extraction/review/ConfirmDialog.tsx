import { CircleAlert, ScanSearch } from 'lucide-react'

import type { DraftLine } from '@/features/extraction/api/types'
import { Button } from '@/features/extraction/components/Button'
import { Modal } from '@/features/extraction/components/Modal'
import { pluralize } from '@/features/extraction/format'
import { isFlagged } from './reviewState'

interface ConfirmDialogProps {
  lines: DraftLine[]
  threshold: number
  pending: boolean
  error: string | null
  onConfirm: () => void
  onCheckFirst: () => void // close and go to the next low-confidence line
  onClose: () => void
}

/** What confirming will do, before it is done. Confirming accepts every line
 * nobody acted on (decision 2026-10-19), so the dialog says how many, and how
 * many of those are below the highlight threshold. */
export function ConfirmDialog({ lines, threshold, pending, error, onConfirm, onCheckFirst, onClose }: ConfirmDialogProps) {
  const count = (action: DraftLine['human_action']) => lines.filter((l) => l.human_action === action).length
  const untouched = lines.filter((l) => l.human_action === 'untouched')
  const unchecked = untouched.filter((l) => isFlagged(l, threshold)).length
  const deleted = count('deleted')
  const done = [
    count('accepted') && `${count('accepted')} accepted`,
    count('edited') && `${count('edited')} edited`,
    count('added') && `${count('added')} added`,
    deleted && `${deleted} deleted (left out)`,
  ].filter(Boolean)

  return (
    <Modal title="Confirm document" onClose={pending ? () => {} : onClose}>
      <div className="space-y-3 text-sm text-ink">
        <p>
          Confirming saves a verified version that Component 03 can audit. It cannot be changed afterwards;
          reopening the document later creates a new version.
        </p>

        <p className="text-ink-muted">{done.length > 0 ? `Your review: ${done.join(' · ')}.` : 'You have not reviewed any lines yet.'}</p>

        {untouched.length > 0 && (
          <div className="rounded-(--radius) border border-warning/30 bg-warning/8 px-3 py-2.5">
            <p className="text-ink-h">
              {pluralize(untouched.length, 'line')} you have not reviewed will be marked <strong>accepted</strong>.
            </p>
            {unchecked > 0 && (
              <p className="mt-1 text-warning">
                {unchecked} of them {unchecked === 1 ? 'is' : 'are'} below the highlight threshold ({threshold.toFixed(2)}).
              </p>
            )}
          </div>
        )}

        {error && (
          <p role="alert" className="flex items-start gap-1.5 text-danger">
            <CircleAlert size={15} className="mt-0.5 shrink-0" aria-hidden /> {error}
          </p>
        )}
      </div>

      <div className="mt-5 flex flex-wrap justify-end gap-2">
        {unchecked > 0 && (
          <Button variant="ghost" onClick={onCheckFirst} disabled={pending} className="mr-auto">
            <ScanSearch size={15} aria-hidden /> Check them first
          </Button>
        )}
        <Button onClick={onClose} disabled={pending}>Cancel</Button>
        <Button variant="primary" onClick={onConfirm} disabled={pending}>
          {pending ? 'Confirming…' : untouched.length > 0 ? `Accept ${untouched.length} and confirm` : 'Confirm'}
        </Button>
      </div>
    </Modal>
  )
}
