import { useState } from 'react'

const KEY = 'nomos.review.threshold'
export const DEFAULT_THRESHOLD = 0.9

/** The low-confidence highlight threshold. Display only: it colours lines and
 * is never sent to the server or used for routing (D4). Remembered per
 * browser as a convenience. */
export function useDisplayThreshold(): [number, (value: number) => void] {
  const [threshold, setThreshold] = useState(() => {
    try {
      const stored = Number(localStorage.getItem(KEY))
      return stored > 0 && stored <= 1 ? stored : DEFAULT_THRESHOLD
    } catch {
      return DEFAULT_THRESHOLD
    }
  })
  const update = (value: number) => {
    setThreshold(value)
    try {
      localStorage.setItem(KEY, String(value))
    } catch {
      // storage unavailable (private window): keep it for this visit only
    }
  }
  return [threshold, update]
}
