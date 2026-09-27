<script setup lang="ts">
/**
 * CandyConc - Main Application
 */
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Filter } from 'lucide-vue-next'
import AppShell from '@/components/layout/AppShell.vue'
import SearchBar from '@/components/search/SearchBar.vue'
import ScopeHeader from '@/components/search/ScopeHeader.vue'
import SubcorpusDrawer from '@/components/search/SubcorpusDrawer.vue'
import DocDetailDrawer from '@/components/search/DocDetailDrawer.vue'
import TabNav from '@/components/search/TabNav.vue'
import KwicPlaceholder from '@/components/search/KwicPlaceholder.vue'
import HeaderActions from '@/components/layout/HeaderActions.vue'
import CorpusSwitcher from '@/components/layout/CorpusSwitcher.vue'
import StatusBar from '@/components/layout/StatusBar.vue'
// Lazy-loaded UI components
import { ShortcutsOverlay, CommandPalette } from '@/components/ui/lazy'
import SpotlightTour from '@/components/onboarding/SpotlightTour.vue'
import {
  analysisComponentForTab,
  analysisComponentPropsForTab,
} from '@/components/analysis/surfaceComponents'
import FadeTransition from '@/components/transitions/FadeTransition.vue'
import { actionBus } from '@/actions'
import {
  asSwitchTabId,
  useQueryStore,
  useSettingsStore,
  useUiStore,
  useHistoryStore,
  useCorpusCapabilitiesStore,
  useProductCapabilitiesStore,
  useSessionStore
} from '@/stores'
import { useUndoRedo } from '@/composables'
import { useUrlState } from '@/composables/useUrlState'
import { useScrollHandoff } from '@/composables/useScrollHandoff'

const { t } = useI18n()
const queryStore = useQueryStore()
const uiStore = useUiStore()
const settingsStore = useSettingsStore()
const historyStore = useHistoryStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const productCapabilities = useProductCapabilitiesStore()
const sessionStore = useSessionStore()
const KwicTable = defineAsyncComponent(() => import('@/components/search/KwicTable.vue'))

function openSubcorpusFilter() {
  uiStore.openSubcorpus()
}

// The tab area scrolls as a whole. Downward wheel steps over a result table
// that still reaches below the window scroll the tab first.
const tabContentRef = ref<HTMLElement | null>(null)
useScrollHandoff(tabContentRef)

// Enable global undo/redo keyboard shortcuts
useUndoRedo()
useUrlState()
settingsStore.init({
  loadPreferences: false,
  loadEmbeddings: false,
  loadSystemInfo: false,
})

const showKwicTable = computed(() => {
  if (renderedActiveTab.value !== 'kwic') return false
  if (queryStore.hasResults) return true
  if (queryStore.isLoading) return true
  if (queryStore.streamingProgress?.isStreaming) return true
  if (queryStore.error) return true
  return false
})

const renderedActiveTab = computed(() => {
  return productCapabilities.analysisTabAvailability(
    uiStore.activeTab,
    corpusCapabilities.activeSummary,
  ).enabled
    ? uiStore.activeTab
    : null
})

const firstAvailableAnalysisTab = computed(() =>
  productCapabilities.discoverableAnalysisTabs.find((surface) =>
    productCapabilities.surfaceAvailability(
      surface.capabilityId,
      corpusCapabilities.activeSummary,
    ).enabled
  )?.tab ?? null
)

const discoverableAnalysisTabsSignature = computed(() =>
  productCapabilities.discoverableAnalysisTabs.map((surface) => surface.tab).join('|')
)

const activeCorpusFeatureSignature = computed(() =>
  JSON.stringify(corpusCapabilities.activeSummary?.features ?? null)
)

const renderedAnalysisComponent = computed(() =>
  analysisComponentForTab(renderedActiveTab.value)
)

const renderedAnalysisComponentProps = computed(() =>
  analysisComponentPropsForTab(renderedActiveTab.value)
)

const analysisAccessMessage = computed(() => {
  if (sessionStore.needsLogin) {
    return t('layout.app.needsLogin')
  }
  if (sessionStore.hasInvalidToken) {
    return t('layout.app.invalidToken')
  }
  return productCapabilities.analysisTabAvailability(
    uiStore.activeTab,
    corpusCapabilities.activeSummary,
  ).disabledReason
    ?? productCapabilities.accessBlockReason('query.kwic', t('layout.app.kwicSearch'))
    ?? t('layout.app.noAnalysisSurface')
})

function normalizeActiveAnalysisTab() {
  if (productCapabilities.analysisTabAvailability(
    uiStore.activeTab,
    corpusCapabilities.activeSummary,
  ).enabled) return
  const target = firstAvailableAnalysisTab.value
  if (!target) return
  void actionBus.dispatch(
    { type: 'nav/switchTab', payload: { tab: asSwitchTabId(target) } },
    { source: 'system' },
  )
}

watch(
  [() => uiStore.activeTab, discoverableAnalysisTabsSignature, activeCorpusFeatureSignature],
  () => normalizeActiveAnalysisTab(),
  { flush: 'post' },
)

onMounted(() => {
  void productCapabilities.ensureAccessContext().then(() => {
    normalizeActiveAnalysisTab()
    // The guided tour is opt-in only (Einstellungen → „Einführung erneut starten").
    // An expert concordancer must not push a tutorial onto researchers on launch.
  })

  historyStore.setStateHandlers(
    () => ({
      query: queryStore.term,
      selectedRows: Array.from(queryStore.selectedRows),
      tab: uiStore.activeTab,
      scrollPosition: queryStore.scrollPosition,
      filters: queryStore.filters,
      timestamp: Date.now()
    }),
    async (state) => {
      historyStore.setRestoring(true)
      try {
        const restoredFilters = state.filters ?? {}
        await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: asSwitchTabId(state.tab) } }, { source: 'restore' })
        queryStore.setFilters(restoredFilters)
        queryStore.setSelectedRows(state.selectedRows ?? [])

        if (state.query) {
          await actionBus.dispatch({
            type: 'query/execute',
            payload: {
              term: state.query,
              filters: restoredFilters
            }
          }, { source: 'restore', requestId: 'history-restore:query' })
          queryStore.setPendingScrollPosition(state.scrollPosition ?? 0)
        }
      } finally {
        historyStore.setRestoring(false)
      }
    }
  )

})
</script>

<template>
  <AppShell>
    <template #header>
      <div class="header-stack">
        <div class="brand-row">
          <div class="flex items-center gap-3">
            <h1 class="text-lg md:text-xl font-semibold text-neutral-900 dark:text-neutral-100">
              CandyConc
            </h1>
            <span class="text-xs px-2 py-0.5 rounded-full bg-copilot-bg text-copilot-primary">
              {{ t('layout.app.beta') }}
            </span>
          </div>
          <div class="brand-actions">
            <CorpusSwitcher />
            <HeaderActions />
          </div>
        </div>

        <div class="workbar" data-onboarding="search">
          <div class="workbar-inner">
            <div class="workbar-search">
              <SearchBar />
            </div>
            <button
              class="workbar-filter-button"
              type="button"
              :aria-label="t('layout.app.openFilter')"
              @click="openSubcorpusFilter"
            >
              <Filter class="w-4 h-4" />
              <span>{{ t('layout.app.filterButton') }}</span>
            </button>
            <div class="workbar-scope">
              <ScopeHeader inline minimal />
            </div>
          </div>
        </div>
      </div>
    </template>

    <div class="app-main">
      <div class="sticky-top">
        <TabNav data-onboarding="tabs" />
      </div>

      <div ref="tabContentRef" class="tab-content">
        <FadeTransition mode="out-in">
          <!-- KWIC Tab -->
          <template v-if="renderedActiveTab === 'kwic'">
            <div key="kwic-workbench" class="kwic-workbench">
              <div class="kwic-workbench-body">
                <KwicTable v-if="showKwicTable" key="kwic-table" />
                <KwicPlaceholder v-else key="kwic-placeholder" />
              </div>
            </div>
          </template>

          <component
            :is="renderedAnalysisComponent"
            v-else-if="renderedAnalysisComponent"
            :key="renderedActiveTab"
            v-bind="renderedAnalysisComponentProps"
          />

          <div v-else key="analysis-locked" class="capability-empty">
            {{ analysisAccessMessage }}
          </div>
        </FadeTransition>
      </div>
    </div>

    <template #footer>
      <StatusBar />
    </template>
  </AppShell>

  <!-- Global Overlays -->
  <ShortcutsOverlay v-model="uiStore.shortcutsOpen" />
  <CommandPalette v-model="uiStore.commandPaletteOpen" />
  <SpotlightTour />
  <SubcorpusDrawer />
  <DocDetailDrawer
    v-model="uiStore.documentDetailOpen"
    :doc-id="uiStore.documentDetail?.docId ?? null"
    :corpus="uiStore.documentDetail?.corpus"
    :fallback-label="uiStore.documentDetail?.fallbackLabel"
    :fallback-meta="uiStore.documentDetail?.fallbackMeta"
    :highlight="uiStore.documentDetail?.highlight"
    :highlight-position="uiStore.documentDetail?.highlightPosition"
    :highlight-left="uiStore.documentDetail?.highlightLeft"
    :highlight-right="uiStore.documentDetail?.highlightRight"
  />
</template>

<style scoped>
@reference "./style.css";

.app-main {
  @apply flex flex-col h-full;
}

.sticky-top {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  @apply bg-white dark:bg-neutral-900;
}

.header-stack {
  @apply flex flex-col gap-2 md:gap-3 w-full;
}

.brand-row {
  /* Wrap + allow children to shrink so the right-hand action group never forces
     a page-level horizontal scroll at 375px (DESIGN-A11Y-01 / KWIC-PLAIN-03). */
  @apply flex flex-wrap items-center justify-between gap-2 w-full min-w-0;
}

.brand-actions {
  /* Shrinkable, wrap-capable action cluster; min-w-0 lets flex actually shrink it. */
  @apply flex flex-wrap items-center justify-end gap-2 md:gap-4 min-w-0;
}

.workbar {
  @apply w-full;
}

.workbar-inner {
  @apply w-full mx-auto flex flex-wrap items-center gap-2 md:gap-3;
  max-width: 1200px;
}

.workbar-search {
  /* Filter and scope move to the next row before the search field gets
     narrower than this. */
  @apply flex-1;
  min-width: min(100%, 24rem);
}

.workbar-filter-button {
  @apply inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium text-neutral-700;
  @apply hover:bg-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2;
  @apply dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 dark:hover:bg-neutral-700 dark:focus:ring-offset-neutral-900;
}

.workbar-scope {
  @apply shrink-0;
}

.tab-content {
  /* Every view scrolls. Its root is at least as high as this area and may
     grow. Result tables inside size themselves against the height of this
     area through container query units (100cqh), so a table can take the
     whole visible tab once the toolbars above it have scrolled away. */
  @apply flex-1 min-h-0 overflow-auto;
  container-type: size;
}

.kwic-workbench {
  @apply flex min-h-full flex-col;
}

.kwic-workbench-body {
  @apply flex flex-col;
  flex: 1 0 auto;
}

.capability-empty {
  @apply m-4 rounded-xl border border-dashed border-neutral-300 p-6 text-sm text-neutral-600 dark:border-neutral-700 dark:text-neutral-300;
}
</style>
