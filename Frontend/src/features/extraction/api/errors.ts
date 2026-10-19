/** An error returned by (or while reaching) the API. `code` is stable and
 * machine-readable; `message` is safe to show to a user. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export const NETWORK_ERROR = new ApiError(
  0,
  'network_error',
  'Cannot reach the server. Check that the API is running.',
)

/** Turn a failed response body into an ApiError.
 * Handles the API's own {"error": {code, message}} shape, FastAPI's built-in
 * validation errors ({"detail": [...]}), and anything else. */
export function parseErrorBody(status: number, body: unknown): ApiError {
  if (typeof body === 'object' && body !== null) {
    const record = body as Record<string, unknown>
    const error = record.error
    if (typeof error === 'object' && error !== null) {
      const { code, message } = error as Record<string, unknown>
      if (typeof code === 'string' && typeof message === 'string') {
        return new ApiError(status, code, message)
      }
    }
    if ('detail' in record) {
      return new ApiError(status, 'validation_error', 'The request was not valid.')
    }
  }
  return new ApiError(status, `http_${status}`, `Something went wrong (HTTP ${status}).`)
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}
