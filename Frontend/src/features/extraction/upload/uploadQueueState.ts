/** State of the upload queue (the panel in the corner of the library). */

export type UploadStatus = 'uploading' | 'done' | 'error'

export interface UploadItem {
  id: string
  name: string
  size: number
  status: UploadStatus
  /** 0..1 upload progress (bytes sent), not extraction progress. */
  progress: number
  error?: string
  documentId?: string
}

export type UploadAction =
  | { type: 'add'; items: UploadItem[] }
  | { type: 'progress'; id: string; progress: number }
  | { type: 'done'; id: string; documentId: string }
  | { type: 'error'; id: string; message: string }
  | { type: 'dismiss'; id: string }
  | { type: 'clearFinished' }

export function uploadReducer(state: UploadItem[], action: UploadAction): UploadItem[] {
  switch (action.type) {
    case 'add':
      return [...state, ...action.items]
    case 'progress':
      return state.map((i) =>
        i.id === action.id && i.status === 'uploading' ? { ...i, progress: action.progress } : i,
      )
    case 'done':
      return state.map((i) =>
        i.id === action.id ? { ...i, status: 'done', progress: 1, documentId: action.documentId } : i,
      )
    case 'error':
      return state.map((i) =>
        i.id === action.id ? { ...i, status: 'error', error: action.message } : i,
      )
    case 'dismiss':
      return state.filter((i) => i.id !== action.id)
    case 'clearFinished':
      return state.filter((i) => i.status === 'uploading')
  }
}

export function newUploadItem(file: { name: string; size: number }, id: string): UploadItem {
  return { id, name: file.name, size: file.size, status: 'uploading', progress: 0 }
}

export function countByStatus(items: UploadItem[]): Record<UploadStatus, number> {
  const counts: Record<UploadStatus, number> = { uploading: 0, done: 0, error: 0 }
  for (const item of items) counts[item.status]++
  return counts
}
