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

export type ReviewAction =
  | { type: 'editText'; id: string; text: string }
  | { type: 'accept'; id: string }
  | { type: 'delete'; id: string }
  | { type: 'restore'; id: string }
  | { type: 'undo' }
  | { type: 'redo' }

const HISTORY_LIMIT = 200

export function initReview(lines: DraftLine[]): ReviewState {
  return { lines, past: [], future: [], revision: 0 }
}

function updateLine(lines: DraftLine[], id: string, update: (line: DraftLine) => DraftLine): DraftLine[] {
  let changed = false
  const next = lines.map((line) => {
    if (line.line_id !== id) return line
    const updated = update(line)
    if (updated !== line) changed = true
    return updated
  })
  return changed ? next : lines
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
      return commit(
        state,
        updateLine(state.lines, action.id, (line) =>
          line.human_action === 'untouched' ? { ...line, human_action: 'accepted' } : line,
        ),
      )
    case 'delete':
      return commit(
        state,
        updateLine(state.lines, action.id, (line) =>
          line.human_action === 'deleted' ? line : { ...line, human_action: 'deleted' },
        ),
      )
    case 'restore':
      return commit(
        state,
        updateLine(state.lines, action.id, (line) =>
          line.human_action !== 'deleted'
            ? line
            : { ...line, human_action: line.region_id === null ? 'added' : 'untouched' },
        ),
      )
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
