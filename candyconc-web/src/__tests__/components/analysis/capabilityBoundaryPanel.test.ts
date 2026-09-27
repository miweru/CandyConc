import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'

const getMcpTools = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(),
    getAuthSession: vi.fn(),
    getMcpTools: (...args: unknown[]) => getMcpTools(...args),
  }
})

function route(path: string, requiresCorpusFeatures: string[] = []) {
  return {
    path,
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: requiresCorpusFeatures,
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function seedContract() {
  const requiredFeatures = ['semantic.word_similarity']
  const store = useProductCapabilitiesStore()
  store.status = 'ready'
  store.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [
      {
        id: 'analysis.dispersion',
        title: 'Dispersion',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/analysis/dispersion'],
        backend_route_descriptors: [route('/api/v1/analysis/dispersion', requiredFeatures)],
        operations: [
          {
            id: 'analysis.dispersion.stats',
            label: 'Dispersionswerte',
            route: route('/api/v1/analysis/dispersion', requiredFeatures),
            description: 'Berechnet Dispersionskennzahlen.',
            effects: ['read'],
            handler_key: 'analysis_dispersion',
            copilot_tools: ['dispersion_offsets'],
            surface_slot: 'analysis.dispersion.stats',
            priority: 10,
          },
        ],
        frontend_evidence: [],
        action_types: ['analysis/dispersion'],
        copilot_tools: ['dispersion_offsets'],
        preconditions: ['Eine Query muss aktiv sein.'],
        requires_corpus_features: requiredFeatures,
        limits: ['DP/DPnorm werden über die volle ausgewiesene Basis berechnet.'],
      },
    ],
  } as never
}

function seedActiveCorpusWithWordSimilarity() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 100,
    doc_count: 1,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: true, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]
}

describe('CapabilityBoundaryPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getMcpTools.mockResolvedValue({ tools: [] })
    seedContract()
  })

  it('renders product limits, preconditions, runtime warnings and method provenance together', () => {
    const wrapper = mount(CapabilityBoundaryPanel, {
      props: {
        capabilityId: 'analysis.dispersion',
        runtimeLimitations: [{ message: 'Offsets per Fallback bestimmt.' }],
        runtimeNotes: ['Basis: Subkorpus-lokal'],
        method: {
          statistics: [{ key: 'dp', name: 'Gries DP', latex_formula: 'DP = ...' }],
          indexFingerprint: 'abc123',
        },
      },
    })

    expect(wrapper.text()).toContain('Eine Query muss aktiv sein.')
    expect(wrapper.text()).toContain('wartet auf bestätigte Korpusfähigkeiten')
    expect(wrapper.text()).toContain('Wort-Embedding-Index')
    expect(wrapper.text()).toContain('DP/DPnorm werden über die volle ausgewiesene Basis berechnet.')
    expect(wrapper.text()).not.toContain('Dispersionswerte')
    expect(wrapper.text()).not.toContain('Product Contract')
    expect(wrapper.text()).not.toContain('Backend-Operationen')
    expect(wrapper.text()).toContain('Offsets per Fallback bestimmt.')
    expect(wrapper.text()).toContain('Basis: Subkorpus-lokal')
    expect(wrapper.text()).toContain('Methode / Reproduzierbarkeit')
    expect(wrapper.text()).toContain('Gries DP')
  })

  it('renders active corpus feature evidence when requirements are satisfied', () => {
    seedActiveCorpusWithWordSimilarity()

    const wrapper = mount(CapabilityBoundaryPanel, {
      props: { capabilityId: 'analysis.dispersion' },
    })

    expect(wrapper.text()).toContain('Aktiver Korpus erfüllt: Wort-Embedding-Index.')
    expect(wrapper.text()).toContain('Aktiver Korpus: default')
  })

  it('does not render when no contract, runtime warning or method is available', () => {
    const store = useProductCapabilitiesStore()
    store.contract = null
    store.status = 'idle'
    const wrapper = mount(CapabilityBoundaryPanel, {
      props: { capabilityId: 'analysis.frequency' },
    })

    expect(wrapper.html()).toBe('<!--v-if-->')
  })
})
