/**
 * Fast comparison utilities to replace JSON.stringify comparisons
 */

/**
 * Shallow equality check for objects
 */
export function shallowEqual<T extends Record<string, unknown>>(a: T | null | undefined, b: T | null | undefined): boolean {
  if (a === b) return true
  if (a == null || b == null) return false

  const keysA = Object.keys(a)
  const keysB = Object.keys(b)

  if (keysA.length !== keysB.length) return false

  for (const key of keysA) {
    if (a[key] !== b[key]) return false
  }

  return true
}

/**
 * Fast deep equality check for nested objects
 * Handles arrays, objects, primitives, null, undefined
 */
export function deepEqual(a: unknown, b: unknown): boolean {
  // Same reference or both primitives with same value
  if (a === b) return true

  // Handle null/undefined
  if (a == null || b == null) return a === b

  // Different types
  if (typeof a !== typeof b) return false

  // Primitives (already checked === above)
  if (typeof a !== 'object') return false

  // Arrays
  if (Array.isArray(a)) {
    if (!Array.isArray(b)) return false
    if (a.length !== b.length) return false
    for (let i = 0; i < a.length; i++) {
      if (!deepEqual(a[i], b[i])) return false
    }
    return true
  }

  // Objects
  if (Array.isArray(b)) return false

  const objA = a as Record<string, unknown>
  const objB = b as Record<string, unknown>
  const keysA = Object.keys(objA)
  const keysB = Object.keys(objB)

  if (keysA.length !== keysB.length) return false

  for (const key of keysA) {
    if (!Object.prototype.hasOwnProperty.call(objB, key)) return false
    if (!deepEqual(objA[key], objB[key])) return false
  }

  return true
}

/**
 * Compute a simple hash string for an object (faster than JSON.stringify for comparison)
 */
export function objectHash(obj: unknown): string {
  if (obj === null) return 'null'
  if (obj === undefined) return 'undefined'

  const type = typeof obj
  if (type !== 'object') return `${type}:${String(obj)}`

  if (Array.isArray(obj)) {
    return `[${obj.map(objectHash).join(',')}]`
  }

  const record = obj as Record<string, unknown>
  const keys = Object.keys(record).sort()
  const parts = keys.map(k => `${k}:${objectHash(record[k])}`)
  return `{${parts.join(',')}}`
}

/**
 * Compute difference between two objects (for incremental updates)
 */
export function objectDiff<T extends Record<string, unknown>>(
  prev: T | null | undefined,
  curr: T
): Partial<T> | null {
  if (!prev) return curr

  const diff: Partial<T> = {}
  let hasDiff = false

  for (const key of Object.keys(curr) as Array<keyof T>) {
    if (!deepEqual(prev[key], curr[key])) {
      diff[key] = curr[key]
      hasDiff = true
    }
  }

  return hasDiff ? diff : null
}
