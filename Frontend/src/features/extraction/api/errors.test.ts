import { describe, expect, it } from 'vitest'

import { ApiError, errorMessage, parseErrorBody } from './errors'

describe('parseErrorBody', () => {
  it("reads the API's own error shape", () => {
    const error = parseErrorBody(415, { error: { code: 'unsupported_type', message: 'Unsupported file type.' } })

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(415)
    expect(error.code).toBe('unsupported_type')
    expect(error.message).toBe('Unsupported file type.')
  })

  it('maps FastAPI validation errors to a friendly message', () => {
    const error = parseErrorBody(422, { detail: [{ loc: ['body', 'name'], msg: 'bad' }] })

    expect(error.code).toBe('validation_error')
    expect(error.message).toBe('The request was not valid.')
  })

  it('falls back for anything else', () => {
    expect(parseErrorBody(500, null).code).toBe('http_500')
    expect(parseErrorBody(502, 'Bad Gateway').message).toBe('Something went wrong (HTTP 502).')
    expect(parseErrorBody(400, { error: { code: 1 } }).code).toBe('http_400')
  })
})

describe('errorMessage', () => {
  it('returns the message of an Error, or a default', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage('nope')).toBe('Something went wrong.')
  })
})
