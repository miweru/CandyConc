import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  getWordSketch: vi.fn(),
  getWordSketchDiff: vi.fn(),
  getMetaSchema: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getCorpusCapabilities: (...args: unknown[]) => apiMocks.getCorpusCapabilities(...args),
    getWordSketch: (...args: unknown[]) => apiMocks.getWordSketch(...args),
    getWordSketchDiff: (...args: unknown[]) => apiMocks.getWordSketchDiff(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
  }
})

import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useUiStore } from '@/stores/ui'

function route(path: string, method = 'POST', requiresCorpusFeatures: string[] = []) {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: requiresCorpusFeatures,
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function wordSketchOperation() {
  const profileRoute = route('/api/v1/analysis/wordsketch', 'POST', ['token_attributes.rel'])
  return {
    id: 'analysis.wordsketch.profile',
    capability_id: 'analysis.wordsketch',
    label: 'Word Sketch',
    description: '',
    route: profileRoute,
    effects: ['read'],
    handler_key: 'word_sketch',
    surface_slot: 'analysis.wordsketch.profile',
    priority: 10,
  }
}

function wordSketchDiffOperation() {
  const diffRoute = route('/api/v1/analysis/wordsketch_diff', 'POST', ['token_attributes.rel'])
  return {
    id: 'analysis.wordsketch.diff',
    capability_id: 'analysis.wordsketch',
    label: 'Word-Sketch-Vergleich',
    description: '',
    route: diffRoute,
    effects: ['read'],
    handler_key: 'word_sketch_diff',
    surface_slot: 'analysis.wordsketch.diff',
    priority: 20,
  }
}

function wordSketchContract(options: { includeProfileOperation?: boolean; includeDiffOperation?: boolean } = {}) {
  const includeProfileOperation = options.includeProfileOperation ?? true
  const includeDiffOperation = options.includeDiffOperation ?? true
  const profileRoute = route('/api/v1/analysis/wordsketch', 'POST', ['token_attributes.rel'])
  const diffRoute = route('/api/v1/analysis/wordsketch_diff', 'POST', ['token_attributes.rel'])
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
        id: 'analysis.wordsketch',
        title: 'Word Sketches',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/analysis/wordsketch', '/api/v1/analysis/wordsketch_diff'],
        backend_route_descriptors: [profileRoute, diffRoute],
        operations: [
          ...(includeProfileOperation ? [wordSketchOperation()] : []),
          ...(includeDiffOperation ? [wordSketchDiffOperation()] : []),
        ],
        frontend_evidence: [],
        action_types: ['analysis/wordSketch', 'analysis/wordSketchDiff'],
        copilot_tools: ['word_sketch'],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
    ],
  }
}

function relCorpusSummary() {
  return {
    name: 'default',
    path: '/corpora/default',
    token_count: 1000,
    doc_count: 10,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'rel', cql_attribute: 'rel', label: 'Relation' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }
}

describe('analysis/wordSketch action lifecycle', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    actionBus.releaseLock()
    actionBus.clearHistory()
    vi.clearAllMocks()
    apiMocks.getProductCapabilities.mockResolvedValue(wordSketchContract())
    apiMocks.getCorpusCapabilities.mockResolvedValue(relCorpusSummary())
    apiMocks.getMetaSchema.mockResolvedValue({ fields: [] })
    const corpusCapabilities = useCorpusCapabilitiesStore()
    corpusCapabilities.loaded = true
    corpusCapabilities.corpora = [relCorpusSummary()]
    apiMocks.getWordSketch.mockResolvedValue({
      term: 'Sprache',
      relations: [{ relation: 'SB', words: [{ word: 'wirkt', score: 8.5, frequency: 12 }] }],
      relationLabels: { SB: 'Subjekt von' },
    })
    apiMocks.getWordSketchDiff.mockResolvedValue({
      termA: 'Sprache',
      termB: 'Rede',
      relationLabels: { SB: 'Subjekt von' },
      relations: [
        { relation: 'SB', common: [], onlyA: [{ word: 'wirkt', score: 8.5, frequency: 12 }], onlyB: [] },
      ],
    })
  })

  it('runs word sketch through the declared ProductOperation and relation-attribute gate', async () => {
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/wordSketch',
      payload: {
        term: 'Sprache',
        limit: 25,
        corpus: 'default',
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('wordsketch')
    expect(apiMocks.getWordSketch).toHaveBeenCalledWith({
      term: 'Sprache',
      limit: 25,
      corpus: 'default',
      docsetId: undefined,
    })
    expect(result.data).toMatchObject({
      term: 'Sprache',
      relations: [{ relation: 'SB' }],
      relationLabels: { SB: 'Subjekt von' },
    })
    expect(result.executionScope).toMatchObject({
      corpusId: 'default',
      label: 'Gesamtkorpus',
    })
  })

  it('blocks word sketch before backend execution when no term is available', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/wordSketch',
      payload: {},
    })

    expect(result.success).toBe(false)
    expect(result.error).toContain('Term')
    expect(apiMocks.getWordSketch).not.toHaveBeenCalled()
  })

  it('does not start word sketch when the ProductOperation is missing from the contract', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(wordSketchContract({
      includeProfileOperation: false,
      includeDiffOperation: true,
    }))

    const result = await actionBus.dispatch({
      type: 'analysis/wordSketch',
      payload: { term: 'Sprache', corpus: 'default' },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Serverfunktion')
    expect(apiMocks.getWordSketch).not.toHaveBeenCalled()
  })

  it('runs word sketch diff through the declared ProductOperation and relation-attribute gate', async () => {
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/wordSketchDiff',
      payload: {
        termA: 'Sprache',
        termB: 'Rede',
        limit: 20,
        corpus: 'default',
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('wordsketch')
    expect(apiMocks.getWordSketchDiff).toHaveBeenCalledWith({
      termA: 'Sprache',
      termB: 'Rede',
      limit: 20,
      corpus: 'default',
      docsetId: undefined,
    })
    expect(result.data).toMatchObject({
      termA: 'Sprache',
      termB: 'Rede',
      relations: [{ relation: 'SB' }],
      relationLabels: { SB: 'Subjekt von' },
    })
  })

  it('blocks word sketch diff before backend execution when a term is missing', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/wordSketchDiff',
      payload: { termA: 'Sprache' },
    })

    expect(result.success).toBe(false)
    expect(result.error).toContain('zwei Terme')
    expect(apiMocks.getWordSketchDiff).not.toHaveBeenCalled()
  })

  it('does not start word sketch diff when the diff ProductOperation is missing from the contract', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(wordSketchContract({
      includeProfileOperation: true,
      includeDiffOperation: false,
    }))

    const result = await actionBus.dispatch({
      type: 'analysis/wordSketchDiff',
      payload: { termA: 'Sprache', termB: 'Rede', corpus: 'default' },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Serverfunktion')
    expect(apiMocks.getWordSketchDiff).not.toHaveBeenCalled()
  })
})
