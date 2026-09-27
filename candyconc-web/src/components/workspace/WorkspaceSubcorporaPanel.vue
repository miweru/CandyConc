<script setup lang="ts">
/**
 * WorkspaceSubcorporaPanel - Content for Subcorpus Manager in Workspace
 */
import { computed, onMounted, ref, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { Archive, Play, Trash2, PauseCircle, Layers, Edit3, CalendarClock, Copy, X, Loader2, AlertTriangle } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import FilterSpecChips from '@/components/filters/FilterSpecChips.vue'
import { useDocsetStore, useSettingsStore, useUiStore, useSubcorporaStore } from '@/stores'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useParallelOperations } from '@/composables/useParallelOperations'
import type { SubcorpusOrigin, SubcorpusSnapshot, SubcorpusStatus } from '@/stores/subcorpora'
import { deriveFilterSpecFromLegacy, searchableFilterSpecText } from '@/lib/filterSpec'
import { isCorpusPaired } from '@/lib/corpusFeatureOptions'
import { pairSideValues, textTypeLabel } from '@/lib/pairSides'
import type { AlignmentRefDocResult } from '@/api/client'
import AlignmentComparison from '@/components/search/AlignmentComparison.vue'
import { formatNumber, formatDate, formatDateTime } from '@/i18n/format'

const props = defineProps<{ active: boolean }>()

const { t } = useI18n()
const uiStore = useUiStore()
const docsetStore = useDocsetStore()
const settingsStore = useSettingsStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const subcorporaStore = useSubcorporaStore()
const productCapabilities = useProductCapabilitiesStore()
const {
  groupsAvailability: parallelGroupsAvailability,
  canLoadParallelGroups,
  canOpenAlignment,
  parallelGroupsBlockReason: parallelBlockReason,
  alignmentBlockReason,
  loadParallelGroups,
  loadAlignmentRefDoc,
} = useParallelOperations()

const activeCorpus = computed(() => docsetStore.activeCorpus ?? 'default')
const activeHasDocset = computed(() => docsetStore.hasActiveDocset)
const canUseParallel = computed(() => canLoadParallelGroups.value)

const nameModalOpen = ref(false)
const nameDraft = ref('')
const nameStatus = ref<SubcorpusStatus>('parked')
const nameInput = ref<HTMLInputElement | null>(null)
const renameModalOpen = ref(false)
const renameDraft = ref('')
const renameTargetId = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)
const canSaveSubcorpora = computed(() => subcorporaStore.canSaveSubcorpora)
const canDeleteSubcorpora = computed(() => subcorporaStore.canDeleteSubcorpora)
const canResolveSubcorpora = computed(() => subcorporaStore.canResolveSubcorpora)
const canRenameSubcorpora = computed(() => canSaveSubcorpora.value && canDeleteSubcorpora.value)
const saveSubcorporaBlockReason = computed(() => subcorporaStore.saveAvailability.disabledReason)
const deleteSubcorporaBlockReason = computed(() => subcorporaStore.deleteAvailability.disabledReason)
const resolveSubcorporaBlockReason = computed(() => subcorporaStore.resolveAvailability.disabledReason)
const renameSubcorporaBlockReason = computed(() =>
  saveSubcorporaBlockReason.value
  ?? deleteSubcorporaBlockReason.value
  ?? t('workspace.subcorporaPanel.renameNeedsSaveDelete')
)
const canSaveName = computed(() => nameDraft.value.trim().length > 0 && canSaveSubcorpora.value)
const canSaveRename = computed(() => renameDraft.value.trim().length > 0 && canRenameSubcorpora.value)

const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const statusFilter = ref<'all' | 'parked' | 'archived'>('all')

const parallelRefs = ref<number[]>([])
const parallelSelectedRef = ref<number | null>(null)
const isLoadingParallel = ref(false)
const parallelError = ref<string | null>(null)

const alignmentOpen = ref(false)
const alignmentResult = ref<AlignmentRefDocResult | null>(null)
const alignmentError = ref<string | null>(null)
const isLoadingAlignment = ref(false)

const activeStats = computed(() => {
  if (docsetStore.hasActiveDocset) {
    return {
      docs: docsetStore.stats.docCount,
      tokens: docsetStore.stats.tokenCount,
      refs: docsetStore.stats.refDocCount,
    }
  }
  return {
    tokens: corpusCapabilities.activeCorpusTokenCount || (
      settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.tokenCount : 0
    ),
    docs: corpusCapabilities.activeCorpusDocCount || (
      settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.documentCount : 0
    ),
    refs: 0,
  }
})

// Provenance follows how the active docset was built, not the live search box
// (the same rule as ScopeHeader and buildSnapshot, SUBC-01).
const originText = computed(() => {
  if (!docsetStore.hasActiveDocset) return t('workspace.subcorporaPanel.originWholeCorpus')
  const origin = docsetStore.activeDocsetOrigin
  const builtQuery = origin?.kind === 'search' ? origin.query.trim() : ''
  if (builtQuery) return t('workspace.subcorporaPanel.originQuery', { query: builtQuery })
  if (origin?.kind === 'meta' || docsetStore.filtersActive) return t('workspace.subcorporaPanel.originFilter')
  return t('workspace.subcorporaPanel.originSubcorpus')
})

function formatOrigin(origin: SubcorpusOrigin): string {
  if (origin.query) return t('workspace.subcorporaPanel.originKindQuery', { query: origin.query })
  if (origin.type === 'filter') return t('workspace.subcorporaPanel.originKindFilter')
  if (origin.type === 'intersection') {
    return origin.label
      ? t('workspace.subcorporaPanel.originKindIntersectionLabel', { label: origin.label })
      : t('workspace.subcorporaPanel.originKindIntersection')
  }
  return origin.type
}

function formatStatus(status: SubcorpusStatus): string {
  return status === 'archived' ? t('workspace.shared.statusArchived') : t('workspace.shared.statusParked')
}

function formatResolvedAt(ts?: number | null): string {
  if (!ts) return t('workspace.subcorporaPanel.notChecked')
  return formatDateTime(ts)
}

function snapshotResolutionLabel(snapshot: SubcorpusSnapshot): string {
  const status = snapshot.resolution?.status
  if (status === 'stale') return t('workspace.subcorporaPanel.resolutionStale')
  if (status === 'fresh') return t('workspace.subcorporaPanel.resolutionFresh')
  if (status === 'error') return t('workspace.subcorporaPanel.resolutionError')
  return t('workspace.subcorporaPanel.notChecked')
}

function snapshotResolutionTitle(snapshot: SubcorpusSnapshot): string {
  return snapshot.resolution?.message
    ?? t('workspace.subcorporaPanel.resolutionTitle', { status: snapshotResolutionLabel(snapshot) })
}

function snapshotResolutionClass(snapshot: SubcorpusSnapshot): string {
  const status = snapshot.resolution?.status
  if (status === 'stale') return 'status-stale'
  if (status === 'fresh') return 'status-resolution'
  if (status === 'error') return 'status-error'
  return 'status-unresolved'
}

/**
 * Reference documents exist in paired corpora only. A count above zero is
 * shown in any case, for a corpus the catalog does not list (yet).
 */
function showsRefCount(corpus: string, refDocCount: number): boolean {
  const summary = corpusCapabilities.corpora.find((entry) => entry.name === corpus) ?? null
  return isCorpusPaired(summary) || refDocCount > 0
}

/**
 * A side tag only when the subcorpus leaves one side of a pair out. Both
 * switches are on by default, for unpaired corpora too, and every subcorpus
 * was tagged "AI" and "Human". The label names the side values the corpus has.
 */
function pairSideTag(snapshot: SubcorpusSnapshot): string | null {
  if (snapshot.includeAi === snapshot.includeHuman) return null
  const summary = corpusCapabilities.corpora.find((entry) => entry.name === snapshot.corpus) ?? null
  const sides = pairSideValues(summary)
  return textTypeLabel(snapshot.includeAi ? sides.version : sides.anchor)
}

function snapshotStatsLabel(snapshot: SubcorpusSnapshot): string {
  if (!snapshot.statsResolved) {
    if (snapshot.resolution?.status === 'error') return t('workspace.subcorporaPanel.statsFailed')
    return t('workspace.subcorporaPanel.statsPending')
  }
  if (!showsRefCount(snapshot.corpus, snapshot.stats.refDocCount)) {
    return t('workspace.subcorporaPanel.statsLineNoRefs', {
      docs: formatNumber(snapshot.stats.docCount),
      tokens: formatNumber(snapshot.stats.tokenCount),
    })
  }
  return t('workspace.subcorporaPanel.statsLine', {
    docs: formatNumber(snapshot.stats.docCount),
    tokens: formatNumber(snapshot.stats.tokenCount),
    refs: formatNumber(snapshot.stats.refDocCount),
  })
}

function snapshotFilterSpec(snapshot: SubcorpusSnapshot) {
  return deriveFilterSpecFromLegacy(snapshot.filters, snapshot.filterSpec)
}

function matchesSearch(snapshot: SubcorpusSnapshot): boolean {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return true
  const haystack = [
    snapshot.name,
    snapshot.corpus,
    snapshot.origin.query ?? '',
    searchableFilterSpecText(snapshotFilterSpec(snapshot)),
  ]
    .join(' ')
    .toLowerCase()
  return haystack.includes(query)
}

const filteredParked = computed(() =>
  subcorporaStore.parked.filter((snapshot) => matchesSearch(snapshot))
)

const filteredArchived = computed(() =>
  subcorporaStore.archived.filter((snapshot) => matchesSearch(snapshot))
)

const showParked = computed(() => statusFilter.value === 'all' || statusFilter.value === 'parked')
const showArchived = computed(() => statusFilter.value === 'all' || statusFilter.value === 'archived')
const hasParked = computed(() => subcorporaStore.parked.length > 0)
const hasArchived = computed(() => subcorporaStore.archived.length > 0)
const totalSubcorporaCount = computed(() =>
  subcorporaStore.parked.length + subcorporaStore.archived.length
)
const unresolvedSnapshotCount = computed(() =>
  subcorporaStore.snapshots.filter((snapshot) => !snapshot.statsResolved).length
)
const isResolvingSnapshotStats = ref(false)
const activeSnapshot = computed(() => {
  if (!docsetStore.activeDocsetId) return null
  return (
    subcorporaStore.parked.find((snapshot) => snapshot.docsetId === docsetStore.activeDocsetId) ??
    subcorporaStore.archived.find((snapshot) => snapshot.docsetId === docsetStore.activeDocsetId) ??
    null
  )
})
const activeScopeWarning = computed(() => docsetStore.activeScopeWarning)
const showParallelPanel = computed(() =>
  activeHasDocset.value
  && parallelGroupsAvailability.value.visible
  && (canLoadParallelGroups.value || Boolean(parallelBlockReason.value))
)

const searchLabel = computed(() => searchQuery.value.trim())

const parkedEmptyMessage = computed(() => {
  if (!hasParked.value) return t('workspace.subcorporaPanel.parkedEmpty')
  if (searchLabel.value) return t('workspace.shared.noMatchesFor', { query: searchLabel.value })
  return t('workspace.shared.noMatchesFilter')
})

const archivedEmptyMessage = computed(() => {
  if (!hasArchived.value) return t('workspace.subcorporaPanel.archivedEmpty')
  if (searchLabel.value) return t('workspace.shared.noMatchesFor', { query: searchLabel.value })
  return t('workspace.shared.noMatchesFilter')
})

const hasActiveFilters = computed(() =>
  !!searchQuery.value.trim() || statusFilter.value !== 'all'
)

const filteredTotal = computed(() => {
  if (statusFilter.value === 'parked') return filteredParked.value.length
  if (statusFilter.value === 'archived') return filteredArchived.value.length
  return filteredParked.value.length + filteredArchived.value.length
})

const totalForFilter = computed(() => {
  if (statusFilter.value === 'parked') return subcorporaStore.parked.length
  if (statusFilter.value === 'archived') return subcorporaStore.archived.length
  return totalSubcorporaCount.value
})

const filteredCountLabel = computed(() => {
  const total = totalForFilter.value
  const filtered = filteredTotal.value
  const countLabel = (count: number) =>
    t('workspace.subcorporaPanel.count', { count: formatNumber(count) }, count)
  if (!hasActiveFilters.value) return countLabel(total)
  if (total === 0) return countLabel(0)
  if (filtered === total) return countLabel(filtered)
  return t(
    'workspace.subcorporaPanel.countOf',
    { count: formatNumber(filtered), total: formatNumber(total) },
    filtered,
  )
})

const filterSummary = computed(() => {
  const parts: string[] = []
  const query = searchQuery.value.trim()
  if (query) parts.push(t('workspace.subcorporaPanel.filterSearch', { query }))
  if (statusFilter.value !== 'all') {
    parts.push(t('workspace.subcorporaPanel.filterStatus', {
      status: statusFilter.value === 'parked'
        ? t('workspace.shared.statusParked')
        : t('workspace.shared.statusArchived'),
    }))
  }
  return parts.join(' · ')
})

function buildSnapshot(status: SubcorpusStatus): SubcorpusSnapshot | null {
  if (!docsetStore.hasActiveDocset || !docsetStore.activeDocsetId) return null
  // The ORIGIN must follow how the active docset was actually built, NOT the
  // current search box. A metadata/filter docset persists as {type:'filter'};
  // only a search-built docset persists as {type:'query'} with its real query.
  // Baking queryStore.term in unconditionally conflated a stale unrelated search
  // term into a metadata scope (683 docs shown → 0 persisted; SUBC-01).
  const origin = docsetStore.activeDocsetOrigin
  const builtQuery = origin?.kind === 'search' ? origin.query.trim() : ''
  return subcorporaStore.createSnapshot({
    name: builtQuery
      ? t('workspace.subcorporaPanel.defaultNameQuery', { query: builtQuery })
      : t('workspace.subcorporaPanel.defaultNameDate', { date: formatDate(new Date()) }),
    status,
    corpus: activeCorpus.value,
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
    origin: builtQuery ? { type: 'query', query: builtQuery } : { type: 'filter' },
    metadataSchemaHash: docsetStore.metaSchemaHash ?? undefined,
    resolution: {
      status: docsetStore.activeScopeStale ? 'stale' : 'fresh',
      stale: docsetStore.activeScopeStale,
      resolvedAt: docsetStore.activeScopeResolvedAt ?? Date.now(),
      message: docsetStore.activeScopeWarning ?? undefined,
    },
  })
}

function openNameModal(status: SubcorpusStatus) {
  // Name suggestion must also follow the build origin, not the stale search box.
  const origin = docsetStore.activeDocsetOrigin
  const term = origin?.kind === 'search' ? origin.query.trim() : ''
  nameStatus.value = status
  nameDraft.value = subcorporaStore.suggestName({
    term,
    corpus: activeCorpus.value,
    filters: docsetStore.filters,
    includeAi: docsetStore.includeAi,
    includeHuman: docsetStore.includeHuman,
    filterSpec: docsetStore.activeFilterSpec,
  })
  nameModalOpen.value = true
}

function resetFilters() {
  searchQuery.value = ''
  statusFilter.value = 'all'
  void nextTick(() => {
    searchInput.value?.focus()
  })
}

function clearSearch() {
  searchQuery.value = ''
  void nextTick(() => {
    searchInput.value?.focus()
  })
}

async function resolvePendingSnapshotStats() {
  if (!canResolveSubcorpora.value || isResolvingSnapshotStats.value) return
  isResolvingSnapshotStats.value = true
  try {
    await subcorporaStore.resolveStats()
  } finally {
    isResolvingSnapshotStats.value = false
  }
}

function parkActive() {
  if (!docsetStore.hasActiveDocset) return
  if (!canSaveSubcorpora.value) {
    uiStore.showToast(saveSubcorporaBlockReason.value ?? t('workspace.subcorporaPanel.saveNotEnabledSession'), 'warning')
    return
  }
  openNameModal('parked')
}

function archiveActive() {
  if (!docsetStore.hasActiveDocset) return
  if (!canSaveSubcorpora.value) {
    uiStore.showToast(saveSubcorporaBlockReason.value ?? t('workspace.subcorporaPanel.saveNotEnabledSession'), 'warning')
    return
  }
  openNameModal('archived')
}

function confirmName() {
  const snapshot = buildSnapshot(nameStatus.value)
  if (!snapshot) return
  snapshot.name = nameDraft.value.trim() || snapshot.name
  if (!subcorporaStore.add(snapshot)) {
    uiStore.showToast(subcorporaStore.error ?? t('workspace.subcorporaPanel.saveFailed'), 'warning')
    return
  }
  if (nameStatus.value === 'archived') {
    docsetStore.resetDocset()
  }
  nameModalOpen.value = false
}

function openRename(snapshot: SubcorpusSnapshot) {
  if (!canRenameSubcorpora.value) {
    uiStore.showToast(renameSubcorporaBlockReason.value, 'warning')
    return
  }
  renameTargetId.value = snapshot.id
  renameDraft.value = snapshot.name
  renameModalOpen.value = true
}

function duplicateSnapshot(snapshot: SubcorpusSnapshot) {
  const baseName = snapshot.name.trim()
  // New names follow the interface language, stored names are not renamed.
  const nextName = baseName.endsWith(t('workspace.subcorporaPanel.copySuffix'))
    ? `${baseName} 2`
    : t('workspace.subcorporaPanel.copyName', { name: baseName })
  const clone = subcorporaStore.createSnapshot({
    name: nextName,
    status: snapshot.status,
    corpus: snapshot.corpus,
    docsetId: snapshot.docsetId,
    stats: { ...snapshot.stats },
    filters: {
      prompting_method: [...snapshot.filters.prompting_method],
      model: [...snapshot.filters.model],
      register: [...snapshot.filters.register],
      source: [...snapshot.filters.source],
    },
    filterSpec: snapshotFilterSpec(snapshot),
    includeAi: snapshot.includeAi,
    includeHuman: snapshot.includeHuman,
    origin: { ...snapshot.origin },
    metadataSchemaHash: snapshot.metadataSchemaHash,
    resolution: snapshot.resolution ? { ...snapshot.resolution } : undefined,
  })
  if (!subcorporaStore.add(clone)) {
    uiStore.showToast(subcorporaStore.error ?? t('workspace.subcorporaPanel.duplicateFailed'), 'warning')
    return
  }
  uiStore.showToast(t('workspace.subcorporaPanel.duplicated'), 'success', 2000)
}

function confirmRename() {
  if (!renameTargetId.value) return
  const nextName = renameDraft.value.trim()
  if (!nextName) return
  if (!canRenameSubcorpora.value) {
    uiStore.showToast(renameSubcorporaBlockReason.value, 'warning')
    return
  }
  if (!subcorporaStore.update(renameTargetId.value, { name: nextName })) {
    uiStore.showToast(subcorporaStore.error ?? t('workspace.subcorporaPanel.renameFailed'), 'warning')
    return
  }
  renameModalOpen.value = false
}

function isActiveSnapshot(snapshot: SubcorpusSnapshot): boolean {
  return (
    !!snapshot.docsetId &&
    snapshot.corpus === docsetStore.activeCorpus &&
    docsetStore.activeDocsetId === snapshot.docsetId
  )
}

function canActivateSnapshot(snapshot: SubcorpusSnapshot): boolean {
  return !isActiveSnapshot(snapshot) && canResolveSubcorpora.value
}

function activationTitle(snapshot: SubcorpusSnapshot): string {
  if (isActiveSnapshot(snapshot)) return t('workspace.subcorporaPanel.alreadyActive')
  if (!canResolveSubcorpora.value) {
    return resolveSubcorporaBlockReason.value ?? t('workspace.subcorporaPanel.resolveNotEnabled')
  }
  return snapshot.corpus === activeCorpus.value
    ? t('workspace.subcorporaPanel.activate')
    : t('workspace.subcorporaPanel.activateSwitch', { corpus: snapshot.corpus })
}

async function activateSnapshot(snapshot: SubcorpusSnapshot) {
  if (!canResolveSubcorpora.value) {
    uiStore.showToast(resolveSubcorporaBlockReason.value ?? t('workspace.subcorporaPanel.resolveNotEnabledSession'), 'warning')
    return
  }
  await docsetStore.applySnapshot({
    corpus: snapshot.corpus,
    docsetId: snapshot.docsetId ?? '',
    name: subcorporaStore.durableNameForSnapshot(snapshot),
    filterSpec: snapshot.filterSpec,
    metadataSchemaHash: snapshot.metadataSchemaHash,
    stats: {
      docCount: snapshot.stats.docCount,
      hitDocCount: 0,
      refDocCount: snapshot.stats.refDocCount,
      tokenCount: snapshot.stats.tokenCount,
    },
    filters: snapshot.filters,
    includeAi: snapshot.includeAi,
    includeHuman: snapshot.includeHuman,
    query: snapshot.origin.query,
  })
  if (!docsetStore.activeDocsetId) {
    uiStore.showToast(docsetStore.error ?? t('workspace.subcorporaPanel.activateFailed'), 'warning')
    return
  }
  if (docsetStore.activeDocsetId) {
    subcorporaStore.markResolved(snapshot.id, {
      docsetId: docsetStore.activeDocsetId,
      stats: {
        docCount: docsetStore.stats.docCount,
        tokenCount: docsetStore.stats.tokenCount,
        refDocCount: snapshot.stats.refDocCount,
      },
      statsResolved: true,
      resolution: {
        status: docsetStore.activeScopeStale ? 'stale' : 'fresh',
        stale: docsetStore.activeScopeStale,
        resolvedAt: docsetStore.activeScopeResolvedAt ?? Date.now(),
        message: docsetStore.activeScopeWarning ?? undefined,
      },
    })
  }
  uiStore.closeWorkspace()
}

async function moveSnapshot(snapshot: SubcorpusSnapshot, status: SubcorpusStatus) {
  if (!(await subcorporaStore.move(snapshot.id, status))) {
    uiStore.showToast(subcorporaStore.error ?? t('workspace.subcorporaPanel.moveFailed'), 'warning')
  }
}

async function removeSnapshot(snapshot: SubcorpusSnapshot) {
  if (!settingsStore.confirmDeletion(snapshot.name)) return
  if (!(await subcorporaStore.remove(snapshot.id))) {
    uiStore.showToast(subcorporaStore.error ?? t('workspace.subcorporaPanel.deleteFailed'), 'warning')
  }
}

onMounted(() => {
  subcorporaStore.init()
  void productCapabilities.load()
})

watch(
  () => [props.active, uiStore.workspaceOpen],
  ([active, open]) => {
    if (!active || !open) return
    if (canUseParallel.value) {
      void loadParallelRefs()
    }
  }
)

watch(canUseParallel, (allowed) => {
  if (allowed) return
  parallelRefs.value = []
  parallelSelectedRef.value = null
  alignmentOpen.value = false
  alignmentResult.value = null
  alignmentError.value = null
})

watch(
  () => [props.active, uiStore.workspaceOpen],
  ([active, open]) => {
    if (!active || !open) return
    void nextTick(() => {
      searchInput.value?.focus()
    })
  }
)

watch(
  () => uiStore.workspaceOpen,
  (open) => {
    if (open) return
    searchQuery.value = ''
    statusFilter.value = 'all'
  }
)

watch(
  () => [subcorporaStore.parked.length, subcorporaStore.archived.length],
  ([parkedCount, archivedCount]) => {
    if (statusFilter.value === 'parked' && parkedCount === 0) {
      statusFilter.value = 'all'
    }
    if (statusFilter.value === 'archived' && archivedCount === 0) {
      statusFilter.value = 'all'
    }
  }
)

watch(nameModalOpen, (open) => {
  if (!open) return
  void nextTick(() => {
    nameInput.value?.focus()
  })
})

watch(renameModalOpen, (open) => {
  if (!open) return
  void nextTick(() => {
    renameInput.value?.focus()
  })
})

async function loadParallelRefs() {
  parallelError.value = null
  parallelRefs.value = []
  parallelSelectedRef.value = null
  if (!canLoadParallelGroups.value || !docsetStore.hasActiveDocset || !docsetStore.activeDocsetId) {
    if (docsetStore.hasActiveDocset && parallelBlockReason.value) {
      parallelError.value = parallelBlockReason.value
    }
    return
  }
  isLoadingParallel.value = true
  try {
    const result = await loadParallelGroups({
      corpus: activeCorpus.value,
      docsetId: docsetStore.activeDocsetId,
      includeAllVariants: true,
      limit: 200,
      sort: 'variant_count',
    })
    const refs = (result.groups ?? []).map((g) => g.ref_doc)
    parallelRefs.value = refs
    parallelSelectedRef.value = refs[0] ?? null
  } catch (err) {
    parallelError.value = err instanceof Error ? err.message : t('workspace.subcorporaPanel.parallelGroupsFailed')
  } finally {
    isLoadingParallel.value = false
  }
}

async function openAlignment() {
  if (!canOpenAlignment.value) {
    alignmentError.value = alignmentBlockReason.value ?? t('workspace.subcorporaPanel.alignmentNotEnabledSession')
    return
  }
  if (!parallelSelectedRef.value) return
  alignmentOpen.value = true
  alignmentError.value = null
  alignmentResult.value = null
  isLoadingAlignment.value = true
  try {
    alignmentResult.value = await loadAlignmentRefDoc({
      refDoc: parallelSelectedRef.value,
      corpus: activeCorpus.value,
      windowSentences: 24,
      maxVariants: 6,
    })
  } catch (err) {
    alignmentError.value = err instanceof Error ? err.message : t('workspace.subcorporaPanel.alignmentFailed')
  } finally {
    isLoadingAlignment.value = false
  }
}

function closeAlignment() {
  alignmentOpen.value = false
  alignmentResult.value = null
  alignmentError.value = null
}
</script>

<template>
  <div class="drawer-body">
    <section class="block">
      <div class="toolbar">
        <div class="toolbar-search">
          <div class="search-field" role="search">
            <input
              v-model="searchQuery"
              ref="searchInput"
              type="search"
              class="search-input"
              :placeholder="t('workspace.subcorporaPanel.searchPlaceholder')"
              :aria-label="t('workspace.subcorporaPanel.searchLabel')"
              autocomplete="off"
              spellcheck="false"
              inputmode="search"
              enterkeyhint="search"
              autocapitalize="none"
              @keydown.esc.prevent="clearSearch"
            />
            <button
              v-if="searchQuery"
              class="search-clear"
              type="button"
              :title="t('workspace.shared.clearSearch')"
              :aria-label="t('workspace.shared.clearSearch')"
              @click="clearSearch"
            >
              <X class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        <div class="toolbar-filters">
          <button
            class="filter-btn"
            :class="{ active: statusFilter === 'all' }"
            :disabled="totalSubcorporaCount === 0"
            :title="totalSubcorporaCount === 0 ? t('workspace.subcorporaPanel.noSubcorpora') : t('workspace.subcorporaPanel.allSubcorpora')"
            @click="statusFilter = 'all'"
            type="button"
          >
            {{ t('workspace.shared.filterAll', { count: formatNumber(totalSubcorporaCount) }) }}
          </button>
          <button
            class="filter-btn"
            :class="{ active: statusFilter === 'parked' }"
            :disabled="!subcorporaStore.parked.length"
            @click="statusFilter = 'parked'"
            type="button"
            :title="subcorporaStore.parked.length ? t('workspace.subcorporaPanel.parkedSubcorpora') : t('workspace.subcorporaPanel.noParked')"
          >
            {{ t('workspace.subcorporaPanel.filterParked', { count: formatNumber(subcorporaStore.parked.length) }) }}
          </button>
          <button
            class="filter-btn"
            :class="{ active: statusFilter === 'archived' }"
            :disabled="!subcorporaStore.archived.length"
            @click="statusFilter = 'archived'"
            type="button"
            :title="subcorporaStore.archived.length ? t('workspace.subcorporaPanel.archivedSubcorpora') : t('workspace.subcorporaPanel.noArchived')"
          >
            {{ t('workspace.subcorporaPanel.filterArchived', { count: formatNumber(subcorporaStore.archived.length) }) }}
          </button>
        </div>
        <div class="toolbar-meta">
          <span aria-live="polite">{{ filteredCountLabel }}</span>
          <span v-if="filterSummary" class="toolbar-meta-secondary" :title="filterSummary">
            {{ filterSummary }}
          </span>
          <span v-else class="toolbar-meta-secondary" :title="t('workspace.shared.noFilters')">
            {{ t('workspace.shared.noFilters') }}
          </span>
          <button
            v-if="hasActiveFilters"
            class="filter-reset"
            type="button"
            :title="t('workspace.shared.resetFilters')"
            :aria-label="t('workspace.shared.resetFilters')"
            @click="resetFilters"
          >
            {{ t('workspace.shared.resetFilters') }}
          </button>
          <button
            v-if="unresolvedSnapshotCount"
            class="filter-reset"
            type="button"
            :disabled="!canResolveSubcorpora || isResolvingSnapshotStats"
            :title="!canResolveSubcorpora ? resolveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.resolveNotEnabled') : t('workspace.subcorporaPanel.resolveNow')"
            @click="resolvePendingSnapshotStats"
          >
            <Loader2 v-if="isResolvingSnapshotStats" class="w-3.5 h-3.5 animate-spin" />
            <span>{{ isResolvingSnapshotStats ? t('workspace.subcorporaPanel.resolvingStats') : t('workspace.subcorporaPanel.resolveStats', { count: formatNumber(unresolvedSnapshotCount) }) }}</span>
          </button>
        </div>
      </div>

      <div class="block-head">
        <div class="block-title">{{ t('workspace.subcorporaPanel.activeScope') }}</div>
        <div class="block-actions">
          <button
            class="chip-btn"
            :disabled="!activeHasDocset || !canSaveSubcorpora"
            :title="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.saveNotEnabled') : t('workspace.subcorporaPanel.parkActive')"
            @click="parkActive"
          >
            <PauseCircle class="w-4 h-4" />
            {{ t('workspace.subcorporaPanel.park') }}
          </button>
          <button
            class="chip-btn chip-danger"
            :disabled="!activeHasDocset || !canSaveSubcorpora"
            :title="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.saveNotEnabled') : t('workspace.subcorporaPanel.archiveActive')"
            @click="archiveActive"
          >
            <Archive class="w-4 h-4" />
            {{ t('workspace.subcorporaPanel.archive') }}
          </button>
        </div>
      </div>

      <div class="scope-card">
        <div class="scope-row">
          <span class="scope-badge" :class="{ active: activeHasDocset }">
            {{ activeHasDocset ? t('workspace.shared.subcorpus') : t('workspace.shared.wholeCorpus') }}
          </span>
          <span class="scope-meta">{{ t('workspace.shared.corpus', { corpus: activeCorpus }) }}</span>
          <span
            v-if="activeSnapshot"
            class="scope-status"
            :class="`status-${activeSnapshot.status}`"
          >
            {{ formatStatus(activeSnapshot.status) }}
          </span>
        </div>
        <div class="scope-stats">
          <template v-if="activeHasDocset && showsRefCount(activeCorpus, activeStats.refs)">
            {{ t('workspace.subcorporaPanel.activeStats', {
              docs: formatNumber(activeStats.docs),
              tokens: formatNumber(activeStats.tokens),
              refs: formatNumber(activeStats.refs),
            }) }}
          </template>
          <template v-else-if="activeHasDocset">
            {{ t('workspace.subcorporaPanel.activeStatsNoRefs', {
              docs: formatNumber(activeStats.docs),
              tokens: formatNumber(activeStats.tokens),
            }) }}
          </template>
          <template v-else>
            {{ t('workspace.subcorporaPanel.wholeCorpusStats', { tokens: formatNumber(activeStats.tokens) }) }}
          </template>
        </div>
        <div class="scope-origin">{{ originText }}</div>
        <div class="scope-summary">
          <span class="summary-label">{{ t('workspace.subcorporaPanel.structure') }}</span>
          <span>{{ docsetStore.summaryParts.join(' · ') || t('workspace.shared.noFilters') }}</span>
        </div>
        <div v-if="activeScopeWarning" class="scope-warning" role="alert">
          <AlertTriangle class="w-4 h-4" />
          <span>{{ activeScopeWarning }}</span>
        </div>
        <div v-if="docsetStore.activeScopeResolvedAt" class="scope-evidence">
          {{ t('workspace.subcorporaPanel.resolveCheck', { time: formatResolvedAt(docsetStore.activeScopeResolvedAt) }) }}
        </div>
        <div v-if="docsetStore.activeDocsetId" class="scope-id">
          {{ t('workspace.shared.docsetId', { id: docsetStore.activeDocsetId.slice(0, 8) }) }}
        </div>
        <div v-if="canUseParallel && parallelRefs.length" class="scope-parallel">
          <span class="scope-badge active">{{ t('workspace.subcorporaPanel.parallelAvailable') }}</span>
          <span class="scope-meta">{{ t('workspace.subcorporaPanel.refDocCount', { count: formatNumber(parallelRefs.length) }, parallelRefs.length) }}</span>
        </div>
      </div>

      <div v-if="showParallelPanel" class="parallel-panel">
        <div class="panel-title">
          <Layers class="w-4 h-4" />
          <span>{{ t('workspace.subcorporaPanel.parallelView') }}</span>
        </div>
        <div v-if="!canLoadParallelGroups" class="panel-hint panel-hint-error" role="status" aria-live="polite">
          <span>{{ parallelBlockReason ?? t('workspace.subcorporaPanel.parallelNotEnabled') }}</span>
        </div>
        <div v-else-if="isLoadingParallel" class="panel-hint panel-hint-loading" role="status" aria-live="polite">
          <Loader2 class="w-4 h-4 animate-spin" />
          <span>{{ t('workspace.subcorporaPanel.loadingRefDocs') }}</span>
        </div>
        <div v-else-if="parallelError" class="panel-hint panel-hint-error" role="alert">
          <span>{{ parallelError }}</span>
          <button class="panel-action" type="button" @click="loadParallelRefs">
            {{ t('workspace.subcorporaPanel.reload') }}
          </button>
        </div>
        <div v-else-if="!parallelRefs.length" class="panel-hint" role="status" aria-live="polite">
          {{ t('workspace.subcorporaPanel.noParallelCorpus') }}
        </div>
        <div v-else class="panel-controls">
          <label class="panel-label" for="parallelRefSelect">{{ t('workspace.subcorporaPanel.refDoc') }}</label>
          <select
            v-model.number="parallelSelectedRef"
            class="panel-select"
            id="parallelRefSelect"
            :disabled="isLoadingParallel || !parallelRefs.length"
          >
            <option v-for="ref in parallelRefs" :key="`ref-${ref}`" :value="ref">
              #{{ ref }}
            </option>
          </select>
          <button
            class="chip-btn"
            type="button"
            :disabled="!parallelSelectedRef || isLoadingAlignment || !canOpenAlignment"
            :title="!canOpenAlignment ? alignmentBlockReason ?? t('workspace.subcorporaPanel.alignmentNotEnabled') : (isLoadingAlignment ? t('workspace.subcorporaPanel.alignmentComputing') : (!parallelSelectedRef ? t('workspace.subcorporaPanel.pickReference') : t('workspace.subcorporaPanel.showAlignment')))"
            @click="openAlignment"
          >
            <Loader2 v-if="isLoadingAlignment" class="w-4 h-4 animate-spin" />
            <span>{{ isLoadingAlignment ? t('workspace.subcorporaPanel.loadingAlignment') : t('workspace.subcorporaPanel.showAlignment') }}</span>
          </button>
        </div>
      </div>
    </section>

      <section v-if="showParked" class="block">
        <div class="block-head">
          <div class="block-title">
            {{ t('workspace.shared.statusParked') }}
            <span class="block-count">{{ filteredParked.length }}</span>
          </div>
        </div>
        <div v-if="filteredParked.length" class="list">
        <div
          v-for="snapshot in filteredParked"
          :key="snapshot.id"
          class="snapshot-card"
          :class="{ active: isActiveSnapshot(snapshot) }"
        >
          <div class="snapshot-head">
            <div class="snapshot-title">
              <span :title="snapshot.name">{{ snapshot.name }}</span>
              <span class="snapshot-status" :class="`status-${snapshot.status}`">
                {{ formatStatus(snapshot.status) }}
              </span>
              <span
                class="snapshot-status"
                :class="snapshotResolutionClass(snapshot)"
                :title="snapshotResolutionTitle(snapshot)"
              >
                {{ snapshotResolutionLabel(snapshot) }}
              </span>
              <span v-if="isActiveSnapshot(snapshot)" class="snapshot-badge">{{ t('workspace.subcorporaPanel.active') }}</span>
            </div>
            <div class="snapshot-actions">
              <button
                class="icon-btn"
                :disabled="!canActivateSnapshot(snapshot)"
                :title="activationTitle(snapshot)"
                :aria-label="activationTitle(snapshot)"
                @click="activateSnapshot(snapshot)"
              >
                <Play class="w-4 h-4" />
              </button>
              <button
                class="icon-btn"
                :disabled="!canRenameSubcorpora"
                :title="!canRenameSubcorpora ? renameSubcorporaBlockReason : t('workspace.subcorporaPanel.rename')"
                :aria-label="!canRenameSubcorpora ? renameSubcorporaBlockReason : t('workspace.subcorporaPanel.rename')"
                @click="openRename(snapshot)"
              >
                <Edit3 class="w-4 h-4" />
              </button>
              <button
                class="icon-btn"
                :disabled="!canSaveSubcorpora"
                :title="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.duplicateNotEnabled') : t('workspace.subcorporaPanel.duplicate')"
                :aria-label="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.duplicateNotEnabled') : t('workspace.subcorporaPanel.duplicate')"
                @click="duplicateSnapshot(snapshot)"
              >
                <Copy class="w-4 h-4" />
              </button>
              <button
                class="icon-btn"
                :disabled="!canSaveSubcorpora || !canDeleteSubcorpora"
                :title="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.archiveNotEnabled') : (!canDeleteSubcorpora ? deleteSubcorporaBlockReason ?? t('workspace.subcorporaPanel.keyChangeNotEnabled') : t('workspace.subcorporaPanel.moveToArchive'))"
                :aria-label="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.archiveNotEnabled') : (!canDeleteSubcorpora ? deleteSubcorporaBlockReason ?? t('workspace.subcorporaPanel.keyChangeNotEnabled') : t('workspace.subcorporaPanel.moveToArchive'))"
                @click="moveSnapshot(snapshot, 'archived')"
              >
                <Archive class="w-4 h-4" />
              </button>
              <button
                class="icon-btn danger"
                :disabled="!canDeleteSubcorpora"
                :title="!canDeleteSubcorpora ? deleteSubcorporaBlockReason ?? t('workspace.subcorporaPanel.deleteNotEnabled') : t('workspace.subcorporaPanel.delete')"
                :aria-label="!canDeleteSubcorpora ? deleteSubcorporaBlockReason ?? t('workspace.subcorporaPanel.deleteNotEnabled') : t('workspace.subcorporaPanel.delete')"
                @click="removeSnapshot(snapshot)"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
          <div class="snapshot-meta">
            {{ snapshotStatsLabel(snapshot) }} ·
            {{ t('workspace.shared.corpus', { corpus: snapshot.corpus }) }}
          </div>
          <div class="snapshot-origin">
            {{ t('workspace.subcorporaPanel.snapshotOrigin', { origin: formatOrigin(snapshot.origin) }) }}
          </div>
          <div v-if="snapshot.resolution?.message" class="snapshot-warning">
            <AlertTriangle class="w-3.5 h-3.5" />
            <span>{{ snapshot.resolution.message }}</span>
          </div>
          <div class="snapshot-foot">
            <CalendarClock class="w-4 h-4" />
            <span>{{ formatDate(snapshot.createdAt) }}</span>
            <span v-if="snapshot.resolution?.resolvedAt">
              · {{ t('workspace.shared.checkedAt', { time: formatResolvedAt(snapshot.resolution.resolvedAt) }) }}
            </span>
          </div>
          <div class="snapshot-tags">
            <FilterSpecChips
              :spec="snapshotFilterSpec(snapshot)"
              :empty-label="t('workspace.shared.wholeCorpus')"
              dense
            />
            <span v-if="pairSideTag(snapshot)" class="tag">{{ pairSideTag(snapshot) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-note" role="status" aria-live="polite">
        <span>{{ parkedEmptyMessage }}</span>
        <span v-if="filterSummary" class="empty-hint" :title="filterSummary">
          {{ filterSummary }}
        </span>
        <button
          v-if="hasActiveFilters"
          class="empty-reset"
          type="button"
          :title="t('workspace.shared.resetFilters')"
          :aria-label="t('workspace.shared.resetFilters')"
          @click="resetFilters"
        >
          {{ t('workspace.shared.resetFilters') }}
        </button>
      </div>
    </section>

    <section v-if="showArchived" class="block">
      <div class="block-head">
        <div class="block-title">
          {{ t('workspace.shared.statusArchived') }}
          <span class="block-count">{{ filteredArchived.length }}</span>
        </div>
      </div>
      <div v-if="filteredArchived.length" class="list">
        <div
          v-for="snapshot in filteredArchived"
          :key="snapshot.id"
          class="snapshot-card"
          :class="{ active: isActiveSnapshot(snapshot) }"
        >
          <div class="snapshot-head">
            <div class="snapshot-title">
              <span :title="snapshot.name">{{ snapshot.name }}</span>
              <span class="snapshot-status" :class="`status-${snapshot.status}`">
                {{ formatStatus(snapshot.status) }}
              </span>
              <span
                class="snapshot-status"
                :class="snapshotResolutionClass(snapshot)"
                :title="snapshotResolutionTitle(snapshot)"
              >
                {{ snapshotResolutionLabel(snapshot) }}
              </span>
              <span v-if="isActiveSnapshot(snapshot)" class="snapshot-badge">{{ t('workspace.subcorporaPanel.active') }}</span>
            </div>
            <div class="snapshot-actions">
              <button
                class="icon-btn"
                :disabled="!canActivateSnapshot(snapshot)"
                :title="activationTitle(snapshot)"
                :aria-label="activationTitle(snapshot)"
                @click="activateSnapshot(snapshot)"
              >
                <Play class="w-4 h-4" />
              </button>
              <button
                class="icon-btn"
                :disabled="!canRenameSubcorpora"
                :title="!canRenameSubcorpora ? renameSubcorporaBlockReason : t('workspace.subcorporaPanel.rename')"
                :aria-label="!canRenameSubcorpora ? renameSubcorporaBlockReason : t('workspace.subcorporaPanel.rename')"
                @click="openRename(snapshot)"
              >
                <Edit3 class="w-4 h-4" />
              </button>
              <button
                class="icon-btn"
                :disabled="!canSaveSubcorpora"
                :title="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.duplicateNotEnabled') : t('workspace.subcorporaPanel.duplicate')"
                :aria-label="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.duplicateNotEnabled') : t('workspace.subcorporaPanel.duplicate')"
                @click="duplicateSnapshot(snapshot)"
              >
                <Copy class="w-4 h-4" />
              </button>
              <button
                class="icon-btn danger"
                :disabled="!canDeleteSubcorpora"
                :title="!canDeleteSubcorpora ? deleteSubcorporaBlockReason ?? t('workspace.subcorporaPanel.deleteNotEnabled') : t('workspace.subcorporaPanel.delete')"
                :aria-label="!canDeleteSubcorpora ? deleteSubcorporaBlockReason ?? t('workspace.subcorporaPanel.deleteNotEnabled') : t('workspace.subcorporaPanel.delete')"
                @click="removeSnapshot(snapshot)"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
          <div class="snapshot-meta">
            {{ snapshotStatsLabel(snapshot) }} ·
            {{ t('workspace.shared.corpus', { corpus: snapshot.corpus }) }}
          </div>
          <div class="snapshot-origin">
            {{ t('workspace.subcorporaPanel.snapshotOrigin', { origin: formatOrigin(snapshot.origin) }) }}
          </div>
          <div v-if="snapshot.resolution?.message" class="snapshot-warning">
            <AlertTriangle class="w-3.5 h-3.5" />
            <span>{{ snapshot.resolution.message }}</span>
          </div>
          <div class="snapshot-foot">
            <CalendarClock class="w-4 h-4" />
            <span>{{ formatDate(snapshot.createdAt) }}</span>
            <span v-if="snapshot.resolution?.resolvedAt">
              · {{ t('workspace.shared.checkedAt', { time: formatResolvedAt(snapshot.resolution.resolvedAt) }) }}
            </span>
          </div>
          <div class="snapshot-tags">
            <FilterSpecChips
              :spec="snapshotFilterSpec(snapshot)"
              :empty-label="t('workspace.shared.wholeCorpus')"
              dense
            />
            <span v-if="pairSideTag(snapshot)" class="tag">{{ pairSideTag(snapshot) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-note" role="status" aria-live="polite">
        <span>{{ archivedEmptyMessage }}</span>
        <span v-if="filterSummary" class="empty-hint" :title="filterSummary">
          {{ filterSummary }}
        </span>
        <button
          v-if="hasActiveFilters"
          class="empty-reset"
          type="button"
          :title="t('workspace.shared.resetFilters')"
          :aria-label="t('workspace.shared.resetFilters')"
          @click="resetFilters"
        >
          {{ t('workspace.shared.resetFilters') }}
        </button>
      </div>
    </section>
  </div>

  <Modal
    v-model="nameModalOpen"
    :title="t('workspace.subcorporaPanel.nameTitle')"
    :description="t('workspace.subcorporaPanel.nameDescription')"
  >
    <div class="name-modal">
      <label class="name-label" for="subcorpusNameInput">{{ t('workspace.subcorporaPanel.nameLabel') }}</label>
      <input
        v-model="nameDraft"
        ref="nameInput"
        class="name-input"
        type="text"
        id="subcorpusNameInput"
        autocomplete="off"
        maxlength="120"
        @keydown.enter.prevent="confirmName"
        @keydown.esc.prevent="nameModalOpen = false"
      />
      <div class="name-actions">
        <Button variant="ghost" size="sm" @click="nameModalOpen = false">
          {{ t('workspace.subcorporaPanel.cancel') }}
        </Button>
        <Button
          variant="primary"
          size="sm"
          :disabled="!canSaveName"
          :title="!canSaveSubcorpora ? saveSubcorporaBlockReason ?? t('workspace.subcorporaPanel.saveNotEnabled') : t('workspace.subcorporaPanel.save')"
          @click="confirmName"
        >
          {{ t('workspace.subcorporaPanel.save') }}
        </Button>
      </div>
    </div>
  </Modal>

  <Modal
    v-model="renameModalOpen"
    :title="t('workspace.subcorporaPanel.rename')"
    :description="t('workspace.subcorporaPanel.renameDescription')"
  >
    <div class="name-modal">
      <label class="name-label" for="subcorpusRenameInput">{{ t('workspace.subcorporaPanel.nameLabel') }}</label>
      <input
        v-model="renameDraft"
        ref="renameInput"
        class="name-input"
        type="text"
        id="subcorpusRenameInput"
        autocomplete="off"
        maxlength="120"
        @keydown.enter.prevent="confirmRename"
        @keydown.esc.prevent="renameModalOpen = false"
      />
      <div class="name-actions">
        <Button variant="ghost" size="sm" @click="renameModalOpen = false">
          {{ t('workspace.subcorporaPanel.cancel') }}
        </Button>
        <Button
          variant="primary"
          size="sm"
          :disabled="!canSaveRename"
          :title="!canRenameSubcorpora ? renameSubcorporaBlockReason : t('workspace.subcorporaPanel.save')"
          @click="confirmRename"
        >
          {{ t('workspace.subcorporaPanel.save') }}
        </Button>
      </div>
    </div>
  </Modal>

  <Modal
    v-model="alignmentOpen"
    size="xl"
    :title="t('workspace.subcorporaPanel.compareTitle')"
    :description="t('workspace.subcorporaPanel.compareDescription')"
    @close="closeAlignment"
  >
    <div v-if="isLoadingAlignment" class="panel-hint panel-hint-loading" role="status" aria-live="polite">
      <Loader2 class="w-4 h-4 animate-spin" />
      <span>{{ t('workspace.subcorporaPanel.loadingVariants') }}</span>
    </div>
    <div v-else-if="alignmentError" class="panel-hint panel-hint-error" role="alert">
      <span>{{ alignmentError }}</span>
      <button class="panel-action" type="button" @click="openAlignment">
        {{ t('workspace.subcorporaPanel.reload') }}
      </button>
    </div>
    <AlignmentComparison v-else-if="alignmentResult" :result="alignmentResult" />
    <div v-else class="panel-hint">
      {{ t('workspace.subcorporaPanel.noAlignmentData') }}
    </div>
  </Modal>
</template>

<style scoped>
@reference "../../style.css";

.drawer-body {
  @apply flex flex-col gap-6;
}

.block {
  @apply flex flex-col gap-3;
}

.toolbar {
  @apply flex flex-col gap-3;
  @apply sm:flex-row sm:flex-wrap sm:items-center sm:justify-between;
}

/* Keep the search field readable when filter chips and counters share the row. */
.toolbar-search {
  @apply flex-1 sm:min-w-[16rem];
}

.toolbar-meta {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  @apply flex flex-wrap items-center gap-2;
  @apply self-end;
}

.toolbar-meta-secondary {
  @apply text-[11px] text-neutral-400 dark:text-neutral-500;
}

.search-field {
  @apply relative;
}

.search-input {
  @apply w-full px-3 py-2 rounded-lg text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
  @apply pr-9;
}

.search-clear {
  @apply absolute right-2 top-1/2 -translate-y-1/2;
  @apply p-1 rounded-md;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
}

.toolbar-filters {
  @apply flex flex-wrap items-center gap-2;
}

.filter-btn {
  @apply px-2.5 py-1 rounded-full text-xs font-medium;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
  @apply transition-colors;
}

.filter-btn:disabled {
  @apply opacity-60 cursor-not-allowed;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.filter-btn.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.block-head {
  @apply flex items-center justify-between;
}

.block-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.block-count {
  @apply ml-2 px-2 py-0.5 rounded-full text-[11px] font-medium;
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.block-actions {
  @apply flex items-center gap-2;
}

.chip-btn {
  @apply inline-flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-700 dark:text-neutral-200;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
  @apply transition-colors;
}

.chip-danger {
  @apply text-error-600 dark:text-error-400;
}

.scope-card {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply p-4 space-y-2;
}

.scope-row {
  @apply flex items-center gap-2;
}

.scope-badge {
  @apply px-2 py-0.5 rounded-full text-xs font-medium;
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-badge.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.scope-status {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-status.status-parked {
  @apply bg-amber-100 text-amber-700;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.scope-status.status-archived {
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-meta {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.scope-stats,
.scope-origin,
.scope-summary,
.scope-id,
.scope-evidence {
  @apply text-xs text-neutral-600 dark:text-neutral-400;
}

.scope-warning,
.snapshot-warning {
  @apply flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2;
  @apply text-xs text-warning-800 dark:border-warning-900/60 dark:bg-warning-900/20 dark:text-warning-200;
}

.scope-parallel {
  @apply flex items-center gap-2;
}

.parallel-panel {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply p-3 space-y-2;
}

.panel-title {
  @apply flex items-center gap-2 text-sm font-medium text-neutral-800 dark:text-neutral-100;
}

.panel-controls {
  @apply flex flex-col gap-2;
}

.panel-label {
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-400;
}

.panel-select {
  @apply w-full px-2 py-1.5 rounded-lg text-sm;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.panel-select:disabled {
  @apply opacity-60 cursor-not-allowed;
}

.panel-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.panel-hint-loading {
  @apply flex items-center gap-2;
}

.panel-hint-error {
  @apply flex flex-col gap-2;
}

.panel-action {
  @apply inline-flex items-center justify-center;
  @apply px-2.5 py-1 rounded-md text-xs;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
}

.summary-label {
  @apply mr-1 font-medium text-neutral-700 dark:text-neutral-300;
}

.list {
  @apply flex flex-col gap-3;
}

.snapshot-card {
  @apply rounded-xl border border-neutral-200/80 dark:border-neutral-700/80;
  @apply bg-white dark:bg-neutral-900;
  @apply p-3 space-y-2;
  @apply transition-shadow;
  @apply hover:shadow-sm;
}

.snapshot-card.active {
  @apply ring-1 ring-primary-300/60 dark:ring-primary-500/40;
  @apply border-primary-200/70 dark:border-primary-500/40;
}

.snapshot-head {
  @apply flex items-center justify-between gap-2;
}

.snapshot-title {
  @apply flex items-center gap-2 text-[15px] font-semibold text-neutral-800 dark:text-neutral-100;
  @apply break-words leading-snug;
}

.snapshot-badge {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.snapshot-status {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.snapshot-status.status-parked {
  @apply bg-amber-100 text-amber-700;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.snapshot-status.status-archived {
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.snapshot-status.status-resolution {
  @apply bg-success-100 text-success-700;
  @apply dark:bg-success-900/30 dark:text-success-200;
}

.snapshot-status.status-stale {
  @apply bg-warning-100 text-warning-800;
  @apply dark:bg-warning-900/40 dark:text-warning-200;
}

.snapshot-status.status-error {
  @apply bg-error-100 text-error-700;
  @apply dark:bg-error-900/40 dark:text-error-200;
}

.snapshot-status.status-unresolved {
  @apply bg-neutral-100 text-neutral-500;
  @apply dark:bg-neutral-800 dark:text-neutral-400;
}

.snapshot-actions {
  @apply flex items-center gap-1;
}

.icon-btn {
  @apply p-1.5 rounded-md;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply disabled:opacity-40 disabled:cursor-not-allowed;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
}

.icon-btn.danger {
  @apply text-error-600 dark:text-error-400;
}

.snapshot-meta,
.snapshot-origin {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
  @apply leading-snug;
}

.snapshot-foot {
  @apply flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400;
  @apply leading-snug;
}

.snapshot-tags {
  @apply flex flex-wrap gap-1.5;
}

.tag {
  @apply px-2 py-0.5 rounded-full text-[10px] font-medium;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply border border-transparent;
  @apply max-w-[240px] truncate;
}

.empty-note {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  @apply flex flex-col gap-2;
  @apply items-start;
}

.empty-reset {
  @apply text-[11px] text-primary-600 dark:text-primary-300;
  @apply hover:underline self-start;
}

.empty-hint {
  @apply text-[11px] text-neutral-400 dark:text-neutral-500;
}

.filter-reset {
  @apply text-[11px] text-primary-600 dark:text-primary-300;
  @apply hover:underline;
}

.name-modal {
  @apply flex flex-col gap-3;
}

.name-label {
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-400;
}

.name-input {
  @apply w-full px-3 py-2 rounded-lg text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.name-actions {
  @apply flex items-center justify-end gap-2;
}
</style>
