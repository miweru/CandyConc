<script setup lang="ts">
/**
 * SubcorpusPanel - Lightweight docset/subkorpus controls
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDocsetStore, useQueryStore, useCorpusCapabilitiesStore } from '@/stores'
import { PAIRED_TREE_FIELDS } from '@/stores/docset'
import type { MetaFieldDescriptor } from '@/stores/docset'
import type { FilterSpec } from '@/api/client'
import { AlertTriangle, Check, CheckCircle2, Filter, RefreshCw, RotateCcw } from 'lucide-vue-next'
import FilterField from '@/components/filters/FilterField.vue'
import GenericFilterSpecPanel from '@/components/filters/GenericFilterSpecPanel.vue'
import { describeScopeEvidence } from '@/lib/scopeEvidence'
import { deriveFilterSpecFromLegacy, LEGACY_FILTER_FIELDS } from '@/lib/filterSpec'
import { actionBus } from '@/actions/bus'
import { formatNumber } from '@/i18n/format'
import { pairSideValues } from '@/lib/pairSides'

const props = withDefaults(defineProps<{ variant?: 'inline' | 'drawer' }>(), {
  variant: 'inline',
})

const { t } = useI18n()
const docsetStore = useDocsetStore()
const queryStore = useQueryStore()
const corpusCapabilities = useCorpusCapabilitiesStore()

const isDrawer = computed(() => props.variant === 'drawer')
const isOpen = ref(false)

const registerSelection = ref<string[]>([])
const sourceSelection = ref<string[]>([])
const modelSelection = ref<string[]>([])
const promptingSelection = ref('')
const includeAiLocal = ref(true)
const includeHumanLocal = ref(true)

type TreeField = 'prompting_method' | 'model' | 'register' | 'source'

const treeOptions = ref<Record<TreeField, string[]>>({
  prompting_method: [],
  model: [],
  register: [],
  source: [],
})

const treeCounts = ref<Record<TreeField, Record<string, number>>>({
  prompting_method: {},
  model: {},
  register: {},
  source: {},
})

const isLoadingTree = ref(false)
const treeError = ref<string | null>(null)
const treeRequestId = ref(0)

const bodyOpen = computed(() => (isDrawer.value ? true : isOpen.value))
const metaValuesBlockReason = computed(() => docsetStore.metaValuesAvailability.disabledReason)
const metaCountsBlockReason = computed(() => docsetStore.metaCountsAvailability.disabledReason)
const docsetFromSearchBlockReason = computed(() => docsetStore.docsetFromSearchAvailability.disabledReason)
const docsetFromMetaBlockReason = computed(() => docsetStore.docsetFromMetaAvailability.disabledReason)
const canLoadFilterMetadata = computed(() => docsetStore.canLoadMetaValues)
const canLoadFilterCounts = computed(() => docsetStore.canLoadMetaCounts)
const canApplySearchDocset = computed(() => docsetStore.canBuildDocsetFromSearch)
const canApplyGenericDocset = computed(() => docsetStore.canBuildDocsetFromMeta)

function syncFromStore() {
  registerSelection.value = [...docsetStore.filters.register]
  sourceSelection.value = [...docsetStore.filters.source]
  modelSelection.value = [...docsetStore.filters.model]
  promptingSelection.value = docsetStore.filters.prompting_method[0] ?? ''
  includeAiLocal.value = docsetStore.includeAi
  includeHumanLocal.value = docsetStore.includeHuman
}

watch(
  () => [docsetStore.filters, docsetStore.includeAi, docsetStore.includeHuman] as const,
  () => {
    syncFromStore()
    if (bodyOpen.value) {
      void refreshTreeOptions()
    }
  },
  { deep: true, immediate: true }
)

const hasTerm = computed(() => !!queryStore.term.trim())
const activeCorpus = computed(() => docsetStore.activeCorpus ?? 'default')

// The classic tree only works when every one of its select fields is safely
// enumerable. Other corpora use the schema-driven filter below.
const usePairedTree = computed(
  () => corpusCapabilities.isPaired && docsetStore.hasLegacyMetaFields
)
// The two include switches name the sides the corpus has: human and AI texts
// only where the pairs carry those values, anchor and versions otherwise.
const usesAnchorSides = computed(() => pairSideValues(corpusCapabilities.activeSummary).anchor === 'anchor')

const docsetIdShort = computed(() => {
  const id = docsetStore.activeDocsetId
  return id ? id.slice(0, 8) : ''
})
const scopeEvidence = computed(() => describeScopeEvidence({
  hasActiveDocset: docsetStore.hasActiveDocset,
  isDirty: docsetStore.isDirty,
  activeScopeStale: docsetStore.activeScopeStale,
  activeScopeWarning: docsetStore.activeScopeWarning,
  activeScopeResolvedAt: docsetStore.activeScopeResolvedAt,
}))

const FIELD_LABEL_KEYS: Record<string, string> = {
  prompting_method: 'subcorpus.panel.fieldPrompt',
  model: 'subcorpus.panel.fieldModel',
  register: 'subcorpus.panel.fieldRegister',
  source: 'subcorpus.panel.fieldSource',
}
const pairedTreeFieldsLabel = computed(() =>
  PAIRED_TREE_FIELDS.map((field) => (FIELD_LABEL_KEYS[field] ? t(FIELD_LABEL_KEYS[field]) : field)).join(' · ')
)
// Reference documents exist in paired corpora only. A count above zero is
// shown in any case, the corpus summary may not have loaded yet.
const showRefCount = computed(() => corpusCapabilities.isPaired || docsetStore.stats.refDocCount > 0)
const alignmentWarning = computed(() => {
  if (!includeAiLocal.value || !includeHumanLocal.value) return ''
  if (promptingSelection.value && treeOptions.value.model.length === 0) {
    return t('subcorpus.panel.noModels')
  }
  if (docsetStore.hasActiveDocset && docsetStore.stats.refDocCount === 0) {
    return t('subcorpus.panel.noRefDocs')
  }
  return ''
})

const compatibilityStatus = computed(() => {
  if (!includeAiLocal.value || !includeHumanLocal.value) {
    return { state: 'neutral', text: t('subcorpus.panel.parallelOff') }
  }
  if (alignmentWarning.value) {
    return { state: 'warn', text: alignmentWarning.value }
  }
  return { state: 'ok', text: t('subcorpus.panel.parallelOn') }
})

const treePathLabel = computed(() => {
  const parts: string[] = []
  if (promptingSelection.value) parts.push(t('subcorpus.panel.pathPrompt', { value: promptingSelection.value }))
  if (modelSelection.value.length) {
    const preview = modelSelection.value.slice(0, 2).join(', ')
    const suffix = modelSelection.value.length > 2 ? '…' : ''
    parts.push(t('subcorpus.panel.pathModels', { values: `${preview}${suffix}` }))
  }
  if (registerSelection.value.length) {
    const preview = registerSelection.value.slice(0, 2).join(', ')
    const suffix = registerSelection.value.length > 2 ? '…' : ''
    parts.push(t('subcorpus.panel.pathRegister', { values: `${preview}${suffix}` }))
  }
  if (sourceSelection.value.length) {
    const preview = sourceSelection.value.slice(0, 2).join(', ')
    const suffix = sourceSelection.value.length > 2 ? '…' : ''
    parts.push(t('subcorpus.panel.pathSource', { values: `${preview}${suffix}` }))
  }
  if (!parts.length) return t('subcorpus.panel.pathAll')
  return t('subcorpus.panel.path', { parts: parts.join(' → ') })
})

function optionCount(field: TreeField, value: string): number | null {
  const counts = treeCounts.value[field] ?? {}
  const count = counts[value]
  return typeof count === 'number' ? count : null
}

function setBaseOptions() {
  treeOptions.value = {
    prompting_method: [...docsetStore.metaOptions.prompting_method],
    model: [...docsetStore.metaOptions.model],
    register: [...docsetStore.metaOptions.register],
    source: [...docsetStore.metaOptions.source],
  }
}

function clampSelection(selection: string[], options: string[]): string[] {
  const allowed = new Set(options)
  return selection.filter((value) => allowed.has(value))
}

function buildAiFilters(): Record<string, string | string[]> | undefined {
  if (!includeAiLocal.value) return undefined
  const filters: Record<string, string | string[]> = {}
  if (promptingSelection.value) filters.prompting_method = promptingSelection.value
  if (modelSelection.value.length) filters.model = [...modelSelection.value]
  return Object.keys(filters).length ? filters : undefined
}

async function refreshModelOptions(requestId: number) {
  if (!includeAiLocal.value || !promptingSelection.value) {
    treeOptions.value.model = [...docsetStore.metaOptions.model]
    return
  }
  if (!canLoadFilterMetadata.value) {
    treeError.value = metaValuesBlockReason.value ?? t('subcorpus.panel.valuesBlockedSession')
    return
  }
  const values = await docsetStore.fetchMetaValues({
    fields: ['model'],
    corpus: activeCorpus.value,
    filters: { prompting_method: promptingSelection.value },
  }, {}, t('subcorpus.panel.opModelValues'))
  if (!values) return
  if (requestId !== treeRequestId.value) return
  treeOptions.value.model = [...(values.model ?? [])]
  modelSelection.value = clampSelection(modelSelection.value, treeOptions.value.model)
}

async function refreshRegisterSourceOptions(requestId: number) {
  const aiFilters = buildAiFilters()
  if (!aiFilters) {
    treeOptions.value.register = [...docsetStore.metaOptions.register]
    treeOptions.value.source = [...docsetStore.metaOptions.source]
  } else {
    if (!canLoadFilterMetadata.value) {
      treeError.value = metaValuesBlockReason.value ?? t('subcorpus.panel.valuesBlockedSession')
      return
    }
    const values = await docsetStore.fetchMetaValues({
      fields: ['register', 'source'],
      corpus: activeCorpus.value,
      filters: aiFilters,
    }, {}, t('subcorpus.panel.opRegisterSourceValues'))
    if (!values) return
    if (requestId !== treeRequestId.value) return
    treeOptions.value.register = [...(values.register ?? [])]
    treeOptions.value.source = [...(values.source ?? [])]
  }
  registerSelection.value = clampSelection(registerSelection.value, treeOptions.value.register)
  sourceSelection.value = clampSelection(sourceSelection.value, treeOptions.value.source)
}

async function refreshCounts(requestId: number) {
  if (requestId !== treeRequestId.value) return
  if (!canLoadFilterCounts.value) {
    treeCounts.value = { prompting_method: {}, model: {}, register: {}, source: {} }
    treeError.value = metaCountsBlockReason.value ?? t('subcorpus.panel.countsBlockedSession')
    return
  }
  try {
    const promptCounts = await docsetStore.fetchMetaCounts({
      fields: ['prompting_method'],
      corpus: activeCorpus.value,
    })
    if (!promptCounts) return
    if (requestId !== treeRequestId.value) return
    treeCounts.value.prompting_method = promptCounts.prompting_method ?? {}

    if (includeAiLocal.value) {
      const promptFilters = promptingSelection.value
        ? { prompting_method: promptingSelection.value }
        : undefined
      const modelCounts = await docsetStore.fetchMetaCounts({
        fields: ['model'],
        corpus: activeCorpus.value,
        filters: promptFilters,
      }, {}, t('subcorpus.panel.opModelCounts'))
      if (!modelCounts) return
      if (requestId !== treeRequestId.value) return
      treeCounts.value.model = modelCounts.model ?? {}
    } else {
      treeCounts.value.model = {}
    }

    const rsCounts = await docsetStore.fetchMetaCounts({
      fields: ['register', 'source'],
      corpus: activeCorpus.value,
      filters: buildAiFilters(),
    }, {}, t('subcorpus.panel.opRegisterSourceCounts'))
    if (!rsCounts) return
    if (requestId !== treeRequestId.value) return
    treeCounts.value.register = rsCounts.register ?? {}
    treeCounts.value.source = rsCounts.source ?? {}
  } catch (err) {
    if (requestId !== treeRequestId.value) return
    treeError.value = err instanceof Error ? err.message : t('subcorpus.panel.optionsFailed')
  }
}

async function refreshTreeOptions() {
  if (!bodyOpen.value) return
  const requestId = ++treeRequestId.value
  isLoadingTree.value = true
  treeError.value = null
  try {
    if (!canLoadFilterMetadata.value) {
      treeError.value = metaValuesBlockReason.value ?? t('subcorpus.panel.valuesBlockedSession')
      return
    }
    // Resolve the schema before touching the legacy tree. Otherwise a paired
    // corpus with a high-cardinality `model` field briefly looks unknown and
    // triggers the very large option request the generic flow avoids.
    await docsetStore.loadMetaSchema()
    if (!usePairedTree.value) return
    await docsetStore.loadMetaOptions()
    if (requestId !== treeRequestId.value) return
    setBaseOptions()
    await refreshModelOptions(requestId)
    await refreshRegisterSourceOptions(requestId)
    await refreshCounts(requestId)
  } catch (err) {
    if (requestId !== treeRequestId.value) return
    treeError.value = err instanceof Error ? err.message : t('subcorpus.panel.optionsFailed')
  } finally {
    if (requestId === treeRequestId.value) {
      isLoadingTree.value = false
    }
  }
}

async function handleApply() {
  if (!canApplySearchDocset.value) {
    treeError.value = docsetFromSearchBlockReason.value ?? t('subcorpus.panel.searchDocsetBlockedSession')
    return
  }
  docsetStore.setFilter('register', registerSelection.value)
  docsetStore.setFilter('source', sourceSelection.value)
  docsetStore.setFilter('model', modelSelection.value)
  docsetStore.setFilter(
    'prompting_method',
    promptingSelection.value ? [promptingSelection.value] : []
  )
  docsetStore.setIncludeAi(includeAiLocal.value)
  docsetStore.setIncludeHuman(includeHumanLocal.value)
  const built = await docsetStore.buildDocset(true)
  if (built) await refreshVisibleKwic()
}

async function handleReset() {
  docsetStore.clearFilters()
  genericFilterSpec.value = {}
  syncFromStore()
  // Reset means "back to the whole corpus". Keeping a query-derived docset
  // with empty filters would obscure that fact and leave the visible KWIC stale.
  docsetStore.resetDocset()
  await refreshVisibleKwic()
}

function toggleOpen() {
  if (isDrawer.value) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    void refreshTreeOptions()
  }
}

function handlePromptChange() {
  modelSelection.value = []
  docsetStore.markDirty()
  void refreshTreeOptions()
}

function handleModelChange() {
  docsetStore.markDirty()
  void refreshTreeOptions()
}

function handleRegisterChange() {
  docsetStore.markDirty()
}

function handleSourceChange() {
  docsetStore.markDirty()
}

function handleIncludeToggle() {
  docsetStore.markDirty()
  void refreshTreeOptions()
}

watch(
  () => docsetStore.activeCorpus,
  () => {
    if (bodyOpen.value) {
      void refreshTreeOptions()
    }
  }
)

// ============================================
// Field-agnostic filter mode (generic corpora)
// ============================================

/**
 * The classic paired tree (Prompttyp → Modell → Register/Quelle) only makes
 * sense for paired corpora that actually expose the legacy meta fields. For any
 * other corpus we fall back to a field-agnostic filter built from the corpus
 * meta schema: enum fields → multi-select, numeric/date fields → range controls.
 */
const enumFields = computed<MetaFieldDescriptor[]>(() => docsetStore.enumFields)
const rangeFields = computed<MetaFieldDescriptor[]>(() => docsetStore.rangeFields)
const textFields = computed<MetaFieldDescriptor[]>(() => docsetStore.textFields)
const legacyFilterFieldSet = new Set<string>(LEGACY_FILTER_FIELDS)
const genericEnumFields = computed<MetaFieldDescriptor[]>(() =>
  usePairedTree.value
    ? enumFields.value.filter((field) => !legacyFilterFieldSet.has(field.name))
    : enumFields.value
)
const genericRangeFields = computed<MetaFieldDescriptor[]>(() => rangeFields.value)
const genericTextFields = computed<MetaFieldDescriptor[]>(() =>
  usePairedTree.value
    ? textFields.value.filter((field) => !legacyFilterFieldSet.has(field.name))
    : textFields.value
)
const showGenericFilters = computed(() =>
  !usePairedTree.value
    || genericEnumFields.value.length > 0
    || genericRangeFields.value.length > 0
    || genericTextFields.value.length > 0
)
const genericFieldKey = computed(() => [
  ...genericEnumFields.value.map((field) => `enum:${field.name}`),
  ...genericRangeFields.value.map((field) => `${field.kind}:${field.name}`),
  ...genericTextFields.value.map((field) => `text:${field.name}`),
].join('|'))

// Selections keyed by field name.
const enumOptions = ref<Record<string, string[]>>({})
const genericFilterSpec = ref<FilterSpec>({})
const isLoadingGeneric = ref(false)
const genericError = ref<string | null>(null)
const genericRequestId = ref(0)

async function loadGenericOptions() {
  if (!showGenericFilters.value) return
  const fields = genericEnumFields.value.map((f) => f.name)
  if (!fields.length) {
    enumOptions.value = {}
    return
  }
  const requestId = ++genericRequestId.value
  isLoadingGeneric.value = true
  genericError.value = null
  try {
    if (!canLoadFilterMetadata.value) {
      genericError.value = metaValuesBlockReason.value ?? t('subcorpus.panel.valuesBlockedSession')
      return
    }
    const values = await docsetStore.fetchMetaValues(
      { fields, corpus: activeCorpus.value },
      {},
      t('subcorpus.panel.opGenericValues'),
    )
    if (!values) return
    if (requestId !== genericRequestId.value) return
    const next: Record<string, string[]> = {}
    for (const field of fields) {
      next[field] = [...(values[field] ?? [])].sort()
    }
    enumOptions.value = next
  } catch (err) {
    if (requestId !== genericRequestId.value) return
    genericError.value = err instanceof Error ? err.message : t('subcorpus.panel.optionsFailed')
  } finally {
    if (requestId === genericRequestId.value) isLoadingGeneric.value = false
  }
}

async function refreshGenericOptions() {
  if (!bodyOpen.value) return
  await docsetStore.loadMetaSchema()
  if (showGenericFilters.value) await loadGenericOptions()
}

function buildTreeFilterSpec(): FilterSpec {
  return deriveFilterSpecFromLegacy({
    prompting_method: promptingSelection.value ? [promptingSelection.value] : [],
    model: modelSelection.value,
    register: registerSelection.value,
    source: sourceSelection.value,
  })
}

function buildMetadataFilterSpec(): FilterSpec {
  return {
    ...(usePairedTree.value ? buildTreeFilterSpec() : {}),
    ...genericFilterSpec.value,
  }
}

const hasMetadataFilters = computed(() => Object.keys(buildMetadataFilterSpec()).length > 0)
const primaryApplyDisabled = computed(() => {
  if (docsetStore.isBuildingDocset) return true
  if (!usePairedTree.value) return !canApplyGenericDocset.value || !hasMetadataFilters.value
  return !hasTerm.value || !canApplySearchDocset.value || (!docsetStore.isDirty && docsetStore.hasActiveDocset)
})
const primaryApplyTitle = computed(() => {
  if (!usePairedTree.value) {
    return !canApplyGenericDocset.value
      ? docsetFromMetaBlockReason.value ?? t('subcorpus.panel.metaDocsetBlocked')
      : t('subcorpus.panel.applyMeta')
  }
  if (!hasTerm.value) return t('subcorpus.panel.searchFirst')
  return !canApplySearchDocset.value
    ? docsetFromSearchBlockReason.value ?? t('subcorpus.panel.searchDocsetBlocked')
    : t('subcorpus.panel.applySubcorpus')
})
const primaryApplyLabel = computed(() =>
  usePairedTree.value ? t('subcorpus.panel.apply') : t('subcorpus.panel.applyMetaShort')
)

async function applyGeneric() {
  if (!canApplyGenericDocset.value) {
    genericError.value = docsetFromMetaBlockReason.value ?? t('subcorpus.panel.metaDocsetBlockedSession')
    return
  }
  const built = await docsetStore.buildDocsetFromMeta(buildMetadataFilterSpec())
  if (built) await refreshVisibleKwic()
}

async function refreshVisibleKwic() {
  const term = queryStore.term.trim()
  const docsetId = docsetStore.activeDocsetId
  // A metadata scope can be prepared before the first search. Once a query is
  // visible, applying or resetting scope must immediately refresh that query.
  if (!term || !docsetId) {
    if (term && !docsetStore.hasActiveDocset) {
      await actionBus.dispatch({ type: 'query/execute', payload: { term } })
    }
    return
  }
  const result = await actionBus.dispatch({
    type: 'query/execute',
    payload: { term, docsetId },
  })
  if (!result.success) {
    const message = result.error ?? t('subcorpus.panel.kwicRefreshFailed')
    if (usePairedTree.value) treeError.value = message
    else genericError.value = message
  }
}

function resetGeneric() {
  genericFilterSpec.value = {}
  if (!usePairedTree.value) {
    docsetStore.resetDocset()
  }
}

function genericSpecFromActive(): FilterSpec {
  const spec = docsetStore.activeFilterSpec ?? {}
  if (!usePairedTree.value) return { ...spec }
  return Object.fromEntries(
    Object.entries(spec).filter(([field]) => !legacyFilterFieldSet.has(field))
  )
}

async function handlePrimaryApply() {
  if (!usePairedTree.value) {
    await applyGeneric()
    return
  }
  await handleApply()
}

watch(
  () => [bodyOpen.value, activeCorpus.value, usePairedTree.value, genericFieldKey.value] as const,
  () => {
    void refreshGenericOptions()
  },
  { immediate: true }
)

watch(
  () => [docsetStore.activeFilterSpec, usePairedTree.value] as const,
  () => {
    genericFilterSpec.value = genericSpecFromActive()
  },
  { immediate: true, deep: true }
)
</script>

<template>
  <div class="subcorpus-panel" :class="{ 'is-drawer': isDrawer }" data-onboarding="subcorpus">
    <div class="panel-head" :class="{ 'is-drawer': isDrawer }">
      <button v-if="!isDrawer" class="toggle-btn" type="button" @click="toggleOpen">
        <Filter class="w-4 h-4" />
        <span>{{ t('subcorpus.panel.toggle') }}</span>
        <span v-if="docsetStore.isDirty" class="dirty-dot" />
      </button>
      <div v-else class="panel-title">
        <Filter class="w-4 h-4" />
        <span>{{ t('subcorpus.panel.title') }}</span>
        <span v-if="docsetStore.isDirty" class="dirty-dot-inline" />
      </div>

      <div class="panel-status">
        <span
          class="scope-pill"
          :class="{
            active: docsetStore.hasActiveDocset,
            'scope-pill-warn': scopeEvidence.visible && scopeEvidence.tone === 'warn'
          }"
          :title="scopeEvidence.title"
        >
          {{ docsetStore.scopeLabel }}
        </span>
        <span v-if="docsetStore.hasActiveDocset" class="status-text">
          {{ showRefCount
            ? t('subcorpus.panel.stats', {
              docs: formatNumber(docsetStore.stats.docCount),
              tokens: formatNumber(docsetStore.stats.tokenCount),
              refs: formatNumber(docsetStore.stats.refDocCount),
            })
            : t('subcorpus.panel.statsNoRefs', {
              docs: formatNumber(docsetStore.stats.docCount),
              tokens: formatNumber(docsetStore.stats.tokenCount),
            }) }}
        </span>
        <span v-if="docsetStore.hasActiveDocset && docsetIdShort" class="docset-id">
          #{{ docsetIdShort }}
        </span>
      </div>

      <div class="panel-actions">
        <button
          class="btn"
          type="button"
          :disabled="primaryApplyDisabled"
          :title="primaryApplyTitle"
          @click="handlePrimaryApply"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': docsetStore.isBuildingDocset }" />
          <span>{{ primaryApplyLabel }}</span>
        </button>
        <button class="btn btn-ghost" type="button" @click="handleReset">
          <RotateCcw class="w-4 h-4" />
          <span>{{ t('subcorpus.panel.reset') }}</span>
        </button>
      </div>
    </div>

    <div v-if="bodyOpen" class="panel-body">
      <p class="scope-purpose">
        <template v-if="usePairedTree">
          {{ t('subcorpus.panel.purposePaired') }}
        </template>
        <template v-else>
          {{ t('subcorpus.panel.purposeGeneric') }}
        </template>
      </p>
      <div v-if="docsetStore.summaryParts.length" class="summary">
        {{ docsetStore.summaryParts.join(' · ') }}
      </div>

      <div v-if="usePairedTree" class="required-fields">
        {{ t('subcorpus.panel.coreFilters', { fields: pairedTreeFieldsLabel }) }}
      </div>

      <div v-if="docsetStore.error" class="error">
        {{ docsetStore.error }}
      </div>
      <div v-if="scopeEvidence.warning" class="compatibility-row status-warn">
        <AlertTriangle class="w-4 h-4" />
        <span>{{ scopeEvidence.warning }}</span>
      </div>
      <div v-if="treeError" class="error">
        {{ treeError }}
      </div>
      <div v-if="usePairedTree && !canLoadFilterMetadata" class="compatibility-row status-warn">
        <AlertTriangle class="w-4 h-4" />
        <span>{{ metaValuesBlockReason ?? t('subcorpus.panel.valuesBlocked') }}</span>
      </div>
      <div v-else-if="usePairedTree && !canLoadFilterCounts" class="compatibility-row status-warn">
        <AlertTriangle class="w-4 h-4" />
        <span>{{ metaCountsBlockReason ?? t('subcorpus.panel.countsBlocked') }}</span>
      </div>
      <div v-if="usePairedTree" class="structure-hint">
        {{ t('subcorpus.panel.structure') }}
      </div>
      <div v-if="usePairedTree" class="compatibility-row" :class="`status-${compatibilityStatus.state}`">
        <component
          :is="compatibilityStatus.state === 'warn' ? AlertTriangle : CheckCircle2"
          class="w-4 h-4"
        />
        <span>{{ compatibilityStatus.text }}</span>
      </div>
      <div v-if="usePairedTree && !hasTerm" class="hint">
        {{ t('subcorpus.panel.needsSearch') }}
      </div>
      <div v-else-if="usePairedTree && isLoadingTree" class="hint">
        {{ t('subcorpus.panel.loadingOptions') }}
      </div>

      <div v-if="usePairedTree" class="toggle-row">
        <label class="field checkbox-field">
          <input v-model="includeAiLocal" type="checkbox" @change="handleIncludeToggle" />
          <span>{{ usesAnchorSides ? t('subcorpus.panel.includeVersions') : t('subcorpus.panel.includeAi') }}</span>
        </label>
        <label class="field checkbox-field">
          <input v-model="includeHumanLocal" type="checkbox" @change="handleIncludeToggle" />
          <span>{{ usesAnchorSides ? t('subcorpus.panel.includeAnchors') : t('subcorpus.panel.includeHuman') }}</span>
        </label>
        <span class="tree-path">{{ treePathLabel }}</span>
      </div>

      <div v-if="usePairedTree" class="tree-grid">
        <section class="tree-section">
          <div class="tree-head">
            <span class="tree-step">1</span>
            <div>
              <div class="tree-title">{{ t('subcorpus.panel.promptTitle') }}</div>
              <div class="tree-desc">{{ t('subcorpus.panel.promptDesc') }}</div>
            </div>
          </div>
          <FilterField :label="t('subcorpus.panel.fieldPrompt')">
            <select
              v-model="promptingSelection"
              class="select"
              @change="handlePromptChange"
              :disabled="!includeAiLocal || isLoadingTree || !canLoadFilterMetadata"
            >
              <option value="">{{ t('subcorpus.panel.all') }}</option>
              <option v-for="opt in treeOptions.prompting_method" :key="opt" :value="opt">
                {{ opt }}{{ optionCount('prompting_method', opt) !== null ? ` · ${formatNumber(optionCount('prompting_method', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <div v-if="!promptingSelection" class="tree-hint">
            {{ t('subcorpus.panel.noPrompt') }}
          </div>
        </section>

        <section class="tree-section">
          <div class="tree-head">
            <span class="tree-step">2</span>
            <div>
              <div class="tree-title">{{ t('subcorpus.panel.modelTitle') }}</div>
              <div class="tree-desc">{{ t('subcorpus.panel.modelDesc') }}</div>
            </div>
          </div>
          <FilterField :label="t('subcorpus.panel.fieldModel')">
            <select
              v-model="modelSelection"
              class="select"
              multiple
              size="6"
              @change="handleModelChange"
              :disabled="!includeAiLocal || isLoadingTree || !canLoadFilterMetadata"
            >
              <option
                v-for="opt in treeOptions.model"
                :key="opt"
                :value="opt"
                :disabled="optionCount('model', opt) === 0"
              >
                {{ opt }}{{ optionCount('model', opt) !== null ? ` · ${formatNumber(optionCount('model', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
        </section>

        <section class="tree-section">
          <div class="tree-head">
            <span class="tree-step">3</span>
            <div>
              <div class="tree-title">{{ t('subcorpus.panel.registerSourceTitle') }}</div>
              <div class="tree-desc">{{ t('subcorpus.panel.registerSourceDesc') }}</div>
            </div>
          </div>
          <FilterField :label="t('subcorpus.panel.fieldRegister')">
            <select
              v-model="registerSelection"
              class="select"
              multiple
              size="6"
              @change="handleRegisterChange"
              :disabled="isLoadingTree || !canLoadFilterMetadata"
            >
              <option
                v-for="opt in treeOptions.register"
                :key="opt"
                :value="opt"
                :disabled="optionCount('register', opt) === 0"
              >
                {{ opt }}{{ optionCount('register', opt) !== null ? ` · ${formatNumber(optionCount('register', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>

          <FilterField :label="t('subcorpus.panel.fieldSource')">
            <select
              v-model="sourceSelection"
              class="select"
              multiple
              size="6"
              @change="handleSourceChange"
              :disabled="isLoadingTree || !canLoadFilterMetadata"
            >
              <option
                v-for="opt in treeOptions.source"
                :key="opt"
                :value="opt"
                :disabled="optionCount('source', opt) === 0"
              >
                {{ opt }}{{ optionCount('source', opt) !== null ? ` · ${formatNumber(optionCount('source', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
        </section>
      </div>

      <GenericFilterSpecPanel
        v-if="showGenericFilters"
        v-model="genericFilterSpec"
        :enum-fields="genericEnumFields"
        :range-fields="genericRangeFields"
        :text-fields="genericTextFields"
        :enum-options="enumOptions"
        :loading="isLoadingGeneric"
        :error="genericError"
        :can-load-metadata="canLoadFilterMetadata"
        :metadata-block-reason="metaValuesBlockReason"
        :can-apply="canApplyGenericDocset"
        :apply-block-reason="docsetFromMetaBlockReason"
        :is-applying="docsetStore.isBuildingDocset"
        :title="usePairedTree ? t('subcorpus.panel.moreFieldsTitle') : t('subcorpus.generic.title')"
        :hint="usePairedTree ? t('subcorpus.panel.moreFieldsHint') : t('subcorpus.panel.genericHint')"
        :empty-label="usePairedTree ? t('subcorpus.panel.moreFieldsEmpty') : t('subcorpus.generic.empty')"
        :apply-label="usePairedTree ? t('subcorpus.panel.moreFieldsApply') : t('subcorpus.generic.apply')"
        @apply="applyGeneric"
        @reset="resetGeneric"
      />

      <div
        v-if="docsetStore.hasActiveDocset"
        class="applied-note"
        :class="{ 'applied-note-warn': scopeEvidence.tone === 'warn' }"
      >
        <component :is="scopeEvidence.tone === 'warn' ? AlertTriangle : Check" class="w-4 h-4" />
        <span>{{ t('subcorpus.panel.applied', { scope: scopeEvidence.label }) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.subcorpus-panel {
  @apply px-3 md:px-4 py-2 md:py-3;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
  @apply flex flex-col gap-2;
}

.subcorpus-panel.is-drawer {
  @apply px-0 py-0;
  @apply border-b-0;
  @apply bg-transparent;
}

.panel-head {
  @apply flex flex-wrap items-center gap-2 md:gap-3;
  @apply justify-between;
}

.panel-head.is-drawer {
  @apply pb-2 mb-2;
  @apply border-b border-neutral-200/70 dark:border-neutral-700/70;
}

.panel-title {
  @apply inline-flex items-center gap-2 text-sm font-semibold;
  @apply text-neutral-800 dark:text-neutral-100;
}

.toggle-btn {
  @apply inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-800 dark:text-neutral-100;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
  position: relative;
}

.dirty-dot {
  @apply inline-block w-2 h-2 rounded-full bg-primary-500;
  position: absolute;
  top: -2px;
  right: -2px;
}

.dirty-dot-inline {
  @apply inline-block w-2 h-2 rounded-full bg-primary-500;
}

.panel-status {
  @apply flex flex-wrap items-center gap-2 text-xs md:text-sm;
  @apply text-neutral-600 dark:text-neutral-400;
}

.scope-pill {
  @apply px-2 py-0.5 rounded-full text-xs font-medium;
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-pill.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.scope-pill.scope-pill-warn {
  @apply bg-amber-100 text-amber-700;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.status-text {
  @apply font-medium;
}

.docset-id {
  @apply font-mono text-xs text-neutral-500 dark:text-neutral-400;
}

.panel-actions {
  @apply flex items-center gap-2;
}

.btn {
  @apply inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm;
  @apply bg-primary-600 text-white;
  @apply hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

.btn-ghost {
  @apply bg-neutral-100 text-neutral-800;
  @apply dark:bg-neutral-800 dark:text-neutral-100;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
}

.summary {
  @apply text-xs text-neutral-600 dark:text-neutral-400;
}

.scope-purpose {
  @apply text-xs leading-relaxed text-neutral-600 dark:text-neutral-300;
}

.required-fields {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.structure-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.error {
  @apply text-sm text-error-600 dark:text-error-400;
}

.compatibility-row {
  @apply flex items-center gap-2 text-xs;
  @apply px-2.5 py-1.5 rounded-lg;
  @apply border;
}

.compatibility-row.status-neutral {
  @apply text-neutral-600 dark:text-neutral-300;
  @apply bg-neutral-50 dark:bg-neutral-900;
  @apply border-neutral-200 dark:border-neutral-800;
}

.compatibility-row.status-warn {
  @apply text-amber-700 dark:text-amber-300;
  @apply bg-amber-50 dark:bg-amber-900/30;
  @apply border-amber-200 dark:border-amber-800/60;
}

.compatibility-row.status-ok {
  @apply text-emerald-700 dark:text-emerald-300;
  @apply bg-emerald-50 dark:bg-emerald-900/30;
  @apply border-emerald-200 dark:border-emerald-800/60;
}

.panel-body {
  @apply mt-1 pt-2 border-t border-neutral-100 dark:border-neutral-800;
  @apply flex flex-col gap-3;
}

.toggle-row {
  @apply flex flex-wrap items-center gap-3;
  @apply text-xs text-neutral-600 dark:text-neutral-400;
}

.tree-path {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.tree-grid {
  @apply grid gap-3;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.tree-section {
  @apply rounded-xl border border-neutral-200/80 dark:border-neutral-700/70;
  @apply bg-white dark:bg-neutral-900;
  @apply p-3 space-y-2;
  @apply shadow-sm;
}

.tree-head {
  @apply flex items-center gap-3;
}

.tree-step {
  @apply w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.tree-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.tree-desc {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.tree-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.field {
  @apply flex flex-col gap-1;
}

.checkbox-field {
  @apply flex-row items-center gap-2;
}

.field-label {
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-400;
}

.select {
  @apply w-full px-2 py-1.5 rounded-lg text-sm;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
  min-height: 120px;
}

.applied-note {
  @apply inline-flex items-center gap-2 text-xs;
  @apply text-success-600 dark:text-success-400;
}

.applied-note-warn {
  @apply items-start text-amber-700 dark:text-amber-300;
}

.generic-filters {
  @apply flex flex-col gap-3;
}

.generic-actions {
  @apply flex items-center gap-2;
}

.range-row {
  @apply flex items-center gap-2;
}

.range-input {
  @apply w-full px-2 py-1.5 rounded-lg text-sm;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.range-sep {
  @apply text-neutral-500 dark:text-neutral-400;
}
</style>
