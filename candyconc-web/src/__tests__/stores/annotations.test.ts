import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAnnotationsStore, rowIdFor, bareRowIdFor, splitRowId } from '@/stores/annotations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import {
  getAnnotations,
  putAnnotation,
  deleteAnnotation,
  getAnnotationScheme,
  previewAnnotationScheme,
  putAnnotationScheme,
  getAnnotationSettings,
  putAnnotationSettings,
  getAnnotationAgreement,
  getProductCapabilities,
} from '@/api/client'

// The store reloads on corpus/docset change via a watcher; getAnnotations is
// mocked to a stable empty payload so each test starts from a clean slate.
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAnnotations: vi.fn(async () => ({ annotations: {}, scheme: { categories: [], revision: 0 } })),
    putAnnotation: vi.fn(async () => ({
      categoryId: null,
      note: null,
      annotator: null,
      updatedAt: 123,
    })),
    deleteAnnotation: vi.fn(async () => ({ status: 'deleted' })),
    getAnnotationScheme: vi.fn(async () => ({ categories: [], revision: 0 })),
    previewAnnotationScheme: vi.fn(async (scheme: { categories: unknown[]; revision: number }) => ({
      status: 'ready' as const,
      categories: scheme.categories,
      revision: scheme.revision,
      removals: [],
      confirmationToken: null,
    })),
    putAnnotationScheme: vi.fn(async (scheme: { categories: unknown[]; revision: number }) => scheme),
    // Multi-coder setting + agreement are hydrated by the corpus watcher / toggle.
    getAnnotationSettings: vi.fn(async () => ({ multiCoder: false })),
    putAnnotationSettings: vi.fn(async (enabled: boolean) => ({ multiCoder: enabled })),
    getAnnotationAgreement: vi.fn(async () => ({
      comparableRows: 0,
      annotators: [],
      percentAgreement: null,
      cohensKappa: null,
      fleissKappa: null,
      perCategory: [],
    })),
    getProductCapabilities: vi.fn(),
  }
})

function route(path: string, method = 'GET') {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(id: string, path: string, method: string, label: string) {
  return {
    id,
    capability_id: 'research.annotations',
    label,
    description: '',
    route: route(path, method),
    effects: [method === 'GET' ? 'read' : 'write'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: id,
    priority: 10,
  }
}

function annotationContract(options: { includeWrite?: boolean } = {}) {
  const includeWrite = options.includeWrite ?? true
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      {
        id: 'research.annotations',
        title: 'KWIC annotation workflow',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [
          '/api/v1/annotations',
          '/api/v1/annotations/{row_id}',
          '/api/v1/annotations/scheme',
          '/api/v1/annotations/scheme/preview',
          '/api/v1/annotations/settings',
          '/api/v1/annotations/agreement',
        ],
        backend_route_descriptors: [
          route('/api/v1/annotations', 'GET'),
          route('/api/v1/annotations/{row_id}', 'PUT'),
          route('/api/v1/annotations/{row_id}', 'DELETE'),
          route('/api/v1/annotations/scheme', 'GET'),
          route('/api/v1/annotations/scheme', 'PUT'),
          route('/api/v1/annotations/scheme/preview', 'POST'),
          route('/api/v1/annotations/settings', 'GET'),
          route('/api/v1/annotations/settings', 'PUT'),
          route('/api/v1/annotations/agreement', 'GET'),
        ],
        operations: [
          operation('research.annotations.read', '/api/v1/annotations', 'GET', 'Annotationen laden'),
          operation('research.annotations.scheme_read', '/api/v1/annotations/scheme', 'GET', 'Kodierschema laden'),
          operation('research.annotations.scheme_preview', '/api/v1/annotations/scheme/preview', 'POST', 'Schemaänderung prüfen'),
          ...(includeWrite
            ? [
                operation('research.annotations.write', '/api/v1/annotations/{row_id}', 'PUT', 'Annotation speichern'),
                operation('research.annotations.delete', '/api/v1/annotations/{row_id}', 'DELETE', 'Annotation löschen'),
                operation('research.annotations.scheme_write', '/api/v1/annotations/scheme', 'PUT', 'Kodierschema speichern'),
                operation('research.annotations.settings_read', '/api/v1/annotations/settings', 'GET', 'Annotationseinstellungen laden'),
                operation('research.annotations.settings_write', '/api/v1/annotations/settings', 'PUT', 'Annotationseinstellungen speichern'),
                operation('research.annotations.agreement', '/api/v1/annotations/agreement', 'GET', 'Übereinstimmung laden'),
              ]
            : []),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
    ],
  }
}

beforeEach(() => {
  vi.mocked(getProductCapabilities).mockResolvedValue(annotationContract())
})

function seedProductContract(options: { includeWrite?: boolean } = {}) {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = annotationContract(options)
  productCapabilities.status = 'ready'
}

describe('annotations store — row_id keying', () => {
  it('derives `${corpus}::${file}:${pos}` when doc id + position exist', () => {
    expect(
      rowIdFor({ docId: 'doc7', position: 42, left: 'a', match: 'b', right: 'c' }, 'news')
    ).toBe('news::doc7:42')
  })

  it('falls back to a corpus-prefixed text hash when doc id is missing/unknown', () => {
    const id = rowIdFor({ docId: 'unknown', position: 1, left: 'links', match: 'wort', right: 'rechts' }, 'news')
    expect(id.startsWith('news::h:')).toBe(true)
    // Stable: same corpus + text → same hash.
    const id2 = rowIdFor({ docId: 'unknown', position: 99, left: 'links', match: 'wort', right: 'rechts' }, 'news')
    expect(id).toBe(id2)
  })

  it('namespaces the same {docId,position} differently per corpus (no cross-corpus aliasing)', () => {
    const row = { docId: 'doc0', position: 0, left: 'l', match: 'm', right: 'r' }
    const idA = rowIdFor(row, 'corpusA')
    const idB = rowIdFor(row, 'corpusB')
    // The collision case: docId is a per-corpus index that restarts at 0, so the
    // BARE id is identical, but the namespaced local ids MUST be distinct.
    expect(bareRowIdFor(row)).toBe('doc0:0')
    expect(idA).toBe('corpusA::doc0:0')
    expect(idB).toBe('corpusB::doc0:0')
    expect(idA).not.toBe(idB)
  })

  it('splitRowId recovers the bare backend id + corpus scope', () => {
    expect(splitRowId('news::doc7:42')).toEqual({ corpus: 'news', rowId: 'doc7:42' })
    expect(splitRowId('news::h:abc')).toEqual({ corpus: 'news', rowId: 'h:abc' })
    // Legacy / bare id without a separator stays well-formed (empty corpus).
    expect(splitRowId('doc7:42')).toEqual({ corpus: '', rowId: 'doc7:42' })
  })
})

describe('annotations store — optimistic writes', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedProductContract()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('applies a category optimistically and reconciles on success', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockResolvedValueOnce({
      categoryId: 'cat1',
      note: null,
      annotator: 'alice',
      updatedAt: 999,
    })
    store.setAnnotator('alice')

    const promise = store.setCategory('doc1:5', 'cat1')
    // Optimistic: present immediately, before the await resolves.
    expect(store.getAnnotation('doc1:5')?.categoryId).toBe('cat1')
    await promise
    // Reconciled with the server record.
    expect(store.getAnnotation('doc1:5')).toMatchObject({ categoryId: 'cat1', annotator: 'alice', updatedAt: 999 })
    expect(putAnnotation).toHaveBeenCalledWith(
      'doc1:5',
      expect.objectContaining({ categoryId: 'cat1' }),
      undefined
    )
  })

  it('replaces the optimistic row with the exact authoritative server annotation', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockResolvedValueOnce({
      categoryId: null,
      note: 'server note',
      annotator: 'server-user',
      updatedAt: '2026-06-21T07:30:00Z',
    })
    store.setAnnotator('client-user')

    await store.setAnnotation('doc1:5', { categoryId: 'cat1', note: 'client note' })

    expect(store.getAnnotation('doc1:5')).toEqual({
      categoryId: null,
      note: 'server note',
      annotator: 'server-user',
      updatedAt: '2026-06-21T07:30:00Z',
    })
  })

  it('sends a valid local annotator even before the user enters a name', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockResolvedValueOnce({
      categoryId: null,
      note: 'client note',
      annotator: 'local-annotator',
      updatedAt: 1,
    })

    await store.setAnnotation('doc1:5', { note: 'client note' })

    expect(putAnnotation).toHaveBeenCalledWith(
      'doc1:5',
      expect.objectContaining({ annotator: 'local-annotator' }),
      undefined,
    )
  })

  it('rolls back to the previous state when the PUT fails', async () => {
    const store = useAnnotationsStore()
    // Seed an existing annotation via a first successful write.
    vi.mocked(putAnnotation).mockResolvedValueOnce({ categoryId: 'cat1', note: null, annotator: null, updatedAt: 1 })
    await store.setCategory('doc1:5', 'cat1')
    expect(store.getAnnotation('doc1:5')?.categoryId).toBe('cat1')

    // Now a failing update must roll back to cat1.
    vi.mocked(putAnnotation).mockRejectedValueOnce(new Error('boom'))
    await expect(store.setCategory('doc1:5', 'cat2')).rejects.toThrow('boom')
    expect(store.getAnnotation('doc1:5')?.categoryId).toBe('cat1')
    expect(store.error).toBeTruthy()
  })

  it('rolls back a brand-new annotation (deletes it) when the PUT fails', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockRejectedValueOnce(new Error('nope'))
    await expect(store.setNote('doc2:1', 'eine Notiz')).rejects.toThrow('nope')
    expect(store.getAnnotation('doc2:1')).toBeUndefined()
  })

  it('deletes optimistically and rolls back on failure', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockResolvedValueOnce({ categoryId: 'cat1', note: 'n', annotator: null, updatedAt: 1 })
    await store.setAnnotation('doc3:9', { categoryId: 'cat1', note: 'n' })
    expect(store.getAnnotation('doc3:9')).toBeDefined()

    vi.mocked(deleteAnnotation).mockRejectedValueOnce(new Error('offline'))
    await expect(store.removeAnnotation('doc3:9')).rejects.toThrow('offline')
    // Restored after the failed delete.
    expect(store.getAnnotation('doc3:9')).toBeDefined()
  })

  it('clearing both category and note deletes the row', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockResolvedValueOnce({ categoryId: 'cat1', note: null, annotator: null, updatedAt: 1 })
    await store.setCategory('doc4:2', 'cat1')
    expect(store.getAnnotation('doc4:2')).toBeDefined()

    vi.mocked(deleteAnnotation).mockResolvedValueOnce({ status: 'deleted' })
    await store.setCategory('doc4:2', null)
    expect(store.getAnnotation('doc4:2')).toBeUndefined()
    // ANN-IAA-DELETE: the DELETE now carries the coder slot so it targets the
    // SAME named slot the PUT wrote (default coder here -> 'local-annotator').
    expect(deleteAnnotation).toHaveBeenCalledWith('doc4:2', undefined, 'local-annotator')
  })

  it('sends the BARE backend id + corpus scope for a namespaced local key', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockResolvedValueOnce({ categoryId: 'cat1', note: null, annotator: null, updatedAt: 7 })
    // Local key is corpus-namespaced (as KwicTable would build via rowIdFor).
    await store.setCategory('news::doc1:5', 'cat1')
    // Backend receives the bare id and the corpus as a separate scope param.
    expect(putAnnotation).toHaveBeenCalledWith(
      'doc1:5',
      expect.objectContaining({ categoryId: 'cat1' }),
      'news'
    )
    expect(store.getAnnotation('news::doc1:5')?.categoryId).toBe('cat1')
  })

  it('blocks writes before optimistic mutation when the ProductOperation is missing', async () => {
    vi.mocked(getProductCapabilities).mockResolvedValueOnce(annotationContract({ includeWrite: false }))
    seedProductContract({ includeWrite: false })
    const store = useAnnotationsStore()

    await expect(store.setCategory('doc-blocked:1', 'cat1')).rejects.toThrow('Serverfunktion')

    expect(putAnnotation).not.toHaveBeenCalled()
    expect(store.getAnnotation('doc-blocked:1')).toBeUndefined()
    expect(store.canWriteAnnotations).toBe(false)
  })

  it('a late-FAILING earlier write does not clobber a newer succeeded value', async () => {
    const store = useAnnotationsStore()
    let rejectFirst!: (e: Error) => void
    // First write hangs; we control its (eventual) rejection.
    vi.mocked(putAnnotation).mockImplementationOnce(
      () => new Promise((_, reject) => { rejectFirst = reject })
    )
    const first = store.setCategory('doc9:1', 'cat-OLD').catch(() => {})
    expect(store.getAnnotation('doc9:1')?.categoryId).toBe('cat-OLD')

    // Second (newer) write for the SAME row resolves quickly with cat-NEW.
    vi.mocked(putAnnotation).mockResolvedValueOnce({ categoryId: 'cat-NEW', note: null, annotator: null, updatedAt: 2 })
    await store.setCategory('doc9:1', 'cat-NEW')
    expect(store.getAnnotation('doc9:1')?.categoryId).toBe('cat-NEW')

    // Now the FIRST write finally fails — its rollback must be a no-op because a
    // newer write owns the row.
    rejectFirst(new Error('late failure'))
    await first
    expect(store.getAnnotation('doc9:1')?.categoryId).toBe('cat-NEW')
  })

  it('a late-SUCCEEDING earlier write does not clobber a newer succeeded value', async () => {
    const store = useAnnotationsStore()
    let resolveFirst!: (r: { categoryId: string; note: null; annotator: null; updatedAt: number }) => void
    vi.mocked(putAnnotation).mockImplementationOnce(
      () => new Promise((resolve) => { resolveFirst = resolve })
    )
    const first = store.setCategory('doc9:2', 'cat-OLD').catch(() => {})

    vi.mocked(putAnnotation).mockResolvedValueOnce({ categoryId: 'cat-NEW', note: null, annotator: null, updatedAt: 5 })
    await store.setCategory('doc9:2', 'cat-NEW')
    expect(store.getAnnotation('doc9:2')?.categoryId).toBe('cat-NEW')

    // The first write's late reconciliation must be dropped.
    resolveFirst({ categoryId: 'cat-OLD', note: null, annotator: null, updatedAt: 1 })
    await first
    expect(store.getAnnotation('doc9:2')?.categoryId).toBe('cat-NEW')
  })
})

describe('annotations store — counts + filter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedProductContract()
    vi.clearAllMocks()
  })

  it('aggregates per-category counts and matches the filter predicate', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotation).mockImplementation(async (_rowId, input) => ({
      categoryId: input.categoryId ?? null,
      note: input.note ?? null,
      annotator: input.annotator ?? null,
      updatedAt: 1,
    }))
    await store.setCategory('a:1', 'cat1')
    await store.setCategory('b:2', 'cat1')
    await store.setCategory('c:3', 'cat2')
    await store.setNote('d:4', 'note only')

    expect(store.categoryCounts.byCategory['cat1']).toBe(2)
    expect(store.categoryCounts.byCategory['cat2']).toBe(1)
    expect(store.categoryCounts.uncategorized).toBe(1)
    expect(store.annotatedCount).toBe(4)

    // Filter off → everything passes.
    expect(store.rowMatchesFilter('a:1')).toBe(true)
    expect(store.rowMatchesFilter('zzz:9')).toBe(true)

    // Filter by cat1.
    store.setFilter('cat1', true)
    expect(store.rowMatchesFilter('a:1')).toBe(true)
    expect(store.rowMatchesFilter('c:3')).toBe(false)

    // Filter "annotated" (null) → any annotated row passes.
    store.setFilter(null, true)
    expect(store.rowMatchesFilter('c:3')).toBe(true)
    expect(store.rowMatchesFilter('zzz:9')).toBe(false)

    // Filter "uncategorized" ('') → only note-only rows.
    store.setFilter('', true)
    expect(store.rowMatchesFilter('d:4')).toBe(true)
    expect(store.rowMatchesFilter('a:1')).toBe(false)
  })
})

describe('annotations store — scheme persistence', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedProductContract()
    vi.clearAllMocks()
  })

  it('keeps loadAnnotations defensive against an empty backend', async () => {
    const store = useAnnotationsStore()
    await store.load()
    expect(getAnnotations).toHaveBeenCalled()
    expect(store.categories).toEqual([])
    expect(store.annotatedCount).toBe(0)
  })

  it('loads the coding scheme through the scheme_read ProductOperation', async () => {
    vi.mocked(getAnnotationScheme).mockResolvedValueOnce({
      categories: [{ id: 'cat1', label: 'Metapher', color: '#ef4444', shortcut: 'm' }],
      revision: 4,
    })
    const store = useAnnotationsStore()

    await store.loadScheme()

    expect(getAnnotationScheme).toHaveBeenCalled()
    expect(store.categories).toEqual([
      { id: 'cat1', label: 'Metapher', color: '#ef4444', shortcut: 'm' },
    ])
    expect(store.schemeRevision).toBe(4)
  })

  it('requires an explicit reviewed confirmation before deleting used codes', async () => {
    const next = [{ id: 'keep', label: 'Behalten' }]
    vi.mocked(previewAnnotationScheme).mockResolvedValue({
      status: 'ready',
      categories: [
        { id: 'keep', label: 'Behalten' },
        { id: 'drop', label: 'Entfernen' },
      ],
      revision: 3,
      removals: [{
        categoryId: 'drop',
        label: 'Entfernen',
        annotationCount: 5,
        corpusCount: 2,
        annotatorCount: 3,
      }],
      confirmationToken: 'reviewed-token',
    })
    vi.mocked(putAnnotationScheme).mockResolvedValue({ categories: next, revision: 4 })
    const store = useAnnotationsStore()
    store.schemeRevision = 3

    const first = await store.saveScheme(next)
    expect(first).toMatchObject({ status: 'confirmation_required' })
    expect(putAnnotationScheme).not.toHaveBeenCalled()

    const confirmed = await store.saveScheme(next, 'reviewed-token')
    expect(confirmed).toEqual({ status: 'saved' })
    expect(putAnnotationScheme).toHaveBeenCalledWith(
      { categories: next, revision: 3 },
      { expectedRevision: 3, confirmationToken: 'reviewed-token', corpus: 'default' },
    )
    expect(store.categories).toEqual(next)
    expect(store.schemeRevision).toBe(4)
  })

  it('loads and saves the scheme of the active corpus', async () => {
    useQueryStore().setFilters({ corpus: 'paired_en' })
    const store = useAnnotationsStore()
    vi.mocked(getAnnotationScheme).mockResolvedValueOnce({ categories: [], revision: 0 })
    await store.loadScheme()
    expect(getAnnotationScheme).toHaveBeenCalledWith('paired_en')
    vi.mocked(previewAnnotationScheme).mockResolvedValueOnce({
      status: 'ready', categories: [], revision: 0, removals: [], confirmationToken: null,
    })
    vi.mocked(putAnnotationScheme).mockResolvedValueOnce({ categories: [{ id: 'a', label: 'A' }], revision: 1 })
    await store.saveScheme([{ id: 'a', label: 'A' }])
    expect(previewAnnotationScheme).toHaveBeenCalledWith(expect.anything(), 0, 'paired_en')
    expect(putAnnotationScheme).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ corpus: 'paired_en' }))
  })

  it('never overwrites a scheme changed by another manager', async () => {
    vi.mocked(previewAnnotationScheme).mockResolvedValueOnce({
      status: 'stale',
      categories: [{ id: 'current', label: 'Aktueller Stand' }],
      revision: 8,
      removals: [],
      confirmationToken: null,
    })
    const store = useAnnotationsStore()
    store.schemeRevision = 7

    const result = await store.saveScheme([{ id: 'mine', label: 'Mein Entwurf' }])

    expect(result).toMatchObject({ status: 'stale' })
    expect(putAnnotationScheme).not.toHaveBeenCalled()
    expect(store.categories).toEqual([{ id: 'current', label: 'Aktueller Stand' }])
    expect(store.schemeRevision).toBe(8)
  })

  it('blocks scheme loading before the backend route is called when scheme_read is absent', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = annotationContract()
    productCapabilities.contract.capabilities[0]!.operations =
      productCapabilities.contract.capabilities[0]!.operations.filter(
        (item) => item.id !== 'research.annotations.scheme_read',
      )
    const store = useAnnotationsStore()

    await expect(store.loadScheme()).rejects.toThrow('Serverfunktion')
    expect(getAnnotationScheme).not.toHaveBeenCalled()
  })

  it('names a blocked schema action instead of exposing a generic server-function warning', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = annotationContract()
    productCapabilities.contract.capabilities[0]!.operations =
      productCapabilities.contract.capabilities[0]!.operations.filter(
        (item) => item.id !== 'research.annotations.scheme_preview',
      )
    const store = useAnnotationsStore()

    expect(store.schemeWriteBlockReason).toContain('Schemaänderung prüfen')
    expect(store.schemeWriteBlockReason).not.toContain('Benötigte Serverfunktion')
  })
})

describe('annotations store — multi-coder persistence (C-multicoder-iaa-02)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedProductContract()
    vi.clearAllMocks()
  })

  it('setMultiCoder PUTs the backend setting (not just local state)', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotationSettings).mockResolvedValueOnce({ multiCoder: true })

    await store.setMultiCoder(true)

    // Without persisting the server stays single-coder and IAA overlap is 0:
    // the toggle MUST drive the backend.
    expect(putAnnotationSettings).toHaveBeenCalledWith(true)
    expect(store.multiCoderEnabled).toBe(true)
    // Enabling also triggers an agreement refresh.
    expect(getAnnotationAgreement).toHaveBeenCalled()
  })

  it('rolls the toggle back when the persist fails', async () => {
    const store = useAnnotationsStore()
    vi.mocked(putAnnotationSettings).mockRejectedValueOnce(new Error('forbidden'))

    await expect(store.setMultiCoder(true)).rejects.toThrow('forbidden')
    expect(store.multiCoderEnabled).toBe(false)
    expect(store.agreementError).toBeTruthy()
  })

  it('hydrates the multi-coder flag from the backend on load', async () => {
    vi.mocked(getAnnotationSettings).mockResolvedValue({ multiCoder: true })
    const store = useAnnotationsStore()
    await store.loadMultiCoderSetting()
    expect(getAnnotationSettings).toHaveBeenCalled()
    expect(store.multiCoderEnabled).toBe(true)
  })

  it('loads the active coder slot instead of a representative coding in multi-coder mode', async () => {
    vi.mocked(getAnnotationSettings).mockResolvedValue({ multiCoder: true })
    vi.mocked(getAnnotations).mockImplementation(async (params = {}) => ({
      annotations: params.annotator === 'bob'
        ? {
            'doc1:5': { categoryId: 'cat-bob', note: 'bob note', annotator: 'bob', updatedAt: 2 },
          }
        : {},
      scheme: { categories: [] },
    }))
    const store = useAnnotationsStore()
    store.setAnnotator('bob')

    await store.loadMultiCoderSetting()

    expect(getAnnotations).toHaveBeenLastCalledWith(expect.objectContaining({ annotator: 'bob' }))
    expect(store.getAnnotation('default::doc1:5')).toMatchObject({
      categoryId: 'cat-bob',
      annotator: 'bob',
    })
  })
})

describe('annotations store — coder name across reloads', () => {
  const storage = window.localStorage as unknown as {
    getItem: ReturnType<typeof vi.fn>
    setItem: ReturnType<typeof vi.fn>
    removeItem: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    seedProductContract()
    vi.clearAllMocks()
    storage.getItem.mockReset()
    storage.setItem.mockReset()
    storage.removeItem.mockReset()
  })

  afterEach(() => {
    storage.getItem.mockReset()
  })

  it('stores the coder name when it is entered', () => {
    const store = useAnnotationsStore()
    store.setAnnotator('  MR ')
    expect(store.annotator).toBe('MR')
    expect(storage.setItem).toHaveBeenCalledWith('candyconc_annotator', 'MR')
  })

  it('starts with the stored coder name after a reload', () => {
    storage.getItem.mockImplementation((key: string) => (key === 'candyconc_annotator' ? 'MR' : null))
    const store = useAnnotationsStore()
    expect(store.annotator).toBe('MR')
  })

  it('forgets the stored name when the field is cleared', () => {
    const store = useAnnotationsStore()
    store.setAnnotator('')
    expect(store.annotator).toBe('local-annotator')
    expect(storage.removeItem).toHaveBeenCalledWith('candyconc_annotator')
  })

  it('uses the default coder when storage is unavailable', () => {
    storage.getItem.mockImplementation(() => {
      throw new Error('blocked')
    })
    const store = useAnnotationsStore()
    expect(store.annotator).toBe('local-annotator')
  })
})
