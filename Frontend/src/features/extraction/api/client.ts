import createClient from 'openapi-fetch'

import { API_BASE_URL } from '@/features/extraction/config'
import { ApiError, NETWORK_ERROR, parseErrorBody } from './errors'
import type { paths } from './generated/schema'
import type { DocumentOut } from './types'

// `fetch` is looked up at call time (not captured when the client is created),
// so tests can replace it and nothing depends on module import order.
export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  fetch: (request) => globalThis.fetch(request),
})

interface Result<T> {
  data?: T
  error?: unknown
  response: Response
}

/** Await an openapi-fetch call and return its data, or throw an ApiError. */
export async function call<T>(request: Promise<Result<T>>): Promise<T> {
  let result: Result<T>
  try {
    result = await request
  } catch {
    throw NETWORK_ERROR
  }
  if (!result.response.ok) throw parseErrorBody(result.response.status, result.error)
  return result.data as T
}

/** Like call(), for endpoints that return no body (e.g. 204). */
export async function callVoid(request: Promise<Result<unknown>>): Promise<void> {
  await call(request)
}

export const pageImageUrl = (documentId: string, pageNumber: number): string =>
  `${API_BASE_URL}/api/v1/documents/${documentId}/pages/${pageNumber}/image`

interface UploadOptions {
  folderId?: string | null
  onProgress?: (fraction: number) => void
}

/** Upload one file. Uses XMLHttpRequest because fetch cannot report upload
 * progress. Resolves when the server has accepted the file (202); the
 * extraction itself continues in the background. */
export function uploadDocument(file: File, options: UploadOptions = {}): Promise<DocumentOut> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/api/v1/documents`)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        // non-JSON body: fall through to the generic error
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as DocumentOut)
      else reject(parseErrorBody(xhr.status, body))
    }
    xhr.onerror = () => reject(NETWORK_ERROR)

    const form = new FormData()
    form.append('file', file)
    if (options.folderId) form.append('folder_id', options.folderId)
    xhr.send(form)
  })
}

export { ApiError }
