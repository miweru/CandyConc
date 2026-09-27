/**
 * Docset Store - Subkorpus management backed by backend docset endpoints
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useQueryStore } from './query'
import { useCorpusCapabilitiesStore } from './corpusCapabilities'
import { useProductCapabilitiesStore, type ProductOperationAccessOptions } from './productCapabilities'
import { useProductOperationRunsStore, type ProductOperationRunRecord } from './productOperationRuns'
import {
  createDocsetFromSearch,
  docsetFromMeta,
  getDocsetIntersection,
  getMetaSchema,
  getMetaCounts,
  getMetaValues,
  getMetaValuesPage,
  resolveSubcorpus,
  type DocsetFromMetaResult,
  type DocsetIntersectionParams,
  type DocsetIntersectionResult,
  type FilterSpec,
  type FilterSpecValue,
  type MetaCountsParams,
  type MetaValuesPage,
  type MetaValuesParams,
  type ResolveSubcorpusResult,
} from '@/api/client'
import type { MetaSchemaResponse } from '@/api/schemas'
import { isCqlfQuery } from '@/lib/cqlDetection'
import {
  deriveFilterSpecFromLegacy,
  filterSpecChips,
  filterSpecSummaryParts,
  LEGACY_FILTER_FIELDS,
  legacyFiltersFromSpec,
} from '@/lib/filterSpec'
import { t } from '@/i18n'

/**
 * Paired-corpus fields used for the guided comparison filter. They are not
 * mandatory selections: the schema-driven filter remains the fallback when a
 * corpus does not expose all four as enumerable metadata.
 */
export const PAIRED_TREE_FIELDS = ['prompting_method', 'model', 'register', 'source'] as const
type MetaField = (typeof PAIRED_TREE_FIELDS)[number]

export type MetaFieldKind = 'enum' | 'number' | 'date' | 'text'

export interface MetaFieldDescriptor {
  name: string
  kind: MetaFieldKind
}

/** Op-tagged range selection produced by numeric/date controls. */
export interface RangeFilter {
  lo?: number | string
  hi?: number | string
}

export interface DocsetFilters {
  prompting_method: string[]
  model: string[]
  register: string[]
  source: string[]
}

export interface DocsetStats {
  docCount: number
  hitDocCount: number
  refDocCount: number
  tokenCount: number
}

export interface DocsetSnapshot {
  corpus: string
  docsetId: string
  stats: DocsetStats
  filters: DocsetFilters
  includeAi: boolean
  includeHuman: boolean
  query?: string
  /** Durable subcorpus name; when present the docset id is re-resolved at runtime. */
  name?: string
  /** Op-tagged filter spec for field-agnostic / search-less resolution. */
  filterSpec?: FilterSpec
  metadataSchemaHash?: string
}

const HINT_STORAGE_KEY = 'candyconc_docset_hints'
export const DOCSET_OPERATIONS = {
  metaSchema: 'research.subcorpora_docsets.meta_schema',
  metaValues: 'research.subcorpora_docsets.meta_values',
  metaCounts: 'research.subcorpora_docsets.meta_counts',
  docsetFromMeta: 'research.subcorpora_docsets.docset_from_meta',
  docsetFromSearch: 'research.subcorpora_docsets.docset_from_search',
  docsetIntersection: 'research.subcorpora_docsets.docset_intersection',
  subcorporaResolve: 'research.subcorpora_docsets.subcorpora_resolve',
} as const

function emptyFilters(): DocsetFilters {
  return {
    prompting_method: [],
    model: [],
    register: [],
    source: [],
  }
}

function emptyStats(): DocsetStats {
  return {
    docCount: 0,
    hitDocCount: 0,
    refDocCount: 0,
    tokenCount: 0,
  }
}

function emptyMetaOptions(): Record<MetaField, string[]> {
  return {
    prompting_method: [],
    model: [],
    register: [],
    source: [],
  }
}

function hasAnyFilter(filters: DocsetFilters): boolean {
  return (
    filters.prompting_method.length > 0 ||
    filters.model.length > 0 ||
    filters.register.length > 0 ||
    filters.source.length > 0
  )
}

// A native multi-select is useful for a research category, not for a document
// identity or an alignment pointer. Internal coordinates have dedicated product
// workflows (document access and alignment), so they do not belong in the
// researcher-facing metadata filter at all.
export const MAX_ENUM_FACET_VALUES = 250

const IDENTITY_FIELD_NAMES = new Set([
  'doc_id',
  'origin_doc_id',
  'origin_id',
  'paired_with',
  'path',
  'ref_doc',
  'reference_hash',
  'step_index',
])

export function isIdentityField(name: string): boolean {
  const n = name.toLowerCase()
  if (IDENTITY_FIELD_NAMES.has(n)) return true
  return /(^|_)(id|hash|uuid|guid|path|url)$/.test(n)
}

function classifyField(field: {
  kind?: string
  hasNumber?: boolean
  hasString?: boolean
  name: string
  stringValueCount?: number | null
}): MetaFieldKind {
  const kind = (field.kind ?? '').toLowerCase()
  // Relation fields such as ref_doc and paired_with are internal coordinates,
  // even when the index happens to encode them numerically.
  if (isIdentityField(field.name)) return 'text'
  if (kind === 'number' || kind === 'numeric' || kind === 'int' || kind === 'float') return 'number'
  if (kind === 'date' || kind === 'datetime' || kind === 'timestamp') return 'date'
  if (kind === 'enum' || kind === 'string' || kind === 'categorical' || field.hasString) {
    const valueCount = field.stringValueCount
    // The schema supplies this count from the index lexicon. Large categories
    // are still filterable by exact value, but loading every option would make
    // the filter drawer unusable on real corpora.
    if (typeof valueCount === 'number' && valueCount > MAX_ENUM_FACET_VALUES) return 'text'
    return 'enum'
  }
  // Heuristic fallback from value-presence flags.
  if (field.hasNumber && !field.hasString) return 'number'
  if (/(date|year|jahr|datum|time|zeit)/i.test(field.name)) return 'date'
  // Unknown/list-like fields can contain arbitrary numbers of relationship
  // values. Treat them as exact-value filters rather than guessing a facet.
  return 'text'
}

// ---- sessionStorage hint map (name -> docsetId) -----------------------------

function readHints(): Record<string, string> {
  try {
    const raw = sessionStorage.getItem(HINT_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function writeHint(name: string, docsetId: string) {
  try {
    const hints = readHints()
    hints[name] = docsetId
    sessionStorage.setItem(HINT_STORAGE_KEY, JSON.stringify(hints))
  } catch {
    // sessionStorage unavailable — hints are best-effort only.
  }
}

function clearHint(name: string) {
  try {
    const hints = readHints()
    delete hints[name]
    sessionStorage.setItem(HINT_STORAGE_KEY, JSON.stringify(hints))
  } catch {
    // ignore
  }
}

export const useDocsetStore = defineStore('docset', () => {
  const queryStore = useQueryStore()
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const productCapabilities = useProductCapabilitiesStore()
  const operationRuns = useProductOperationRunsStore()

  const filters = ref<DocsetFilters>(emptyFilters())
  const includeAi = ref(true)
  const includeHuman = ref(true)

  const activeDocsetId = ref<string | null>(null)
  const stats = ref<DocsetStats>(emptyStats())

  const metaOptions = ref<Record<MetaField, string[]>>(emptyMetaOptions())

  // Field-agnostic schema state, derived from the corpus meta schema.
  const metaFields = ref<MetaFieldDescriptor[]>([])
  const metaSchemaHash = ref<string | null>(null)
  /** Distinct values per metadata field of the active corpus (all fields, identity fields included). */
  const metaFieldValueCounts = ref<Record<string, number | null>>({})
  const activeFilterSpec = ref<FilterSpec | null>(null)

  const isLoadingOptions = ref(false)
  const isBuildingDocset = ref(false)
  const error = ref<string | null>(null)
  const isDirty = ref(false)
  const activeScopeStale = ref(false)
  const activeScopeWarning = ref<string | null>(null)
  const activeScopeResolvedAt = ref<number | null>(null)
  const activeSubcorpusName = ref<string | null>(null)

  // How the ACTIVE docset was actually built. Persisting a subcorpus must follow
  // this, NOT the current queryStore.term (a stale unrelated search term would
  // otherwise be baked into a metadata-built scope → 683 docs shown, 0 resolved;
  // SUBC-01). 'search' carries the query used to build it; 'meta' is filter-only.
  const activeDocsetOrigin = ref<{ kind: 'search'; query: string } | { kind: 'meta' } | null>(null)

  const lastQuery = ref('')
  const lastCorpus = ref('default')

  // In-flight ordering guards: rapid corpus/filter switches can let a slower
  // earlier response overwrite a newer one. Each load bumps its sequence and
  // aborts the previous request; only the latest sequence applies its result.
  let metaSchemaSeq = 0
  let metaOptionsSeq = 0
  let metaSchemaController: AbortController | null = null
  let metaOptionsController: AbortController | null = null

  const activeCorpus = computed(() => queryStore.filters.corpus ?? 'default')

  const enumFields = computed(() => metaFields.value.filter((f) => f.kind === 'enum'))
  const rangeFields = computed(() =>
    metaFields.value.filter((f) => f.kind === 'number' || f.kind === 'date')
  )
  const textFields = computed(() => metaFields.value.filter((f) => f.kind === 'text'))

  /** Whether the corpus exposes the legacy paired fields the classic tree needs. */
  const hasLegacyMetaFields = computed(() => {
    if (!metaFields.value.length) return true // unknown schema: don't break the legacy UI
    const byName = new Map(metaFields.value.map((field) => [field.name, field]))
    // The paired tree has select boxes for every step. If one of its fields is
    // high-cardinality, use the generic exact-value flow instead of fetching
    // and rendering an unbounded list of models or sources.
    return PAIRED_TREE_FIELDS.every((field) => byName.get(field)?.kind === 'enum')
  })

  const filtersActive = computed(() => {
    const anyFilter = hasAnyFilter(filters.value)
    const includeDefaults = includeAi.value && includeHuman.value
    return anyFilter || !includeDefaults
  })

  const hasActiveDocset = computed(() => !!activeDocsetId.value)

  const scopeLabel = computed(() => (hasActiveDocset.value ? t('subcorpus.store.scopeSubcorpus') : t('subcorpus.store.scopeWholeCorpus')))

  const summaryParts = computed(() => {
    const parts: string[] = []
    if (filters.value.prompting_method.length) {
      parts.push(t('subcorpus.docset.partPrompt', { values: filters.value.prompting_method.join(', ') }))
    }
    if (filters.value.register.length) {
      parts.push(t('subcorpus.docset.partRegister', { values: filters.value.register.join(', ') }))
    }
    if (filters.value.source.length) parts.push(t('subcorpus.docset.partSource', { values: filters.value.source.join(', ') }))
    if (filters.value.model.length) parts.push(t('subcorpus.docset.partModel', { values: filters.value.model.join(', ') }))
    if (!includeAi.value) parts.push(t('subcorpus.docset.withoutAi'))
    if (!includeHuman.value) parts.push(t('subcorpus.docset.withoutHuman'))
    if (!parts.length && activeFilterSpec.value) {
      parts.push(...filterSpecSummaryParts(activeFilterSpec.value))
    } else if (activeFilterSpec.value) {
      const legacyFields = new Set<string>(LEGACY_FILTER_FIELDS)
      parts.push(
        ...filterSpecChips(activeFilterSpec.value)
          .filter((chip) => !legacyFields.has(chip.field))
          .map((chip) => chip.title)
      )
    }
    return parts
  })
  const metaSchemaAvailability = computed(() =>
    productCapabilities.productOperationAvailability(DOCSET_OPERATIONS.metaSchema)
  )
  const metaValuesAvailability = computed(() =>
    productCapabilities.productOperationAvailability(DOCSET_OPERATIONS.metaValues)
  )
  const metaCountsAvailability = computed(() =>
    productCapabilities.productOperationAvailability(DOCSET_OPERATIONS.metaCounts)
  )
  const docsetFromMetaAvailability = computed(() =>
    productCapabilities.productOperationAvailability(DOCSET_OPERATIONS.docsetFromMeta)
  )
  const docsetFromSearchAvailability = computed(() =>
    productCapabilities.productOperationAvailability(DOCSET_OPERATIONS.docsetFromSearch)
  )
  const docsetIntersectionAvailability = computed(() =>
    productCapabilities.productOperationAvailability(DOCSET_OPERATIONS.docsetIntersection)
  )
  const subcorpusResolveAvailability = computed(() =>
    productCapabilities.productOperationAvailability(DOCSET_OPERATIONS.subcorporaResolve)
  )
  const canLoadMetaSchema = computed(() => metaSchemaAvailability.value.enabled)
  const canLoadMetaValues = computed(() => metaValuesAvailability.value.enabled)
  const canLoadMetaCounts = computed(() => metaCountsAvailability.value.enabled)
  const canBuildDocsetFromMeta = computed(() => docsetFromMetaAvailability.value.enabled)
  const canBuildDocsetFromSearch = computed(() => docsetFromSearchAvailability.value.enabled)
  const canBuildDocsetIntersection = computed(() => docsetIntersectionAvailability.value.enabled)
  const canResolveSubcorpus = computed(() => subcorpusResolveAvailability.value.enabled)

  function markDirty() {
    isDirty.value = true
  }

  function startDocsetRun(
    operationId: string,
    sourceId: string,
    label: string,
    detail: string | null = null,
  ): ProductOperationRunRecord {
    return operationRuns.startRun({
      operationId,
      sourceId,
      kind: 'operation',
      surfaceId: 'research.subcorpora_docsets',
      label,
      detail,
      status: 'running',
      progress: 5,
      message: t('subcorpus.store.running', { label }),
    })
  }

  function finishDocsetRun(run: ProductOperationRunRecord, message: string): void {
    operationRuns.finishRun(run.id, message)
  }

  function failDocsetRun(run: ProductOperationRunRecord, err: unknown, fallback: string): void {
    operationRuns.failRun(run.id, err instanceof Error ? err.message : fallback)
  }

  function setFilter(field: MetaField, values: string[]) {
    filters.value[field] = values
    markDirty()
  }

  function setIncludeAi(value: boolean) {
    includeAi.value = value
    markDirty()
  }

  function setIncludeHuman(value: boolean) {
    includeHuman.value = value
    markDirty()
  }

  function clearFilters() {
    filters.value = emptyFilters()
    includeAi.value = true
    includeHuman.value = true
    markDirty()
  }

  function resetDocset() {
    activeDocsetId.value = null
    stats.value = emptyStats()
    activeFilterSpec.value = null
    activeDocsetOrigin.value = null
    error.value = null
    activeScopeStale.value = false
    activeScopeWarning.value = null
    activeScopeResolvedAt.value = null
    activeSubcorpusName.value = null
  }

  function resetScopeForCorpusChange(corpus: string) {
    // A transient docset belongs to exactly one backend corpus.  Keeping its
    // id or filter evidence after activation would silently scope the next
    // request to the wrong corpus (or yield a backend 404).
    resetDocset()
    filters.value = emptyFilters()
    includeAi.value = true
    includeHuman.value = true
    metaOptions.value = emptyMetaOptions()
    metaFields.value = []
    metaFieldValueCounts.value = {}
    metaSchemaHash.value = null
    lastQuery.value = ''
    lastCorpus.value = corpus
    isDirty.value = false
  }

  function setResolveEvidence(params: {
    stale: boolean
    name?: string
    warning?: string | null
  }) {
    activeScopeStale.value = params.stale
    activeScopeWarning.value = params.warning ?? (
      params.stale
        ? t('subcorpus.store.schemaChanged')
        : null
    )
    activeScopeResolvedAt.value = Date.now()
    activeSubcorpusName.value = params.name ?? null
  }

  async function ensureDocsetOperationAccess(
    label: string,
    operationId: string,
    options: ProductOperationAccessOptions = {},
  ): Promise<boolean> {
    try {
      await productCapabilities.assertProductOperationAccess(operationId, label, options)
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : t('subcorpus.store.notEnabled', { label })
      return false
    }
  }

  function docsetSurfaceConfirmation(interaction: string): ProductOperationAccessOptions {
    return {
      contextualConfirmation: {
        surfaceId: 'research.subcorpora_docsets',
        interaction,
        source: 'native_surface',
      },
    }
  }

  function ensureDocsetSurfaceAccess(
    label: string,
    operationId: string,
    interaction = label,
  ): Promise<boolean> {
    return ensureDocsetOperationAccess(label, operationId, docsetSurfaceConfirmation(interaction))
  }

  async function fetchMetaValues(
    params: MetaValuesParams,
    options: { signal?: AbortSignal } = {},
    label = t('subcorpus.store.opMetaValues'),
  ): Promise<Record<string, string[]> | null> {
    if (!(await ensureDocsetOperationAccess(label, DOCSET_OPERATIONS.metaValues))) {
      return null
    }
    return getMetaValues(params, options)
  }

  async function fetchMetaValuesPage(
    params: MetaValuesParams,
    options: { signal?: AbortSignal } = {},
    label = t('subcorpus.store.opMetaValues'),
  ): Promise<MetaValuesPage | null> {
    if (!(await ensureDocsetOperationAccess(label, DOCSET_OPERATIONS.metaValues))) {
      return null
    }
    return getMetaValuesPage(params, options)
  }

  async function fetchMetaSchema(
    corpus = activeCorpus.value,
    options: { signal?: AbortSignal } = {},
    label = t('subcorpus.store.opMetaSchema'),
  ): Promise<MetaSchemaResponse | null> {
    // Without a corpus there is no schema, and the server answers 503.
    if (corpusCapabilities.catalogEmpty) return null
    if (!(await ensureDocsetOperationAccess(label, DOCSET_OPERATIONS.metaSchema))) {
      return null
    }
    return getMetaSchema({ corpus }, options)
  }

  async function fetchMetaCounts(
    params: MetaCountsParams,
    options: { signal?: AbortSignal } = {},
    label = t('subcorpus.store.opMetaCounts'),
  ): Promise<Record<string, Record<string, number>> | null> {
    if (!(await ensureDocsetOperationAccess(label, DOCSET_OPERATIONS.metaCounts))) {
      return null
    }
    return getMetaCounts(params, options)
  }

  async function createTransientDocsetFromMeta(
    spec: FilterSpec,
    corpus = activeCorpus.value,
    label = t('subcorpus.store.opMetaDocset'),
  ): Promise<DocsetFromMetaResult | null> {
    if (!(await ensureDocsetSurfaceAccess(label, DOCSET_OPERATIONS.docsetFromMeta))) {
      return null
    }
    const run = startDocsetRun(
      DOCSET_OPERATIONS.docsetFromMeta,
      `transient-meta:${corpus}:${Date.now()}`,
      label,
      filterSpecSummaryParts(spec).join(', ') || corpus,
    )
    try {
      const result = await docsetFromMeta(spec, corpus)
      finishDocsetRun(run, t('subcorpus.store.computed', { label }))
      return result
    } catch (err) {
      failDocsetRun(run, err, t('subcorpus.store.computeFailed', { label }))
      throw err
    }
  }

  async function resolveNamedSubcorpusDocset(
    name: string,
    corpus = activeCorpus.value,
  ): Promise<ResolveSubcorpusResult | null> {
    if (!(await ensureDocsetSurfaceAccess(
      t('subcorpus.store.opResolve'),
      DOCSET_OPERATIONS.subcorporaResolve,
      t('subcorpus.store.resolveFresh'),
    ))) {
      return null
    }
    const run = startDocsetRun(
      DOCSET_OPERATIONS.subcorporaResolve,
      `transient-resolve:${name}:${Date.now()}`,
      t('subcorpus.store.opResolve'),
      name,
    )
    try {
      const result = await resolveSubcorpus(name, corpus)
      finishDocsetRun(run, t('subcorpus.store.resolveDone'))
      return result
    } catch (err) {
      failDocsetRun(run, err, t('subcorpus.store.resolveFailed'))
      throw err
    }
  }

  async function fetchDocsetIntersection(
    params: DocsetIntersectionParams,
  ): Promise<DocsetIntersectionResult | null> {
    if (!(await ensureDocsetSurfaceAccess(
      t('subcorpus.store.opIntersection'),
      DOCSET_OPERATIONS.docsetIntersection,
      t('subcorpus.store.intersect'),
    ))) {
      return null
    }
    const run = startDocsetRun(
      DOCSET_OPERATIONS.docsetIntersection,
      `intersection:${Date.now()}`,
      t('subcorpus.store.opIntersection'),
      params.corpus ?? activeCorpus.value,
    )
    try {
      const result = await getDocsetIntersection(params)
      finishDocsetRun(run, t('subcorpus.store.computed', { label: t('subcorpus.store.opIntersection') }))
      return result
    } catch (err) {
      failDocsetRun(run, err, t('subcorpus.store.computeFailed', { label: t('subcorpus.store.opIntersection') }))
      throw err
    }
  }

  async function ensureCqlfAccess(term: string): Promise<boolean> {
    if (!isCqlfQuery(term)) return true
    const decision = await productCapabilities.ensureCapabilityAccess('query.cqlf', 'CQLF')
    if (!decision.allowed) {
      error.value = decision.reason ?? t('subcorpus.store.cqlfNotEnabled')
      isDirty.value = false
      return false
    }
    return true
  }

  function applyResolvedScopeCounts(result: { doc_count?: number; token_count?: number }) {
    stats.value = {
      docCount: result.doc_count ?? stats.value.docCount,
      hitDocCount: 0,
      refDocCount: stats.value.refDocCount,
      tokenCount: result.token_count ?? stats.value.tokenCount,
    }
  }

  function localSchemaStale(def: DocsetSnapshot): boolean {
    return Boolean(def.metadataSchemaHash && metaSchemaHash.value && def.metadataSchemaHash !== metaSchemaHash.value)
  }

  /** Build an op-tagged filter spec from the current legacy 4-field selection. */
  function _filterSpecPayload(): FilterSpec {
    const spec: FilterSpec = {}
    if (filters.value.prompting_method.length) spec.prompting_method = [...filters.value.prompting_method]
    if (filters.value.model.length) spec.model = [...filters.value.model]
    if (filters.value.register.length) spec.register = [...filters.value.register]
    if (filters.value.source.length) spec.source = [...filters.value.source]
    return spec
  }

  /**
   * Re-hydrate a durable subcorpus definition into a FRESH, live docset id.
   *
   * `docsetId` is only ever a cache hint. Durable named subcorpora are always
   * re-resolved against the backend so the `stale` evidence bit cannot be hidden
   * by a sessionStorage hint. Returns the live docset id (or null on failure /
   * empty scope).
   */
  async function resolveDocset(def: DocsetSnapshot): Promise<string | null> {
    const corpus = def.corpus || activeCorpus.value
    const name = def.name

    // 1) Durable definitions are re-resolved by name.
    if (name) {
      if (!(await ensureDocsetSurfaceAccess(
        t('subcorpus.store.opResolve'),
        DOCSET_OPERATIONS.subcorporaResolve,
        t('subcorpus.store.activateSaved'),
      ))) {
        return null
      }
      const run = startDocsetRun(
        DOCSET_OPERATIONS.subcorporaResolve,
        `resolve:${name}`,
        t('subcorpus.store.opResolve'),
        name,
      )
      try {
        const resolved = await resolveSubcorpus(name, corpus)
        writeHint(name, resolved.docset_id)
        applyResolvedScopeCounts(resolved)
        setResolveEvidence({ stale: Boolean(resolved.stale), name })
        finishDocsetRun(run, t('subcorpus.store.resolveDone'))
        return resolved.docset_id
      } catch (err) {
        failDocsetRun(run, err, t('subcorpus.store.resolveFailed'))
        if (name) clearHint(name)
        // Fall through to the local fallbacks below.
      }
    }

    // 2) Metadata-only subcorpus (no query): resolve from the filter spec.
    const spec = def.filterSpec && Object.keys(def.filterSpec).length ? def.filterSpec : undefined
    if (!def.query && spec) {
      if (!(await ensureDocsetSurfaceAccess(
        t('subcorpus.store.opMetaDocset'),
        DOCSET_OPERATIONS.docsetFromMeta,
        t('subcorpus.store.activateSavedMeta'),
      ))) {
        return null
      }
      const run = startDocsetRun(
        DOCSET_OPERATIONS.docsetFromMeta,
        `meta:${name ?? Date.now()}`,
        t('subcorpus.store.opMetaDocset'),
        name ?? corpus,
      )
      try {
        const result = await docsetFromMeta(spec, corpus)
        if (name) writeHint(name, result.docset_id)
        applyResolvedScopeCounts(result)
        const stale = localSchemaStale(def)
        setResolveEvidence({ stale, name })
        finishDocsetRun(run, t('subcorpus.store.computed', { label: t('subcorpus.store.opMetaDocset') }))
        return result.docset_id
      } catch (err) {
        failDocsetRun(run, err, t('subcorpus.store.computeFailed', { label: t('subcorpus.store.opMetaDocset') }))
        // fall through
      }
    }

    // 3) Query-based subcorpus without a durable name: rebuild from search.
    if (def.query) {
      if (!(await ensureCqlfAccess(def.query))) return null
      if (!(await ensureDocsetSurfaceAccess(
        t('subcorpus.store.opSearchDocset'),
        DOCSET_OPERATIONS.docsetFromSearch,
        t('subcorpus.store.useHits'),
      ))) {
        return null
      }
      const run = startDocsetRun(
        DOCSET_OPERATIONS.docsetFromSearch,
        `search:${name ?? Date.now()}`,
        t('subcorpus.store.opSearchDocset'),
        def.query,
      )
      try {
        const result = await createDocsetFromSearch({
          query: def.query,
          corpus,
          includeAi: def.includeAi,
          includeHuman: def.includeHuman,
        })
        applyResolvedScopeCounts(result)
        const stale = localSchemaStale(def)
        setResolveEvidence({ stale, name })
        finishDocsetRun(run, t('subcorpus.store.computed', { label: t('subcorpus.store.opSearchDocset') }))
        return result.docset_id
      } catch (err) {
        failDocsetRun(run, err, t('subcorpus.store.computeFailed', { label: t('subcorpus.store.opSearchDocset') }))
        // fall through
      }
    }

    // 4) Last resort: trust the stored id (may be dead, but better than nothing).
    setResolveEvidence({
      stale: localSchemaStale(def),
      name,
      warning: def.docsetId
        ? t('subcorpus.store.hintUnverified')
        : null,
    })
    return def.docsetId || null
  }

  async function ensureSnapshotCorpus(snapshot: DocsetSnapshot): Promise<boolean> {
    const targetCorpus = snapshot.corpus?.trim() || activeCorpus.value
    if (!targetCorpus || targetCorpus === activeCorpus.value) return true

    await corpusCapabilities.setActive(targetCorpus)
    if (activeCorpus.value === targetCorpus) return true

    activeDocsetId.value = null
    activeSubcorpusName.value = snapshot.name ?? null
    error.value =
      corpusCapabilities.activationError ??
      t('subcorpus.store.corpusSwitchFailed', { name: snapshot.name ?? snapshot.docsetId, corpus: targetCorpus })
    return false
  }

  /**
   * Apply a saved subcorpus snapshot. The docset id is ALWAYS re-resolved through
   * `resolveDocset` rather than trusting a possibly-dead stored id.
   */
  async function applySnapshot(snapshot: DocsetSnapshot) {
    if (!(await ensureSnapshotCorpus(snapshot))) return

    filters.value = {
      prompting_method: [...snapshot.filters.prompting_method],
      model: [...snapshot.filters.model],
      register: [...snapshot.filters.register],
      source: [...snapshot.filters.source],
    }
    includeAi.value = snapshot.includeAi
    includeHuman.value = snapshot.includeHuman
    stats.value = { ...snapshot.stats }
    activeFilterSpec.value = snapshot.filterSpec ? { ...snapshot.filterSpec } : null
    // Preserve the build origin so a re-park persists faithfully (SUBC-01).
    activeDocsetOrigin.value = snapshot.query
      ? { kind: 'search', query: snapshot.query }
      : { kind: 'meta' }
    lastQuery.value = snapshot.query ?? lastQuery.value
    lastCorpus.value = snapshot.corpus
    error.value = null
    activeScopeStale.value = false
    activeScopeWarning.value = null
    activeScopeResolvedAt.value = null
    activeSubcorpusName.value = snapshot.name ?? null
    isDirty.value = false

    const liveId = await resolveDocset(snapshot)
    activeDocsetId.value = liveId
  }

  /** Fields of the active filter spec that the paired tree does not hold. */
  function _genericScopeFilters(): FilterSpec {
    const spec = activeFilterSpec.value
    if (!spec) return {}
    const legacy = new Set<string>(LEGACY_FILTER_FIELDS)
    return Object.fromEntries(Object.entries(spec).filter(([field]) => !legacy.has(field)))
  }

  /**
   * The documents with hits of ``term`` inside the active scope, as a new
   * docset. The active scope stays as it is. The request is the one a saved
   * subcorpus with this query and filter spec replays on resolve
   * (``_resolve_subcorpus_doc_ids``), so counts at saving and at resolving
   * agree.
   */
  async function buildHitsDocset(term: string): Promise<{
    docsetId: string
    stats: DocsetStats
    filterSpec: FilterSpec | null
  } | null> {
    const query = term.trim()
    if (!query) return null
    if (!(await ensureCqlfAccess(query))) return null
    if (!(await ensureDocsetSurfaceAccess(
      t('subcorpus.docset.searchDocsetLabel'),
      DOCSET_OPERATIONS.docsetFromSearch,
      t('subcorpus.docset.searchDocsetInteraction'),
    ))) {
      return null
    }
    const scopeSpec = hasActiveDocset.value
      ? deriveFilterSpecFromLegacy(filters.value, activeFilterSpec.value)
      : deriveFilterSpecFromLegacy(filters.value)
    const filterSpec = Object.keys(scopeSpec).length ? scopeSpec : null
    try {
      const result = await createDocsetFromSearch({
        query,
        corpus: activeCorpus.value,
        includeAi: includeAi.value,
        includeHuman: includeHuman.value,
        aiFilters: _aiFiltersPayload(),
        metaFilters: filterSpec ?? undefined,
      })
      return {
        docsetId: result.docset_id,
        stats: {
          docCount: result.doc_count ?? 0,
          hitDocCount: result.hit_doc_count ?? 0,
          refDocCount: result.ref_doc_count ?? 0,
          tokenCount: result.token_count ?? 0,
        },
        filterSpec,
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      return null
    }
  }

  function _metaFiltersPayload(): Record<string, string | string[]> | undefined {
    const meta: Record<string, string | string[]> = {}
    if (filters.value.register.length) meta.register = [...filters.value.register]
    if (filters.value.source.length) meta.source = [...filters.value.source]
    return Object.keys(meta).length ? meta : undefined
  }

  function _aiFiltersPayload(): Record<string, string | string[]> | undefined {
    const ai: Record<string, string | string[]> = {}
    if (filters.value.model.length) ai.model = [...filters.value.model]
    if (filters.value.prompting_method.length) {
      ai.prompting_method = [...filters.value.prompting_method]
    }
    return Object.keys(ai).length ? ai : undefined
  }

  /** Load the corpus meta schema and derive the field-agnostic descriptor list. */
  async function loadMetaSchema(force = false) {
    if (!force && metaFields.value.length && metaSchemaHash.value) return
    if (corpusCapabilities.catalogEmpty) {
      metaFields.value = []
      metaSchemaHash.value = null
      return
    }
    const seq = ++metaSchemaSeq
    metaSchemaController?.abort()
    const controller = new AbortController()
    metaSchemaController = controller
    try {
      if (!(await ensureDocsetOperationAccess(t('subcorpus.store.opMetaSchema'), DOCSET_OPERATIONS.metaSchema))) {
        return
      }
      const schema: MetaSchemaResponse = await getMetaSchema(
        { corpus: activeCorpus.value },
        { signal: controller.signal }
      )
      // A newer request superseded this one; discard the stale result.
      if (seq !== metaSchemaSeq) return
      metaSchemaHash.value = schema.metadataSchemaHash ?? schema.fingerprint ?? null
      const rawFields = (schema.metadataFields ?? []) as Array<{
        name: string
        kind?: string
        hasNumber?: boolean
        hasString?: boolean
        stringValueCount?: number | null
        placeholder?: boolean
      }>
      metaFieldValueCounts.value = Object.fromEntries(
        rawFields.map((field) => [field.name, field.stringValueCount ?? null]),
      )
      // Builder placeholders of an unpaired corpus (model=none,
      // text_type=standalone, variant=document) are not offered as filters.
      metaFields.value = rawFields
        .filter((field) => !isIdentityField(field.name) && !field.placeholder)
        .map((field) => ({
          name: field.name,
          kind: classifyField(field),
        }))
    } catch (err) {
      if (seq !== metaSchemaSeq || (err instanceof Error && err.name === 'AbortError')) return
      const message = err instanceof Error ? err.message : t('subcorpus.store.schemaLoadFailed')
      error.value = message
    }
  }

  async function loadMetaOptions(force = false) {
    // The legacy four-select UI can only represent genuinely enumerable
    // metadata. Resolve the schema first so simply mounting a query surface
    // never asks the backend to materialize a high-cardinality model field.
    await loadMetaSchema(force)
    if (!hasLegacyMetaFields.value) {
      metaOptions.value = emptyMetaOptions()
      return
    }
    if (!force && metaOptions.value.prompting_method.length) return
    const seq = ++metaOptionsSeq
    metaOptionsController?.abort()
    const controller = new AbortController()
    metaOptionsController = controller
    isLoadingOptions.value = true
    try {
      if (!(await ensureDocsetOperationAccess(t('subcorpus.store.opMetaValues'), DOCSET_OPERATIONS.metaValues))) {
        return
      }
      const values = await fetchMetaValues(
        {
          fields: [...PAIRED_TREE_FIELDS],
          corpus: activeCorpus.value,
        },
        { signal: controller.signal },
      )
      if (!values) return
      // A newer request superseded this one; discard the stale result.
      if (seq !== metaOptionsSeq) return
      metaOptions.value = {
        prompting_method: [...(values.prompting_method ?? [])].sort(),
        model: [...(values.model ?? [])].sort(),
        register: [...(values.register ?? [])].sort(),
        source: [...(values.source ?? [])].sort(),
      }
    } catch (err) {
      if (seq !== metaOptionsSeq || (err instanceof Error && err.name === 'AbortError')) return
      const message = err instanceof Error ? err.message : t('subcorpus.store.metaLoadFailed')
      error.value = message
    } finally {
      if (seq === metaOptionsSeq) isLoadingOptions.value = false
    }
  }

  async function loadModelOptionsForPrompt(promptingMethod?: string) {
    // Shares the metaOptions sequence/controller since it also writes
    // metaOptions: a newer corpus/filter switch must win regardless of which
    // loader issued the request.
    const seq = ++metaOptionsSeq
    metaOptionsController?.abort()
    const controller = new AbortController()
    metaOptionsController = controller
    isLoadingOptions.value = true
    try {
      if (!(await ensureDocsetOperationAccess(t('subcorpus.store.opModelValues'), DOCSET_OPERATIONS.metaValues))) {
        return
      }
      const filters = promptingMethod ? { prompting_method: promptingMethod } : undefined
      const values = await fetchMetaValues(
        {
          fields: ['model'],
          corpus: activeCorpus.value,
          filters,
        },
        { signal: controller.signal },
        t('subcorpus.store.opModelValues'),
      )
      if (!values) return
      if (seq !== metaOptionsSeq) return
      metaOptions.value = {
        ...metaOptions.value,
        model: [...(values.model ?? [])].sort(),
      }
    } catch (err) {
      if (seq !== metaOptionsSeq || (err instanceof Error && err.name === 'AbortError')) return
      const message = err instanceof Error ? err.message : t('subcorpus.store.modelsLoadFailed')
      error.value = message
    } finally {
      if (seq === metaOptionsSeq) isLoadingOptions.value = false
    }
  }

  async function buildDocset(force = false, queryOverride?: string): Promise<boolean> {
    const term = (queryOverride ?? queryStore.term).trim()
    if (!term) {
      resetDocset()
      error.value = t('subcorpus.store.searchFirst')
      isDirty.value = false
      return false
    }

    if (!(await ensureCqlfAccess(term))) return false

    if (!force && !filtersActive.value) {
      resetDocset()
      isDirty.value = false
      return true
    }

    isBuildingDocset.value = true
    error.value = null
    let run: ProductOperationRunRecord | null = null

    try {
      if (!(await ensureDocsetSurfaceAccess(
        t('subcorpus.store.opSearchDocset'),
        DOCSET_OPERATIONS.docsetFromSearch,
        t('subcorpus.store.useHits'),
      ))) {
        isDirty.value = false
        return false
      }
      run = startDocsetRun(
        DOCSET_OPERATIONS.docsetFromSearch,
        `search:${activeCorpus.value}:${Date.now()}`,
        t('subcorpus.store.opSearchDocset'),
        term,
      )
      // Metadata fields beyond the four paired-tree fields (for example party
      // from a saved subcorpus) restrict the rebuilt scope as well. Without
      // them a new search term widened the scope to the whole corpus.
      const genericFilters = _genericScopeFilters()
      const metaFilters = { ...(_metaFiltersPayload() ?? {}), ...genericFilters }
      const result = await createDocsetFromSearch({
        query: term,
        corpus: activeCorpus.value,
        includeAi: includeAi.value,
        includeHuman: includeHuman.value,
        aiFilters: _aiFiltersPayload(),
        metaFilters: Object.keys(metaFilters).length ? metaFilters : undefined,
      })

      activeDocsetId.value = result.docset_id
      stats.value = {
        docCount: result.doc_count ?? 0,
        hitDocCount: result.hit_doc_count ?? 0,
        refDocCount: result.ref_doc_count ?? 0,
        tokenCount: result.token_count ?? 0,
      }
      const filterSpec = { ..._filterSpecPayload(), ...genericFilters }
      activeFilterSpec.value = Object.keys(filterSpec).length ? filterSpec : null
      activeDocsetOrigin.value = { kind: 'search', query: term }
      setResolveEvidence({ stale: false })
      lastQuery.value = term
      lastCorpus.value = activeCorpus.value
      isDirty.value = false
      finishDocsetRun(run, t('subcorpus.store.computed', { label: t('subcorpus.store.opSearchDocset') }))
      return true
    } catch (err) {
      const message = err instanceof Error ? err.message : t('subcorpus.store.buildFailed')
      error.value = message
      if (run) failDocsetRun(run, err, message)
      return false
    } finally {
      isBuildingDocset.value = false
    }
  }

  /**
   * Build a metadata-only subcorpus (no search) from the current op-tagged
   * filter spec via `docset_from_meta`.
   */
  async function buildDocsetFromMeta(spec?: FilterSpec): Promise<boolean> {
    const filterSpec = spec ?? _filterSpecPayload()
    if (!Object.keys(filterSpec).length) {
      resetDocset()
      isDirty.value = false
      return true
    }
    isBuildingDocset.value = true
    error.value = null
    let run: ProductOperationRunRecord | null = null
    try {
      if (!(await ensureDocsetSurfaceAccess(
        t('subcorpus.store.opMetaDocset'),
        DOCSET_OPERATIONS.docsetFromMeta,
        t('subcorpus.store.applyMetaFilter'),
      ))) {
        isDirty.value = false
        return false
      }
      run = startDocsetRun(
        DOCSET_OPERATIONS.docsetFromMeta,
        `meta:${activeCorpus.value}:${Date.now()}`,
        t('subcorpus.store.opMetaDocset'),
        filterSpecSummaryParts(filterSpec).join(', ') || activeCorpus.value,
      )
      const result = await docsetFromMeta(filterSpec, activeCorpus.value)
      activeDocsetId.value = result.docset_id
      activeFilterSpec.value = { ...filterSpec }
      activeDocsetOrigin.value = { kind: 'meta' }
      stats.value = {
        docCount: result.doc_count ?? 0,
        hitDocCount: 0,
        refDocCount: 0,
        tokenCount: result.token_count ?? 0,
      }
      setResolveEvidence({ stale: false })
      lastCorpus.value = activeCorpus.value
      isDirty.value = false
      finishDocsetRun(run, t('subcorpus.store.computed', { label: t('subcorpus.store.opMetaDocset') }))
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : t('subcorpus.store.buildFailed')
      if (run) failDocsetRun(run, err, error.value)
      return false
    } finally {
      isBuildingDocset.value = false
    }
  }

  /**
   * Narrow the active scope by one metadata condition and make the result the
   * active scope, as a filter set by hand would. Without a scope the condition
   * alone is the scope, a metadata scope gets the condition added, and a scope
   * built from the hits of a query is built again with the condition. The
   * back path from a trend period uses it.
   */
  async function narrowScope(field: string, value: FilterSpecValue): Promise<boolean> {
    const origin = activeDocsetOrigin.value
    const base = hasActiveDocset.value ? deriveFilterSpecFromLegacy(filters.value, activeFilterSpec.value) : {}
    const spec: FilterSpec = { ...base, [field]: value }
    activeSubcorpusName.value = null
    if (hasActiveDocset.value && origin?.kind === 'search') {
      filters.value = legacyFiltersFromSpec(spec)
      activeFilterSpec.value = spec
      return buildDocset(true, origin.query)
    }
    return buildDocsetFromMeta(spec)
  }

  /**
   * Replace the active scope by a metadata scope. The back path from a
   * contrast row opens the concordance in the group of that row.
   */
  async function setMetaScope(spec: FilterSpec): Promise<boolean> {
    activeSubcorpusName.value = null
    filters.value = legacyFiltersFromSpec(spec)
    return buildDocsetFromMeta({ ...spec })
  }

  // When the corpus changes, reload the schema + options and mark stale.
  // Before the catalog has answered, no corpus is chosen yet: the schema of
  // the implicit "default" is not requested then (on a first start without a
  // corpus the server answers 503). It loads when the catalog names a corpus.
  const waitsForCatalog = () => !queryStore.filters.corpus?.trim() && !corpusCapabilities.loaded
  watch(
    activeCorpus,
    (corpus, previousCorpus) => {
      if (previousCorpus !== undefined && corpus !== previousCorpus) {
        resetScopeForCorpusChange(corpus)
      }
      if (waitsForCatalog()) return
      void loadMetaSchema(true)
    },
    { immediate: true }
  )
  watch(
    () => corpusCapabilities.loaded,
    (loaded, wasLoaded) => {
      // With an active corpus in the catalog the corpus watcher above loads it.
      if (loaded && !wasLoaded && !queryStore.filters.corpus?.trim()) void loadMetaSchema(true)
    },
  )

  // A metadata-only scope remains valid for every search term. A query-built
  // scope instead has to be rebuilt before a different query may use it.
  watch(
    () => queryStore.term,
    (term) => {
      if (!term.trim()) {
        resetDocset()
        isDirty.value = false
        return
      }
      if (
        hasActiveDocset.value &&
        activeDocsetOrigin.value?.kind !== 'meta' &&
        (activeDocsetOrigin.value?.kind === 'search' || filtersActive.value)
      ) {
        markDirty()
      }
    }
  )

  return {
    // State
    filters,
    includeAi,
    includeHuman,
    activeDocsetId,
    stats,
    metaOptions,
    metaFields,
    metaSchemaHash,
    metaFieldValueCounts,
    activeFilterSpec,
    activeDocsetOrigin,
    isLoadingOptions,
    isBuildingDocset,
    error,
    isDirty,
    activeScopeStale,
    activeScopeWarning,
    activeScopeResolvedAt,
    activeSubcorpusName,
    lastQuery,
    lastCorpus,
    // Computed
    activeCorpus,
    enumFields,
    rangeFields,
    textFields,
    hasLegacyMetaFields,
    filtersActive,
    hasActiveDocset,
    scopeLabel,
    summaryParts,
    metaSchemaAvailability,
    metaValuesAvailability,
    metaCountsAvailability,
    docsetFromMetaAvailability,
    docsetFromSearchAvailability,
    docsetIntersectionAvailability,
    subcorpusResolveAvailability,
    canLoadMetaSchema,
    canLoadMetaValues,
    canLoadMetaCounts,
    canBuildDocsetFromMeta,
    canBuildDocsetFromSearch,
    canBuildDocsetIntersection,
    canResolveSubcorpus,
    // Actions
    markDirty,
    setFilter,
    setIncludeAi,
    setIncludeHuman,
    clearFilters,
    resetDocset,
    fetchMetaSchema,
    fetchMetaValues,
    fetchMetaValuesPage,
    fetchMetaCounts,
    createTransientDocsetFromMeta,
    resolveNamedSubcorpusDocset,
    fetchDocsetIntersection,
    applySnapshot,
    resolveDocset,
    loadMetaSchema,
    loadMetaOptions,
    loadModelOptionsForPrompt,
    buildDocset,
    buildDocsetFromMeta,
    buildHitsDocset,
    narrowScope,
    setMetaScope,
  }
})
