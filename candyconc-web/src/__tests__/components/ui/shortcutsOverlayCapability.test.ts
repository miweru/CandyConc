import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ShortcutsOverlay from '@/components/ui/ShortcutsOverlay.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapabilityContract } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(),
    getAuthSession: vi.fn(),
  }
})

const stubs = {
  Modal: { template: '<div class="modal"><slot name="header" /><slot /><slot name="footer" /></div>' },
}

function capability(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
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
      capability('query.kwic'),
      capability('analysis.semantic_similarity', {
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
      }),
      capability('research.replay_export', {
        backend_routes: ['/api/v1/export/pdf'],
        backend_route_descriptors: [{
          path: '/api/v1/export/pdf',
          methods: ['POST'],
          mutates: false,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        }],
      }),
    ],
  }
}

function seedCorpus() {
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
      semantic: { passage_search: true, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]
}

function seedUserSession() {
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

describe('ShortcutsOverlay capability awareness', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    seedCorpus()
    seedUserSession()
  })

  it('uses surface availability for partial and role-blocked shortcut help', () => {
    const wrapper = mount(ShortcutsOverlay, {
      props: { modelValue: true },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('Semantik Tab')
    expect(wrapper.text()).toContain('teilweise')
    expect(wrapper.text()).toContain('Wort-Embedding-Index')
    expect(wrapper.text()).toContain('Export-Dialog öffnen')
    expect(wrapper.text()).toContain('Rolle Admin')
  })
})
