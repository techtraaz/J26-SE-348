import clsx from 'clsx'
import { CircleAlert, CircleCheck, Clock, LoaderCircle, ScanSearch } from 'lucide-react'

import { statusMeta } from './status'
import type { StatusTone } from './status'

// Status colours from the app palette, as soft tints of the same token.
const TONES: Record<StatusTone, string> = {
  slate: 'bg-surface-muted text-ink-muted',
  blue: 'bg-info/12 text-info',
  amber: 'bg-warning/14 text-warning',
  green: 'bg-success/12 text-success',
  red: 'bg-danger/12 text-danger',
}

function StatusIcon({ status }: { status: string }) {
  const props = { size: 13, 'aria-hidden': true }
  switch (status) {
    case 'processing':
      return <LoaderCircle {...props} className="animate-spin" />
    case 'needs_review':
      return <ScanSearch {...props} />
    case 'verified':
      return <CircleCheck {...props} />
    case 'failed':
      return <CircleAlert {...props} />
    default:
      return <Clock {...props} />
  }
}

export function StatusChip({ status }: { status: string }) {
  const { label, tone } = statusMeta(status)
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium',
        TONES[tone],
      )}
    >
      <StatusIcon status={status} />
      {label}
    </span>
  )
}
