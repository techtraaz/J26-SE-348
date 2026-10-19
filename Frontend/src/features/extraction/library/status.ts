import type { DocumentStatus } from '@/features/extraction/api/types'

export type StatusTone = 'slate' | 'blue' | 'amber' | 'green' | 'red'

export const STATUS_META: Record<DocumentStatus, { label: string; tone: StatusTone }> = {
  uploaded: { label: 'Queued', tone: 'slate' },
  processing: { label: 'Processing', tone: 'blue' },
  needs_review: { label: 'Needs review', tone: 'amber' },
  verified: { label: 'Verified', tone: 'green' },
  failed: { label: 'Failed', tone: 'red' },
}

export function statusMeta(status: string): { label: string; tone: StatusTone } {
  return STATUS_META[status as DocumentStatus] ?? { label: status, tone: 'slate' }
}

/** Filter pills in the library. "In progress" covers queued and processing. */
export type StatusFilter = 'all' | 'in_progress' | 'needs_review' | 'verified' | 'failed'

export const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'needs_review', label: 'Needs review' },
  { id: 'verified', label: 'Verified' },
  { id: 'failed', label: 'Failed' },
]

export function matchesFilter(status: string, filter: StatusFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'in_progress') return status === 'uploaded' || status === 'processing'
  return status === filter
}

export function parseStatusFilter(value: string | null): StatusFilter {
  return STATUS_FILTERS.some((f) => f.id === value) ? (value as StatusFilter) : 'all'
}
