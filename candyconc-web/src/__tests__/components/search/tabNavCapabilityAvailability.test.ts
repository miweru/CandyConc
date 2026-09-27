import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import TabNav from '@/components/search/TabNav.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

const dispatch = vi.fn()

vi.mock('@/composables', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables')>()
  return {
    ...actual,
    useDispatch: () => ({ dispatch }),
  }
})

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
    ],
  }
}

function roleBlockedContract(): ProductCapabilityContract {
  return {
    ...contract(),
    capabilities: [
      capability('query.kwic'),
      capability('analysis.frequency', {
        backend_routes: ['/api/v1/analysis/frequency_list'],
        backend_route_descriptors: [{
          path: '/api/v1/analysis/frequency_list',
          methods: ['GET'],
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

function readStyleBlock(componentPath: string): string {
  const src = readFileSync(componentPath, 'utf8')
  const match = src.match(/<style[^>]*>([\s\S]*?)<\/style>/)
  return (match?.[1] ?? '').replace(/\s+/g, ' ')
}

describe('TabNav corpus feature availability', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dispatch.mockClear()
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    seedSemanticCorpus({ passage_search: false, word_similarity: false, sentence_alignment: false })
  })

  it('renders product-visible but corpus-blocked tabs as disabled with a reason', async () => {
    const uiStore = useUiStore()
    const wrapper = mount(TabNav, {
      global: {
        stubs: {
          Dropdown: { template: '<div><slot name="trigger" /><slot /></div>' },
          DropdownItem: { props: ['disabled'], template: '<button type="button" :disabled="disabled"><slot /></button>' },
        },
      },
    })

    const semanticButton = wrapper.findAll('button').find((button) => button.text().includes('Semantik'))
    expect(semanticButton).toBeTruthy()
    expect(semanticButton?.attributes('aria-disabled')).toBe('true')
    expect(semanticButton?.attributes('aria-label')).toContain('Semantik')
    expect(semanticButton?.attributes('title')).toContain('Wort-Embedding-Index')

    await semanticButton?.trigger('click')

    expect(dispatch).not.toHaveBeenCalled()
    expect(uiStore.toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Embedding-Index'),
    })
  })

  it('renders partially backed semantic tabs as enabled but visibly partial', async () => {
    seedSemanticCorpus({ passage_search: true, word_similarity: false, sentence_alignment: false })
    const wrapper = mount(TabNav, {
      global: {
        stubs: {
          Dropdown: { template: '<div><slot name="trigger" /><slot /></div>' },
          DropdownItem: { props: ['disabled'], template: '<button type="button" :disabled="disabled"><slot /></button>' },
        },
      },
    })

    const semanticButton = wrapper.findAll('button').find((button) => button.text().includes('Semantik'))
    expect(semanticButton).toBeTruthy()
    expect(semanticButton?.attributes('aria-disabled')).toBe('false')
    expect(semanticButton?.attributes('aria-label')).toContain('Semantik')
    expect(semanticButton?.classes()).toContain('is-partial')
    expect(semanticButton?.text()).toContain('teilweise')
    expect(semanticButton?.attributes('title')).toContain('Wort-Embedding-Index')

    await semanticButton?.trigger('click')

    expect(dispatch).toHaveBeenCalledWith({ type: 'nav/switchTab', payload: { tab: 'semantic' } })
  })

  it('keeps role-blocked first-class analysis tabs visible with an execution reason', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = roleBlockedContract()
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
    const wrapper = mount(TabNav, {
      global: {
        stubs: {
          Dropdown: { template: '<div><slot name="trigger" /><slot /></div>' },
          DropdownItem: { props: ['disabled'], template: '<button type="button" :disabled="disabled"><slot /></button>' },
        },
      },
    })

    const frequencyButton = wrapper.findAll('button').find((button) => button.text().includes('Frequenz'))
    expect(frequencyButton).toBeTruthy()
    expect(frequencyButton?.attributes('aria-disabled')).toBe('true')
    expect(frequencyButton?.attributes('title')).toContain('Rolle Admin')

    await frequencyButton?.trigger('click')

    expect(dispatch).not.toHaveBeenCalled()
    expect(uiStore.toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Rolle Admin'),
    })
  })

  it('keeps desktop tabs out of the mobile layout where MobileNav owns navigation', () => {
    const css = readStyleBlock(resolve(process.cwd(), 'src/components/search/TabNav.vue'))
    expect(css).toMatch(/\.tab-nav\s*\{[^}]*hidden[^}]*md:flex/)
  })
})
