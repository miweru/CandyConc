/**
 * The embedding settings switch the server's embedding backend between
 * spacy and none and describe the word vector packages as the server does.
 *
 * Before, an installed package had an "Activate" button that sent the
 * package name as the backend. The server serves only spacy and none and
 * answers anything else with 422 (release/rest_backend 6afd2352a). The note
 * said word vector packages extend the similar-words thesaurus, but no
 * analysis reads a package (limits of settings.embedding_management).
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EmbeddingsManager from '@/components/settings/EmbeddingsManager.vue'
import { getAuthSession, getEmbeddingBackend, getProductCapabilities, setEmbeddingBackend } from '@/api/client'
import { applyLocale } from '@/i18n/locale'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(),
    getAuthSession: vi.fn(),
    getPrefs: vi.fn(async () => ({ prefs: {} })),
    getLocalSemanticIndexPreflight: vi.fn(async () => null),
    getEmbeddingModels: vi.fn(async () => []),
    getEmbeddingBackend: vi.fn(),
    setEmbeddingBackend: vi.fn(),
  }
})

const LIMITS = [
  'The embedding backend is spacy (vectors of the pipeline named in CANDYCONC_EMB_SPACY_MODEL) or none (off). The server rejects other values. A change lasts until the server stops.',
  'The list of word vector packages comes from vendor/embedding_packages.json in the package. This release does not ship the file, so the list is empty. No analysis reads an installed package.',
]

function route(path: string, method: string) {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }
}

function embeddingCapability(withBackendRead: boolean): ProductCapability {
  const specs: Array<[string, string, string]> = [
    ['settings.embedding_management.list', '/api/v1/embeddings/list', 'GET'],
    ['settings.embedding_management.remove', '/api/v1/embeddings/remove', 'POST'],
    ['settings.embedding_management.set_active', '/api/v1/settings/embeddings', 'POST'],
  ]
  if (withBackendRead) specs.push(['settings.embedding_management.backend', '/api/v1/settings/embeddings', 'GET'])
  const routes = specs.map(([, path, method]) => route(path, method))
  return {
    id: 'settings.embedding_management',
    title: 'Embeddings',
    area: 'settings',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: routes.map((r) => r.path),
    backend_route_descriptors: routes,
    operations: specs.map(([id, path, method]) => ({
      id,
      capability_id: 'settings.embedding_management',
      label: id,
      description: '',
      route: route(path, method),
      effects: method === 'GET' ? ['read'] : ['write'],
      handler_key: id,
      surface_slot: id,
      priority: 10,
    })),
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: withBackendRead ? LIMITS : [],
    notes: '',
  } as unknown as ProductCapability
}

function seed(withBackendRead = true) {
  const contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [embeddingCapability(withBackendRead)],
  } as ProductCapabilityContract
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = contract
  productCapabilities.status = 'ready'
  // Reloads of the access context return the same contract and session.
  vi.mocked(getProductCapabilities).mockResolvedValue(contract)
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'admin',
    role: 'admin',
    effective_role: 'admin',
    rbac_enabled: false,
    security_mode: 'local_dev_unsafe',
    release_mode: false,
    unsafe_token_transport: false,
    dev_token_available: true,
    can_access_all_roles: true,
  } as any
  vi.mocked(getAuthSession).mockResolvedValue(session.session as any)
  const settings = useSettingsStore()
  settings.embeddings = [{ id: 'installed', name: 'Installed vectors', size: '1 MB', downloaded: true }]
}

function mountManager() {
  return mount(EmbeddingsManager, { global: { stubs: { LoadingSpinner: true } } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  applyLocale('en')
  vi.mocked(getEmbeddingBackend).mockResolvedValue({ backend: 'spacy', supportedBackends: ['spacy', 'none'], spacyModel: 'en_core_web_md' })
  vi.mocked(setEmbeddingBackend).mockImplementation(async (backend: string) => ({
    backend, supportedBackends: ['spacy', 'none'], spacyModel: 'en_core_web_md',
  }))
})

afterEach(() => {
  useSettingsStore().stopLocalSemanticIndexPolling()
  applyLocale('de')
})

describe('embedding backend in the settings', () => {
  it('shows the backend and switches it between spacy and none', async () => {
    seed()
    const wrapper = mountManager()
    await flushPromises()

    const options = wrapper.findAll('[data-embedding-backend]')
    expect(options.map((option) => option.attributes('data-embedding-backend'))).toEqual(['spacy', 'none'])
    expect(wrapper.get('[data-embedding-backend="spacy"]').attributes('aria-checked')).toBe('true')
    expect(wrapper.text()).toContain('en_core_web_md')

    await wrapper.get('[data-embedding-backend="none"]').trigger('click')
    await flushPromises()
    expect(setEmbeddingBackend).toHaveBeenCalledWith('none')
    expect(wrapper.get('[data-embedding-backend="none"]').attributes('aria-checked')).toBe('true')
  })

  it('offers no activation of a word vector package', async () => {
    seed()
    const wrapper = mountManager()
    await flushPromises()
    expect(wrapper.text()).toContain('Installed vectors')
    expect(wrapper.find('.btn-activate').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/\bActivate\b/)
  })

  it('describes the packages with the limits of the capability contract', async () => {
    seed()
    const wrapper = mountManager()
    await flushPromises()
    const note = wrapper.get('.info-box').text()
    for (const limit of LIMITS) expect(note).toContain(limit)
    expect(note).not.toContain('extend the similar-words thesaurus')
  })

  it('keeps the switch away on a server without the backend route', async () => {
    seed(false)
    const wrapper = mountManager()
    await flushPromises()
    expect(getEmbeddingBackend).not.toHaveBeenCalled()
    expect(wrapper.find('[data-embedding-backend]').exists()).toBe(false)
    expect(wrapper.get('.info-box').text()).not.toContain('extend the similar-words thesaurus')
  })
})

// "spaCy pipeline: de_core_news_md" did not say what the pipeline is for, and
// the word vectors of the active corpus come from its own pipeline. The server
// sends both (spacy_model_used_for, word_vectors per corpus).
describe('scope of the spaCy pipeline and word vectors of the active corpus', () => {
  const english = {
    backend: 'spacy',
    supportedBackends: ['spacy', 'none'],
    spacyModel: 'de_core_news_md',
    spacyModelUsedFor: ['passage_queries', 'copilot_word_clusters', 'fallback'],
    wordVectors: [
      { corpus: 'dta_de', available: true, source: 'pipeline', pipeline: 'de_core_news_md', reason: '' },
      { corpus: 'default', available: true, source: 'pipeline', pipeline: 'en_core_web_md', reason: '' },
    ],
  }

  it('says what the pipeline embeds and where the active corpus takes its vectors from', async () => {
    vi.mocked(getEmbeddingBackend).mockResolvedValue(english as never)
    seed()
    await useSettingsStore().setLanguage('en')
    const wrapper = mountManager()
    await flushPromises()
    const text = wrapper.get('[data-testid="embedding-backend"]').text()
    expect(text).toContain('Default spaCy pipeline: de_core_news_md')
    expect(text).toContain('the search text of a passage search')
    expect(text).toContain('the word clusters of the Copilot')
    expect(text).toContain('text of corpora that do not record their pipeline')
    const vectors = wrapper.get('[data-testid="corpus-word-vectors"]').text()
    expect(vectors).toContain('Word vectors of default: from the pipeline en_core_web_md')
    expect(vectors).not.toContain('de_core_news_md')
  })

  it('names the reason when the active corpus has no word vectors', async () => {
    vi.mocked(getEmbeddingBackend).mockResolvedValue({
      ...english,
      wordVectors: [{
        corpus: 'default',
        available: false,
        source: null,
        pipeline: 'blank:en',
        reason: 'The corpus was imported with blank:en, which only tokenizes and has no word vectors.',
      }],
    } as never)
    seed()
    await useSettingsStore().setLanguage('en')
    const wrapper = mountManager()
    await flushPromises()
    expect(wrapper.get('[data-testid="corpus-word-vectors"]').text()).toBe(
      'No word vectors for default: The corpus was imported with blank:en, which only tokenizes and has no word vectors.',
    )
  })

  it('reads in German', async () => {
    vi.mocked(getEmbeddingBackend).mockResolvedValue(english as never)
    seed()
    await useSettingsStore().setLanguage('de')
    const wrapper = mountManager()
    await flushPromises()
    const text = wrapper.get('[data-testid="embedding-backend"]').text()
    expect(text).toContain('Standard-spaCy-Pipeline: de_core_news_md')
    expect(text).toContain('den Suchtext einer Passagensuche')
    expect(wrapper.get('[data-testid="corpus-word-vectors"]').text()).toContain(
      'Wortvektoren von default: aus der Pipeline en_core_web_md',
    )
  })
})

