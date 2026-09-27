import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import WordSketchTab from '@/components/analysis/WordSketchTab.vue'
import { getWordSketch } from '@/api/client'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, useSessionStore } from '@/stores'
import { applyLocale } from '@/i18n/locale'

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


describe('logDice threshold in the Word Sketch score tooltip', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    ;(getWordSketch as Mock).mockReset()
    seedWordSketchAvailability()
    ;(getWordSketch as Mock).mockResolvedValue({
      term: 'freedom',
      relations: [{ relation: 'amod', words: [{ word: 'religious', score: 9.1, frequency: 12 }] }],
      relationLabels: { amod: 'adjectival modifier' },
    })
  })

  afterEach(() => applyLocale('de'))

  for (const [locale, strength] of [['de', 'Assoziationsstärke'], ['en', 'association strength']] as const) {
    it(`describes the score without a significance threshold (${locale})`, async () => {
      applyLocale(locale)
      const wrapper = mountTab()
      await runSearch(wrapper, 'freedom')
      const title = wrapper.get('.item-score').attributes('title') ?? ''
      expect(title).toContain('Score = logDice')
      expect(title).toContain(strength)
      expect(title).toContain('2·O11 / (f(u) + f(v))')
      expect(title).not.toMatch(/≥\s*7|>=\s*7|statistisch bedeutsam|statistically significant/)
    })
  }
})
