import { useState } from 'react'

export type ViewMode = 'list' | 'grid'
const KEY = 'auditmind.library.view'

/** List/grid preference, remembered across visits. */
export function useViewMode(): [ViewMode, (mode: ViewMode) => void] {
  const [mode, setMode] = useState<ViewMode>(() => {
    try {
      return localStorage.getItem(KEY) === 'grid' ? 'grid' : 'list'
    } catch {
      return 'list'
    }
  })
  const update = (next: ViewMode) => {
    setMode(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      // storage unavailable: the choice just won't persist
    }
  }
  return [mode, update]
}
