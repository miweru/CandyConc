import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import CommandPalette from '@/components/ui/CommandPalette.vue'
import { actionBus } from '@/actions'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

const actionBusMock = vi.hoisted(() => ({ dispatch: vi.fn() }))

vi.mock('@/composables/useFocusTrap', () => ({
  useFocusTrap: () => ({ activate: vi.fn(), deactivate: vi.fn() }),
}))
vi.mock('@/composables/useAnnounce', () => ({
  useAnnounce: () => ({ announce: vi.fn() }),
}))
vi.mock('@/actions', () => ({
  actionBus: actionBusMock,
}))
vi.mock('@/actions/bus', () => ({
  actionBus: actionBusMock,
}))

function capability(id: string, visibility: 'first_class_ui' | 'hidden_experimental' = 'first_class_ui') {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: visibility === 'first_class_ui' ? 'guarded' : 'experimental',
    visibility,
    backend_routes: [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    limits: [],
  }
}

function contract(): ProductCapabilityContract {
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
      capability('corpus.catalogue'),
      capability('corpus.import'),
      capability('settings.embedding_management', 'hidden_experimental'),
    ],
  }
}

function wordSketchContract(): ProductCapabilityContract {
  return {
    ...contract(),
    capabilities: [
      capability('query.kwic'),
      {
        ...capability('analysis.wordsketch'),
        backend_routes: ['/api/v1/analysis/wordsketch'],
        backend_route_descriptors: [{
          path: '/api/v1/analysis/wordsketch',
          methods: ['POST'],
          mutates: false,
          requires_corpus_features: ['token_attributes.rel'],
        }],
      },
    ],
  }
}

function semanticContract(): ProductCapabilityContract {
  return {
    ...contract(),
    capabilities: [
      capability('query.kwic'),
      {
        ...capability('analysis.semantic_similarity'),
        backend_routes: ['/api/v1/semantic/similar_words', '/api/v1/analysis/embedding_search'],
        backend_route_descriptors: [
          {
            path: '/api/v1/semantic/similar_words',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: ['semantic.word_similarity'],
          },
          {
            path: '/api/v1/analysis/embedding_search',
            methods: ['POST'],
            mutates: false,
            requires_corpus_features: ['semantic.passage_search'],
          },
        ],
      },
    ],
  }
}

function adminImportContract(): ProductCapabilityContract {
  return {
    ...contract(),
    capabilities: [
      capability('corpus.catalogue'),
      {
        ...capability('corpus.import'),
        backend_routes: ['/api/v1/corpora/imports'],
        backend_route_descriptors: [{
          path: '/api/v1/corpora/imports',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        }],
      },
    ],
  }
}

function productRoute(path: string, methods: string[] = ['GET']) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
}

function operationCommandContract(): ProductCapabilityContract {
  const wordSketchRoute = {
    ...productRoute('/api/v1/analysis/wordsketch', ['POST']),
    mutates: false,
    requires_corpus_features: ['token_attributes.rel'],
  }
  const importRoute = {
    ...productRoute('/api/v1/corpora/imports', ['POST']),
    access: 'admin' as const,
    required_role: 'admin',
    route_class: 'admin_surface' as const,
  }
  return {
    ...contract(),
    capabilities: [
      capability('query.kwic'),
      {
        ...capability('analysis.wordsketch'),
        backend_routes: ['/api/v1/analysis/wordsketch'],
        backend_route_descriptors: [wordSketchRoute],
        operations: [{
          id: 'analysis.wordsketch.profile',
          capability_id: 'analysis.wordsketch',
          label: 'Word Sketch berechnen',
          description: 'Berechnet ein Word Sketch Profil.',
          route: wordSketchRoute,
          effects: ['read'],
          handler_key: 'loadWordSketch',
          surface_slot: 'analysis.wordsketch.profile',
          priority: 10,
        }],
      },
      {
        ...capability('corpus.import'),
        backend_routes: ['/api/v1/corpora/imports'],
        backend_route_descriptors: [importRoute],
        operations: [{
          id: 'corpus.import.start',
          capability_id: 'corpus.import',
          label: 'Importjob starten',
          description: 'Startet einen beobachtbaren Importjob.',
          route: importRoute,
          effects: ['write', 'long_running'],
          handler_key: 'startImport',
          surface_slot: 'corpus.import.start',
          priority: 10,
        }],
      },
    ],
  }
}

function seedWordOnlyCorpus() {
  seedSemanticCorpus({ passage_search: false, word_similarity: false, sentence_alignment: false })
}

function seedSemanticCorpus(semantic: { passage_search: boolean; word_similarity: boolean; sentence_alignment: boolean }) {
  const corpusCapabilities = useCorpusCapabilitiesStore()
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
      semantic,
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]
}

function seedFeatureRichCorpus() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'test',
    paired: true,
    pair_axes: ['language'],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Wortform' },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma' },
        { id: 'pos', cql_attribute: 'pos', label: 'POS' },
        { id: 'rel', cql_attribute: 'rel', label: 'Relation' },
      ],
      frequency_groups: [
        { id: 'word', label: 'Wortform' },
        { id: 'lemma', label: 'Lemma' },
        { id: 'pos', label: 'POS' },
      ],
      semantic: { passage_search: true, word_similarity: true, sentence_alignment: true },
      alignment: { paired: true, pair_axes: ['language'], parallel_groups: true, parallel_kwic: true },
    },
  }]
}

function seedAdminSession() {
  const sessionStore = useSessionStore()
  sessionStore.status = 'ready'
  sessionStore.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'admin',
    role: 'admin',
    effective_role: 'admin',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: true,
  }
}

function operationCommandId(operationId: string): string {
  return `operation-${operationId.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase()}`
}

describe('CommandPalette capability commands', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(actionBus.dispatch).mockClear()
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
  })

  it('offers corpus management as a direct command separate from settings', async () => {
    const uiStore = useUiStore()
    const wrapper = mount(CommandPalette, {
      props: { modelValue: true },
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
        },
      },
    })

    expect(wrapper.text()).toContain('Korpus importieren und verwalten')
    expect(wrapper.text()).not.toContain('Einstellungen öffnen')

    await wrapper.find('#corpus-manager-open').trigger('click')

    expect(uiStore.settingsOpen).toBe(true)
    expect(uiStore.corpusManagerOpen).toBe(true)
  })

  it('shows corpus-feature blocked analysis commands as disabled with a reason', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = wordSketchContract()
    seedWordOnlyCorpus()
    const uiStore = useUiStore()
    const wrapper = mount(CommandPalette, {
      props: { modelValue: true },
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
        },
      },
    })

    expect(wrapper.text()).toContain('Word Sketch')
    expect(wrapper.text()).toContain('Tokenattribut rel')
    expect(wrapper.find('#analysis-wordsketch').attributes('aria-disabled')).toBe('true')

    await wrapper.find('#analysis-wordsketch').trigger('click')

    expect(actionBus.dispatch).not.toHaveBeenCalled()
    expect(uiStore.toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Tokenattribut rel'),
    })
  })

  it('keeps role-blocked first-class utility surfaces discoverable with a reason', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = adminImportContract()
    const sessionStore = useSessionStore()
    sessionStore.status = 'ready'
    sessionStore.session = {
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
    const uiStore = useUiStore()
    const wrapper = mount(CommandPalette, {
      props: { modelValue: true },
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
        },
      },
    })

    expect(wrapper.text()).toContain('Korpus importieren und verwalten')
    expect(wrapper.text()).toContain('Rolle Admin')
    expect(wrapper.find('#corpus-manager-open').attributes('aria-disabled')).toBe('true')

    await wrapper.find('#corpus-manager-open').trigger('click')

    expect(uiStore.corpusManagerOpen).toBe(false)
    expect(uiStore.toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Rolle Admin'),
    })
  })

  it('marks partially backed semantic commands as runnable with a method note', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = semanticContract()
    seedSemanticCorpus({ passage_search: true, word_similarity: false, sentence_alignment: false })
    const wrapper = mount(CommandPalette, {
      props: { modelValue: true },
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
        },
      },
    })

    expect(wrapper.text()).toContain('Semantik')
    expect(wrapper.text()).toContain('teilweise')
    expect(wrapper.text()).toContain('Wort-Embedding-Index')
    expect(wrapper.find('#nav-semantic').attributes('aria-disabled')).toBe('false')

    await wrapper.find('#nav-semantic').trigger('click')

    expect(actionBus.dispatch).toHaveBeenCalledWith({ type: 'nav/switchTab', payload: { tab: 'semantic' } })
  })

  it('offers safe ProductOperations as visible surface-open commands', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = operationCommandContract()
    seedAdminSession()
    seedFeatureRichCorpus()

    const wrapper = mount(CommandPalette, {
      props: { modelValue: true },
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
        },
      },
    })

    const command = wrapper.find('#operation-analysis-wordsketch-profile')
    const openableOperationIds = productCapabilities.firstClassOperationUiRecords
      .filter((record) => record.openTarget && record.adapterStatus === 'ready')
      .map((record) => record.operationId)

    expect(command.exists()).toBe(true)
    expect(command.attributes('aria-disabled')).toBe('false')
    expect(wrapper.text()).toContain('Analyse öffnen: Word Sketch berechnen')
    expect(wrapper.text()).not.toContain('analysis.wordsketch.profile')
    expect(wrapper.text()).not.toContain('/api/v1/analysis/wordsketch')

    for (const operationId of openableOperationIds) {
      expect(wrapper.find(`#${operationCommandId(operationId)}`).exists()).toBe(true)
    }

    await command.trigger('click')
    await flushPromises()

    expect(actionBus.dispatch).toHaveBeenCalledWith(
      { type: 'nav/switchTab', payload: { tab: 'wordsketch' } },
      { source: 'user' },
    )
    expect(useUiStore().focusedProductOperation?.operationId).toBe('analysis.wordsketch.profile')
  })

  it('opens write or long-running ProductOperations through their fachliche surface', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = operationCommandContract()
    seedAdminSession()
    seedFeatureRichCorpus()
    const uiStore = useUiStore()

    const wrapper = mount(CommandPalette, {
      props: { modelValue: true },
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
        },
      },
    })

    const command = wrapper.find('#operation-corpus-import-start')
    expect(command.exists()).toBe(true)
    expect(command.attributes('aria-disabled')).toBe('false')
    expect(wrapper.text()).toContain('Fachoberfläche öffnen: Importjob starten')
    expect(wrapper.text()).not.toContain('corpus.import.start')
    expect(wrapper.text()).not.toContain('generisch nicht direkt ausführbar')

    await command.trigger('click')
    await flushPromises()

    expect(actionBus.dispatch).not.toHaveBeenCalled()
    expect(uiStore.settingsOpen).toBe(true)
    expect(uiStore.corpusManagerOpen).toBe(true)
    expect(uiStore.settingsTab).toBe('general')
    expect(uiStore.focusedProductOperation?.operationId).toBe('corpus.import.start')
  })

  it('keeps corpus-blocked ProductOperation commands visible but disabled', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = operationCommandContract()
    seedAdminSession()
    seedWordOnlyCorpus()
    const uiStore = useUiStore()

    const wrapper = mount(CommandPalette, {
      props: { modelValue: true },
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
        },
      },
    })

    const command = wrapper.find('#operation-analysis-wordsketch-profile')
    expect(command.exists()).toBe(true)
    expect(command.attributes('aria-disabled')).toBe('true')
    expect(wrapper.text()).toContain('Tokenattribut rel')

    await command.trigger('click')

    expect(actionBus.dispatch).not.toHaveBeenCalled()
    expect(uiStore.toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Tokenattribut rel'),
    })
  })

})
