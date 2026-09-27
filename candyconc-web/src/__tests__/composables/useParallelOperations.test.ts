import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PARALLEL_OPERATIONS, useParallelOperations } from '@/composables/useParallelOperations'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useProductOperationRunsStore } from '@/stores/productOperationRuns'
import { useQueryStore } from '@/stores/query'
import type { CorpusSummary, ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getAlignmentRefDoc: vi.fn(),
  getParallelGroups: vi.fn(),
  getParallelKwic: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAlignmentRefDoc: (...args: unknown[]) => apiMocks.getAlignmentRefDoc(...args),
    getParallelGroups: (...args: unknown[]) => apiMocks.getParallelGroups(...args),
    getParallelKwic: (...args: unknown[]) => apiMocks.getParallelKwic(...args),
  }
})

function route(path: string, feature: string | null = null) {
  return {
    path,
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: feature ? [feature] : [],
    access: null,
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function capability(
  routes = [] as ReturnType<typeof route>[],
  uiExecutionPolicy?: 'contextual_ui' | 'confirmed_contextual_ui',
): ProductCapability {
  return {
    id: 'corpus.alignment_parallel',
    title: 'Parallel corpus alignment helpers',
    area: 'corpus',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: routes.map((item) => item.path),
    backend_route_descriptors: routes,
    operations: routes.map((item) => {
      const operationId = item.path.endsWith('/parallel_groups')
        ? PARALLEL_OPERATIONS.groups
        : item.path.endsWith('/alignment/ref_doc')
          ? PARALLEL_OPERATIONS.alignmentRefDoc
          : PARALLEL_OPERATIONS.kwicParallel
      return {
        id: operationId,
        capability_id: 'corpus.alignment_parallel',
        label: operationId === PARALLEL_OPERATIONS.groups
          ? 'Parallelgruppen'
          : operationId === PARALLEL_OPERATIONS.alignmentRefDoc
            ? 'Alignment-Referenzdokument'
            : 'Parallel-KWIC',
        description: '',
        route: item,
        effects: ['read', 'long_running'] as const,
        ...(uiExecutionPolicy ? { ui_execution_policy: uiExecutionPolicy } : {}),
        handler_key: '',
        surface_slot: '',
        priority: 100,
      }
    }),
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function contract(item: ProductCapability): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [item],
  }
}

function corpus(alignment: NonNullable<NonNullable<CorpusSummary['features']>['alignment']>): CorpusSummary {
  return {
    name: 'demo',
    path: '/corpora/demo',
    status: 'ready',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'generic',
    paired: Boolean(alignment.paired),
    pair_axes: alignment.pair_axes ?? [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment,
    },
  }
}

function seedActiveCorpus(alignment: NonNullable<NonNullable<CorpusSummary['features']>['alignment']>) {
  useQueryStore().setFilters({ corpus: 'demo' })
  useCorpusCapabilitiesStore().corpora = [corpus(alignment)]
}

describe('useParallelOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(window.confirm).mockReset()
    vi.mocked(window.confirm).mockReturnValue(true)
  })

  it('blocks Parallel-KWIC when the concrete backend route is not offered', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability([
      route('/api/v1/analysis/parallel_groups', 'alignment.parallel_groups'),
    ]))
    productCapabilities.status = 'ready'
    seedActiveCorpus({
      paired: true,
      pair_axes: ['language'],
      parallel_groups: true,
      parallel_kwic: true,
    })

    const { loadParallelKwic } = useParallelOperations()

    await expect(loadParallelKwic({ pos: 1, keyword: 'Hase' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.getParallelKwic).not.toHaveBeenCalled()
  })

  it('blocks Parallel-KWIC when the active corpus does not expose the required feature', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability([
      route('/api/v1/analysis/kwic_parallel', 'alignment.parallel_kwic'),
    ]))
    productCapabilities.status = 'ready'
    seedActiveCorpus({
      paired: true,
      pair_axes: ['language'],
      parallel_groups: true,
      parallel_kwic: false,
    })

    const { loadParallelKwic } = useParallelOperations()

    await expect(loadParallelKwic({ pos: 1, keyword: 'Hase' })).rejects.toThrow(
      'benötigt Korpus-Evidenz',
    )
    expect(apiMocks.getParallelKwic).not.toHaveBeenCalled()
  })

  it('calls each backend operation only after route and corpus feature gates pass', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability([
      route('/api/v1/analysis/parallel_groups', 'alignment.parallel_groups'),
      route('/api/v1/analysis/alignment/ref_doc', 'alignment.parallel_groups'),
      route('/api/v1/analysis/kwic_parallel', 'alignment.parallel_kwic'),
    ]))
    productCapabilities.status = 'ready'
    seedActiveCorpus({
      paired: true,
      pair_axes: ['language'],
      parallel_groups: true,
      parallel_kwic: true,
    })
    apiMocks.getParallelGroups.mockResolvedValue({ total: 1, groups: [] })
    apiMocks.getAlignmentRefDoc.mockResolvedValue({ ref_doc: 7, variants: [] })
    apiMocks.getParallelKwic.mockResolvedValue({ ref_doc: 7, base_doc_id: 7, variants: [] })
    vi.mocked(window.confirm).mockReturnValue(false)

    const {
      loadParallelGroups,
      loadAlignmentRefDoc,
      loadParallelKwic,
    } = useParallelOperations()

    await expect(
      loadParallelGroups({ corpus: 'demo', limit: 10 }),
    ).resolves.toEqual({ total: 1, groups: [] })
    await expect(
      loadAlignmentRefDoc({ refDoc: 7, corpus: 'demo' }),
    ).resolves.toMatchObject({ ref_doc: 7 })
    await expect(
      loadParallelKwic({ pos: 1, keyword: 'Hase', corpus: 'demo' }),
    ).resolves.toMatchObject({ ref_doc: 7 })
    expect(apiMocks.getParallelGroups).toHaveBeenCalledWith({ corpus: 'demo', limit: 10 })
    expect(apiMocks.getAlignmentRefDoc).toHaveBeenCalledWith({ refDoc: 7, corpus: 'demo' })
    expect(apiMocks.getParallelKwic).toHaveBeenCalledWith({ pos: 1, keyword: 'Hase', corpus: 'demo' })

    const operationRuns = useProductOperationRunsStore()
    expect(operationRuns.records.map((run) => run.operationId)).toEqual(
      expect.arrayContaining([
        PARALLEL_OPERATIONS.groups,
        PARALLEL_OPERATIONS.alignmentRefDoc,
        PARALLEL_OPERATIONS.kwicParallel,
      ]),
    )
    expect(operationRuns.records.every((run) => run.status === 'succeeded')).toBe(true)
    expect(window.confirm).not.toHaveBeenCalled()
  })

  it('does not reopen native confirmation for every prefetched Parallel-KWIC row', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability([
      route('/api/v1/analysis/kwic_parallel', 'alignment.parallel_kwic'),
    ]))
    productCapabilities.status = 'ready'
    seedActiveCorpus({
      paired: true,
      pair_axes: ['language'],
      parallel_groups: true,
      parallel_kwic: true,
    })
    apiMocks.getParallelKwic.mockResolvedValue({ ref_doc: 7, base_doc_id: 7, variants: [] })
    vi.mocked(window.confirm).mockReturnValue(false)

    const { loadParallelKwic } = useParallelOperations()
    await expect(
      Promise.all([11, 12, 13].map((pos) => loadParallelKwic({
        pos,
        keyword: 'Hase',
        corpus: 'demo',
      }))),
    ).resolves.toHaveLength(3)

    expect(window.confirm).not.toHaveBeenCalled()
    expect(apiMocks.getParallelKwic).toHaveBeenCalledTimes(3)
  })

  it('ignores a stale confirmation policy for a read-only parallel request', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability([
      route('/api/v1/analysis/kwic_parallel', 'alignment.parallel_kwic'),
    ], 'confirmed_contextual_ui'))
    productCapabilities.status = 'ready'
    seedActiveCorpus({
      paired: true,
      pair_axes: ['language'],
      parallel_groups: true,
      parallel_kwic: true,
    })
    vi.mocked(window.confirm).mockReturnValue(false)

    const { loadParallelKwic } = useParallelOperations()

    await expect(loadParallelKwic({ pos: 11, keyword: 'Hase', corpus: 'demo' }))
      .resolves.toMatchObject({ ref_doc: 7 })

    expect(window.confirm).not.toHaveBeenCalled()
    expect(apiMocks.getParallelKwic).toHaveBeenCalledWith({ pos: 11, keyword: 'Hase', corpus: 'demo' })
  })
})
