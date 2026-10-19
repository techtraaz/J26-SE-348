/** The reviewer's working copy of a draft, with undo/redo.
 *
 * The rules mirror the server's (services/review/drafts.py), which stays the
 * authority: a changed machine line is `edited`, a false line is `deleted`
 * (kept, never removed), and machine fields are never touched here. */

import type { DraftLine } from '@/features/extraction/api/types'

export interface ReviewState {
  lines: DraftLine[]
  past: DraftLine[][]
  future: DraftLine[][]
  /** Increases with every change, undo and redo: autosave watches it. */
  revision: number
}

// accept/delete/restore take several lines (bulk actions): one undo step, one save.
export type ReviewAction =
  | { type: 'editText'; id: string; text: string }
  | { type: 'accept'; ids: readonly string[] }
  | { type: 'delete'; ids: readonly string[] }
  | { type: 'restore'; ids: readonly string[] }
  | { type: 'moveBox'; id: string; box: readonly number[] }
  | { type: 'addLine'; line: DraftLine }
  | { type: 'discardAdded'; id: string }
  | { type: 'undo' }
  | { type: 'redo' }

const HISTORY_LIMIT = 200

export function initReview(lines: DraftLine[]): ReviewState {
  return { lines, past: [], future: [], revision: 0 }
}

function updateLines(lines: DraftLine[], ids: readonly string[], update: (line: DraftLine) => DraftLine): DraftLine[] {
  const targets = new Set(ids)
  let changed = false
  const next = lines.map((line) => {
    if (!targets.has(line.line_id)) return line
    const updated = update(line)
    if (updated !== line) changed = true
    return updated
  })
  return changed ? next : lines
}

const updateLine = (lines: DraftLine[], id: string, update: (line: DraftLine) => DraftLine) =>
  updateLines(lines, [id], update)

/** Reading order is the array order; keep `sequence` matching it. */
function renumber(lines: DraftLine[]): DraftLine[] {
  return lines.map((line, i) => (line.sequence === i ? line : { ...line, sequence: i }))
}

const sameBox = (a: readonly number[], b: readonly number[]) => a.every((v, i) => v === b[i])

/** Where a new box belongs in reading order: after the last line that comes
 * before it (earlier page, higher on the page, or left of it on the same row). */
export function readingPosition(lines: DraftLine[], page: number, box: readonly number[]): number {
  const centre = { x: (box[0] + box[2]) / 2, y: (box[1] + box[3]) / 2 }
  const comesBefore = (line: DraftLine) => {
    if (line.page !== page) return line.page < page
    const y = (line.box[1] + line.box[3]) / 2
    const rowHeight = Math.max(line.box[3] - line.box[1], box[3] - box[1])
    if (Math.abs(y - centre.y) < rowHeight / 2) return (line.box[0] + line.box[2]) / 2 < centre.x
    return y < centre.y
  }
  let index = 0
  lines.forEach((line, i) => {
    if (comesBefore(line)) index = i + 1
  })
  return index
}

function commit(state: ReviewState, lines: DraftLine[]): ReviewState {
  if (lines === state.lines) return state
  return {
    lines,
    past: [...state.past, state.lines].slice(-HISTORY_LIMIT),
    future: [],
    revision: state.revision + 1,
  }
}

export function reviewReducer(state: ReviewState, action: ReviewAction): ReviewState {
  switch (action.type) {
    case 'editText':
      return commit(
        state,
        updateLine(state.lines, action.id, (line) => {
          if (line.text === action.text) return line
          // An added line stays added; a deleted line stays deleted until restored.
          const kept = line.region_id === null || line.human_action === 'deleted'
          return { ...line, text: action.text, human_action: kept ? line.human_action : 'edited' }
        }),
      )
    case 'accept':
      // Only lines nobody acted on: a bulk accept never overrides an edit or a delete.
      return commit(
        state,
        updateLines(state.lines, action.ids, (line) =>
          line.human_action === 'untouched' ? { ...line, human_action: 'accepted' } : line,
        ),
      )
    case 'delete':
      return commit(
        state,
        updateLines(state.lines, action.ids, (line) =>
          line.human_action === 'deleted' ? line : { ...line, human_action: 'deleted' },
        ),
      )
    case 'restore':
      return commit(
        state,
        updateLines(state.lines, action.ids, (line) =>
          line.human_action !== 'deleted'
            ? line
            : { ...line, human_action: line.region_id === null ? 'added' : 'untouched' },
        ),
      )
    case 'moveBox':
      return commit(
        state,
        updateLine(state.lines, action.id, (line) => {
          if (line.human_action === 'deleted' || sameBox(line.box, action.box)) return line
          return { ...line, box: [...action.box], human_action: line.region_id === null ? 'added' : 'edited' }
        }),
      )
    case 'addLine': {
      const at = readingPosition(state.lines, action.line.page, action.line.box)
      const lines = [...state.lines.slice(0, at), action.line, ...state.lines.slice(at)]
      return commit(state, renumber(lines))
    }
    case 'discardAdded': {
      // Only a line the reviewer added can disappear; machine lines are deleted, never removed.
      const index = state.lines.findIndex((l) => l.line_id === action.id && l.region_id === null)
      if (index === -1) return state
      return commit(state, renumber(state.lines.filter((_, i) => i !== index)))
    }
    case 'undo': {
      const previous = state.past.at(-1)
      if (!previous) return state
      return {
        lines: previous,
        past: state.past.slice(0, -1),
        future: [state.lines, ...state.future],
        revision: state.revision + 1,
      }
    }
    case 'redo': {
      const [next, ...rest] = state.future
      if (!next) return state
      return { lines: next, past: [...state.past, state.lines], future: rest, revision: state.revision + 1 }
    }
  }
}

// ---- reading the lines -----------------------------------------------------

/** Below the display threshold. A reading aid only: raw scores are not
 * calibrated (D4), and lines without a score are never flagged. */
export function isFlagged(line: DraftLine, threshold: number): boolean {
  return line.confidence != null && line.confidence < threshold
}

export function isReviewed(line: DraftLine): boolean {
  return line.human_action !== 'untouched'
}

/** The line before or after `id` in reading order (null at the ends). */
export function neighbour(lines: DraftLine[], id: string | null, direction: 1 | -1): string | null {
  if (lines.length === 0) return null
  const index = lines.findIndex((l) => l.line_id === id)
  if (index === -1) return direction > 0 ? lines[0].line_id : lines.at(-1)!.line_id
  return lines[index + direction]?.line_id ?? null
}

/** The next flagged line nobody has acted on, after `id`, wrapping around. */
export function nextFlagged(lines: DraftLine[], id: string | null, threshold: number): string | null {
  const start = lines.findIndex((l) => l.line_id === id)
  for (let step = 1; step <= lines.length; step++) {
    const line = lines[(start + step + lines.length) % lines.length]
    if (isFlagged(line, threshold) && !isReviewed(line)) return line.line_id
  }
  return null
}

/** A line the reviewer drew. The server fills confidence (none) and
 * provenance ("human") the same way. */
export function newLine(page: number, box: number[], lineId: string = crypto.randomUUID()): DraftLine {
  return {
    line_id: lineId,
    region_id: null,
    page,
    sequence: 0, // set by its reading position
    text: '',
    box,
    human_action: 'added',
    confidence: null,
    provenance: 'human',
    escalated: null,
  }
}

/** The fields a reviewer controls: what PUT /review accepts. */
export function editableLines(lines: DraftLine[]) {
  return lines.map(({ line_id, region_id, page, sequence, text, box, human_action }) => ({
    line_id,
    region_id,
    page,
    sequence,
    text,
    box,
    human_action,
  }))
}
