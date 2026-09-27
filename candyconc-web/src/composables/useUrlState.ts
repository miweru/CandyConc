/**
 * useUrlState - syncs query/subcorpus state to URL for share/restore
 */
import { ref, onMounted, onScopeDispose, watch } from 'vue'
import { actionBus } from '@/actions'
import { asSwitchTabId, useQueryStore, useUiStore, useDocsetStore, useSubcorporaStore, useProductCapabilitiesStore } from '@/stores'
import type { ActiveTab } from '@/stores/ui'
import { isCqlfQuery } from '@/lib/cqlDetection'
import { t } from '@/i18n'

const PARAMS = {
  query: 'q',
  tab: 'tab',
  corpus: 'corpus',
  prompt: 'pm',
  model: 'model',
  register: 'reg',
  source: 'src',
  includeAi: 'ai',
  includeHuman: 'human',
  subcorpus: 'sub',
  run: 'run',
} as const

function encodeList(values: string[]): string {
  return values.map((v) => encodeURIComponent(v)).join('|')
}

function decodeList(raw: string | null): string[] {
  if (!raw) return []
  return raw
    .split('|')
    .map((v) => decodeURIComponent(v))
    .map((v) => v.trim())
    .filter(Boolean)
}

export function useUrlState() {
  const queryStore = useQueryStore()
  const uiStore = useUiStore()
  const docsetStore = useDocsetStore()
  const subcorporaStore = useSubcorporaStore()
  const productCapabilities = useProductCapabilitiesStore()

  const isRestoring = ref(false)
  let updateTimer: ReturnType<typeof setTimeout> | null = null
  let disposed = false

  function buildParams(): URLSearchParams {
    const params = new URLSearchParams()
    params.set(PARAMS.tab, uiStore.activeTab)

    const corpus = queryStore.filters.corpus
    if (corpus) params.set(PARAMS.corpus, corpus)

    if (docsetStore.filters.prompting_method.length) {
      params.set(PARAMS.prompt, encodeList(docsetStore.filters.prompting_method))
    }
    if (docsetStore.filters.model.length) {
      params.set(PARAMS.model, encodeList(docsetStore.filters.model))
    }
    if (docsetStore.filters.register.length) {
      params.set(PARAMS.register, encodeList(docsetStore.filters.register))
    }
    if (docsetStore.filters.source.length) {
      params.set(PARAMS.source, encodeList(docsetStore.filters.source))
    }

    params.set(PARAMS.includeAi, docsetStore.includeAi ? '1' : '0')
    params.set(PARAMS.includeHuman, docsetStore.includeHuman ? '1' : '0')

    const snapshot = subcorporaStore.snapshots.find(
      (s) => s.docsetId === docsetStore.activeDocsetId
    )
    if (snapshot) {
      params.set(PARAMS.subcorpus, snapshot.id)
    }

    return params
  }

  function updateUrl() {
    if (isRestoring.value) return
    const params = buildParams()
    const url = new URL(window.location.href)
    url.search = params.toString()
    window.history.replaceState({}, '', url)
  }

  function scheduleUpdate() {
    if (isRestoring.value || disposed) return
    if (updateTimer) window.clearTimeout(updateTimer)
    updateTimer = window.setTimeout(updateUrl, 200)
  }

  // A pending URL update does not outlive the component that owns this state,
  // also when a restore ends after the unmount.
  onScopeDispose(() => {
    disposed = true
    if (updateTimer) window.clearTimeout(updateTimer)
    updateTimer = null
  })

  async function restoreFromUrl() {
    const params = new URLSearchParams(window.location.search)
    if (params.size === 0) return

    isRestoring.value = true
    try {
      await productCapabilities.ensureAccessContext()
      if (!subcorporaStore.initialized) {
        await subcorporaStore.init()
      }

      const shouldRun = params.get(PARAMS.run) === '1'
      const term = shouldRun ? params.get(PARAMS.query)?.trim() ?? '' : ''
      const tab = params.get(PARAMS.tab) as ActiveTab | null
      const corpus = params.get(PARAMS.corpus)?.trim() ?? ''
      const subcorpusId = params.get(PARAMS.subcorpus)

      const prompt = decodeList(params.get(PARAMS.prompt))
      const model = decodeList(params.get(PARAMS.model))
      const register = decodeList(params.get(PARAMS.register))
      const source = decodeList(params.get(PARAMS.source))
      const includeAi = params.get(PARAMS.includeAi) !== '0'
      const includeHuman = params.get(PARAMS.includeHuman) !== '0'

      let resolvedTerm = term
      let resolvedFilters = { prompting_method: prompt, model, register, source }
      let resolvedIncludeAi = includeAi
      let resolvedIncludeHuman = includeHuman
      let resolvedCorpus = corpus

      if (subcorpusId) {
        const snapshot = subcorporaStore.snapshots.find((s) => s.id === subcorpusId)
        if (snapshot) {
          resolvedFilters = snapshot.filters
          resolvedIncludeAi = snapshot.includeAi
          resolvedIncludeHuman = snapshot.includeHuman
          resolvedCorpus = snapshot.corpus
          if (!resolvedTerm) {
            resolvedTerm = snapshot.origin.query ?? ''
          }
        }
      }

      if (resolvedCorpus) {
        queryStore.setFilters({ corpus: resolvedCorpus })
      }
      if (tab) {
        await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: asSwitchTabId(tab) } }, { source: 'restore' })
      }

      docsetStore.clearFilters()
      docsetStore.setIncludeAi(resolvedIncludeAi)
      docsetStore.setIncludeHuman(resolvedIncludeHuman)
      docsetStore.setFilter('prompting_method', [...resolvedFilters.prompting_method])
      docsetStore.setFilter('model', [...resolvedFilters.model])
      docsetStore.setFilter('register', [...resolvedFilters.register])
      docsetStore.setFilter('source', [...resolvedFilters.source])

      if (resolvedTerm && shouldRun) {
        if (isCqlfQuery(resolvedTerm)) {
          if (!productCapabilities.isVisible('query.cqlf')) {
            uiStore.showToast(t('layout.urlState.cqlBlocked'), 'warning')
            return
          }
        }
        if (!productCapabilities.hasContract || !productCapabilities.isVisible('query.kwic')) {
          uiStore.showToast(t('layout.urlState.kwicBlocked'), 'warning')
          return
        }
        queryStore.setTerm(resolvedTerm)
        if (docsetStore.filtersActive || !resolvedIncludeAi || !resolvedIncludeHuman) {
          await docsetStore.buildDocset(true, resolvedTerm)
        }
        await actionBus.dispatch(
          {
            type: 'query/execute',
            payload: {
              term: resolvedTerm,
              contextSize: queryStore.contextSize,
              filters: queryStore.filters,
            },
          },
          { source: 'restore', requestId: 'url-restore:query' }
        )
      }
    } finally {
      isRestoring.value = false
      scheduleUpdate()
    }
  }

  onMounted(() => {
    void restoreFromUrl()
  })

  watch(
    () => [
      queryStore.term,
      uiStore.activeTab,
      queryStore.filters.corpus,
      docsetStore.filters,
      docsetStore.includeAi,
      docsetStore.includeHuman,
      docsetStore.activeDocsetId,
    ],
    scheduleUpdate,
    { deep: true }
  )

  return {
    restoreFromUrl,
  }
}
