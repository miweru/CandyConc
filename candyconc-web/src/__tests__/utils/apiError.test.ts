/**
 * Tests for the shared API-error helpers (utils/apiError) and the toast-store
 * dedupe / auto-expiry behaviour (findings 16 + 19).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { HTTPError } from 'ky'
import { setActivePinia, createPinia } from 'pinia'

import {
  extractApiDetail,
  translateHttpError,
  GENERIC_API_ERROR_DE,
} from '@/utils/apiError'
import { useUiStore } from '@/stores/ui'

/** Build a real ky HTTPError around a Response with the given body + status. */
function makeHttpError(status: number, body: unknown, url = 'http://localhost:5173/api/v1/analysis/dispersion_offsets?term=cql%3A%5B%5D%5D'): HTTPError {
  const responseInit: ResponseInit = {
    status,
    statusText: status === 500 ? 'Internal Server Error' : 'Error',
    headers: { 'content-type': 'application/json' },
  }
  const payload = typeof body === 'string' ? body : JSON.stringify(body)
  const response = new Response(payload, responseInit)
  // jsdom Response has no `url`; define it so the helper sees a realistic object.
  Object.defineProperty(response, 'url', { value: url, configurable: true })
  const request = new Request(url)
  // ky's HTTPError signature is (response, request, options); options is unused here.
  return new HTTPError(response, request, {} as never)
}

describe('translateHttpError', () => {
  it('maps 429 to a friendly rate-limit message', () => {
    expect(translateHttpError(429)).toBe('Zu viele Anfragen. Bitte einen Moment warten')
  })

  it('maps 401/403 to a sign-in message', () => {
    expect(translateHttpError(401)).toBe('Bitte anmelden / Sitzung abgelaufen')
    expect(translateHttpError(403)).toBe('Bitte anmelden / Sitzung abgelaufen')
  })

  it('maps any 5xx to a generic server-error message', () => {
    expect(translateHttpError(500)).toBe('Serverfehler. Bitte erneut versuchen')
    expect(translateHttpError(503)).toBe('Serverfehler. Bitte erneut versuchen')
  })

  it('returns the backend detail for other statuses when present', () => {
    expect(translateHttpError(400, 'CQL Parse Fehler')).toBe('CQL Parse Fehler')
  })

  it('falls back to the generic message for other statuses without a detail', () => {
    expect(translateHttpError(404)).toBe(GENERIC_API_ERROR_DE)
  })
})

describe('extractApiDetail', () => {
  it('reads the backend `detail` for a 4xx ky HTTPError', async () => {
    const err = makeHttpError(404, { detail: 'Nicht gefunden' })
    await expect(extractApiDetail(err)).resolves.toBe('Nicht gefunden')
  })

  it('prefers the rate-limit message over the body for a 429', async () => {
    const err = makeHttpError(429, { detail: 'Rate limit exceeded' })
    await expect(extractApiDetail(err)).resolves.toBe('Zu viele Anfragen. Bitte einen Moment warten')
  })

  it('prefers the sign-in message over the body for a 401', async () => {
    const err = makeHttpError(401, { detail: 'User token required.' })
    await expect(extractApiDetail(err)).resolves.toBe('Bitte anmelden / Sitzung abgelaufen')
  })

  it('returns the generic server message for a 500 and NEVER leaks the URL/status', async () => {
    const err = makeHttpError(500, { detail: 'Interner Serverfehler' })
    const result = await extractApiDetail(err)
    expect(result).toBe('Serverfehler. Bitte erneut versuchen')
    expect(result).not.toContain('http')
    expect(result).not.toContain('500')
  })

  it('falls back to status mapping when the body is not JSON', async () => {
    const err = makeHttpError(500, '<html>oops</html>')
    await expect(extractApiDetail(err)).resolves.toBe('Serverfehler. Bitte erneut versuchen')
  })

  it('handles a plain Error message', async () => {
    await expect(extractApiDetail(new Error('Netzwerkfehler'))).resolves.toBe('Netzwerkfehler')
  })

  it('refuses a raw ky-style Error message (leaks URL + status)', async () => {
    const raw = new Error(
      'Request failed with status code 500 Internal Server Error: GET http://localhost:5173/api/v1/analysis/dispersion_offsets?term=cql%3A%5B%5D%5D'
    )
    const result = await extractApiDetail(raw)
    expect(result).toBe(GENERIC_API_ERROR_DE)
    expect(result).not.toContain('http')
    expect(result).not.toContain('500')
  })

  it('handles a bare string', async () => {
    await expect(extractApiDetail('Etwas ging schief')).resolves.toBe('Etwas ging schief')
  })

  it('falls back to the generic message for unknown values', async () => {
    await expect(extractApiDetail(undefined)).resolves.toBe(GENERIC_API_ERROR_DE)
    await expect(extractApiDetail(null)).resolves.toBe(GENERIC_API_ERROR_DE)
    await expect(extractApiDetail({})).resolves.toBe(GENERIC_API_ERROR_DE)
  })

  it('handles a duck-typed HTTPError-like object (cross-realm)', async () => {
    const response = new Response(JSON.stringify({ detail: 'Doppelt' }), { status: 404 })
    const result = await extractApiDetail({ response })
    expect(result).toBe('Doppelt')
  })
})

describe('toast dedupe + auto-expiry (finding 19)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('dedupes identical consecutive toasts within the window', () => {
    const store = useUiStore()
    const id1 = store.showToast('CQL Parse Fehler', 'error')
    const id2 = store.showToast('CQL Parse Fehler', 'error')
    expect(store.toasts).toHaveLength(1)
    expect(id1).toBe(id2)
  })

  it('does not dedupe toasts that differ in message or type', () => {
    const store = useUiStore()
    store.showToast('A', 'error')
    store.showToast('B', 'error')
    store.showToast('A', 'info')
    expect(store.toasts).toHaveLength(3)
  })

  it('raises a fresh (stacked) error toast once the dedupe window has passed', () => {
    const store = useUiStore()
    // Errors persist (duration 0), so after the dedupe window a repeat stacks.
    store.showToast('Wiederholung', 'error', 0)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(5000) // beyond the 4s dedupe window
    store.showToast('Wiederholung', 'error', 0)
    expect(store.toasts).toHaveLength(2)
  })

  it('auto-expires a non-error toast even when created with duration 0', () => {
    const store = useUiStore()
    store.showToast('Info ohne Dauer', 'info', 0)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(5000)
    expect(store.toasts).toHaveLength(0)
  })

  it('keeps an error toast that was created with duration 0', () => {
    const store = useUiStore()
    store.showToast('Persistenter Fehler', 'error', 0)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(60000)
    expect(store.toasts).toHaveLength(1)
  })

  it('still auto-expires toasts with an explicit positive duration', () => {
    const store = useUiStore()
    store.showToast('Kurz', 'success', 2000)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(2000)
    expect(store.toasts).toHaveLength(0)
  })
})
