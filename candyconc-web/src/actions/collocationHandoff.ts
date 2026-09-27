import { shallowRef } from 'vue'
import type { RunCollocationsAction } from './types'

/**
 * A short-lived bridge for an analysis action that opens the collocations tab.
 * The global ActionBus handler must remain usable while the tab is unmounted,
 * but its completed result must be rendered by that tab rather than replaced by
 * a second, active-scope request during navigation.
 */
export interface CollocationActionResult {
  rows: Array<Record<string, unknown>>
  totalRows: number | null
  rowLimit?: number | null
  totalCandidates?: number | null
  truncated?: boolean
  method?: unknown
}

export interface CollocationActionHandoff {
  id: number
  status: 'pending' | 'completed' | 'failed'
  request: Required<Pick<RunCollocationsAction['payload'], 'term' | 'windowSize' | 'withinSentence' | 'measure' | 'minFreq' | 'corpus'>>
    & Pick<RunCollocationsAction['payload'], 'docsetId' | 'limit'>
  result?: CollocationActionResult
  error?: string
}

export const collocationActionHandoff = shallowRef<CollocationActionHandoff | null>(null)

let nextHandoffId = 1

export function beginCollocationActionHandoff(
  request: CollocationActionHandoff['request'],
): number {
  const id = nextHandoffId++
  collocationActionHandoff.value = { id, status: 'pending', request }
  return id
}

export function completeCollocationActionHandoff(
  id: number,
  result: CollocationActionResult,
): boolean {
  const current = collocationActionHandoff.value
  if (!current || current.id !== id) return false
  collocationActionHandoff.value = { ...current, status: 'completed', result }
  return true
}

export function failCollocationActionHandoff(id: number, error: string): boolean {
  const current = collocationActionHandoff.value
  if (!current || current.id !== id) return false
  collocationActionHandoff.value = { ...current, status: 'failed', error }
  return true
}

export function clearCollocationActionHandoff(id?: number): void {
  const current = collocationActionHandoff.value
  if (!current || (id !== undefined && current.id !== id)) return
  collocationActionHandoff.value = null
}
