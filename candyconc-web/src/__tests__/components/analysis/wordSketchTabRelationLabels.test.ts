import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import WordSketchTab from '@/components/analysis/WordSketchTab.vue'
import { getWordSketch } from '@/api/client'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, useSessionStore } from '@/stores'

// Finding 11: the Word Sketch view must render the human-readable German
// relation labels the r9 backend provides (relationLabels) instead of raw
// parser codes like "SB REV" / "MNR".
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getWordSketch: vi.fn(),
  }
})

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  Button: { template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  EmptyState: { props: ['description'], template: '<div class="empty-state">{{ description }}</div>' },
  JobStatusPill: { template: '<div />' },
  SaveAnalysisButton: { template: '<div />' },
  Skeleton: { template: '<div />' },
  MethodPanel: { template: '<div />' },
}

function mountTab() {
  return mount(WordSketchTab, { global: { stubs } })
}

function seedWordSketchAvailability() {
  const route = {
    path: '/api/v1/analysis/wordsketch',
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: ['token_attributes.rel'],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    capabilities: [{
      id: 'analysis.wordsketch',
      title: 'Word Sketch',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [route.path],
      backend_route_descriptors: [route],
      operations: [{
        id: 'analysis.wordsketch.profile',
        capability_id: 'analysis.wordsketch',
        label: 'Word Sketch',
        description: '',
        route,
        effects: ['read'],
        handler_key: 'word_sketch',
        surface_slot: 'analysis.wordsketch.profile',
        priority: 10,
      }],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  }
  productCapabilities.status = 'ready'

  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'rel', cql_attribute: 'rel', label: 'Relation' }],
    },
  }]

  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'analyst',
    role: 'user',
    effective_role: 'user',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

async function runSearch(wrapper: ReturnType<typeof mount>, term: string) {
  const input = wrapper.find('input.search-input')
  await input.setValue(term)
  await input.trigger('keyup.enter')
  await flushPromises()
}

describe('WordSketchTab relation labels (Finding 11)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    ;(getWordSketch as Mock).mockReset()
    seedWordSketchAvailability()
  })

  it('renders backend gloss labels instead of raw codes for nk/sb_rev/mnr/cj_rev', async () => {
    ;(getWordSketch as Mock).mockResolvedValue({
      term: 'Merkel',
      relations: [
        { relation: 'sb_rev', words: [{ word: 'sagte', score: 9.1, frequency: 2 }] },
        { relation: 'mnr', words: [{ word: 'von', score: 5.0, frequency: 3 }] },
        { relation: 'cj_rev', words: [{ word: 'und', score: 3.0, frequency: 4 }] },
        { relation: 'nk', words: [{ word: 'die', score: 2.7, frequency: 4 }] },
      ],
      relationLabels: {
        sb_rev: 'Subjekt von',
        mnr: 'hat als nachgestellten Modifikator',
        cj_rev: 'Konjunkt (verbunden mit)',
        nk: 'Kern/Attribut im Nominal (Nomen-Kern)',
      },
    })

    const wrapper = mountTab()
    await runSearch(wrapper, 'Merkel')

    const titles = wrapper.findAll('.relation-title').map((n) => n.text())
    expect(titles).toContain('Subjekt von')
    expect(titles).toContain('hat als nachgestellten Modifikator')
    expect(titles).toContain('Konjunkt (verbunden mit)')
    expect(titles).toContain('Kern/Attribut im Nominal (Nomen-Kern)')

    // The raw uppercase codes must NOT survive into the rendered headers.
    const text = wrapper.text()
    expect(text).not.toContain('SB REV')
    expect(text).not.toContain('CJ REV')
    expect(text).not.toContain('MNR')
  })

  it('shows each relation in the dependency search syntax next to its gloss', async () => {
    // The glosses alone gave no way to the dependency search, which needs
    // the code: defend >dobj freedom, freedom >amod political.
    ;(getWordSketch as Mock).mockResolvedValue({
      term: 'freedom',
      relations: [
        { relation: 'amod', words: [{ word: 'political', score: 9.1, frequency: 5 }] },
        { relation: 'dobj_rev', words: [{ word: 'defend', score: 10.2, frequency: 12 }] },
      ],
      relationLabels: {
        amod: 'has adjectival modifier',
        dobj_rev: 'direct object of',
      },
    })

    const wrapper = mountTab()
    await runSearch(wrapper, 'freedom')

    const cards = wrapper.findAll('.relation-card')
    const byTitle = new Map(cards.map((card) => [card.get('.relation-title').text(), card.get('.relation-code')]))
    expect(byTitle.get('has adjectival modifier')!.text()).toBe('>amod')
    expect(byTitle.get('direct object of')!.text()).toBe('<dobj')
    expect(byTitle.get('direct object of')!.attributes('title')).toBe(
      'Relation dobj_rev in der Dependenzsuche: freedom <dobj defend',
    )
    expect(byTitle.get('has adjectival modifier')!.attributes('title')).toContain('freedom >amod political')
  })

  it('falls back to the hardcoded map, then the raw code, when no backend label exists', async () => {
    ;(getWordSketch as Mock).mockResolvedValue({
      term: 'x',
      relations: [
        // Covered by the hardcoded fallback map.
        { relation: 'obj', words: [{ word: 'beta', score: 3.5, frequency: 4 }] },
        // Unknown to both maps -> raw code with underscores replaced.
        { relation: 'weird_code', words: [{ word: 'gamma', score: 1.5, frequency: 2 }] },
      ],
      relationLabels: {},
    })

    const wrapper = mountTab()
    await runSearch(wrapper, 'x')

    const titles = wrapper.findAll('.relation-title').map((n) => n.text())
    expect(titles).toContain('Objekt von')
    expect(titles).toContain('weird code')
  })
})
