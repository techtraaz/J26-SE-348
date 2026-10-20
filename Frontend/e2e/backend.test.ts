import { describe, expect, it } from 'vitest'

import { api, call, pageImageUrl, uploadDocument } from '../src/features/extraction/api/client'
import { ApiError } from '../src/features/extraction/api/errors'

// 1x1 PNG
const PNG = Uint8Array.from(
  atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='),
  (c) => c.charCodeAt(0),
)
const png = (name: string) => new File([PNG], name, { type: 'image/png' })
const corruptPng = (name: string) => new File([PNG.slice(0, 30)], name, { type: 'image/png' })

async function waitForStatus(id: string, wanted: string, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const doc = await call(api.GET('/api/v1/documents/{document_id}', { params: { path: { document_id: id } } }))
    if (doc.status === wanted) return doc
    if (Date.now() > deadline) throw new Error(`Timed out waiting for "${wanted}", last status "${doc.status}"`)
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
}

describe('frontend client against the real backend', () => {
  it('is reachable', async () => {
    const health = await call(api.GET('/api/v1/health'))
    expect(health.status).toBe('ok')
  })

  it('creates a folder, uploads into it, and follows extraction to needs_review', async () => {
    const folder = await call(api.POST('/api/v1/folders', { body: { name: `E2E ${Date.now()}` } }))

    const progress: number[] = []
    const uploaded = await uploadDocument(png('e2e.png'), {
      folderId: folder.id,
      onProgress: (f) => progress.push(f),
    })
    expect(uploaded.folder_id).toBe(folder.id)
    expect(['uploaded', 'processing']).toContain(uploaded.status)

    const done = await waitForStatus(uploaded.id, 'needs_review')
    expect(done.page_count).toBe(1)
    expect(done.latest_run?.pages_done).toBe(done.latest_run?.pages_total)

    const extraction = await call(
      api.GET('/api/v1/documents/{document_id}/extraction', { params: { path: { document_id: uploaded.id } } }),
    )
    expect(extraction.regions.length).toBeGreaterThan(0)
    expect(extraction.regions[0].provenance).toBeTruthy()

    const image = await fetch(pageImageUrl(uploaded.id, 1))
    expect(image.headers.get('content-type')).toBe('image/png')

    const listed = await call(
      api.GET('/api/v1/documents', { params: { query: { folder_id: folder.id } } }),
    )
    expect(listed.items.map((d) => d.id)).toEqual([uploaded.id])
    const folders = await call(api.GET('/api/v1/folders', { params: { query: {} } }))
    expect(folders.items.find((f) => f.id === folder.id)?.document_count).toBe(1)
  })

  it('shows a failure with a readable reason and supports retry', async () => {
    const uploaded = await uploadDocument(corruptPng('broken.png'))
    const failed = await waitForStatus(uploaded.id, 'failed')
    expect(failed.error_code).toBe('corrupt')
    expect(failed.error_message).toBeTruthy()

    const retried = await call(
      api.POST('/api/v1/documents/{document_id}/retry', { params: { path: { document_id: uploaded.id } } }),
    )
    expect(retried.status).toBe('uploaded')
    await waitForStatus(uploaded.id, 'failed') // still corrupt, so it fails again
  })

  it('rejects an unsupported file immediately with a structured error', async () => {
    const error = await uploadDocument(new File(['plain text'], 'notes.txt')).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 415, code: 'unsupported_type' })
  })

  it('maps a missing resource to a typed error', async () => {
    const error = await call(
      api.GET('/api/v1/folders/{folder_id}', { params: { path: { folder_id: '00000000-0000-0000-0000-000000000000' } } }),
    ).catch((e: unknown) => e)

    expect(error).toMatchObject({ status: 404, code: 'folder_not_found' })
  })
})
