/**
 * Subcorpora Store - durable, named subcorpus definitions.
 *
 * The backend holds the durable identity (a `SubcorpusDefinition` keyed by name);
 * `docsetId` is only a transient cache hint and is re-resolved at runtime via the
 * docset store. We keep a local `SubcorpusSnapshot` model (the UI representation)
 * in sync with the backend after the pattern used by `analysisPresets.ts`:
 * `init()` loads `GET /subcorpora` (with a one-time localStorage migration as a
 * fallback), `add()` POSTs, `remove()` confirms before local removal and DELETEs.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useProductCapabilitiesStore, type ProductOperationAccessOptions } from './productCapabilities'
import { useProductOperationRunsStore, type ProductOperationRunRecord } from './productOperationRuns'
import {
  listSubcorpora,
  saveSubcorpus,
  deleteSubcorpus,
  resolveSubcorpus,
  type FilterSpec,
  type SubcorpusDefinition,
} from '@/api/client'
import {
  deriveFilterSpecFromLegacy,
  filterSpecSummaryParts,
  legacyFiltersFromSpec,
} from '@/lib/filterSpec'
import { formatDate } from '@/i18n/format'
import { t } from '@/i18n'

export type SubcorpusStatus = 'parked' | 'archived'
export type SubcorpusOriginType = 'query' | 'filter' | 'intersection'
export type SubcorpusResolutionStatus = 'unresolved' | 'fresh' | 'stale' | 'error'

export interface SubcorpusOrigin {
  type: SubcorpusOriginType
  query?: string
  label?: string
}

export interface SubcorpusResolution {
  status: SubcorpusResolutionStatus
  stale: boolean
  resolvedAt?: number
  message?: string
}

export interface SubcorpusSnapshot {
  id: string
  name: string
  status: SubcorpusStatus
  createdAt: number
  corpus: string
  /** Transient cache hint only — NOT the identity. May be empty after a restart. */
  docsetId?: string
  stats: {
    docCount: number
    tokenCount: number
    refDocCount: number
  }
  /**
   * Whether `stats` reflects a real resolve (true) or is an unresolved
   * placeholder (false/undefined). Snapshots rehydrated from the backend have
   * no stored counts, so they start unresolved and are filled in lazily via
   * `resolveStats()`. Render sites can show "—"/"wird berechnet" while false.
   */
  statsResolved?: boolean
  filters: {
    prompting_method: string[]
    model: string[]
    register: string[]
    source: string[]
  }
  /** Op-tagged, field-agnostic filter spec (durable, sent to the backend). */
  filterSpec?: FilterSpec
  includeAi: boolean
  includeHuman: boolean
  origin: SubcorpusOrigin
  /** Schema hash captured when the definition was saved (staleness detection). */
  metadataSchemaHash?: string
  /** Latest backend resolve/evidence status for reproducibility warnings. */
  resolution?: SubcorpusResolution
}

const STORAGE_KEY = 'candyconc_subcorpora'
const ARCHIVED_PREFIX = '[archived] '
export const SUBCORPORA_OPERATIONS = {
  list: 'research.subcorpora_docsets.subcorpora_list',
  save: 'research.subcorpora_docsets.subcorpora_save',
  delete: 'research.subcorpora_docsets.subcorpora_delete',
  resolve: 'research.subcorpora_docsets.subcorpora_resolve',
} as const

function parseSnapshots(raw: unknown): SubcorpusSnapshot[] {
  if (!raw) return []
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item) => item && typeof item.id === 'string') as SubcorpusSnapshot[]
  } catch {
    return []
  }
}

function snapshotToDefinition(snapshot: SubcorpusSnapshot): SubcorpusDefinition {
  const filterSpec = deriveFilterSpecFromLegacy(snapshot.filters, snapshot.filterSpec)
  // The backend key is the (status-tagged) name so parked/archived can coexist.
  const name = snapshot.status === 'archived' ? `${ARCHIVED_PREFIX}${snapshot.name}` : snapshot.name
  const aiFilters: Record<string, string | string[]> = {}
  if (snapshot.filters.model.length) aiFilters.model = [...snapshot.filters.model]
  if (snapshot.filters.prompting_method.length) {
    aiFilters.prompting_method = [...snapshot.filters.prompting_method]
  }
  return {
    name,
    corpus: snapshot.corpus,
    query: snapshot.origin.query ?? null,
    filter_spec: filterSpec,
    include_ai: snapshot.includeAi,
    include_human: snapshot.includeHuman,
    ai_filters: Object.keys(aiFilters).length ? aiFilters : null,
    metadata_schema_hash: snapshot.metadataSchemaHash ?? null,
    created_at: snapshot.createdAt,
  }
}

function definitionToSnapshot(def: SubcorpusDefinition): SubcorpusSnapshot {
  const isArchived = def.name.startsWith(ARCHIVED_PREFIX)
  const displayName = isArchived ? def.name.slice(ARCHIVED_PREFIX.length) : def.name
  const filters = legacyFiltersFromSpec(def.filter_spec)
  return {
    id: def.name, // durable backend key is the identity
    name: displayName,
    status: isArchived ? 'archived' : 'parked',
    createdAt: def.created_at ?? Date.now(),
    corpus: def.corpus,
    docsetId: undefined, // re-resolved at runtime; never trusted from storage
    // The backend definition carries no counts; leave them unresolved (rather
    // than misleading 0s) and let `resolveStats()` fill them in lazily.
    stats: { docCount: 0, tokenCount: 0, refDocCount: 0 },
    statsResolved: false,
    filters,
    filterSpec: def.filter_spec,
    includeAi: def.include_ai ?? true,
    includeHuman: def.include_human ?? true,
    origin: def.query ? { type: 'query', query: def.query } : { type: 'filter' },
    metadataSchemaHash: def.metadata_schema_hash ?? undefined,
    resolution: { status: 'unresolved', stale: false },
  }
}

function resolutionFromResolve(stale: boolean): SubcorpusResolution {
  return {
    status: stale ? 'stale' : 'fresh',
    stale,
    resolvedAt: Date.now(),
    message: stale
      ? t('subcorpus.saved.schemaChanged')
      : undefined,
  }
}

export const useSubcorporaStore = defineStore('subcorpora', () => {
  const productCapabilities = useProductCapabilitiesStore()
  const operationRuns = useProductOperationRunsStore()
  const snapshots = ref<SubcorpusSnapshot[]>([])
  const initialized = ref(false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  const parked = computed(() => snapshots.value.filter((s) => s.status === 'parked'))
  const archived = computed(() => snapshots.value.filter((s) => s.status === 'archived'))
  const listAvailability = computed(() =>
    productCapabilities.productOperationAvailability(SUBCORPORA_OPERATIONS.list)
  )
  const saveAvailability = computed(() =>
    productCapabilities.productOperationAvailability(SUBCORPORA_OPERATIONS.save)
  )
  const deleteAvailability = computed(() =>
    productCapabilities.productOperationAvailability(SUBCORPORA_OPERATIONS.delete)
  )
  const resolveAvailability = computed(() =>
    productCapabilities.productOperationAvailability(SUBCORPORA_OPERATIONS.resolve)
  )
  const canLoadSubcorpora = computed(() => listAvailability.value.enabled)
  const canSaveSubcorpora = computed(() => saveAvailability.value.enabled)
  const canDeleteSubcorpora = computed(() => deleteAvailability.value.enabled)
  const canResolveSubcorpora = computed(() => resolveAvailability.value.enabled)

  function deny(reason: string | null, fallback: string): false {
    error.value = reason ?? fallback
    return false
  }

  function startResolveRun(snapshot: SubcorpusSnapshot): ProductOperationRunRecord {
    return operationRuns.startRun({
      operationId: SUBCORPORA_OPERATIONS.resolve,
      sourceId: snapshot.id,
      kind: 'operation',
      surfaceId: 'research.subcorpora_docsets',
      label: t('subcorpus.saved.resolveRun', { name: snapshot.name }),
      detail: snapshot.corpus,
      status: 'running',
      progress: 5,
      message: t('subcorpus.saved.resolveRunning'),
    })
  }

  function persistLocal() {
    // Local mirror so the UI survives a transient backend outage.
    localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshots.value))
  }

  async function ensureSubcorporaOperationAccess(
    label: string,
    operationId: string,
    options: ProductOperationAccessOptions = {},
  ): Promise<boolean> {
    try {
      await productCapabilities.assertProductOperationAccess(operationId, label, options)
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : t('subcorpus.saved.notEnabled', { label })
      return false
    }
  }

  function subcorporaSurfaceConfirmation(interaction: string): ProductOperationAccessOptions {
    return {
      contextualConfirmation: {
        surfaceId: 'research.subcorpora_docsets',
        interaction,
        source: 'native_surface',
      },
    }
  }

  /** Fire-and-forget durable save; keeps the local model authoritative for the UI. */
  function syncSave(snapshot: SubcorpusSnapshot) {
    if (!canSaveSubcorpora.value) {
      error.value = saveAvailability.value.disabledReason ?? t('subcorpus.saved.saveBlocked')
      return
    }
    const def = snapshotToDefinition(snapshot)
    void (async () => {
      if (!(await ensureSubcorporaOperationAccess(t('subcorpus.saved.opSave'), SUBCORPORA_OPERATIONS.save))) {
        return
      }
      saveSubcorpus({
        name: def.name,
        corpus: def.corpus,
        filter_spec: def.filter_spec,
        query: def.query,
        include_ai: def.include_ai,
        include_human: def.include_human,
        ai_filters: def.ai_filters,
      }).catch((err) => {
        error.value = err instanceof Error ? err.message : t('subcorpus.saved.saveFailed')
      })
    })()
  }

  async function confirmDelete(): Promise<boolean> {
    if (!canDeleteSubcorpora.value) {
      error.value = deleteAvailability.value.disabledReason ?? t('subcorpus.saved.deleteBlocked')
      return false
    }
    return ensureSubcorporaOperationAccess(t('subcorpus.saved.opDelete'), SUBCORPORA_OPERATIONS.delete)
  }

  function deleteDurably(snapshot: SubcorpusSnapshot) {
    const def = snapshotToDefinition(snapshot)
    deleteSubcorpus(def.name).catch(() => {
      // Already-removed definitions are fine; ignore.
    })
  }

  async function migrateLocal(localSnapshots: SubcorpusSnapshot[]) {
    await productCapabilities.ensureAccessContext()
    if (!canSaveSubcorpora.value) return
    for (const snapshot of localSnapshots) {
      try {
        await saveSubcorpus({
          name: snapshotToDefinition(snapshot).name,
          corpus: snapshot.corpus,
          filter_spec: deriveFilterSpecFromLegacy(snapshot.filters, snapshot.filterSpec),
          query: snapshot.origin.query ?? null,
          include_ai: snapshot.includeAi,
          include_human: snapshot.includeHuman,
        })
      } catch {
        // Ignore individual migration failures.
      }
    }
  }

  async function init() {
    if (isLoading.value) return
    isLoading.value = true
    error.value = null
    const localSnapshots = parseSnapshots(localStorage.getItem(STORAGE_KEY))
    try {
      await productCapabilities.ensureAccessContext()
      if (!canLoadSubcorpora.value) {
        error.value = listAvailability.value.disabledReason ?? t('subcorpus.saved.listBlocked')
        snapshots.value = []
        initialized.value = true
        return
      }
      const defs = await listSubcorpora()
      if (!defs.length && localSnapshots.length) {
        await migrateLocal(localSnapshots)
        const migrated = await listSubcorpora()
        snapshots.value = migrated.map(definitionToSnapshot)
      } else {
        snapshots.value = defs.map(definitionToSnapshot)
      }
      initialized.value = true
      persistLocal()
    } catch (err) {
      // Offline / backend not ready: fall back to the local mirror.
      error.value = err instanceof Error ? err.message : t('subcorpus.saved.listFailed')
      snapshots.value = localSnapshots
      initialized.value = true
    } finally {
      isLoading.value = false
    }
  }

  function ensureInit() {
    if (!initialized.value) void init()
  }

  function add(snapshot: SubcorpusSnapshot): boolean {
    ensureInit()
    if (!canSaveSubcorpora.value) {
      return deny(saveAvailability.value.disabledReason, t('subcorpus.saved.saveBlocked'))
    }
    snapshots.value = [snapshot, ...snapshots.value.filter((s) => s.id !== snapshot.id)]
    persistLocal()
    syncSave(snapshot)
    return true
  }

  function createSnapshot(input: Omit<SubcorpusSnapshot, 'id' | 'createdAt'>): SubcorpusSnapshot {
    return {
      ...input,
      filterSpec: input.filterSpec ?? deriveFilterSpecFromLegacy(input.filters),
      // Snapshots created from a live docset build carry real counts, so treat
      // them as resolved unless the caller says otherwise.
      statsResolved: input.statsResolved ?? true,
      resolution: input.resolution ?? { status: 'fresh', stale: false, resolvedAt: Date.now() },
      id: crypto.randomUUID(),
      createdAt: Date.now(),
    }
  }

  function durableNameForSnapshot(snapshot: SubcorpusSnapshot): string {
    return snapshotToDefinition(snapshot).name
  }

  /**
   * Lazily fill in real doc/token counts for snapshots that were rehydrated
   * from the backend (which carries no stored counts). Mutates snapshots in
   * place so render sites reactively pick up the resolved numbers instead of
   * the placeholder zeros. Resolves sequentially and tolerates per-subcorpus
   * failures so one dead definition never blocks the rest.
   *
   * NOTE: the `/subcorpora/{name}/resolve` endpoint returns doc_count and
   * token_count only — refDocCount is NOT available here and stays 0 until a
   * full docset build runs (see FLAG in the change report).
   */
  async function resolveStats(force = false) {
    if (!initialized.value) {
      await init()
    } else {
      await productCapabilities.ensureAccessContext()
    }
    if (!canResolveSubcorpora.value) {
      error.value = resolveAvailability.value.disabledReason ?? t('subcorpus.saved.resolveBlocked')
      return
    }
    if (!(await ensureSubcorporaOperationAccess(
      t('subcorpus.saved.opResolve'),
      SUBCORPORA_OPERATIONS.resolve,
      subcorporaSurfaceConfirmation(t('subcorpus.saved.resolveOverview')),
    ))) {
      return
    }
    const pending = snapshots.value.filter((s) => force || !s.statsResolved)
    for (const snapshot of pending) {
      const run = startResolveRun(snapshot)
      try {
        const result = await resolveSubcorpus(
          snapshotToDefinition(snapshot).name,
          snapshot.corpus
        )
        const idx = snapshots.value.findIndex((s) => s.id === snapshot.id)
        if (idx === -1) continue
        const current = snapshots.value[idx]!
        snapshots.value[idx] = {
          ...current,
          docsetId: result.docset_id,
          stats: {
            docCount: result.doc_count,
            tokenCount: result.token_count,
            // Not returned by the resolve endpoint; preserve any prior value.
            refDocCount: current.stats.refDocCount,
          },
          statsResolved: true,
          resolution: resolutionFromResolve(Boolean(result.stale)),
        }
        operationRuns.finishRun(run.id, t('subcorpus.saved.resolveDone'))
      } catch {
        operationRuns.failRun(run.id, t('subcorpus.saved.resolveFailed'))
        // Offline / dead definition: leave it unresolved so render sites keep
        // showing the "—"/"wird berechnet" placeholder rather than a fake 0.
        const idx = snapshots.value.findIndex((s) => s.id === snapshot.id)
        if (idx !== -1) {
          const current = snapshots.value[idx]!
          snapshots.value[idx] = {
            ...current,
            resolution: {
              status: 'error',
              stale: false,
              resolvedAt: Date.now(),
              message: t('subcorpus.saved.resolveFailed'),
            },
          }
        }
      }
    }
    persistLocal()
  }

  function suggestName(params: {
    term?: string
    corpus?: string
    filters: {
      prompting_method: string[]
      model: string[]
      register: string[]
      source: string[]
    }
    includeAi: boolean
    includeHuman: boolean
    filterSpec?: FilterSpec | null
  }): string {
    const parts: string[] = []
    const term = params.term?.trim()
    if (term) parts.push(t('subcorpus.naming.query', { term }))

    const label = (name: string, values: string[]) => {
      if (!values.length) return null
      if (values.length === 1) return `${name} ${values[0]}`
      return `${name} (${values.length})`
    }

    const legacyParts: string[] = []
    const prompt = label(t('subcorpus.naming.prompt'), params.filters.prompting_method)
    if (prompt) legacyParts.push(prompt)
    const model = label(t('subcorpus.naming.model'), params.filters.model)
    if (model) legacyParts.push(model)
    const reg = label(t('subcorpus.naming.register'), params.filters.register)
    if (reg) legacyParts.push(reg)
    const src = label(t('subcorpus.naming.source'), params.filters.source)
    if (src) legacyParts.push(src)
    parts.push(...legacyParts)
    if (!legacyParts.length) {
      parts.push(...filterSpecSummaryParts(params.filterSpec).slice(0, 2))
    }

    if (params.includeAi && !params.includeHuman) parts.push(t('subcorpus.naming.ai'))
    if (params.includeHuman && !params.includeAi) parts.push(t('subcorpus.naming.human'))

    if (!parts.length) {
      const date = formatDate(new Date())
      return t('subcorpus.naming.dated', { date })
    }

    let name = parts.join(' · ')
    if (name.length > 120) {
      name = `${name.slice(0, 117)}…`
    }
    return name
  }

  async function update(id: string, updates: Partial<SubcorpusSnapshot>): Promise<boolean> {
    ensureInit()
    const idx = snapshots.value.findIndex((s) => s.id === id)
    if (idx === -1) return false
    const previous = snapshots.value[idx]
    if (!previous) return false
    const next = { ...previous, ...updates } as SubcorpusSnapshot
    const oldKey = snapshotToDefinition(previous).name
    const newKey = snapshotToDefinition(next).name
    if (!canSaveSubcorpora.value) {
      return deny(saveAvailability.value.disabledReason, t('subcorpus.saved.saveBlocked'))
    }
    if (oldKey !== newKey && !canDeleteSubcorpora.value) {
      return deny(deleteAvailability.value.disabledReason, t('subcorpus.saved.renameBlocked'))
    }
    if (oldKey !== newKey && !(await confirmDelete())) {
      return false
    }
    snapshots.value[idx] = next
    persistLocal()

    // A durable update is a delete-of-old-key + save-of-new-key whenever the
    // backend key (name or status) changed; otherwise a plain re-save.
    if (oldKey !== newKey) {
      deleteDurably(previous)
    }
    syncSave(next)
    return true
  }

  async function remove(id: string): Promise<boolean> {
    ensureInit()
    if (!canDeleteSubcorpora.value) {
      return deny(deleteAvailability.value.disabledReason, t('subcorpus.saved.deleteBlocked'))
    }
    const target = snapshots.value.find((s) => s.id === id)
    if (target && !(await confirmDelete())) {
      return false
    }
    snapshots.value = snapshots.value.filter((s) => s.id !== id)
    persistLocal()
    if (target) deleteDurably(target)
    return true
  }

  async function move(id: string, status: SubcorpusStatus): Promise<boolean> {
    ensureInit()
    return update(id, { status })
  }

  function markResolved(
    id: string,
    updates: Pick<SubcorpusSnapshot, 'docsetId' | 'stats' | 'statsResolved' | 'resolution'>
  ) {
    ensureInit()
    const idx = snapshots.value.findIndex((s) => s.id === id)
    if (idx === -1) return
    const current = snapshots.value[idx]!
    snapshots.value[idx] = { ...current, ...updates }
    persistLocal()
  }

  return {
    snapshots,
    parked,
    archived,
    initialized,
    isLoading,
    error,
    listAvailability,
    saveAvailability,
    deleteAvailability,
    resolveAvailability,
    canLoadSubcorpora,
    canSaveSubcorpora,
    canDeleteSubcorpora,
    canResolveSubcorpora,
    init,
    add,
    createSnapshot,
    durableNameForSnapshot,
    suggestName,
    update,
    remove,
    move,
    markResolved,
    resolveStats,
  }
})
