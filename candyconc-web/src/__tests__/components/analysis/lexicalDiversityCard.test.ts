import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import LexicalDiversityCard from '@/components/analysis/LexicalDiversityCard.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'

// IMPORTANT: this suite drives the REAL `getLexicalDiversity` client through a
// fetch stub (it does NOT mock the client). That makes it a load-bearing
// regression gate for T1: it exercises the per_side DICT -> ordered-array
// coercion and the top-level `size_warning` passthrough exactly as the backend
// emits them. Mocking the client here would re-introduce the masking fixture
// the r7 audit flagged.

function jsonResponse(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  )
}

const stubs = {
  Button: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  Skeleton: true,
  RefreshCw: true,
  AlertTriangle: true,
  Activity: true,
}

function seedProductContract() {
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

  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
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
        title: 'Pairing-free and paired contrast analyses',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/analysis/lexical-diversity'],
        backend_route_descriptors: [{
          path: '/api/v1/analysis/lexical-diversity',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        }],
        operations: [{
          id: 'analysis.contrast.lexical_diversity',
          capability_id: 'analysis.contrast',
          label: 'Lexikalische Diversität',
          description: '',
          route: {
            path: '/api/v1/analysis/lexical-diversity',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          effects: ['read'],
          handler_key: 'lexical_diversity',
          surface_slot: 'analysis.contrast.lexical_diversity',
          priority: 30,
        }],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
    ],
  }
}

describe('LexicalDiversityCard (F4)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedProductContract()
  })

  afterEach(() => vi.unstubAllGlobals())

  it('renders two side columns from a per_side DICT and shows backend size_warning', async () => {
    // REAL backend wire shape: per_side is a DICT, sides carry no label, and the
    // size caveat is a top-level string.
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          sttr_window: 1000,
          per_side: {
            target: { ttr: 0.4, sttr: 0.7, guiraud: 22.1, n_tokens: 10000, n_types: 4000 },
            reference: { ttr: 0.6, sttr: 0.72, guiraud: 20.3, n_tokens: 4000, n_types: 2400 },
          },
          size_warning: 'Backend-Warnung: Seiten stark unterschiedlich groß (10000 vs. 4000).',
        })
      )
    )

    const wrapper = mount(LexicalDiversityCard, {
      props: {
        corpus: 'demo',
        targetDocsetId: 'ai',
        referenceDocsetId: 'human',
        targetLabel: 'KI',
        referenceLabel: 'Mensch',
        autoLoad: true,
      },
      global: { stubs },
    })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Lexikalische Diversität')
    expect(text).toContain('STTR')
    expect(text).toContain('1.000') // STTR window reported

    // Coercion produced TWO side columns (one header per side besides "Maß").
    const headerCells = wrapper.findAll('.diversity-table thead th')
    expect(headerCells).toHaveLength(3)
    // Labels fall back to the prop labels (target/reference order preserved).
    expect(headerCells[1].text()).toBe('KI')
    expect(headerCells[2].text()).toBe('Mensch')

    // The BACKEND warning is rendered preferentially (not the local heuristic text).
    const warning = wrapper.find('.length-warning')
    expect(warning.exists()).toBe(true)
    expect(warning.text()).toContain('Backend-Warnung')
  })

  it('falls back to the local heuristic warning when no backend size_warning is present', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          per_side: {
            target: { ttr: 0.4, sttr: 0.7, n_tokens: 10000 },
            reference: { ttr: 0.6, sttr: 0.72, n_tokens: 4000 },
          },
        })
      )
    )
    const wrapper = mount(LexicalDiversityCard, {
      props: { targetDocsetId: 'ai', referenceDocsetId: 'human', autoLoad: true },
      global: { stubs },
    })
    await flushPromises()
    // 10000 vs 4000 -> >20% diff -> local heuristic fires even without backend warning.
    const warning = wrapper.find('.length-warning')
    expect(warning.exists()).toBe(true)
    expect(warning.text()).toContain('Roh-TTR')
  })

  it('does not warn when sides are comparable in size and no backend warning', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          per_side: {
            target: { ttr: 0.5, sttr: 0.7, n_tokens: 5000 },
            reference: { ttr: 0.51, sttr: 0.71, n_tokens: 4900 },
          },
        })
      )
    )
    const wrapper = mount(LexicalDiversityCard, {
      props: { targetDocsetId: 'ai', referenceDocsetId: 'human', autoLoad: true },
      global: { stubs },
    })
    await flushPromises()
    expect(wrapper.find('.length-warning').exists()).toBe(false)
  })

  it('degrades softly when the endpoint is unavailable (404)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(new Response('not found', { status: 404 }))
      )
    )
    const wrapper = mount(LexicalDiversityCard, {
      props: { corpus: 'demo', autoLoad: true },
      global: { stubs },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('noch nicht verfügbar')
  })
})
