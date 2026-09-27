/**
 * Stable Hashing Utilities
 *
 * Provides deterministic hashing for UI state, payloads, and subcorpus filters.
 * Essential for reproducibility: same input → same hash across sessions.
 */

/**
 * Deterministic JSON stringification.
 * Sorts object keys to ensure consistent ordering.
 */
export function stableStringify(value: unknown): string {
  if (value === null || value === undefined) {
    return 'null'
  }

  if (typeof value === 'boolean' || typeof value === 'number') {
    return String(value)
  }

  if (typeof value === 'string') {
    return JSON.stringify(value)
  }

  if (Array.isArray(value)) {
    return '[' + value.map(stableStringify).join(',') + ']'
  }

  if (typeof value === 'object') {
    const keys = Object.keys(value).sort()
    const pairs = keys
      .filter(k => (value as Record<string, unknown>)[k] !== undefined)
      .map(k => `${JSON.stringify(k)}:${stableStringify((value as Record<string, unknown>)[k])}`)
    return '{' + pairs.join(',') + '}'
  }

  // Fallback for functions, symbols, etc.
  return 'null'
}

/**
 * SHA-256 hash of a value using Web Crypto API.
 * Returns hex string.
 */
export async function sha256(value: unknown): Promise<string> {
  const text = typeof value === 'string' ? value : stableStringify(value)
  const encoder = new TextEncoder()
  const data = encoder.encode(text)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Synchronous hash using simple djb2 algorithm.
 * Fast, deterministic, but not cryptographic.
 * Use for quick comparisons where security isn't needed.
 */
export function quickHash(value: unknown): string {
  const text = typeof value === 'string' ? value : stableStringify(value)
  let hash = 5381
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) + hash) ^ text.charCodeAt(i)
  }
  // Convert to unsigned 32-bit and then to hex
  return (hash >>> 0).toString(16).padStart(8, '0')
}

/**
 * Generate a short hash prefix for display purposes.
 * Uses first 8 characters of SHA-256.
 */
export async function shortHash(value: unknown): Promise<string> {
  const full = await sha256(value)
  return full.slice(0, 8)
}

/**
 * Synchronous short hash for immediate display.
 */
export function quickShortHash(value: unknown): string {
  return quickHash(value)
}

/**
 * Hash specifically for subcorpus filters.
 * Normalizes filter structure for consistent hashing.
 */
export async function subcorpusHash(
  corpusId: string,
  filters: Array<{ field: string; op: string; value: unknown }>
): Promise<string> {
  // Sort filters by field name for determinism
  const normalized = [...filters].sort((a, b) => a.field.localeCompare(b.field))
  return sha256({ corpusId, filters: normalized })
}

/**
 * Hash for query parameters.
 * Includes all parameters that affect results.
 */
export async function queryHash(params: {
  mode: 'term' | 'cqlf'
  term?: string
  cqlf?: string
  context?: { left: number; right: number }
  options?: {
    caseSensitive?: boolean
    diacriticsSensitive?: boolean
    lemmatize?: boolean
    regex?: boolean
  }
}): Promise<string> {
  const normalized = {
    mode: params.mode,
    query: params.mode === 'cqlf' ? params.cqlf : params.term,
    context: params.context ?? { left: 5, right: 5 },
    options: {
      caseSensitive: params.options?.caseSensitive ?? false,
      diacriticsSensitive: params.options?.diacriticsSensitive ?? false,
      lemmatize: params.options?.lemmatize ?? false,
      regex: params.options?.regex ?? false,
    },
  }
  return sha256(normalized)
}

/**
 * Hash for action payloads.
 * Used in trace events and run records.
 */
export function payloadHash(payload: Record<string, unknown>): string {
  return quickHash(payload)
}

/**
 * Generate a unique ID with timestamp prefix.
 * Format: timestamp_random (sortable by time)
 */
export function generateId(prefix = ''): string {
  const ts = Date.now().toString(36)
  const rand = Math.random().toString(36).slice(2, 8)
  return prefix ? `${prefix}_${ts}_${rand}` : `${ts}_${rand}`
}

/**
 * Generate a run ID.
 */
export function generateRunId(): string {
  return generateId('run')
}

/**
 * Generate a trace event ID.
 */
export function generateTraceId(): string {
  return generateId('trace')
}

/**
 * Generate an action request ID.
 */
export function generateRequestId(): string {
  return generateId('req')
}
