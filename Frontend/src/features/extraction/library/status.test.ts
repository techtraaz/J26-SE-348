import { describe, expect, it } from 'vitest'

import { matchesFilter, parseStatusFilter, statusMeta } from './status'

describe('status filters', () => {
  it('"in progress" covers queued and processing documents', () => {
    expect(matchesFilter('uploaded', 'in_progress')).toBe(true)
    expect(matchesFilter('processing', 'in_progress')).toBe(true)
    expect(matchesFilter('needs_review', 'in_progress')).toBe(false)
  })

  it('"all" matches everything and other filters match exactly', () => {
    expect(matchesFilter('failed', 'all')).toBe(true)
    expect(matchesFilter('failed', 'failed')).toBe(true)
    expect(matchesFilter('verified', 'failed')).toBe(false)
  })

  it('ignores unknown filter values in the URL', () => {
    expect(parseStatusFilter('verified')).toBe('verified')
    expect(parseStatusFilter('bogus')).toBe('all')
    expect(parseStatusFilter(null)).toBe('all')
  })

  it('has readable labels and a safe fallback for unknown statuses', () => {
    expect(statusMeta('needs_review').label).toBe('Needs review')
    expect(statusMeta('uploaded').label).toBe('Queued')
    expect(statusMeta('something_new')).toEqual({ label: 'something_new', tone: 'slate' })
  })
})
