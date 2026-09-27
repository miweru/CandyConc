import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'

vi.mock('@/api/client', () => ({
  activateCorpus: vi.fn(async (name: string) => ({
    name,
    path: `/corpora/${name}`,
    token_count: 0,
    doc_count: 0,
    import_mode: 'registered',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
  })),
  getCorpora: vi.fn(async () => ({ corpora: [], count: 0 })),
  getProductCapabilities: vi.fn(async () => ({
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
        id: 'corpus.catalogue',
        title: 'corpus.catalogue',
        area: 'corpus',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/corpora/{corpus}/activate'],
        backend_route_descriptors: [
          {
            path: '/api/v1/corpora/{corpus}/activate',
            methods: ['POST'],
            mutates: true,
            requires_corpus_features: [],
          },
        ],
        operations: [
          {
            id: 'corpus.catalogue.activate',
            capability_id: 'corpus.catalogue',
            label: 'Korpus aktivieren',
            description: '',
            route: {
              path: '/api/v1/corpora/{corpus}/activate',
              methods: ['POST'],
              mutates: true,
              requires_corpus_features: [],
            },
            effects: ['write'],
            handler_key: 'corpus_catalogue_activate',
            surface_slot: 'corpus.catalogue.activate',
            priority: 10,
          },
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        limits: [],
      },
    ],
  })),
  getCorpusBuildReport: vi.fn(),
  getCorpusCapabilities: vi.fn(async (name: string) => ({
    name,
    title: name,
    path: `/corpora/${name}`,
    paired: false,
    pair_axes: [],
    capabilities: {},
  })),
  getAuthSession: vi.fn(async () => ({
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
  })),
  getSystemInfo: vi.fn(async () => ({ corpusName: 'anderes-korpus', tokenCount: 0 })),
  registerCorpus: vi.fn(),
  unregisterCorpus: vi.fn(),
}))

describe('corpus scope truth', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('clears stale KWIC rows when the active corpus changes', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults([
      { position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' },
    ], 42, true, false)
    queryStore.selectRow(0)
    queryStore.setHasMore(true)
    queryStore.setNextOffset(100)
    queryStore.setLastExecutedAt(123)

    const corpusStore = useCorpusCapabilitiesStore()
    await corpusStore.setActive('anderes-korpus')

    expect(queryStore.filters.corpus).toBe('anderes-korpus')
    expect(queryStore.results).toEqual([])
    expect(queryStore.totalHits).toBe(0)
    expect(queryStore.totalKnown).toBe(false)
    expect(queryStore.hasMore).toBe(false)
    expect(queryStore.nextOffset).toBe(0)
    expect(queryStore.selectedRows.size).toBe(0)
    expect(queryStore.lastExecutedAt).toBeNull()
  })
})
