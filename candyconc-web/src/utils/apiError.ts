/**
 * apiError - shared helpers for turning backend / network errors into
 * user-facing German messages.
 *
 * Goal: NEVER surface the raw `ky` HTTPError string to users (it leaks the
 * internal URL, query params and HTTP status, e.g.
 *   "Request failed with status code 500 Internal Server Error:
 *    GET http://localhost:5173/api/v1/analysis/dispersion_offsets?term=...").
 * Instead we read the backend's normalized `detail` field from the response
 * body and fall back to a friendly generic German message.
 *
 * This module is intentionally standalone and free of app-store / Vue imports
 * so it can be reused across tabs (Dispersion, Collocations, KWIC, …) and in
 * the SSE / chat clients.
 */

import { HTTPError } from 'ky'
import { t } from '@/i18n'

/**
 * Generic, user-facing fallback when no specific detail is available.
 * GENERIC_API_ERROR_DE keeps the German text for existing callers. Use
 * genericApiError() for the active interface language.
 */
export const GENERIC_API_ERROR_DE = 'Ein Fehler ist aufgetreten. Bitte erneut versuchen.' // i18n-ignore: German constant kept for callers

export function genericApiError(): string {
  return t('errors.api.generic')
}

/**
 * Shape of the normalized error envelope the FastAPI backend returns.
 * `detail` is usually a plain string, but may be an object (e.g. embeddings
 * status) — in that case we look for a nested `.message`.
 */
interface ApiErrorBody {
  detail?: unknown
  message?: unknown
  [key: string]: unknown
}

/**
 * True when the value looks like a `ky` HTTPError: it carries a `response`
 * that is a Fetch `Response`. We duck-type in addition to the `instanceof`
 * check so cloned / cross-realm errors are still handled.
 */
function isHttpErrorLike(err: unknown): err is { response: Response } {
  if (err instanceof HTTPError) return true
  if (!err || typeof err !== 'object') return false
  const response = (err as { response?: unknown }).response
  return (
    !!response &&
    typeof response === 'object' &&
    typeof (response as Response).json === 'function' &&
    typeof (response as Response).status === 'number'
  )
}

/** Pull a usable string out of a parsed error body's `detail` / `message`. */
function detailFromBody(body: ApiErrorBody | null | undefined): string | null {
  if (!body || typeof body !== 'object') return null
  const { detail } = body
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  // Some endpoints nest a message inside an object `detail` (e.g. embeddings).
  if (detail && typeof detail === 'object') {
    const nested = (detail as { message?: unknown }).message
    if (typeof nested === 'string' && nested.trim()) return nested.trim()
  }
  if (typeof body.message === 'string' && body.message.trim()) return body.message.trim()
  return null
}

/**
 * Map an HTTP status (+ optional already-extracted backend detail) to a
 * friendly German message. Specific statuses get a dedicated message; for
 * everything else we prefer the backend detail, then a generic fallback.
 */
export function translateHttpError(status: number, detail?: string | null): string {
  if (status === 429) return t('errors.api.tooManyRequests')
  if (status === 401 || status === 403) return t('errors.api.signIn')
  if (status >= 500) return t('errors.api.server')
  const trimmed = detail?.trim()
  if (trimmed) return trimmed
  return genericApiError()
}

/**
 * Resolve a human-friendly German message from any error a fetch/ky call can
 * throw. Robust to:
 *   - a `ky` HTTPError (reads the backend `detail` from the response body),
 *   - a plain `Error`,
 *   - a bare string,
 *   - anything else.
 *
 * It NEVER returns the raw ky message (which embeds the URL + status). Status
 * 429 / 401 / 403 / 5xx always win over the body detail so the user gets the
 * actionable message; other 4xx surface the backend detail when present.
 *
 * Async because reading a `Response` body is async; callers resolve it into a
 * reactive ref (see DispersionTab / CollocationsTab).
 */
export async function extractApiDetail(err: unknown): Promise<string> {
  if (typeof err === 'string') {
    return err.trim() || genericApiError()
  }

  if (isHttpErrorLike(err)) {
    const { response } = err
    let detail: string | null = null
    try {
      // Clone so the body stays readable for any downstream consumer.
      const body = (await response.clone().json()) as ApiErrorBody
      detail = detailFromBody(body)
    } catch {
      // Body is not JSON / already consumed — fall back to status mapping.
    }
    return translateHttpError(response.status, detail)
  }

  if (err instanceof Error) {
    const message = err.message?.trim()
    // Guard against the raw ky message slipping through (it always contains the
    // HTTP status + an absolute URL). Never expose it to the user.
    if (message && !looksLikeRawKyMessage(message)) return message
    return genericApiError()
  }

  return genericApiError()
}

/**
 * Heuristic for the raw `ky` HTTPError message, e.g.
 *   "Request failed with status code 500 Internal Server Error: GET http://…"
 * We refuse to show these because they leak the internal URL + params.
 */
function looksLikeRawKyMessage(message: string): boolean {
  return /https?:\/\//.test(message) || /status code \d{3}/i.test(message)
}
