import { describe, expect, it } from 'vitest'

import {
  boxRect,
  clampScale,
  fitWidthScale,
  scrollToShow,
  sizeMatches,
  stepScale,
  toPagePoint,
} from './geometry'

const PAGE = { width: 754, height: 1000 }

describe('fitWidthScale', () => {
  it('scales the page to the viewport width minus padding', () => {
    expect(fitWidthScale(PAGE, 754 / 2 + 32, 16)).toBeCloseTo(0.5)
  })

  it('stays within the zoom limits and survives empty sizes', () => {
    expect(fitWidthScale(PAGE, 100_000)).toBe(4)
    expect(fitWidthScale(PAGE, 10)).toBe(0.1)
    expect(fitWidthScale({ width: 0, height: 0 }, 500)).toBe(1)
    expect(fitWidthScale(PAGE, 0)).toBe(1)
  })
})

describe('stepScale', () => {
  it('moves to the next zoom step in either direction', () => {
    expect(stepScale(1, 1)).toBe(1.25)
    expect(stepScale(1, -1)).toBe(0.9)
    expect(stepScale(0.6, 1)).toBe(0.67) // from a fit scale between steps
    expect(stepScale(0.6, -1)).toBe(0.5)
  })

  it('stops at the ends', () => {
    expect(stepScale(4, 1)).toBe(4)
    expect(stepScale(0.1, -1)).toBe(0.1)
  })

  it('clamps nonsense', () => {
    expect(clampScale(Number.NaN)).toBe(1)
    expect(clampScale(99)).toBe(4)
  })
})

describe('boxRect', () => {
  it('turns [x1, y1, x2, y2] into an SVG rectangle in page pixels', () => {
    expect(boxRect([10, 20, 110, 40])).toEqual({ x: 10, y: 20, width: 100, height: 20 })
  })

  it('tolerates swapped corners', () => {
    expect(boxRect([110, 40, 10, 20])).toEqual({ x: 10, y: 20, width: 100, height: 20 })
  })
})

describe('toPagePoint', () => {
  // The page is displayed at half size, 30px from the left and 40px from the top.
  const shown = { left: 30, top: 40, width: 377, height: 500 }

  it('converts a screen point to page pixels', () => {
    const point = toPagePoint(30 + 50, 40 + 100, shown, PAGE)
    expect(point.x).toBeCloseTo(100)
    expect(point.y).toBeCloseTo(200)
  })

  it('is the inverse of drawing a box corner at that scale', () => {
    const [x1, y1] = [52, 610]
    const point = toPagePoint(shown.left + x1 * 0.5, shown.top + y1 * 0.5, shown, PAGE)
    expect(point.x).toBeCloseTo(x1)
    expect(point.y).toBeCloseTo(y1)
  })

  it('clamps points outside the page to its edge', () => {
    expect(toPagePoint(0, 9999, shown, PAGE)).toEqual({ x: 0, y: 1000 })
  })
})

describe('scrollToShow', () => {
  const viewport = { scrollLeft: 0, scrollTop: 0, width: 400, height: 300 }

  it('leaves a visible box alone', () => {
    expect(scrollToShow([10, 20, 110, 40], 1, viewport)).toBeNull()
  })

  it('centres a box that is out of view', () => {
    expect(scrollToShow([100, 900, 300, 940], 1, viewport)).toEqual({ left: 0, top: 770 })
  })

  it('accounts for the display scale', () => {
    expect(scrollToShow([100, 900, 300, 940], 0.5, viewport)).toEqual({ left: 0, top: 310 })
  })
})

describe('sizeMatches', () => {
  it('detects an image that is not the OCR-space image', () => {
    expect(sizeMatches({ width: 754, height: 1000 }, PAGE)).toBe(true)
    expect(sizeMatches({ width: 1508, height: 2000 }, PAGE)).toBe(false)
  })
})
