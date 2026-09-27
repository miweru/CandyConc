<script setup lang="ts">
/**
 * WorkspaceManager - Unified workspace for Subcorpora + Analyses
 */
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import SlideOver from '@/components/ui/SlideOver.vue'
import WorkspaceSubcorporaPanel from '@/components/workspace/WorkspaceSubcorporaPanel.vue'
import WorkspaceAnalysesPanel from '@/components/workspace/WorkspaceAnalysesPanel.vue'
import { useAnalysisPresetsStore, useDocsetStore, useProductCapabilitiesStore, useQueryStore, useSubcorporaStore, useUiStore } from '@/stores'
import { describeScopeEvidence } from '@/lib/scopeEvidence'
import { formatNumber } from '@/i18n/format'

const { t } = useI18n()
const uiStore = useUiStore()
const docsetStore = useDocsetStore()
const queryStore = useQueryStore()
const subcorporaStore = useSubcorporaStore()
const presetsStore = useAnalysisPresetsStore()
const productCapabilities = useProductCapabilitiesStore()

type WorkspaceTabId = 'subcorpora' | 'analyses'
interface WorkspaceTabDef {
  id: WorkspaceTabId
  label: string
  visible: boolean
  enabled: boolean
  disabledReason: string | null
}

function capabilityTab(
  id: WorkspaceTabId,
  label: string,
  capabilityIds: string[],
): WorkspaceTabDef {
  const decisions = capabilityIds.map((capabilityId) =>
    productCapabilities.surfaceAvailability(capabilityId),
  )
  const visible = decisions.some((decision) => decision.visible)
  const enabled = decisions.some((decision) => decision.enabled)
  return {
    id,
    label,
    visible,
    enabled,
    disabledReason: enabled ? null : decisions.find((decision) => decision.disabledReason)?.disabledReason ?? null,
  }
}

const tabs = computed<WorkspaceTabDef[]>(() => [
  capabilityTab('subcorpora', t('workspace.manager.tabSubcorpora'), ['research.subcorpora_docsets']),
  capabilityTab('analyses', t('workspace.manager.tabAnalyses'), ['research.analysis_presets', 'analysis.async_jobs']),
].filter((tab) => tab.visible))
const enabledTabs = computed(() => tabs.value.filter((tab) => tab.enabled))

const activeTab = computed(() => uiStore.workspaceTab)
const scopeLabel = computed(() => docsetStore.scopeLabel)
const scopeCorpus = computed(() => docsetStore.activeCorpus ?? 'default')
const scopeQuery = computed(() => queryStore.term.trim())
const scopeParts = computed(() => docsetStore.summaryParts)
const scopeId = computed(() => (docsetStore.activeDocsetId ? docsetStore.activeDocsetId.slice(0, 8) : null))
const scopeEvidence = computed(() => describeScopeEvidence({
  hasActiveDocset: docsetStore.hasActiveDocset,
  isDirty: docsetStore.isDirty,
  activeScopeStale: docsetStore.activeScopeStale,
  activeScopeWarning: docsetStore.activeScopeWarning,
  activeScopeResolvedAt: docsetStore.activeScopeResolvedAt,
}))
const parkedCount = computed(() => subcorporaStore.parked.length)
const archivedCount = computed(() => subcorporaStore.archived.length)
const analysesCount = computed(() => presetsStore.presets.length)
const canUseSubcorpora = computed(() => tabs.value.some((tab) => tab.id === 'subcorpora' && tab.enabled))
const canUseAnalyses = computed(() => tabs.value.some((tab) => tab.id === 'analyses' && tab.enabled))
watch(
  () => uiStore.workspaceOpen,
  (open) => {
    if (!open) return
    if (canUseSubcorpora.value) subcorporaStore.init()
    if (canUseAnalyses.value) void presetsStore.init()
    const current = tabs.value.find((tab) => tab.id === uiStore.workspaceTab)
    if (!current?.enabled) {
      uiStore.setWorkspaceTab(enabledTabs.value[0]?.id ?? 'subcorpora')
    }
  },
  { immediate: true },
)

watch(tabs, () => {
  const current = tabs.value.find((tab) => tab.id === uiStore.workspaceTab)
  if (!current?.enabled) {
    uiStore.setWorkspaceTab(enabledTabs.value[0]?.id ?? 'subcorpora')
  }
})

function setTab(tab: WorkspaceTabDef) {
  if (!tab.enabled) {
    if (tab.disabledReason) uiStore.showToast(tab.disabledReason, 'warning')
    return
  }
  uiStore.setWorkspaceTab(tab.id)
}
</script>

<template>
  <SlideOver v-model="uiStore.workspaceOpen" size="xl" :title="t('workspace.manager.title')">
    <div class="workspace-scope">
      <div class="scope-head">
        <div class="scope-title">
          <span class="scope-label">{{ scopeLabel }}</span>
          <span class="scope-corpus">{{ t('workspace.shared.corpus', { corpus: scopeCorpus }) }}</span>
        </div>
        <div v-if="scopeId" class="scope-id">{{ t('workspace.shared.docsetId', { id: scopeId }) }}</div>
      </div>
      <div class="scope-chips">
        <span v-if="scopeQuery" class="scope-chip chip-primary">{{ t('workspace.shared.query', { query: scopeQuery }) }}</span>
        <span v-for="part in scopeParts" :key="part" class="scope-chip">{{ part }}</span>
        <span
          v-if="docsetStore.hasActiveDocset"
          class="scope-chip"
          :class="scopeEvidence.tone === 'warn' ? 'chip-warn' : 'chip-ok'"
          :title="scopeEvidence.title"
        >
          {{ scopeEvidence.label }}
        </span>
        <span v-if="scopeEvidence.resolvedAtLabel" class="scope-chip">
          {{ t('workspace.shared.checkedAt', { time: scopeEvidence.resolvedAtLabel }) }}
        </span>
        <span v-if="!scopeQuery && !scopeParts.length" class="scope-muted">
          {{ t('workspace.shared.noFilters') }}
        </span>
      </div>
      <div v-if="scopeEvidence.warning" class="scope-warning">
        {{ scopeEvidence.warning }}
      </div>
    </div>

    <div class="workspace-stats">
      <span class="stat-chip">
        {{ t('workspace.manager.statParked') }} <strong>{{ formatNumber(parkedCount) }}</strong>
      </span>
      <span class="stat-chip">
        {{ t('workspace.manager.statArchived') }} <strong>{{ formatNumber(archivedCount) }}</strong>
      </span>
      <span class="stat-chip">
        {{ t('workspace.manager.statAnalyses') }} <strong>{{ formatNumber(analysesCount) }}</strong>
      </span>
    </div>

    <div class="workspace-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        class="workspace-tab"
        :class="{ active: activeTab === tab.id, disabled: !tab.enabled }"
        :aria-disabled="!tab.enabled"
        :title="tab.disabledReason ?? tab.label"
        @click="setTab(tab)"
      >
        <span>{{ tab.label }}</span>
        <span v-if="tab.id === 'subcorpora'" class="tab-count">{{ formatNumber(parkedCount + archivedCount) }}</span>
        <span v-else class="tab-count">{{ formatNumber(analysesCount) }}</span>
        <span v-if="tab.disabledReason" class="tab-reason">{{ t('workspace.manager.locked') }}</span>
      </button>
    </div>

    <div class="workspace-body">
      <div v-if="activeTab === 'subcorpora' && canUseSubcorpora">
        <WorkspaceSubcorporaPanel :active="activeTab === 'subcorpora' && uiStore.workspaceOpen" />
      </div>
      <div v-else-if="activeTab === 'analyses' && canUseAnalyses">
        <WorkspaceAnalysesPanel />
      </div>
      <div v-else class="workspace-empty">
        {{ t('workspace.manager.noSurface') }}
      </div>
    </div>
  </SlideOver>
</template>

<style scoped>
@reference "../../style.css";

.workspace-scope {
  @apply mb-4 rounded-xl border border-neutral-200/80 dark:border-neutral-700/70;
  @apply bg-white/90 dark:bg-neutral-900/90;
  @apply p-3 space-y-2;
  @apply shadow-sm;
}

.scope-head {
  @apply flex items-center justify-between gap-3;
}

.scope-title {
  @apply flex items-center gap-3 flex-wrap;
  @apply leading-tight;
}

.scope-label {
  @apply px-2 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wide;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.scope-corpus {
  @apply text-sm font-medium text-neutral-700 dark:text-neutral-200;
}

.scope-id {
  @apply text-xs font-mono text-neutral-500 dark:text-neutral-400;
}

.scope-chips {
  @apply flex flex-wrap items-center gap-1.5;
}

.scope-chip {
  @apply px-2.5 py-1 rounded-full text-[11px];
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
}

.scope-chip.chip-primary {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.scope-chip.chip-ok {
  @apply bg-emerald-100 text-emerald-700;
  @apply dark:bg-emerald-900/40 dark:text-emerald-200;
}

.scope-chip.chip-warn {
  @apply bg-amber-100 text-amber-700;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.scope-warning {
  @apply rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800;
  @apply dark:border-amber-800/60 dark:bg-amber-900/30 dark:text-amber-200;
}

.scope-muted {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.workspace-tabs {
  @apply flex items-center gap-2 mb-4 pt-3 pb-3;
  @apply border-b border-neutral-200/70 dark:border-neutral-700/60;
  /* Opaque, and stuck at the top edge of the panel (its content has 1rem
     top padding), so scrolled content does not show above or through it. */
  @apply bg-white dark:bg-neutral-900;
  @apply sticky z-10;
  top: -1rem;
}

.workspace-stats {
  @apply flex flex-wrap items-center gap-2 mb-0;
}

.workspace-operations {
  @apply mb-4;
}

.stat-chip {
  @apply px-2.5 py-1 rounded-full text-[11px] font-medium;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
}

.workspace-tab {
  @apply px-3 py-1.5 rounded-lg text-sm font-medium;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
  @apply transition-colors;
}

.tab-count {
  @apply ml-2 px-2 py-0.5 rounded-full text-[11px];
  @apply bg-white/70 dark:bg-neutral-900/70;
  @apply text-neutral-500 dark:text-neutral-400;
}

.workspace-tab.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.workspace-tab.disabled {
  @apply opacity-50 cursor-not-allowed;
}

.tab-reason {
  @apply ml-2 rounded-full bg-warning-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-700 dark:bg-warning-900/30 dark:text-warning-200;
}

.workspace-body {
  @apply flex flex-col gap-4;
}

.workspace-empty {
  @apply rounded-xl border border-warning-200 bg-warning-50 p-4 text-sm text-warning-800;
  @apply dark:border-warning-900/60 dark:bg-warning-900/20 dark:text-warning-200;
}
</style>
