import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const analyseQuery = vi.fn()

vi.mock('@/api/client', () => ({
  analyseQuery: (...args: unknown[]) => analyseQuery(...args),
}))

import { useCqlSuggestions } from '@/composables/queryBuilder/useCqlSuggestions'

describe('useCqlSuggestions capability gate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.clearAllMocks()
    analyseQuery.mockResolvedValue({
      suggestions: [],
      errors: [],
      warnings: [],
      builder: null,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not call query analysis while CQLF is disabled', async () => {
    const enabled = ref(false)
    const mode = ref<'simple' | 'advanced'>('advanced')
    const generatedCql = ref('cql:[word="Hase"]')

    const suggestions = useCqlSuggestions({
      mode,
      generatedCql,
      enabled,
      queueHistoryLabel: vi.fn(),
      commitHydratedNode: vi.fn(),
    })

    suggestions.scheduleSuggest('cql:[word="Hase"]')
    await vi.advanceTimersByTimeAsync(300)

    expect(analyseQuery).not.toHaveBeenCalled()
    expect(suggestions.isSuggesting.value).toBe(false)
  })

  it('cancels queued analysis when CQLF becomes disabled', async () => {
    const enabled = ref(true)
    const mode = ref<'simple' | 'advanced'>('advanced')
    const generatedCql = ref('cql:[word="Hase"]')

    const suggestions = useCqlSuggestions({
      mode,
      generatedCql,
      enabled,
      queueHistoryLabel: vi.fn(),
      commitHydratedNode: vi.fn(),
    })

    suggestions.scheduleSuggest('cql:[word="Hase"]')
    enabled.value = false
    await vi.advanceTimersByTimeAsync(300)

    expect(analyseQuery).not.toHaveBeenCalled()
    expect(suggestions.isSuggesting.value).toBe(false)
  })

  it('does not call query analysis while the concrete analysis route is disabled', async () => {
    const enabled = ref(true)
    const canAnalyse = ref(false)
    const mode = ref<'simple' | 'advanced'>('advanced')
    const generatedCql = ref('cql:[word="Hase"]')

    const suggestions = useCqlSuggestions({
      mode,
      generatedCql,
      enabled,
      canAnalyse,
      analysisBlockReason: ref('CQLF-Diagnostik benötigt Rolle User.'),
      queueHistoryLabel: vi.fn(),
      commitHydratedNode: vi.fn(),
    })

    suggestions.scheduleSuggest('cql:[word="Hase"]')
    await vi.advanceTimersByTimeAsync(300)

    expect(analyseQuery).not.toHaveBeenCalled()
    expect(suggestions.isSuggesting.value).toBe(false)
    expect(suggestions.unsupportedReason.value).toContain('CQLF-Diagnostik')
    expect(suggestions.diagnosticsStatus.value).toBe('unavailable')
    expect(suggestions.diagnosticsError.value).toContain('CQLF-Diagnostik')
  })

  it('keeps backend analysis failures visible as unavailable diagnostics', async () => {
    const enabled = ref(true)
    const mode = ref<'simple' | 'advanced'>('advanced')
    const generatedCql = ref('cql:[word="Hase"]')
    const failingAnalyse = vi.fn(async () => {
      throw new Error('Backend nicht erreichbar')
    })

    const suggestions = useCqlSuggestions({
      mode,
      generatedCql,
      enabled,
      analyseCqlQuery: failingAnalyse,
      queueHistoryLabel: vi.fn(),
      commitHydratedNode: vi.fn(),
    })

    suggestions.scheduleSuggest('cql:[word="Hase"]')
    await vi.advanceTimersByTimeAsync(300)

    expect(failingAnalyse).toHaveBeenCalledOnce()
    expect(suggestions.suggestions.value).toEqual([])
    expect(suggestions.analysisErrors.value).toEqual([])
    expect(suggestions.analysisWarnings.value).toEqual([])
    expect(suggestions.diagnosticsStatus.value).toBe('unavailable')
    expect(suggestions.diagnosticsError.value).toBe('Backend nicht erreichbar')
  })
})
