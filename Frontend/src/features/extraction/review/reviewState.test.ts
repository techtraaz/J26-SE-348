import { describe, expect, it } from 'vitest'

import type { DraftLine } from '@/features/extraction/api/types'
import {
  editableLines,
  initReview,
  isFlagged,
  neighbour,
  nextFlagged,
  reviewReducer,
} from './reviewState'

function line(id: string, confidence: number | null, extra: Partial<DraftLine> = {}): DraftLine {
  return {
    line_id: id, region_id: id, page: 1, sequence: 0, text: `text ${id}`, box: [0, 0, 10, 10],
    human_action: 'untouched', confidence, provenance: 'paddleocr', escalated: null, ...extra,
  }
}

const LINES = [line('a', 0.99), line('b', 0.41), line('c', 0.95), line('d', 0.62), line('e', null)]
const run = (...actions: Parameters<typeof reviewReducer>[1][]) =>
  actions.reduce(reviewReducer, initReview(LINES))
const action = (state: ReturnType<typeof run>, id: string) =>
  state.lines.find((l) => l.line_id === id)!.human_action

describe('reviewReducer', () => {
  it('marks a machine line edited when its text changes', () => {
    const state = run({ type: 'editText', id: 'b', text: 'TOTAL 42.50' })
    expect(state.lines[1]).toMatchObject({ text: 'TOTAL 42.50', human_action: 'edited' })
    expect(state.lines[1].confidence).toBe(0.41) // machine score untouched
    expect(state.revision).toBe(1)
  })

  it('ignores an edit that changes nothing', () => {
    const state = run({ type: 'editText', id: 'b', text: 'text b' })
    expect(state.revision).toBe(0)
    expect(state.past).toHaveLength(0)
  })

  it('keeps an added line added, and a deleted line deleted, when edited', () => {
    const added = line('n', null, { region_id: null, provenance: 'human', human_action: 'added' })
    const state = [
      { type: 'delete', id: 'a' } as const,
      { type: 'editText', id: 'a', text: 'x' } as const,
      { type: 'editText', id: 'n', text: 'y' } as const,
    ].reduce(reviewReducer, initReview([...LINES, added]))
    expect(action(state, 'a')).toBe('deleted')
    expect(action(state, 'n')).toBe('added')
  })

  it('accepts only lines nobody has acted on', () => {
    const state = run(
      { type: 'accept', id: 'a' },
      { type: 'editText', id: 'b', text: 'x' },
      { type: 'accept', id: 'b' },
    )
    expect(action(state, 'a')).toBe('accepted')
    expect(action(state, 'b')).toBe('edited') // still edited
    expect(state.revision).toBe(2) // the second accept changed nothing
  })

  it('deletes and restores, keeping the line in the draft', () => {
    const deleted = run({ type: 'delete', id: 'c' })
    expect(deleted.lines).toHaveLength(5)
    expect(action(deleted, 'c')).toBe('deleted')

    const restored = reviewReducer(deleted, { type: 'restore', id: 'c' })
    expect(action(restored, 'c')).toBe('untouched')
  })

  it('restores an added line as added', () => {
    const added = line('n', null, { region_id: null, human_action: 'deleted' })
    const state = reviewReducer(initReview([added]), { type: 'restore', id: 'n' })
    expect(state.lines[0].human_action).toBe('added')
  })

  it('undoes and redoes, and a new change clears the redo history', () => {
    const edited = run({ type: 'editText', id: 'a', text: 'one' }, { type: 'editText', id: 'a', text: 'two' })

    const undone = reviewReducer(edited, { type: 'undo' })
    expect(undone.lines[0].text).toBe('one')
    expect(undone.revision).toBe(3) // undo is a change autosave must see

    const redone = reviewReducer(undone, { type: 'redo' })
    expect(redone.lines[0].text).toBe('two')

    const branched = reviewReducer(undone, { type: 'accept', id: 'c' })
    expect(branched.future).toHaveLength(0)
    expect(reviewReducer(branched, { type: 'redo' })).toBe(branched)
  })

  it('does nothing when there is nothing to undo or redo', () => {
    const state = initReview(LINES)
    expect(reviewReducer(state, { type: 'undo' })).toBe(state)
    expect(reviewReducer(state, { type: 'redo' })).toBe(state)
  })
})

describe('navigation', () => {
  it('flags only scored lines below the threshold', () => {
    expect(LINES.filter((l) => isFlagged(l, 0.9)).map((l) => l.line_id)).toEqual(['b', 'd'])
    expect(isFlagged(LINES[4], 0.9)).toBe(false) // no score is not low confidence
  })

  it('moves to neighbouring lines and stops at the ends', () => {
    expect(neighbour(LINES, 'b', 1)).toBe('c')
    expect(neighbour(LINES, 'b', -1)).toBe('a')
    expect(neighbour(LINES, 'e', 1)).toBeNull()
    expect(neighbour(LINES, null, 1)).toBe('a')
    expect(neighbour(LINES, null, -1)).toBe('e')
  })

  it('finds the next flagged line nobody has reviewed, wrapping around', () => {
    expect(nextFlagged(LINES, null, 0.9)).toBe('b')
    expect(nextFlagged(LINES, 'b', 0.9)).toBe('d')
    expect(nextFlagged(LINES, 'd', 0.9)).toBe('b')

    const reviewed = run({ type: 'accept', id: 'b' }).lines
    expect(nextFlagged(reviewed, 'd', 0.9)).toBe('d') // only d left
    expect(nextFlagged(run({ type: 'accept', id: 'b' }, { type: 'delete', id: 'd' }).lines, null, 0.9)).toBeNull()
  })
})

describe('editableLines', () => {
  it('sends only what the reviewer controls', () => {
    expect(Object.keys(editableLines(LINES)[0]).sort()).toEqual(
      ['box', 'human_action', 'line_id', 'page', 'region_id', 'sequence', 'text'],
    )
  })
})
