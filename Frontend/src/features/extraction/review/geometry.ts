/** Page geometry for the review viewer.
 *
 * Boxes are [x1, y1, x2, y2] in the pixels of the OCR-space image of their
 * page (D3). The overlay is an SVG whose viewBox is that page size, so boxes
 * are drawn in those pixels directly and scale together with the image; boxes
 * cannot drift from the text at any zoom. These helpers cover the rest: zoom,
 * box rectangles, and converting a screen point back to page pixels. */

export type Box = readonly number[] // [x1, y1, x2, y2]

export interface Size {
  width: number
  height: number
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

/** Display scale: 1 = one image pixel per CSS pixel. */
export const MIN_SCALE = 0.1
export const MAX_SCALE = 4
export const ZOOM_STEPS = [0.1, 0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1, 1.25, 1.5, 2, 3, 4]

export function clampScale(scale: number): number {
  if (!Number.isFinite(scale)) return 1
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale))
}

/** The scale at which the page fills the viewport's width (minus padding on each side). */
export function fitWidthScale(page: Size, viewportWidth: number, padding = 0): number {
  if (page.width <= 0 || viewportWidth <= 0) return 1
  return clampScale((viewportWidth - 2 * padding) / page.width)
}

/** The next zoom step above (direction 1) or below (-1) the current scale. */
export function stepScale(current: number, direction: 1 | -1): number {
  const eps = 1e-6
  const next =
    direction > 0
      ? ZOOM_STEPS.find((s) => s > current + eps)
      : [...ZOOM_STEPS].reverse().find((s) => s < current - eps)
  return next ?? clampScale(current)
}

/** A box as an SVG rectangle, tolerating swapped corners. */
export function boxRect(box: Box): Rect {
  const [x1, y1, x2, y2] = box
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.abs(x2 - x1),
    height: Math.abs(y2 - y1),
  }
}

/** A point on screen (e.g. a pointer event) in page pixels, clamped to the
 * page. `element` is the on-screen rectangle of the displayed page. */
export function toPagePoint(
  clientX: number,
  clientY: number,
  element: { left: number; top: number; width: number; height: number },
  page: Size,
): { x: number; y: number } {
  const x = ((clientX - element.left) / element.width) * page.width
  const y = ((clientY - element.top) / element.height) * page.height
  return {
    x: Math.min(page.width, Math.max(0, x)),
    y: Math.min(page.height, Math.max(0, y)),
  }
}

/** Scroll offsets that bring a box into the middle of the viewport, or null
 * when it is already fully visible. */
export function scrollToShow(
  box: Box,
  scale: number,
  viewport: { scrollLeft: number; scrollTop: number; width: number; height: number },
): { left: number; top: number } | null {
  const r = boxRect(box)
  const left = r.x * scale
  const top = r.y * scale
  const right = left + r.width * scale
  const bottom = top + r.height * scale
  const visible =
    left >= viewport.scrollLeft &&
    top >= viewport.scrollTop &&
    right <= viewport.scrollLeft + viewport.width &&
    bottom <= viewport.scrollTop + viewport.height
  if (visible) return null
  return {
    left: Math.max(0, (left + right) / 2 - viewport.width / 2),
    top: Math.max(0, (top + bottom) / 2 - viewport.height / 2),
  }
}

// ---- editing boxes (M4.4) --------------------------------------------------

/** Smallest box a reviewer can draw or resize to, in page pixels. */
export const MIN_BOX = 4

export type Corner = 'nw' | 'ne' | 'sw' | 'se'

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** The box spanned by two points (any order), as whole page pixels inside
 * the page; null when it is too small to be a deliberate box. */
export function boxFromPoints(
  a: { x: number; y: number },
  b: { x: number; y: number },
  page: Size,
): number[] | null {
  const x1 = Math.round(clamp(Math.min(a.x, b.x), 0, page.width))
  const y1 = Math.round(clamp(Math.min(a.y, b.y), 0, page.height))
  const x2 = Math.round(clamp(Math.max(a.x, b.x), 0, page.width))
  const y2 = Math.round(clamp(Math.max(a.y, b.y), 0, page.height))
  return x2 - x1 >= MIN_BOX && y2 - y1 >= MIN_BOX ? [x1, y1, x2, y2] : null
}

/** A box shifted by (dx, dy) page pixels, kept whole and inside the page. */
export function moveBox(box: Box, dx: number, dy: number, page: Size): number[] {
  const r = boxRect(box)
  const width = Math.min(r.width, page.width)
  const height = Math.min(r.height, page.height)
  const x = Math.round(clamp(r.x + dx, 0, page.width - width))
  const y = Math.round(clamp(r.y + dy, 0, page.height - height))
  return [x, y, x + Math.round(width), y + Math.round(height)]
}

/** A box with one corner dragged to `point`; the opposite corner stays put. */
export function resizeBox(box: Box, corner: Corner, point: { x: number; y: number }, page: Size): number[] {
  const r = boxRect(box)
  const fixed = {
    x: corner === 'nw' || corner === 'sw' ? r.x + r.width : r.x,
    y: corner === 'nw' || corner === 'ne' ? r.y + r.height : r.y,
  }
  // Keep at least MIN_BOX on each axis, on the side the corner is dragged towards.
  const x = corner === 'nw' || corner === 'sw' ? Math.min(point.x, fixed.x - MIN_BOX) : Math.max(point.x, fixed.x + MIN_BOX)
  const y = corner === 'nw' || corner === 'ne' ? Math.min(point.y, fixed.y - MIN_BOX) : Math.max(point.y, fixed.y + MIN_BOX)
  return boxFromPoints(fixed, { x, y }, page) ?? [...box]
}

/** True when the image the browser loaded is the size the boxes refer to.
 * A mismatch means the boxes would be misplaced (Risk 2). */
export function sizeMatches(natural: Size, page: Size): boolean {
  return natural.width === page.width && natural.height === page.height
}
