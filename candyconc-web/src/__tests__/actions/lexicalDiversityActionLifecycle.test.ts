import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getLexicalDiversity: vi.fn(),
  getMetaSchema: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getLexicalDiversity: (...args: unknown[]) => apiMocks.getLexicalDiversity(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
  }
})

import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useUiStore } from '@/stores/ui'

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

function operation() {
  const lexicalRoute = route('/api/v1/analysis/lexical-diversity', 'GET')
  return {
    id: 'analysis.contrast.lexical_diversity',
    capability_id: 'analysis.contrast',
    label: 'Lexikalische Diversität',
    description: '',
    route: lexicalRoute,
    effects: ['read'],
    handler_key: 'lexical_diversity',
    surface_slot: 'analysis.contrast.lexical_diversity',
    priority: 30,
  }
}

function contract(options: { includeOperation?: boolean } = {}) {
  const includeOperation = options.includeOperation ?? true
  const lexicalRoute = route('/api/v1/analysis/lexical-diversity', 'GET')
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
        id: 'analysis.contrast',
        title: 'Kontrastanalysen',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/analysis/lexical-diversity'],
        backend_route_descriptors: [lexicalRoute],
        operations: includeOperation ? [operation()] : [],
        frontend_evidence: [],
        action_types: ['analysis/lexicalDiversity'],
        copilot_tools: ['lexical_diversity'],
        preconditions: [],
        requires_corpus_features: [],
        limits: ['Raw TTR is length-confounded.'],
      },
    ],
  }
}

describe('analysis/lexicalDiversity action lifecycle', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    actionBus.releaseLock()
    actionBus.clearHistory()
    vi.clearAllMocks()
    apiMocks.getProductCapabilities.mockResolvedValue(contract())
    apiMocks.getMetaSchema.mockResolvedValue({ fields: [] })
    apiMocks.getLexicalDiversity.mockResolvedValue({
      sttr: 0.42,
      mattr: 0.39,
      sttr_window: 1000,
      per_side: [
        { label: 'target', sttr: 0.44, n_tokens: 1200 },
        { label: 'reference', sttr: 0.38, n_tokens: 1100 },
      ],
      limitations: [{ code: 'ttr_length_confounded', message: 'TTR ist längenabhängig.' }],
    })
  })

  it('runs lexical diversity through the declared ProductOperation', async () => {
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/lexicalDiversity',
      payload: {
        targetDocsetId: 'target-docset',
        referenceDocsetId: 'reference-docset',
        corpus: 'demo',
        window: 1000,
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('contrast')
    expect(apiMocks.getLexicalDiversity).toHaveBeenCalledWith({
      corpus: 'demo',
      docsetId: undefined,
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
      window: 1000,
    }, {})
    expect(result.data).toMatchObject({
      sttr: 0.42,
      mattr: 0.39,
      limitations: [{ code: 'ttr_length_confounded' }],
    })
    expect(result.executionScope).toMatchObject({ corpusId: 'demo' })
  })

  it('does not start lexical diversity when the ProductOperation is missing', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(contract({ includeOperation: false }))

    const result = await actionBus.dispatch({
      type: 'analysis/lexicalDiversity',
      payload: { corpus: 'demo' },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Serverfunktion')
    expect(apiMocks.getLexicalDiversity).not.toHaveBeenCalled()
  })
})
