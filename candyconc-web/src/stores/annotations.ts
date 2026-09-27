/**
 * Annotations Store (F7) — row-level KWIC annotation layer + coding scheme.
 *
 * Annotations are keyed LOCALLY by a STABLE, CORPUS-NAMESPACED `row_id` so they
 * survive re-querying, re-sorting and paging AND never alias across corpora:
 * `${corpus}::${file}:${pos}` when a document id + corpus position are available,
 * otherwise `${corpus}::h:${hash}` over the raw KWIC text (left|match|right).
 *
 * The corpus prefix is essential: `docId` is a per-corpus integer index that
 * restarts at 0 for every corpus, so a bare `${docId}:${pos}` would collide
 * (and overwrite annotations) between corpora.
 *
 * The BACKEND `row_id` is the bare `${file}:${pos}` / `h:${hash}` and the corpus
 * travels as a separate `corpus` param on every GET/PUT/DELETE so the server
 * scopes persistence. The store splits its local namespaced key back into
 * `{corpus, rowId}` before each API call (see `splitRowId`).
 *
 * Each row carries at most ONE category plus a free-text note (per spec —
 * single-select coding). Writes are optimistic: the local map is mutated
 * immediately and rolled back if the backend rejects the change.
 *
 * Span-level annotation is explicitly future work; only row-level state lives
 * here today.
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { type KwicRow } from './query'
import { useDocsetStore } from './docset'
import {
  useProductCapabilitiesStore,
} from './productCapabilities'
import {
  getAnnotations,
  putAnnotation,
  deleteAnnotation,
  getAnnotationScheme,
  previewAnnotationScheme,
  putAnnotationScheme,
  getAnnotationAgreement,
  getAnnotationSettings,
  putAnnotationSettings,
  type AnnotationCategory,
  type AnnotationRecord,
  type AgreementResult,
  type AnnotationSchemePreview,
} from '@/api/client'
import { quickHash } from '@/utils/hashing'
import { t } from '@/i18n'

export type { AnnotationCategory, AnnotationRecord, AgreementResult }

/** Separator between the corpus prefix and the bare backend row id. */
const CORPUS_SEP = '::'
const DEFAULT_LOCAL_ANNOTATOR = 'local-annotator'
/** The coder name of this browser, kept across reloads. */
const ANNOTATOR_STORAGE_KEY = 'candyconc_annotator'

function readStoredAnnotator(): string {
  try {
    const stored = window.localStorage.getItem(ANNOTATOR_STORAGE_KEY)
    return typeof stored === 'string' && stored.trim() ? stored.trim() : DEFAULT_LOCAL_ANNOTATOR
  } catch {
    return DEFAULT_LOCAL_ANNOTATOR
  }
}

function storeAnnotator(name: string): void {
  try {
    if (name === DEFAULT_LOCAL_ANNOTATOR) window.localStorage.removeItem(ANNOTATOR_STORAGE_KEY)
    else window.localStorage.setItem(ANNOTATOR_STORAGE_KEY, name)
  } catch {
    // Storage blocked: the name holds for this page only.
  }
}

export const ANNOTATION_OPERATIONS = {
  read: 'research.annotations.read',
  write: 'research.annotations.write',
  delete: 'research.annotations.delete',
  schemeRead: 'research.annotations.scheme_read',
  schemePreview: 'research.annotations.scheme_preview',
  schemeWrite: 'research.annotations.scheme_write',
  settingsRead: 'research.annotations.settings_read',
  settingsWrite: 'research.annotations.settings_write',
  agreement: 'research.annotations.agreement',
} as const

type AnnotationOperationId = (typeof ANNOTATION_OPERATIONS)[keyof typeof ANNOTATION_OPERATIONS]

export type AnnotationSchemeSaveResult =
  | { status: 'saved' }
  | { status: 'confirmation_required'; preview: AnnotationSchemePreview }
  | { status: 'stale'; preview: AnnotationSchemePreview }

/**
 * Compute a stable, CORPUS-NAMESPACED row id for a KWIC row.
 *
 * The bare id alone is NOT unique across corpora: `docId` is a per-corpus
 * integer index that restarts at 0 per corpus, so `${docId}:${pos}` aliases
 * between corpora. Prefixing with the active `corpus` makes the local key unique.
 *
 * Bare-id preference order (then prefixed with `${corpus}::`):
 *  1. `${docId}:${position}` — survives sort/paging/re-query (the backend key).
 *  2. `h:${hash}` of `left|match|right` — fallback when no doc/pos identity exists.
 */
export function rowIdFor(
  row: Pick<KwicRow, 'docId' | 'position' | 'left' | 'match' | 'right'>,
  corpus: string
): string {
  return `${corpus}${CORPUS_SEP}${bareRowIdFor(row)}`
}

/** The bare (corpus-agnostic) backend row id: `${docId}:${pos}` or `h:${hash}`. */
export function bareRowIdFor(
  row: Pick<KwicRow, 'docId' | 'position' | 'left' | 'match' | 'right'>
): string {
  const file = row.docId
  const pos = row.position
  if (file && file !== 'unknown' && Number.isFinite(pos)) {
    return `${file}:${pos}`
  }
  return `h:${quickHash(`${row.left ?? ''}|${row.match ?? ''}|${row.right ?? ''}`)}`
}

/**
 * Split a locally namespaced row id back into `{corpus, rowId}` for the backend.
 * `rowId` is the BARE id the server expects; `corpus` is the scoping param.
 * Falls back to an empty corpus + the whole string if no separator is present
 * (e.g. a legacy/bare id), keeping API calls well-formed.
 */
export function splitRowId(namespacedId: string): { corpus: string; rowId: string } {
  const idx = namespacedId.indexOf(CORPUS_SEP)
  if (idx === -1) return { corpus: '', rowId: namespacedId }
  return {
    corpus: namespacedId.slice(0, idx),
    rowId: namespacedId.slice(idx + CORPUS_SEP.length),
  }
}

export const useAnnotationsStore = defineStore('annotations', () => {
  const docsetStore = useDocsetStore()
  const productCapabilities = useProductCapabilitiesStore()

  // row_id -> annotation record
  const annotations = ref<Record<string, AnnotationRecord>>({})
  const categories = ref<AnnotationCategory[]>([])
  const schemeRevision = ref(0)

  const isLoading = ref(false)
  const isSavingScheme = ref(false)
  const error = ref<string | null>(null)

  /** Active annotator name attached to new/updated annotations. */
  const annotator = ref<string>(readStoredAnnotator())

  /** Filter-by-category UI state: null = show all, '' = uncategorized only. */
  const filterCategoryId = ref<string | null>(null)
  const filterEnabled = ref(false)

  // ── Multi-coder + inter-annotator agreement (FT-ANNOTATION-RESEARCH) ──
  // Opt-in: single-coder remains the default. When enabled, the agreement panel
  // loads IAA from the backend. The agreement result is defensive (degrades to
  // an empty result when the endpoint is absent), so enabling this never breaks
  // the single-coder flow.
  const multiCoderEnabled = ref(false)
  const agreement = ref<AgreementResult | null>(null)
  const isLoadingAgreement = ref(false)
  const agreementError = ref<string | null>(null)
  // Agreement is currently corpus-wide; an active KWIC docset must be named
  // honestly rather than sent to an endpoint that cannot apply it.
  const agreementNotice = ref<string | null>(null)
  let agreementSeq = 0
  // Ordering guard for the backend multi-coder setting hydrate (rapid corpus
  // switches must not let a stale settings read win).
  let settingsSeq = 0

  async function loadAgreement(): Promise<void> {
    const seq = ++agreementSeq
    isLoadingAgreement.value = true
    agreementError.value = null
    agreementNotice.value = null
    try {
      await assertAnnotationOperation(ANNOTATION_OPERATIONS.agreement, t('kwic.annotations.loadAgreement'))
      const corpus = docsetStore.activeCorpus || undefined
      const result = await getAnnotationAgreement({ corpus })
      if (seq !== agreementSeq) return
      agreement.value = result
      if (docsetStore.hasActiveDocset) {
        agreementNotice.value = t('kwic.annotations.agreementCorpusWide')
      }
    } catch (err) {
      if (seq !== agreementSeq) return
      agreementError.value = err instanceof Error ? err.message : t('kwic.annotations.agreementFailed')
    } finally {
      if (seq === agreementSeq) isLoadingAgreement.value = false
    }
  }

  /**
   * Toggle multi-coder mode. CRITICAL: this must drive the BACKEND `multi_coder`
   * setting (PUT /annotations/settings), not just local UI state — without the
   * server actually being in multi-coder mode, every coder writes the same
   * single slot, so IAA overlap is structurally 0 and the agreement panel can
   * never show anything. The local flag is applied optimistically and rolled
   * back if the persist fails.
   */
  async function setMultiCoder(enabled: boolean): Promise<void> {
    const previous = multiCoderEnabled.value
    agreementError.value = null
    try {
      await assertAnnotationOperation(ANNOTATION_OPERATIONS.settingsWrite, t('kwic.annotations.saveMultiCoder'))
      multiCoderEnabled.value = enabled
      const { multiCoder } = await putAnnotationSettings(enabled)
      multiCoderEnabled.value = multiCoder
    } catch (err) {
      multiCoderEnabled.value = previous
      agreementError.value = err instanceof Error ? err.message : t('kwic.annotations.multiCoderFailed')
      throw err
    }
    if (multiCoderEnabled.value) await loadAgreement()
  }

  /** Hydrate the local multi-coder flag from the backend (project setting). */
  async function loadMultiCoderSetting(): Promise<void> {
    const seq = ++settingsSeq
    try {
      await assertAnnotationOperation(ANNOTATION_OPERATIONS.settingsRead, t('kwic.annotations.loadSettings'))
      const { multiCoder } = await getAnnotationSettings()
      if (seq !== settingsSeq) return
      multiCoderEnabled.value = multiCoder
      if (multiCoder) {
        await load()
        await loadAgreement()
      }
    } catch {
      // Defensive: a missing settings route leaves the single-coder default.
    }
  }

  // Ordering guard: rapid corpus/docset switches must not let a stale load win.
  let loadSeq = 0

  function invalidatePendingLoads(): void {
    loadSeq += 1
  }

  // Per-row write ordering guard: a late-resolving earlier write must not clobber
  // a newer value. Each write captures the current seq for its row; on resolve or
  // rollback it only applies if its captured seq is still the latest (mirrors
  // loadSeq, but keyed per row so concurrent rows stay independent).
  const writeSeq = new Map<string, number>()
  function nextWriteSeq(rowId: string): number {
    const seq = (writeSeq.get(rowId) ?? 0) + 1
    writeSeq.set(rowId, seq)
    return seq
  }
  function isLatestWrite(rowId: string, seq: number): boolean {
    return writeSeq.get(rowId) === seq
  }

  function annotationOperationBlockReason(operationId: AnnotationOperationId, label: string): string | null {
    // A missing operation must name the researcher-facing action, not the
    // capability plumbing that happened to reject it.
    const availability = productCapabilities.productOperationAvailability(operationId, label)
    if (availability.enabled) return null
    return availability.disabledReason ?? t('kwic.annotations.notEnabled', { label })
  }

  async function assertAnnotationOperation(operationId: AnnotationOperationId, label: string): Promise<void> {
    await productCapabilities.ensureAccessContext()
    const reason = annotationOperationBlockReason(operationId, label)
    if (reason) throw new Error(reason)
  }

  function assertAnnotationMutation(
    operationId: AnnotationOperationId,
    label: string,
  ): Promise<void> | undefined {
    // Coding and uncoding a single KWIC row are direct, reversible research
    // actions. The capability contract still gates them, but they must never
    // turn a keyboard shortcut into a native confirmation loop. Destructive
    // scheme changes are reviewed separately through the scheme preview.
    if (!productCapabilities.hasContract) {
      return assertAnnotationOperation(operationId, label)
    }
    const reason = annotationOperationBlockReason(operationId, label)
    if (reason) throw new Error(reason)
    return undefined
  }

  const canReadAnnotations = computed(() =>
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.read).enabled
  )
  const canWriteAnnotations = computed(() =>
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.write).enabled
  )
  const canDeleteAnnotations = computed(() =>
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.delete).enabled
  )
  const canEditScheme = computed(() =>
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.schemePreview).enabled &&
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.schemeWrite).enabled
  )
  const canReadScheme = computed(() =>
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.schemeRead).enabled
  )
  const canManageMultiCoder = computed(() =>
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.settingsWrite).enabled
  )
  const canLoadAgreement = computed(() =>
    productCapabilities.productOperationAvailability(ANNOTATION_OPERATIONS.agreement).enabled
  )
  const annotationsReadBlockReason = computed(() =>
    annotationOperationBlockReason(ANNOTATION_OPERATIONS.read, t('kwic.annotations.load'))
  )
  const annotationsWriteBlockReason = computed(() =>
    annotationOperationBlockReason(ANNOTATION_OPERATIONS.write, t('kwic.annotations.save'))
  )
  const schemeWriteBlockReason = computed(() =>
    annotationOperationBlockReason(ANNOTATION_OPERATIONS.schemePreview, t('kwic.annotations.checkSchemeChange')) ??
    annotationOperationBlockReason(ANNOTATION_OPERATIONS.schemeWrite, t('kwic.annotations.saveScheme'))
  )
  const schemeReadBlockReason = computed(() =>
    annotationOperationBlockReason(ANNOTATION_OPERATIONS.schemeRead, t('kwic.annotations.loadScheme'))
  )
  const multiCoderWriteBlockReason = computed(() =>
    annotationOperationBlockReason(ANNOTATION_OPERATIONS.settingsWrite, t('kwic.annotations.saveMultiCoder'))
  )

  // ── Lookups ────────────────────────────────────────────────────────
  const categoryById = computed(() => {
    const map = new Map<string, AnnotationCategory>()
    for (const cat of categories.value) map.set(cat.id, cat)
    return map
  })

  const annotatedCount = computed(() => Object.keys(annotations.value).length)

  function getAnnotation(rowId: string): AnnotationRecord | undefined {
    return annotations.value[rowId]
  }

  function categoryFor(rowId: string): AnnotationCategory | undefined {
    const catId = annotations.value[rowId]?.categoryId
    return catId ? categoryById.value.get(catId) : undefined
  }

  /** Per-category counts across ALL loaded annotations (research deliverable). */
  const categoryCounts = computed(() => {
    const counts: Record<string, number> = {}
    let uncategorized = 0
    for (const record of Object.values(annotations.value)) {
      if (record.categoryId) {
        counts[record.categoryId] = (counts[record.categoryId] ?? 0) + 1
      } else if (record.note) {
        uncategorized += 1
      }
    }
    return { byCategory: counts, uncategorized }
  })

  /**
   * Whether a row passes the active category filter. When the filter is off,
   * every row passes. A null filter means "annotated rows"; '' means
   * "uncategorized (note-only) rows"; otherwise a specific category id.
   */
  function rowMatchesFilter(rowId: string): boolean {
    if (!filterEnabled.value) return true
    const record = annotations.value[rowId]
    if (filterCategoryId.value === null) {
      return Boolean(record)
    }
    if (filterCategoryId.value === '') {
      return Boolean(record && !record.categoryId)
    }
    return record?.categoryId === filterCategoryId.value
  }

  // ── Loading ────────────────────────────────────────────────────────
  async function load(): Promise<void> {
    const seq = ++loadSeq
    const corpus = docsetStore.activeCorpus || ''
    isLoading.value = true
    error.value = null
    try {
      await assertAnnotationOperation(ANNOTATION_OPERATIONS.read, t('kwic.annotations.load'))
      const payload = await getAnnotations({
        corpus: corpus || undefined,
        annotator: multiCoderEnabled.value ? annotator.value : undefined,
      })
      if (seq !== loadSeq) return // superseded by a newer load
      // Backend keys are BARE (`${docId}:${pos}` / `h:${hash}`) and scoped to the
      // requested corpus. Re-key them with the corpus prefix so local lookups via
      // rowIdFor(row, corpus) line up and never alias across corpora.
      const rekeyed: Record<string, AnnotationRecord> = {}
      for (const [bareId, record] of Object.entries(payload.annotations)) {
        rekeyed[`${corpus}${CORPUS_SEP}${bareId}`] = record
      }
      annotations.value = rekeyed
      categories.value = payload.scheme.categories
      schemeRevision.value = payload.scheme.revision
    } catch (err) {
      if (seq !== loadSeq) return
      error.value = err instanceof Error ? err.message : t('kwic.annotations.loadFailed')
    } finally {
      if (seq === loadSeq) isLoading.value = false
    }
  }

  // ── Optimistic writes ──────────────────────────────────────────────

  /**
   * Set (or clear) the category and/or note for a row. Optimistic: applies the
   * change locally first and rolls back on backend failure. Passing
   * `categoryId: null` clears the category; an empty record (no category, no
   * note) is deleted.
   */
  async function setAnnotation(
    rowId: string,
    input: { categoryId?: string | null; note?: string | null }
  ): Promise<void> {
    const accessCheck = assertAnnotationMutation(ANNOTATION_OPERATIONS.write, t('kwic.annotations.save'))
    if (accessCheck) await accessCheck
    invalidatePendingLoads()
    const previous = annotations.value[rowId]
    const next: AnnotationRecord = {
      categoryId: input.categoryId !== undefined ? input.categoryId : (previous?.categoryId ?? null),
      note: input.note !== undefined ? input.note : (previous?.note ?? null),
      annotator: annotator.value.trim() || previous?.annotator || DEFAULT_LOCAL_ANNOTATOR,
      updatedAt: Date.now(),
    }

    // An annotation with neither category nor note is a removal.
    if (!next.categoryId && !next.note) {
      await removeAnnotation(rowId)
      return
    }

    // Claim a write slot for this row; a later write bumps the seq so this one's
    // resolve/rollback becomes a no-op (prevents a late earlier write clobbering
    // a newer value).
    const seq = nextWriteSeq(rowId)

    // Optimistic apply.
    annotations.value = { ...annotations.value, [rowId]: next }
    error.value = null
    // The backend wants the bare id + corpus as a separate scope param.
    const { corpus, rowId: bareId } = splitRowId(rowId)
    try {
      const saved = await putAnnotation(bareId, {
        categoryId: next.categoryId,
        note: next.note,
        annotator: next.annotator,
      }, corpus || undefined)
      // A newer write for this row landed while we were in flight → drop our
      // reconciliation so we don't overwrite the newer value.
      if (!isLatestWrite(rowId, seq)) return
      // Reconcile with the authoritative server record (e.g. updated_at).
      annotations.value = {
        ...annotations.value,
        [rowId]: saved,
      }
    } catch (err) {
      // Only roll back if we are still the latest write; otherwise a newer write
      // owns the row state and our stale failure must not revert it.
      if (isLatestWrite(rowId, seq)) {
        rollback(rowId, previous)
        error.value = err instanceof Error ? err.message : t('kwic.annotations.saveFailed')
      }
      throw err
    }
  }

  /** Convenience: assign a single category to a row (keeps any existing note). */
  async function setCategory(rowId: string, categoryId: string | null): Promise<void> {
    await setAnnotation(rowId, { categoryId })
  }

  /** Convenience: set the free-text note for a row (keeps the category). */
  async function setNote(rowId: string, note: string | null): Promise<void> {
    await setAnnotation(rowId, { note: note && note.trim() ? note : null })
  }

  /** Delete a row's annotation entirely. Optimistic with rollback. */
  async function removeAnnotation(rowId: string): Promise<void> {
    const accessCheck = assertAnnotationMutation(ANNOTATION_OPERATIONS.delete, t('kwic.annotations.delete'))
    if (accessCheck) await accessCheck
    invalidatePendingLoads()
    const previous = annotations.value[rowId]
    if (!previous) return
    const seq = nextWriteSeq(rowId)
    const next = { ...annotations.value }
    delete next[rowId]
    annotations.value = next
    error.value = null
    const { corpus, rowId: bareId } = splitRowId(rowId)
    // Carry the coder slot so the DELETE targets the SAME named slot the PUT
    // wrote (ANN-IAA-DELETE). Prefer the existing coding's annotator; fall back
    // to the active coder. The backend ignores it under a real RBAC principal.
    const slot = previous.annotator || annotator.value.trim() || DEFAULT_LOCAL_ANNOTATOR
    try {
      await deleteAnnotation(bareId, corpus || undefined, slot)
    } catch (err) {
      // Only revert if no newer write has superseded this delete.
      if (isLatestWrite(rowId, seq)) {
        rollback(rowId, previous)
        error.value = err instanceof Error ? err.message : t('kwic.annotations.deleteFailed')
      }
      throw err
    }
  }

  function rollback(rowId: string, previous: AnnotationRecord | undefined) {
    if (previous) {
      annotations.value = { ...annotations.value, [rowId]: previous }
    } else {
      const next = { ...annotations.value }
      delete next[rowId]
      annotations.value = next
    }
  }

  // ── Coding scheme CRUD (persisted per corpus) ──────────────────────
  // The scheme belongs to the active corpus. A corpus without a scheme of its
  // own shows the project scheme until its first save.
  async function loadScheme(): Promise<void> {
    await assertAnnotationOperation(ANNOTATION_OPERATIONS.schemeRead, t('kwic.annotations.loadScheme'))
    const scheme = await getAnnotationScheme(docsetStore.activeCorpus || undefined)
    categories.value = scheme.categories
    schemeRevision.value = scheme.revision
  }

  async function saveScheme(
    nextCategories: AnnotationCategory[],
    confirmationToken: string | null = null,
  ): Promise<AnnotationSchemeSaveResult> {
    await assertAnnotationOperation(ANNOTATION_OPERATIONS.schemePreview, t('kwic.annotations.checkSchemeChange'))
    const accessCheck = assertAnnotationMutation(ANNOTATION_OPERATIONS.schemeWrite, t('kwic.annotations.saveScheme'))
    if (accessCheck) await accessCheck
    invalidatePendingLoads()
    isSavingScheme.value = true
    error.value = null
    try {
      const corpus = docsetStore.activeCorpus || undefined
      const preview = await previewAnnotationScheme(
        { categories: nextCategories, revision: schemeRevision.value },
        schemeRevision.value,
        corpus,
      )
      if (preview.status === 'stale') {
        categories.value = preview.categories
        schemeRevision.value = preview.revision
        return { status: 'stale', preview }
      }
      if (preview.removals.length && confirmationToken !== preview.confirmationToken) {
        return { status: 'confirmation_required', preview }
      }
      const saved = await putAnnotationScheme(
        { categories: nextCategories, revision: preview.revision },
        { expectedRevision: preview.revision, confirmationToken, corpus },
      )
      categories.value = saved.categories
      schemeRevision.value = saved.revision
      return { status: 'saved' }
    } catch (err) {
      error.value = err instanceof Error ? err.message : t('kwic.annotations.saveSchemeFailed')
      throw err
    } finally {
      isSavingScheme.value = false
    }
  }

  function setAnnotator(name: string) {
    annotator.value = name.trim() || DEFAULT_LOCAL_ANNOTATOR
    storeAnnotator(annotator.value)
    if (multiCoderEnabled.value) void load()
  }

  function setFilter(categoryId: string | null, enabled = true) {
    filterCategoryId.value = categoryId
    filterEnabled.value = enabled
  }

  function clearFilter() {
    filterEnabled.value = false
    filterCategoryId.value = null
  }

  function reset() {
    annotations.value = {}
    categories.value = []
    schemeRevision.value = 0
    writeSeq.clear()
    error.value = null
    clearFilter()
  }

  // Reload whenever the corpus or active docset changes. The multi-coder flag is
  // a per-project backend setting, so hydrate it from the server (which in turn
  // refreshes the agreement when enabled) instead of trusting only local state.
  watch(
    () => [docsetStore.activeCorpus, docsetStore.activeDocsetId],
    () => {
      void load()
      void loadMultiCoderSetting()
    },
    { immediate: true }
  )

  return {
    // State
    annotations,
    categories,
    schemeRevision,
    isLoading,
    isSavingScheme,
    error,
    annotator,
    filterCategoryId,
    filterEnabled,
    // Multi-coder / IAA
    multiCoderEnabled,
    agreement,
    isLoadingAgreement,
    agreementError,
    agreementNotice,
    // Computed
    categoryById,
    annotatedCount,
    categoryCounts,
    canReadAnnotations,
    canWriteAnnotations,
    canDeleteAnnotations,
    canReadScheme,
    canEditScheme,
    canManageMultiCoder,
    canLoadAgreement,
    annotationsReadBlockReason,
    annotationsWriteBlockReason,
    schemeReadBlockReason,
    schemeWriteBlockReason,
    multiCoderWriteBlockReason,
    // Getters
    getAnnotation,
    categoryFor,
    rowMatchesFilter,
    // Actions
    load,
    loadScheme,
    loadAgreement,
    loadMultiCoderSetting,
    setMultiCoder,
    setAnnotation,
    setCategory,
    setNote,
    removeAnnotation,
    saveScheme,
    setAnnotator,
    setFilter,
    clearFilter,
    reset,
  }
})
