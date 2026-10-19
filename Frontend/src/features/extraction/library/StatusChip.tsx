import clsx from 'clsx'
import { CircleAlert, CircleCheck, Clock, LoaderCircle, ScanSearch } from 'lucide-react'

import { statusMeta } from './status'
import type { StatusTone } from './status'

const TONES: Record<StatusTone, string> = {
  slate: 'bg-slate-100 text-slate-700',
  blue: 'bg-blue-50 text-blue-700',
  amber: 'bg-amber-50 text-amber-800',
  green: 'bg-green-50 text-green-700',
  red: 'bg-red-50 text-red-700',
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
