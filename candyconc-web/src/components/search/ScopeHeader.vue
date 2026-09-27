<script setup lang="ts">
/**
 * ScopeHeader - Global scope header with scope chip, view title, and actions
 */
import { computed, ref } from 'vue'
import {
  Archive,
  Layers,
  Scale,
  Edit3,
  PauseCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  MoreHorizontal,
  Filter,
  AlertTriangle,
} from 'lucide-vue-next'
import Dropdown from '@/components/ui/Dropdown.vue'
import DropdownItem from '@/components/ui/DropdownItem.vue'
import { useDocsetStore, useUiStore, useSubcorporaStore, useSettingsStore } from '@/stores'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import type { ActiveTab } from '@/stores/ui'
import { useGlobalOnlineStatus } from '@/composables/useOnlineStatus'
import { actionBus } from '@/actions'
import { describeScopeEvidence } from '@/lib/scopeEvidence'
import { formatNumber, formatTime } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  inline?: boolean
  minimal?: boolean
}>()

const docsetStore = useDocsetStore()
const uiStore = useUiStore()
const subcorporaStore = useSubcorporaStore()
const settingsStore = useSettingsStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const { isOnline, isBackendReady, backendReadiness, lastCheckTimestamp, isChecking, forceCheck } = useGlobalOnlineStatus()

// The name to show (display_name from the catalogue), requests keep the identifier.
const corpusLabel = computed(() => {
  if (corpusCapabilities.catalogEmpty) return t('search.scopeHeader.noCorpus')
  return corpusCapabilities.activeDisplayName || docsetStore.activeCorpus || 'default'
})
const activeCorpusSummary = computed(() => corpusCapabilities.activeSummary)
const scopeLabel = computed(() => {
  // Without a corpus there is no whole corpus either: "Scope: no corpus".
  if (docsetStore.hasActiveDocset || corpusCapabilities.catalogEmpty) return t('search.scopeHeader.scope')
  return t('search.scopeHeader.wholeCorpus')
})
const scopeDetails = computed(() => {
  if (!docsetStore.hasActiveDocset) return ''
  if (!docsetStore.summaryParts.length) return ''
  return docsetStore.summaryParts.join(' · ')
})
const activeSnapshotStatus = computed(() => {
  if (!docsetStore.activeDocsetId) return null
  const match =
    subcorporaStore.parked.find((snapshot) => snapshot.docsetId === docsetStore.activeDocsetId) ??
    subcorporaStore.archived.find((snapshot) => snapshot.docsetId === docsetStore.activeDocsetId)
  return match?.status ?? null
})

const VIEW_LABEL_KEYS: Record<ActiveTab, string> = {
  kwic: 'search.scopeHeader.views.kwic',
  reader: 'search.scopeHeader.views.reader',
  frequency: 'search.scopeHeader.views.frequency',
  collocations: 'search.scopeHeader.views.collocations',
  collocation_network: 'search.scopeHeader.views.collocationNetwork',
  dispersion: 'search.scopeHeader.views.dispersion',
  semantic: 'search.scopeHeader.views.semantic',
  ngrams: 'search.scopeHeader.views.ngrams',
  contrast: 'search.scopeHeader.views.contrast',
  keyness: 'search.scopeHeader.views.keyness',
  wordsketch: 'search.scopeHeader.views.wordsketch',
  trend: 'search.scopeHeader.views.trend',
}

const viewTitle = computed(() => {
  const key = VIEW_LABEL_KEYS[uiStore.activeTab]
  return key ? t(key) : t('search.scopeHeader.view')
})
const isInline = computed(() => props.inline ?? false)
const isMinimal = computed(() => props.minimal ?? false)
const isCompactActions = computed(() => isInline.value && !isMinimal.value)
const showStatus = computed(() => !isMinimal.value)
const showActions = computed(() => !isMinimal.value)

const canManageSubcorpus = computed(() =>
  docsetStore.hasActiveDocset
  && !!docsetStore.activeDocsetId
  && !docsetStore.isDirty
  && subcorporaStore.canSaveSubcorpora
)
const manageSubcorpusTitle = computed(() =>
  subcorporaStore.canSaveSubcorpora
    ? (
      docsetStore.isDirty
        ? t('search.scopeHeader.applyFirst')
        : t('search.scopeHeader.manageActive')
    )
    : subcorporaStore.saveAvailability.disabledReason ?? t('search.scopeHeader.saveNotEnabled')
)

// The query term only belongs in the name when the ACTIVE docset was actually
// built from a search (origin.kind === 'search'). A metadata/filter-built scope
// must NOT inherit a stale, unrelated queryStore.term (e.g. a committed 'und')
// — that mislabels the filter scope as "Query und" (SUBC-01).
const originTerm = computed(() => {
  const origin = docsetStore.activeDocsetOrigin
  return origin?.kind === 'search' ? origin.query.trim() : ''
})

function suggestName(): string {
  return subcorporaStore.suggestName({
    term: originTerm.value,
    corpus: docsetStore.activeCorpus,
    filters: docsetStore.filters,
    includeAi: docsetStore.includeAi,
    includeHuman: docsetStore.includeHuman,
  })
}

const scopeName = computed(() => {
  if (!docsetStore.hasActiveDocset) {
    return corpusLabel.value
  }
  const raw = suggestName()
  if (raw.length <= 80) return raw
  return `${raw.slice(0, 77)}…`
})
const compactScopeName = computed(() => scopeDetails.value || scopeName.value)
const scopeEditTitle = computed(() => {
  const current = docsetStore.hasActiveDocset ? compactScopeName.value : corpusLabel.value
  return t('search.scopeHeader.editScope', { current })
})

const originLabel = computed(() => {
  if (!docsetStore.hasActiveDocset) return ''
  // Provenance comes from how the docset was built, not the live search box.
  const origin = docsetStore.activeDocsetOrigin
  if (origin?.kind === 'search' && origin.query.trim()) return t('search.scopeHeader.originQuery', { query: origin.query.trim() })
  if (origin?.kind === 'meta' || docsetStore.filtersActive) return t('search.scopeHeader.originFilter')
  return t('search.scopeHeader.originSubcorpus')
})

const showDetails = ref(false)
const hasDetails = computed(
  () =>
    (!!activeCorpusSummary.value && !docsetStore.hasActiveDocset) ||
    !!scopeDetails.value ||
    !!originLabel.value ||
    docsetStore.hasActiveDocset ||
    !!activeSnapshotStatus.value
)
const detailsLabel = computed(() => (showDetails.value ? t('search.scopeHeader.hideDetails') : t('search.scopeHeader.showDetails')))

const docCountLabel = computed(() => {
  const count = docsetStore.hasActiveDocset
    ? docsetStore.stats.docCount
    : corpusCapabilities.activeCorpusDocCount || (
      settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.documentCount : 0
    )
  return formatNumber(count ?? 0)
})

const tokenCountLabel = computed(() => {
  const count = docsetStore.hasActiveDocset
    ? docsetStore.stats.tokenCount
    : corpusCapabilities.activeCorpusTokenCount || (
      settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.tokenCount : 0
    )
  return formatNumber(count ?? 0)
})

const refDocLabel = computed(() => {
  if (!docsetStore.hasActiveDocset) return ''
  if (!docsetStore.stats.refDocCount) return ''
  return formatNumber(docsetStore.stats.refDocCount)
})

const scopeEvidence = computed(() => describeScopeEvidence({
  hasActiveDocset: docsetStore.hasActiveDocset,
  isDirty: docsetStore.isDirty,
  activeScopeStale: docsetStore.activeScopeStale,
  activeScopeWarning: docsetStore.activeScopeWarning,
  activeScopeResolvedAt: docsetStore.activeScopeResolvedAt,
}))

const showInlineScopeWarning = computed(() => (
  scopeEvidence.value.visible &&
  scopeEvidence.value.tone === 'warn' &&
  (!showDetails.value || isMinimal.value)
))

function activeResolution() {
  if (!docsetStore.hasActiveDocset) return undefined
  const stale = Boolean(docsetStore.activeScopeStale)
  return {
    status: stale ? 'stale' as const : 'fresh' as const,
    stale,
    resolvedAt: docsetStore.activeScopeResolvedAt ?? Date.now(),
    message: docsetStore.activeScopeWarning ?? undefined,
  }
}

// The durable subcorpus origin must follow how the docset was BUILT, not the
// live search box: baking queryStore.term into a metadata scope persists a
// stale, unrelated query into the saved definition (SUBC-01). 'search' scopes
// carry their query; 'meta'/filter scopes are query-less.
function activeOrigin(): { type: 'query'; query: string } | { type: 'filter' } {
  const origin = docsetStore.activeDocsetOrigin
  if (origin?.kind === 'search' && origin.query.trim()) {
    return { type: 'query', query: origin.query.trim() }
  }
  return { type: 'filter' }
}

const statusLabel = computed(() => {
  if (!isOnline.value) return t('search.scopeHeader.offline')
  if (backendReadiness.value === 'checking') return t('search.scopeHeader.serverChecking')
  if (backendReadiness.value === 'auth_required') return t('search.scopeHeader.authRequired')
  if (backendReadiness.value === 'contract_unavailable') return t('search.scopeHeader.serverNotReady')
  if (!isBackendReady.value) return t('search.scopeHeader.serverOffline')
  return t('search.scopeHeader.online')
})

const statusTone = computed(() => {
  if (!isOnline.value || !isBackendReady.value) return 'offline'
  return 'online'
})

const lastCheckLabel = computed(() => {
  if (!lastCheckTimestamp.value) return t('search.scopeHeader.never')
  return formatTime(lastCheckTimestamp.value, {
    hour: '2-digit',
    minute: '2-digit',
  })
})

const statusTitle = computed(() => t('search.scopeHeader.statusTitle', { status: statusLabel.value, time: lastCheckLabel.value }))

function parkActive() {
  if (!docsetStore.hasActiveDocset || !docsetStore.activeDocsetId) {
    uiStore.showToast(t('search.scopeHeader.noActive'), 'warning')
    return
  }
  if (docsetStore.isDirty) {
    uiStore.showToast(t('search.scopeHeader.applyBeforeSave'), 'warning')
    return
  }
  if (!subcorporaStore.canSaveSubcorpora) {
    uiStore.showToast(subcorporaStore.saveAvailability.disabledReason ?? t('search.scopeHeader.saveNotEnabledDot'), 'warning')
    return
  }
  const name = suggestName()
  const snapshot = subcorporaStore.createSnapshot({
    name,
    status: 'parked',
    corpus: docsetStore.activeCorpus,
    docsetId: docsetStore.activeDocsetId,
    stats: {
      docCount: docsetStore.stats.docCount,
      tokenCount: docsetStore.stats.tokenCount,
      refDocCount: docsetStore.stats.refDocCount,
    },
    filters: {
      prompting_method: [...docsetStore.filters.prompting_method],
      model: [...docsetStore.filters.model],
      register: [...docsetStore.filters.register],
      source: [...docsetStore.filters.source],
    },
    filterSpec: docsetStore.activeFilterSpec ?? undefined,
    includeAi: docsetStore.includeAi,
    includeHuman: docsetStore.includeHuman,
    statsResolved: true,
    metadataSchemaHash: docsetStore.metaSchemaHash ?? undefined,
    resolution: activeResolution(),
    origin: activeOrigin(),
  })
  if (!subcorporaStore.add(snapshot)) {
    uiStore.showToast(subcorporaStore.error ?? t('search.scopeHeader.saveFailed'), 'warning')
    return
  }
  uiStore.showToast(t('search.scopeHeader.parked'), 'success', 2000)
}

function archiveActive() {
  if (!docsetStore.hasActiveDocset || !docsetStore.activeDocsetId) {
    uiStore.showToast(t('search.scopeHeader.noActive'), 'warning')
    return
  }
  if (docsetStore.isDirty) {
    uiStore.showToast(t('search.scopeHeader.applyBeforeArchive'), 'warning')
    return
  }
  if (!subcorporaStore.canSaveSubcorpora) {
    uiStore.showToast(subcorporaStore.saveAvailability.disabledReason ?? t('search.scopeHeader.saveNotEnabledDot'), 'warning')
    return
  }
  const name = suggestName()
  const snapshot = subcorporaStore.createSnapshot({
    name,
    status: 'archived',
    corpus: docsetStore.activeCorpus,
    docsetId: docsetStore.activeDocsetId,
    stats: {
      docCount: docsetStore.stats.docCount,
      tokenCount: docsetStore.stats.tokenCount,
      refDocCount: docsetStore.stats.refDocCount,
    },
    filters: {
      prompting_method: [...docsetStore.filters.prompting_method],
      model: [...docsetStore.filters.model],
      register: [...docsetStore.filters.register],
      source: [...docsetStore.filters.source],
    },
    filterSpec: docsetStore.activeFilterSpec ?? undefined,
    includeAi: docsetStore.includeAi,
    includeHuman: docsetStore.includeHuman,
    statsResolved: true,
    metadataSchemaHash: docsetStore.metaSchemaHash ?? undefined,
    resolution: activeResolution(),
    origin: activeOrigin(),
  })
  if (!subcorporaStore.add(snapshot)) {
    uiStore.showToast(subcorporaStore.error ?? t('search.scopeHeader.archiveFailed'), 'warning')
    return
  }
  docsetStore.resetDocset()
  uiStore.showToast(t('search.scopeHeader.archived'), 'success', 2000)
}

function openWorkspace() {
  uiStore.openWorkspace('subcorpora')
}

function openFilterBuilder() {
  uiStore.openSubcorpus()
}

function startContrast() {
  void actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'contrast' } })
}

function renameHint() {
  uiStore.openWorkspace('subcorpora')
}
</script>

<template>
  <div class="scope-header" :class="{ 'is-inline': isInline, 'is-minimal': isMinimal }">
    <div class="scope-left">
      <button
        class="scope-chip scope-chip-button"
        type="button"
        :title="scopeEditTitle"
        :aria-label="scopeEditTitle"
        @click="openFilterBuilder"
      >
        <span class="scope-chip-label">{{ scopeLabel }}</span>
        <span class="scope-chip-name">{{ isMinimal ? compactScopeName : scopeName }}</span>
      </button>
      <span
        v-if="showInlineScopeWarning"
        class="scope-evidence-chip tone-warn"
        :title="scopeEvidence.title"
      >
        {{ scopeEvidence.label }}
      </span>
      <div v-if="showDetails" class="scope-subline">
        <span class="scope-subline-item">{{ t('search.scopeHeader.corpus', { name: corpusLabel }) }}</span>
        <span v-if="scopeDetails" class="scope-subline-item">· {{ scopeDetails }}</span>
        <span v-if="originLabel" class="scope-subline-item">· {{ originLabel }}</span>
        <span v-if="activeSnapshotStatus" class="scope-subline-item status-chip" :class="`status-${activeSnapshotStatus}`">
          {{ activeSnapshotStatus === 'archived' ? t('search.scopeHeader.statusArchived') : t('search.scopeHeader.statusParked') }}
        </span>
      </div>
      <div v-if="showDetails" class="scope-stats">
        <span class="scope-stat">{{ t('search.scopeHeader.docs', { count: docCountLabel }) }}</span>
        <span class="scope-stat">{{ t('search.scopeHeader.tokens', { count: tokenCountLabel }) }}</span>
        <span v-if="refDocLabel" class="scope-stat">{{ t('search.scopeHeader.refDocs', { count: refDocLabel }) }}</span>
        <span
          v-if="scopeEvidence.visible"
          class="scope-evidence-chip"
          :class="`tone-${scopeEvidence.tone}`"
          :title="scopeEvidence.title"
        >
          {{ scopeEvidence.label }}
        </span>
        <span v-if="scopeEvidence.resolvedAtLabel" class="scope-stat">{{ t('search.scopeHeader.checkedAt', { time: scopeEvidence.resolvedAtLabel }) }}</span>
      </div>
      <div v-if="showDetails && scopeEvidence.warning" class="scope-warning">
        <AlertTriangle class="w-3.5 h-3.5" />
        <span>{{ scopeEvidence.warning }}</span>
      </div>
    </div>

    <div v-if="!isInline && !isMinimal" class="scope-center">
      <span class="view-title">{{ viewTitle }}</span>
    </div>

    <div class="scope-right">
      <button
        v-if="hasDetails && showActions"
        class="scope-action scope-action-ghost"
        type="button"
        :title="detailsLabel"
        :aria-label="detailsLabel"
        @click="showDetails = !showDetails"
      >
        <component :is="showDetails ? ChevronUp : ChevronDown" class="w-4 h-4" aria-hidden="true" />
        <span>{{ t('search.scopeHeader.details') }}</span>
      </button>
      <div v-if="showStatus" class="status-pill" :class="statusTone" :title="statusTitle">
        <span class="status-dot" />
        <span class="status-text">{{ t('search.scopeHeader.server') }}</span>
        <span class="status-state">{{ statusLabel }}</span>
        <button
          class="status-refresh"
          type="button"
          :disabled="isChecking"
          @click="forceCheck"
          :title="t('search.scopeHeader.refreshStatus')"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isChecking }" />
        </button>
      </div>
      <Dropdown v-if="isCompactActions && showActions" align="right" width="md">
        <template #trigger="{ triggerProps }">
          <button class="scope-action" type="button" :title="t('search.scopeHeader.actions')" :aria-label="t('search.scopeHeader.actions')" v-bind="triggerProps">
            <MoreHorizontal class="w-4 h-4" aria-hidden="true" />
            <span>{{ t('search.scopeHeader.actions') }}</span>
          </button>
        </template>
        <DropdownItem :icon="Layers" @click="openWorkspace">{{ t('search.scopeHeader.workspace') }}</DropdownItem>
        <DropdownItem :icon="Filter" @click="openFilterBuilder">{{ t('search.scopeHeader.editSubcorpus') }}</DropdownItem>
        <DropdownItem :icon="PauseCircle" :disabled="!canManageSubcorpus" @click="parkActive">
          {{ t('search.scopeHeader.park') }}
        </DropdownItem>
        <DropdownItem :icon="Archive" :disabled="!canManageSubcorpus" @click="archiveActive">
          {{ t('search.scopeHeader.archive') }}
        </DropdownItem>
        <DropdownItem :icon="Scale" @click="startContrast">{{ t('search.scopeHeader.contrast') }}</DropdownItem>
        <DropdownItem :icon="Edit3" :disabled="!canManageSubcorpus" @click="renameHint">
          {{ t('search.scopeHeader.rename') }}
        </DropdownItem>
      </Dropdown>

      <template v-else-if="showActions">
        <button class="scope-action" type="button" @click="openWorkspace" :title="t('search.scopeHeader.openWorkspace')">
          <Layers class="w-4 h-4" />
          <span>{{ t('search.scopeHeader.workspace') }}</span>
        </button>
        <button class="scope-action" type="button" @click="openFilterBuilder" :title="t('search.scopeHeader.editSubcorpus')">
          <Filter class="w-4 h-4" />
          <span>{{ t('search.scopeHeader.subcorpus') }}</span>
        </button>
        <button
          class="scope-action"
          type="button"
          :disabled="!canManageSubcorpus"
          @click="parkActive"
          :title="manageSubcorpusTitle"
        >
          <PauseCircle class="w-4 h-4" />
          <span>{{ t('search.scopeHeader.park') }}</span>
        </button>
        <button
          class="scope-action"
          type="button"
          :disabled="!canManageSubcorpus"
          @click="archiveActive"
          :title="manageSubcorpusTitle"
        >
          <Archive class="w-4 h-4" />
          <span>{{ t('search.scopeHeader.archiveShort') }}</span>
        </button>
        <button class="scope-action" type="button" @click="startContrast" :title="t('search.scopeHeader.startContrast')">
          <Scale class="w-4 h-4" />
          <span>{{ t('search.scopeHeader.contrast') }}</span>
        </button>
        <button
          class="scope-action scope-action-ghost"
          type="button"
          :disabled="!canManageSubcorpus"
          @click="renameHint"
          :title="t('search.scopeHeader.rename')"
        >
          <Edit3 class="w-4 h-4" />
          <span>{{ t('search.scopeHeader.rename') }}</span>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.scope-header {
  @apply flex flex-wrap items-center gap-3 px-3 md:px-4 py-2;
  @apply text-xs md:text-sm text-neutral-600 dark:text-neutral-300;
  @apply border-b border-neutral-100 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
}

.scope-header.is-inline,
.scope-header.is-minimal {
  @apply px-0 py-0;
  @apply border-0 bg-transparent;
}

.scope-header.is-inline .scope-left,
.scope-header.is-minimal .scope-left {
  @apply flex-row items-center gap-3;
}

.scope-header.is-inline .scope-chip,
.scope-header.is-minimal .scope-chip {
  @apply py-0.5;
}

.scope-left {
  @apply flex flex-col gap-1 min-w-0;
}

.scope-chip {
  @apply inline-flex items-center gap-2 px-2.5 py-1 rounded-full;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-xs font-medium text-neutral-700 dark:text-neutral-200;
}

.scope-chip-button {
  @apply cursor-pointer border-0 transition-colors;
  @apply hover:bg-neutral-200 focus:outline-none focus:ring-2 focus:ring-primary-500/40;
  @apply dark:hover:bg-neutral-700;
}

.scope-chip-label {
  @apply uppercase tracking-wide text-[10px] text-neutral-500 dark:text-neutral-400;
}

.scope-chip-name {
  @apply font-semibold text-neutral-800 dark:text-neutral-100;
}

.scope-subline {
  @apply flex flex-wrap items-center gap-1.5 text-[11px];
  @apply text-neutral-500 dark:text-neutral-400;
}

.scope-subline-item {
  @apply whitespace-nowrap;
}

.status-chip {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
}

.status-chip.status-parked {
  @apply bg-amber-100 text-amber-700;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.status-chip.status-archived {
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-stats {
  @apply flex flex-wrap items-center gap-2 text-[11px];
  @apply text-neutral-500 dark:text-neutral-400;
}

.scope-stat {
  @apply whitespace-nowrap;
}

.scope-evidence-chip {
  @apply px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap;
  @apply border border-transparent;
}

.scope-evidence-chip.tone-ok {
  @apply bg-emerald-100 text-emerald-700;
  @apply dark:bg-emerald-900/40 dark:text-emerald-200;
}

.scope-evidence-chip.tone-warn {
  @apply bg-amber-100 text-amber-700;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.scope-evidence-chip.tone-neutral {
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-warning {
  @apply flex max-w-3xl items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5;
  @apply text-[11px] text-amber-800;
  @apply dark:border-amber-800/60 dark:bg-amber-900/30 dark:text-amber-200;
}

.scope-center {
  @apply text-xs font-semibold uppercase tracking-wide;
  @apply text-neutral-500 dark:text-neutral-400;
}

.scope-right {
  @apply ml-auto flex flex-wrap items-center gap-2;
}


.status-pill {
  @apply inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px];
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply border border-transparent;
}

.status-pill.online {
  @apply text-success-700 dark:text-success-300;
}

.status-pill.offline {
  @apply text-error-600 dark:text-error-400;
}

.status-dot {
  @apply w-2 h-2 rounded-full bg-success-500;
}

.status-pill.offline .status-dot {
  @apply bg-error-500;
}

.status-text {
  @apply hidden md:inline;
}

.status-state {
  @apply font-medium;
}

.status-refresh {
  @apply ml-1 p-0.5 rounded-md;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
}

.scope-action {
  @apply inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-700 dark:text-neutral-200;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

.scope-action-ghost {
  @apply bg-transparent;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}
</style>
