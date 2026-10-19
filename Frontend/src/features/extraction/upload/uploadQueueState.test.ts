import { describe, expect, it } from 'vitest'

import { countByStatus, newUploadItem, uploadReducer } from './uploadQueueState'
import type { UploadItem } from './uploadQueueState'

const item = (id: string): UploadItem => newUploadItem({ name: `${id}.pdf`, size: 100 }, id)

describe('uploadReducer', () => {
  it('adds items in the uploading state', () => {
    const state = uploadReducer([], { type: 'add', items: [item('a'), item('b')] })

    expect(state.map((i) => i.status)).toEqual(['uploading', 'uploading'])
  })

  it('tracks progress only for the right item, while uploading', () => {
    let state = uploadReducer([], { type: 'add', items: [item('a'), item('b')] })
    state = uploadReducer(state, { type: 'progress', id: 'a', progress: 0.4 })

    expect(state[0].progress).toBe(0.4)
    expect(state[1].progress).toBe(0)

    state = uploadReducer(state, { type: 'done', id: 'a', documentId: 'doc-1' })
    state = uploadReducer(state, { type: 'progress', id: 'a', progress: 0.1 }) // late event
    expect(state[0]).toMatchObject({ status: 'done', progress: 1, documentId: 'doc-1' })
  })

  it('records errors with their message', () => {
    let state = uploadReducer([], { type: 'add', items: [item('a')] })
    state = uploadReducer(state, { type: 'error', id: 'a', message: 'File too large' })

    expect(state[0]).toMatchObject({ status: 'error', error: 'File too large' })
  })

  it('dismisses one item, and clearFinished keeps only uploads in flight', () => {
    let state = uploadReducer([], { type: 'add', items: [item('a'), item('b'), item('c')] })
    state = uploadReducer(state, { type: 'done', id: 'a', documentId: 'x' })
    state = uploadReducer(state, { type: 'error', id: 'b', message: 'nope' })

    expect(uploadReducer(state, { type: 'dismiss', id: 'b' }).map((i) => i.id)).toEqual(['a', 'c'])
    expect(uploadReducer(state, { type: 'clearFinished' }).map((i) => i.id)).toEqual(['c'])
  })

  it('counts items by status', () => {
    let state = uploadReducer([], { type: 'add', items: [item('a'), item('b'), item('c')] })
    state = uploadReducer(state, { type: 'done', id: 'a', documentId: 'x' })

    expect(countByStatus(state)).toEqual({ uploading: 2, done: 1, error: 0 })
  })
})
