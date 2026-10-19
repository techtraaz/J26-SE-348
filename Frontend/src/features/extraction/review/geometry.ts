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

/** True when the image the browser loaded is the size the boxes refer to.
 * A mismatch means the boxes would be misplaced (Risk 2). */
export function sizeMatches(natural: Size, page: Size): boolean {
  return natural.width === page.width && natural.height === page.height
}
