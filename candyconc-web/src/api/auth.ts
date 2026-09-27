import { acceptLanguageHeader } from '@/i18n/locale'

const AUTH_TOKEN_STORAGE_KEY = 'auth_token'

/**
 * C3 hardening: the bearer token is held in module memory first.
 *
 * Tradeoff (re-audit C3, 2026-06): the app now has a small release login
 * surface, but still needs reload-persistence and compatibility with existing
 * deployments that seed a token externally. We keep a read fallback chain:
 *
 *   1. in-memory module state  — set via setAuthToken(), never persisted,
 *      not readable by storage-scanning XSS payloads after the fact
 *   2. sessionStorage          — per-tab, cleared when the tab closes;
 *      this is where setAuthToken() mirrors the token so the session
 *      survives a reload (the app relies on reload-persistence)
 *   3. localStorage (legacy)   — compatibility with existing deployments that
 *      seed `auth_token` there; once read, it is migrated to sessionStorage and
 *      removed from persistent storage.
 *
 * sessionStorage and localStorage remain XSS-readable; the real fix is an
 * HttpOnly session cookie, which needs backend support. Until then this
 * narrows the exposure: runtime-acquired tokens stay out of persistent
 * storage, and legacy persistent copies are scrubbed on first read.
 */
let inMemoryAuthToken: string | null = null
let devTokenPromise: Promise<void> | null = null
let authBootstrapPromise: Promise<void> | null = null
const AUTH_SESSION_PROBE_TIMEOUT_MS = 1000

function normalizeToken(token: string | null | undefined): string | null {
  const normalized = token?.trim()
  return normalized ? normalized : null
}

/** Store the token in memory and mirror it to sessionStorage for reload-persistence. */
export function setAuthToken(token: string | null): void {
  inMemoryAuthToken = normalizeToken(token)
  try {
    if (inMemoryAuthToken) {
      globalThis.sessionStorage?.setItem(AUTH_TOKEN_STORAGE_KEY, inMemoryAuthToken)
    } else {
      globalThis.sessionStorage?.removeItem(AUTH_TOKEN_STORAGE_KEY)
    }
  } catch {
    // Storage unavailable (private mode, quota): in-memory token still works for this page lifetime.
  }
}

/** Drop the token from memory, sessionStorage and legacy localStorage copies. */
export function clearAuthToken(): void {
  setAuthToken(null)
  try {
    globalThis.localStorage?.removeItem(AUTH_TOKEN_STORAGE_KEY)
  } catch {
    // Storage unavailable.
  }
}

export function getAuthToken(): string | null {
  if (inMemoryAuthToken) {
    return inMemoryAuthToken
  }
  try {
    const sessionToken = normalizeToken(globalThis.sessionStorage?.getItem(AUTH_TOKEN_STORAGE_KEY))
    if (sessionToken) {
      inMemoryAuthToken = sessionToken
      return sessionToken
    }
  } catch {
    // fall through to legacy storage
  }
  try {
    const legacyToken = normalizeToken(globalThis.localStorage?.getItem(AUTH_TOKEN_STORAGE_KEY))
    if (!legacyToken) return null
    inMemoryAuthToken = legacyToken
    try {
      globalThis.sessionStorage?.setItem(AUTH_TOKEN_STORAGE_KEY, legacyToken)
      globalThis.localStorage?.removeItem(AUTH_TOKEN_STORAGE_KEY)
    } catch {
      // Keep in-memory token for this page lifetime even if migration cleanup fails.
    }
    return legacyToken
  } catch {
    return null
  }
}

/**
 * Common request headers for fetch() calls outside the ky client: the bearer
 * token when present and `Accept-Language` for the active interface language.
 */
export function withAuthHeaders(headers?: HeadersInit): Headers {
  const nextHeaders = new Headers(headers)
  const token = getAuthToken()

  if (!nextHeaders.has('Accept-Language')) {
    nextHeaders.set('Accept-Language', acceptLanguageHeader())
  }

  if (token) {
    nextHeaders.set('Authorization', `Bearer ${token}`)
  }

  return nextHeaders
}

/**
 * Local-first convenience: when the app has no token, fetch a guest dev-token
 * from the backend. The backend only issues one when RBAC is disabled AND it
 * is not in release mode — so this is never a production authorization path.
 * Without it, a local/dev session 401s on token-gated analysis endpoints.
 * Never throws: on any failure the app simply stays unauthenticated and
 * degrades gracefully.
 */
export async function ensureDevToken(): Promise<void> {
  if (getAuthToken()) return
  if (devTokenPromise) return devTokenPromise
  devTokenPromise = (async () => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 3000)
    try {
      const res = await fetch('/api/v1/auth/dev-token', {
        // Returns only a token, no user-visible text, so no Accept-Language.
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      })
      if (!res.ok) return
      const data = await res.json().catch(() => null)
      const token = data && typeof (data as { token?: unknown }).token === 'string'
        ? (data as { token: string }).token
        : null
      if (token && !getAuthToken()) setAuthToken(token)
    } catch {
      // backend down / dev-token not available (RBAC or release mode): stay unauthenticated.
    } finally {
      clearTimeout(timer)
    }
  })().finally(() => {
    devTokenPromise = null
  })
  return devTokenPromise
}

function isInvalidLocalDevTokenSession(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const session = value as Record<string, unknown>
  return (
    session.token_present === true &&
    session.authenticated === false &&
    session.rbac_enabled === false &&
    session.dev_token_available === true &&
    session.release_mode === false
  )
}

async function refreshInvalidLocalDevToken(): Promise<void> {
  const token = getAuthToken()
  if (!token) {
    await ensureDevToken()
    return
  }

  // Local dev tokens live only in the backend process. Validate a restored
  // browser token before mounting so a restarted local backend cannot leave
  // search working while provenance and analysis routes silently 401.
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), AUTH_SESSION_PROBE_TIMEOUT_MS)
  try {
    const response = await fetch('/api/v1/auth/session', {
      headers: {
        Accept: 'application/json',
        'Accept-Language': acceptLanguageHeader(),
        Authorization: `Bearer ${token}`,
      },
      signal: controller.signal,
    })
    if (!response.ok) return
    const session = await response.json().catch(() => null)
    if (!isInvalidLocalDevTokenSession(session)) return
    clearAuthToken()
    await ensureDevToken()
  } catch {
    // Keep a possibly valid existing session when the local backend is down.
  } finally {
    clearTimeout(timer)
  }
}

export function startAuthBootstrap(): Promise<void> {
  if (!authBootstrapPromise) {
    authBootstrapPromise = refreshInvalidLocalDevToken()
  }
  return authBootstrapPromise
}

export async function waitForAuthBootstrap(): Promise<void> {
  if (authBootstrapPromise) {
    await authBootstrapPromise
  }
}

export async function withAuthHeadersReady(headers?: HeadersInit): Promise<Headers> {
  await waitForAuthBootstrap()
  return withAuthHeaders(headers)
}
