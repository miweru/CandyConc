import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

import { useMetaValueOptions } from '@/composables/queryBuilder/useMetaValueOptions'
import { createBuilderNode, createMetaCond, type CqlBuilderNode } from '@/lib/queryBuilder/ast'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getMetaValuesPage: vi.fn(),
  getProductCapabilities: vi.fn(),
  getAuthSession: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getMetaValuesPage: (...args: unknown[]) => apiMocks.getMetaValuesPage(...args),
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getAuthSession: (...args: unknown[]) => apiMocks.getAuthSession(...args),
  }
})

function contract(includeMetaValues: boolean): ProductCapabilityContract {
  const routes = includeMetaValues
    ? [{ path: '/api/v1/analysis/meta_values', methods: ['POST'], mutates: false }]
    : []
  const operations = includeMetaValues
    ? [{
        id: 'research.subcorpora_docsets.meta_values',
        capability_id: 'research.subcorpora_docsets',
        label: 'Metadatenwerte',
        description: '',
        route: {
          path: '/api/v1/analysis/meta_values',
          methods: ['POST'],
          mutates: false,
          requires_corpus_features: [],
        },
        effects: ['read'],
        handler_key: 'research_subcorpora_docsets_meta_values',
        surface_slot: 'research.subcorpora_docsets.meta_values',
        priority: 10,
      }]
    : []
  return {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [{
      id: 'research.subcorpora_docsets',
      title: 'Subcorpora and docsets',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: routes.map((route) => route.path),
      backend_route_descriptors: routes.map((route) => ({
        ...route,
        requires_corpus_features: [],
        access: 'user',
        required_role: 'user',
        transport: 'http',
        route_class: 'product_surface',
      })),
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      operations,
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as ProductCapabilityContract
}

function seedContracts(includeMetaValues: boolean) {
  const productCapabilities = useProductCapabilitiesStore()
  const seeded = contract(includeMetaValues)
  productCapabilities.contract = seeded
  productCapabilities.status = 'ready'
  apiMocks.getProductCapabilities.mockResolvedValue(seeded)

  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'user',
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

function rootWithMetaField(field = 'genre'): CqlBuilderNode {
  return {
    id: 'where-1',
    type: 'where',
    expr: createMetaCond({ field }),
    node: createBuilderNode('tok'),
  }
}

describe('useMetaValueOptions route-operation gates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.clearAllMocks()
    apiMocks.getMetaValuesPage.mockResolvedValue({
      values: { genre: ['essay', 'news'] },
      truncatedFields: [],
      limit: 250,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not call meta_values when the concrete route operation is absent', async () => {
    seedContracts(false)
    const options = useMetaValueOptions({
      rootNode: ref(rootWithMetaField()),
      mode: ref('advanced'),
      activeCorpus: ref('demo'),
    })

    options.scheduleMetaValueLoad()
    await vi.advanceTimersByTimeAsync(350)

    expect(apiMocks.getMetaValuesPage).not.toHaveBeenCalled()
    expect(options.metaValueOptions.value).toEqual({})
    expect(options.metaValueError.value).toContain('Builder-Metadatenwerte')
  })

  it('loads meta_values when the concrete route operation is offered', async () => {
    seedContracts(true)
    const options = useMetaValueOptions({
      rootNode: ref(rootWithMetaField()),
      mode: ref('advanced'),
      activeCorpus: ref('demo'),
    })

    options.scheduleMetaValueLoad()
    await vi.advanceTimersByTimeAsync(350)

    expect(apiMocks.getMetaValuesPage).toHaveBeenCalledWith(
      { fields: ['genre'], corpus: 'demo' },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(options.metaValueOptions.value).toEqual({ genre: ['essay', 'news'] })
    expect(options.metaValueError.value).toBeNull()
  })
})
