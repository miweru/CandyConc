import { ref, watch, type Ref } from 'vue'
import type { QueryAnalysisResult, SuggestionItem } from '@/api/client'
import { useCqlfOperations } from '@/composables/useCqlfOperations'
import { getAutocompleteSeedQuery, sortSuggestionsBySalience } from '@/components/search/cqlAutocomplete'
import { hydrateBuilderState, type CqlBuilderMode, type CqlBuilderNode } from '@/lib/queryBuilder/ast'
import { localizeCqlDiagnostic } from '@/lib/cqlDetection'
import { t } from '@/i18n'

/**
 * Debounced CQL analysis: suggestions, parse errors and builder hydration.
 *
 * Extracted verbatim from QueryBuilderStudio.vue (Phase 2 split). Owns the
 * suggestion list, the analysis error / unsupported-reason state and the
 * debounce timer / abort controller / request id.
 *
 * Writing the hydrated node back into the tree and tagging the history entry
 * stay component concerns and are injected as callbacks.
 */
export function useCqlSuggestions(options: {
  mode: Ref<CqlBuilderMode>
  generatedCql: Ref<string>
  corpus?: Ref<string | undefined>
  enabled?: Ref<boolean>
  canAnalyse?: Ref<boolean>
  analysisBlockReason?: Ref<string | null>
  analyseCqlQuery?: (query: string, signal?: AbortSignal, corpus?: string) => Promise<QueryAnalysisResult>
  queueHistoryLabel: (label: string) => void
  commitHydratedNode: (next: CqlBuilderNode) => void
}) {
  const { mode, generatedCql, queueHistoryLabel, commitHydratedNode } = options
  const cqlfOperations = useCqlfOperations()
  const analyseCqlQuery = options.analyseCqlQuery ?? cqlfOperations.analyseCqlQuery

  const suggestions = ref<SuggestionItem[]>([])
  const isSuggesting = ref(false)
  const analysisErrors = ref<string[]>([])
  const analysisWarnings = ref<string[]>([])
  const diagnosticsStatus = ref<'idle' | 'loading' | 'ok' | 'unavailable'>('idle')
  const diagnosticsError = ref<string | null>(null)
  const unsupportedReason = ref<string | null>(null)

  let suggestTimer: ReturnType<typeof setTimeout> | null = null
  let suggestAbort: AbortController | null = null
  let suggestRequestId = 0

  function clearSuggestTimer() {
    if (suggestTimer) {
      clearTimeout(suggestTimer)
      suggestTimer = null
    }
  }

  function cancelSuggestRequest() {
    if (suggestAbort) {
      suggestAbort.abort()
      suggestAbort = null
    }
  }

  function resetSuggestions() {
    suggestions.value = []
    isSuggesting.value = false
    analysisErrors.value = []
    analysisWarnings.value = []
    diagnosticsStatus.value = 'idle'
    diagnosticsError.value = null
  }

  function setDiagnosticsUnavailable(reason: string) {
    diagnosticsStatus.value = 'unavailable'
    diagnosticsError.value = reason
  }

  function clearDiagnostics() {
    analysisErrors.value = []
    analysisWarnings.value = []
    diagnosticsStatus.value = 'idle'
    diagnosticsError.value = null
    unsupportedReason.value = null
  }

  function errorMessage(error: unknown): string {
    if (error instanceof Error && error.message.trim()) return error.message
    return t('querybuilder.suggestions.diagnosticsUnreachable')
  }

  function isAbortError(error: unknown): boolean {
    return (
      (error instanceof DOMException || error instanceof Error) &&
      error.name === 'AbortError'
    )
  }

  function scheduleSuggest(rawTerm: string) {
    clearSuggestTimer()
    cancelSuggestRequest()

    if (options.enabled?.value === false || mode.value !== 'advanced') {
      resetSuggestions()
      return
    }
    if (options.canAnalyse?.value === false) {
      resetSuggestions()
      unsupportedReason.value = options.analysisBlockReason?.value ?? t('querybuilder.suggestions.diagnosticsNotEnabled')
      setDiagnosticsUnavailable(unsupportedReason.value)
      return
    }

    const effectiveTerm = rawTerm.trim() || generatedCql.value
    const seedOnly = !effectiveTerm.trim()
    const query = getAutocompleteSeedQuery(effectiveTerm)
    if (!query) {
      resetSuggestions()
      return
    }

    suggestRequestId += 1
    const requestId = suggestRequestId
    suggestAbort = new AbortController()

    suggestTimer = setTimeout(async () => {
      if (options.enabled?.value === false) {
        resetSuggestions()
        return
      }
      if (options.canAnalyse?.value === false) {
        resetSuggestions()
        unsupportedReason.value = options.analysisBlockReason?.value ?? t('querybuilder.suggestions.diagnosticsNotEnabled')
        setDiagnosticsUnavailable(unsupportedReason.value)
        return
      }
      isSuggesting.value = true
      diagnosticsStatus.value = 'loading'
      diagnosticsError.value = null
      try {
        const result = await analyseCqlQuery(query, suggestAbort?.signal, options.corpus?.value)
        if (requestId !== suggestRequestId) return
        suggestions.value = sortSuggestionsBySalience(result.suggestions).slice(0, 14)
        // Parser token errors arrive as "expected IDENT, got EOF" in every
        // request language.
        analysisErrors.value = seedOnly ? [] : result.errors.map(localizeCqlDiagnostic)
        analysisWarnings.value = seedOnly ? [] : result.warnings.map(localizeCqlDiagnostic)
        diagnosticsStatus.value = 'ok'
        diagnosticsError.value = null
        if (seedOnly) {
          unsupportedReason.value = null
          return
        }
        const hydrated = hydrateBuilderState(result.builder)
        if (hydrated.node) {
          queueHistoryLabel(seedOnly
            ? t('querybuilder.suggestions.historyStartApplied')
            : t('querybuilder.suggestions.historyFreeApplied'))
          commitHydratedNode(hydrated.node)
          unsupportedReason.value = null
        } else if (!result.errors.length) {
          unsupportedReason.value = hydrated.unsupportedReason ?? t('querybuilder.suggestions.notConvertible')
        }
        if (result.errors.length) {
          unsupportedReason.value = null
        }
      } catch (error) {
        if (requestId !== suggestRequestId) return
        if (isAbortError(error)) return
        suggestions.value = []
        analysisErrors.value = []
        analysisWarnings.value = []
        setDiagnosticsUnavailable(errorMessage(error))
      } finally {
        if (requestId === suggestRequestId) {
          isSuggesting.value = false
        }
      }
    }, 260)
  }

  if (options.enabled) {
    watch(options.enabled, (enabled) => {
      if (enabled) return
      clearSuggestTimer()
      cancelSuggestRequest()
      resetSuggestions()
      unsupportedReason.value = null
    })
  }

  if (options.canAnalyse) {
    watch(options.canAnalyse, (enabled) => {
      if (enabled) return
      clearSuggestTimer()
      cancelSuggestRequest()
      resetSuggestions()
      unsupportedReason.value = options.analysisBlockReason?.value ?? t('querybuilder.suggestions.diagnosticsNotEnabled')
      setDiagnosticsUnavailable(unsupportedReason.value)
    })
  }

  return {
    suggestions,
    isSuggesting,
    analysisErrors,
    analysisWarnings,
    diagnosticsStatus,
    diagnosticsError,
    unsupportedReason,
    clearDiagnostics,
    clearSuggestTimer,
    cancelSuggestRequest,
    resetSuggestions,
    scheduleSuggest,
  }
}
