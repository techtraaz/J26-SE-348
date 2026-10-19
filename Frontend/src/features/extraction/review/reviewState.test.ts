import { describe, expect, it } from 'vitest'

import type { DraftLine } from '@/features/extraction/api/types'
import {
  editableLines,
  initReview,
  isFlagged,
  neighbour,
  newLine,
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
      { type: 'delete', ids: ['a'] } as const,
      { type: 'editText', id: 'a', text: 'x' } as const,
      { type: 'editText', id: 'n', text: 'y' } as const,
    ].reduce(reviewReducer, initReview([...LINES, added]))
    expect(action(state, 'a')).toBe('deleted')
    expect(action(state, 'n')).toBe('added')
  })

  it('accepts only lines nobody has acted on', () => {
    const state = run(
      { type: 'accept', ids: ['a'] },
      { type: 'editText', id: 'b', text: 'x' },
      { type: 'accept', ids: ['b'] },
    )
    expect(action(state, 'a')).toBe('accepted')
    expect(action(state, 'b')).toBe('edited') // still edited
    expect(state.revision).toBe(2) // the second accept changed nothing
  })

  it('deletes and restores, keeping the line in the draft', () => {
    const deleted = run({ type: 'delete', ids: ['c'] })
    expect(deleted.lines).toHaveLength(5)
    expect(action(deleted, 'c')).toBe('deleted')

    const restored = reviewReducer(deleted, { type: 'restore', ids: ['c'] })
    expect(action(restored, 'c')).toBe('untouched')
  })

  it('restores an added line as added', () => {
    const added = line('n', null, { region_id: null, human_action: 'deleted' })
    const state = reviewReducer(initReview([added]), { type: 'restore', ids: ['n'] })
    expect(state.lines[0].human_action).toBe('added')
  })

  it('undoes and redoes, and a new change clears the redo history', () => {
    const edited = run({ type: 'editText', id: 'a', text: 'one' }, { type: 'editText', id: 'a', text: 'two' })

    const undone = reviewReducer(edited, { type: 'undo' })
    expect(undone.lines[0].text).toBe('one')
    expect(undone.revision).toBe(3) // undo is a change autosave must see

    const redone = reviewReducer(undone, { type: 'redo' })
    expect(redone.lines[0].text).toBe('two')

    const branched = reviewReducer(undone, { type: 'accept', ids: ['c'] })
    expect(branched.future).toHaveLength(0)
    expect(reviewReducer(branched, { type: 'redo' })).toBe(branched)
  })

  it('does nothing when there is nothing to undo or redo', () => {
    const state = initReview(LINES)
    expect(reviewReducer(state, { type: 'undo' })).toBe(state)
    expect(reviewReducer(state, { type: 'redo' })).toBe(state)
  })
})

describe('bulk actions', () => {
  it('accepts several lines in one undo step, skipping lines already acted on', () => {
    const state = run(
      { type: 'editText', id: 'a', text: 'fixed' },
      { type: 'delete', ids: ['c'] },
      { type: 'accept', ids: ['a', 'b', 'c', 'd'] },
    )
    expect(['a', 'b', 'c', 'd'].map((id) => action(state, id))).toEqual(['edited', 'accepted', 'deleted', 'accepted'])

    const undone = reviewReducer(state, { type: 'undo' })
    expect(['b', 'd'].map((id) => action(undone, id))).toEqual(['untouched', 'untouched'])
  })

  it('deletes and restores several lines at once', () => {
    const deleted = run({ type: 'delete', ids: ['a', 'b'] })
    expect(deleted.past).toHaveLength(1)
    const restored = reviewReducer(deleted, { type: 'restore', ids: ['a', 'b', 'c'] })
    expect(['a', 'b', 'c'].map((id) => action(restored, id))).toEqual(['untouched', 'untouched', 'untouched'])
  })
})

describe('boxes and added lines', () => {
  // Two rows on page 1 and one on page 2.
  const PLACED = [
    line('top', 0.99, { page: 1, sequence: 0, box: [10, 10, 100, 30] }),
    line('mid', 0.99, { page: 1, sequence: 1, box: [10, 100, 100, 120] }),
    line('p2', 0.99, { page: 2, sequence: 2, box: [10, 10, 100, 30] }),
  ]
  const order = (state: ReturnType<typeof run>) => state.lines.map((l) => `${l.line_id}:${l.sequence}`)

  it('marks a moved machine box edited, and ignores a move to the same place', () => {
    const moved = reviewReducer(initReview(PLACED), { type: 'moveBox', id: 'top', box: [12, 10, 102, 30] })
    expect(moved.lines[0]).toMatchObject({ box: [12, 10, 102, 30], human_action: 'edited' })
    expect(reviewReducer(initReview(PLACED), { type: 'moveBox', id: 'top', box: [10, 10, 100, 30] }).revision).toBe(0)
  })

  it('does not move a deleted line', () => {
    const state = [
      { type: 'delete', ids: ['top'] } as const,
      { type: 'moveBox', id: 'top', box: [0, 0, 50, 50] } as const,
    ].reduce(reviewReducer, initReview(PLACED))
    expect(state.lines[0].box).toEqual([10, 10, 100, 30])
  })

  it('places a drawn line in reading order and renumbers', () => {
    const between = reviewReducer(initReview(PLACED), { type: 'addLine', line: newLine(1, [10, 50, 90, 70], 'new') })
    expect(order(between)).toEqual(['top:0', 'new:1', 'mid:2', 'p2:3'])

    const sameRow = reviewReducer(initReview(PLACED), { type: 'addLine', line: newLine(1, [120, 12, 200, 28], 'new') })
    expect(order(sameRow)).toEqual(['top:0', 'new:1', 'mid:2', 'p2:3']) // right of "top", same row

    const leftOfRow = reviewReducer(initReview(PLACED), { type: 'addLine', line: newLine(1, [0, 102, 8, 118], 'new') })
    expect(order(leftOfRow)).toEqual(['top:0', 'new:1', 'mid:2', 'p2:3']) // left of "mid", same row

    const end = reviewReducer(initReview(PLACED), { type: 'addLine', line: newLine(2, [10, 300, 90, 320], 'new') })
    expect(order(end)).toEqual(['top:0', 'mid:1', 'p2:2', 'new:3'])
  })

  it('adds a line the way the server stores it', () => {
    const added = newLine(1, [10, 50, 90, 70], 'new')
    expect(added).toMatchObject({ region_id: null, human_action: 'added', provenance: 'human', confidence: null })
  })

  it('discards an added line entirely, but never a machine line', () => {
    const added = reviewReducer(initReview(PLACED), { type: 'addLine', line: newLine(1, [10, 50, 90, 70], 'new') })
    const discarded = reviewReducer(added, { type: 'discardAdded', id: 'new' })
    expect(order(discarded)).toEqual(['top:0', 'mid:1', 'p2:2'])
    expect(reviewReducer(added, { type: 'discardAdded', id: 'top' })).toBe(added)
  })

  it('keeps a moved added line added', () => {
    const added = reviewReducer(initReview(PLACED), { type: 'addLine', line: newLine(1, [10, 50, 90, 70], 'new') })
    const moved = reviewReducer(added, { type: 'moveBox', id: 'new', box: [20, 50, 100, 70] })
    expect(moved.lines[1]).toMatchObject({ box: [20, 50, 100, 70], human_action: 'added' })
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

    const reviewed = run({ type: 'accept', ids: ['b'] }).lines
    expect(nextFlagged(reviewed, 'd', 0.9)).toBe('d') // only d left
    expect(nextFlagged(run({ type: 'accept', ids: ['b'] }, { type: 'delete', ids: ['d'] }).lines, null, 0.9)).toBeNull()
  })
})

describe('editableLines', () => {
  it('sends only what the reviewer controls', () => {
    expect(Object.keys(editableLines(LINES)[0]).sort()).toEqual(
      ['box', 'human_action', 'line_id', 'page', 'region_id', 'sequence', 'text'],
    )
  })
})
