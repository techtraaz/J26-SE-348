import { describe, expect, it } from 'vitest'

import { formatBytes, formatDuration, formatRelativeTime, pluralize } from './format'

describe('formatBytes', () => {
  it('scales units', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(25 * 1024 * 1024)).toBe('25 MB')
  })
})

describe('formatRelativeTime', () => {
  const now = new Date('2026-10-17T12:00:00Z')
  it('describes recent and older times', () => {
    expect(formatRelativeTime('2026-10-17T11:59:50Z', now)).toBe('just now')
    expect(formatRelativeTime('2026-10-17T11:30:00Z', now)).toBe('30 min ago')
    expect(formatRelativeTime('2026-10-17T07:00:00Z', now)).toBe('5 h ago')
    expect(formatRelativeTime('2026-10-14T12:00:00Z', now)).toBe('3 d ago')
  })
})

describe('formatDuration', () => {
  it('formats seconds and minutes', () => {
    expect(formatDuration(4200)).toBe('4.2 s')
    expect(formatDuration(52000)).toBe('52 s')
    expect(formatDuration(125000)).toBe('2 min 5 s')
  })
})

describe('pluralize', () => {
  it('handles one and many', () => {
    expect(pluralize(1, 'page')).toBe('1 page')
    expect(pluralize(0, 'page')).toBe('0 pages')
    expect(pluralize(3, 'item')).toBe('3 items')
  })
})
