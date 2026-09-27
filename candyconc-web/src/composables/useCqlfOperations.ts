import { computed } from 'vue'
import {
  analyseQuery,
  getLexiconSuggestions,
  getSuggestions,
  type QueryAnalysisResult,
  type SuggestionItem,
} from '@/api/client'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { t } from '@/i18n'

export const CQLF_CAPABILITY_ID = 'query.cqlf'
export const CQLF_ROUTES = {
  analyse: '/api/v1/query/analyse',
  lexiconSuggest: '/api/v1/query/lexicon/suggest',
} as const
export const CQLF_OPERATIONS = {
  analyse: 'query.cqlf.analyse',
  lexiconSuggest: 'query.cqlf.lexicon_suggest',
} as const

function denied(reason: string | null | undefined, fallback: string): Error {
  const error = new Error(reason ?? fallback)
  error.name = 'ProductCapabilityDeniedError'
  return error
}

export function useCqlfOperations() {
  const productCapabilities = useProductCapabilitiesStore()

  const canUseCqlf = computed(() => productCapabilities.isVisible(CQLF_CAPABILITY_ID))
  const analyseAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CQLF_OPERATIONS.analyse, t('search.cqlfOps.diagnostics')),
  )
  const lexiconSuggestAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CQLF_OPERATIONS.lexiconSuggest, t('search.cqlfOps.lexicon')),
  )
  async function analyseCqlQuery(
    term: string,
    signal?: AbortSignal,
    corpus?: string,
  ): Promise<QueryAnalysisResult> {
    await productCapabilities.ensureAccessContext()
    const availability = analyseAvailability.value
    if (!availability.enabled) {
      throw denied(
        availability.disabledReason,
        t('search.cqlfOps.diagnosticsNotEnabled'),
      )
    }
    return analyseQuery(term, signal, corpus)
  }

  async function loadSuggestions(
    term: string,
    signal?: AbortSignal,
    corpus?: string,
  ): Promise<SuggestionItem[]> {
    await productCapabilities.ensureAccessContext()
    const availability = analyseAvailability.value
    if (!availability.enabled) {
      throw denied(
        availability.disabledReason,
        t('search.cqlfOps.diagnosticsNotEnabled'),
      )
    }
    return getSuggestions(term, signal, corpus)
  }

  async function loadLexiconSuggestions(
    attr: string,
    prefix: string,
    limit = 20,
    signal?: AbortSignal,
    corpus?: string,
  ): Promise<string[]> {
    await productCapabilities.ensureAccessContext()
    const availability = lexiconSuggestAvailability.value
    if (!availability.enabled) {
      throw denied(
        availability.disabledReason,
        t('search.cqlfOps.lexiconNotEnabled'),
      )
    }
    return getLexiconSuggestions(attr, prefix, limit, signal, corpus)
  }

  return {
    canUseCqlf,
    analyseAvailability,
    lexiconSuggestAvailability,
    canAnalyseQuery: computed(() => analyseAvailability.value.enabled),
    canSuggestLexicon: computed(() => lexiconSuggestAvailability.value.enabled),
    analyseBlockReason: computed(() => analyseAvailability.value.disabledReason),
    lexiconSuggestBlockReason: computed(() => lexiconSuggestAvailability.value.disabledReason),
    analyseCqlQuery,
    loadSuggestions,
    loadLexiconSuggestions,
  }
}
