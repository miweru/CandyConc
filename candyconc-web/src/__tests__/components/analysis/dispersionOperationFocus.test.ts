import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DispersionTab from '@/components/analysis/DispersionTab.vue'
import { useCorpusCapabilitiesStore, useQueryStore, useSettingsStore } from '@/stores'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getDispersion: vi.fn(),
  getDispersionOffsets: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getDispersion: (...args: unknown[]) => apiMocks.getDispersion(...args),
    getDispersionOffsets: (...args: unknown[]) => apiMocks.getDispersionOffsets(...args),
  }
})

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  CapabilityBoundaryPanel: { template: '<div class="boundary-stub" />' },
  EmptyState: { template: '<div class="empty-state"><slot /></div>' },
  Heatmap: { template: '<div class="heatmap-stub" />' },
  JobStatusPill: { template: '<div class="job-status-stub" />' },
  MethodPanel: { template: '<div class="method-stub" />' },
  SaveAnalysisButton: { template: '<button />' },
  Skeleton: { template: '<div class="skeleton-stub" />' },
}

function dispersionContract(): ProductCapabilityContract {
  const statsRoute = {
    path: '/api/v1/analysis/dispersion',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
  const offsetsRoute = {
    path: '/api/v1/analysis/dispersion_offsets',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [{
      id: 'analysis.dispersion',
      title: 'Dispersion',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [statsRoute.path, offsetsRoute.path],
      backend_route_descriptors: [statsRoute, offsetsRoute],
      operations: [
        {
          id: 'analysis.dispersion.stats',
          capability_id: 'analysis.dispersion',
          label: 'Dispersion',
          description: 'Dispersionsstatistik laden.',
          route: statsRoute,
          effects: ['read'],
          handler_key: 'loadDispersion',
          copilot_tools: ['dispersion_offsets'],
          surface_slot: 'analysis.dispersion.stats',
          priority: 10,
        },
        {
          id: 'analysis.dispersion.offsets',
          capability_id: 'analysis.dispersion',
          label: 'Dispersions-Offsets',
          description: 'Offset-Evidence laden.',
          route: offsetsRoute,
          effects: ['read'],
          handler_key: 'loadDispersionOffsets',
          copilot_tools: ['dispersion_offsets'],
          surface_slot: 'analysis.dispersion.offsets',
          priority: 20,
        },
      ],
      frontend_evidence: [],
      action_types: ['analysis/dispersion'],
      copilot_tools: ['dispersion_offsets'],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
      notes: '',
    }],
  }
}

function seedSessionAndContract(): void {
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
  productCapabilities.contract = dispersionContract()
  productCapabilities.status = 'ready'

  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'demo',
    path: '/corpora/demo',
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
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]

  const settings = useSettingsStore()
  settings.systemInfo = {
    ...settings.systemInfo,
    tokenCount: 1000,
  }
}

function captureCsvBlob() {
  let captured: Blob | null = null
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: vi.fn((blob: Blob) => {
      captured = blob
      return 'blob:dispersion'
    }),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: vi.fn(),
  })
  return () => captured
}

async function blobText(blob: Blob): Promise<string> {
  if (typeof blob.text === 'function') return blob.text()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
}

function mountTab() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  return mount(DispersionTab, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs,
    },
  })
}

describe('DispersionTab ProductOperation focus', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMocks.getDispersion.mockResolvedValue({
      term: 'Hase',
      partitions: [1, 0, 2],
      total: 3,
      dp: 0.42,
      dpnorm: 0.36,
      positional_dp_windowed: 0.31,
      positional_window_count: 3,
      classification: 'fairly_clustered',
      unit: 'document',
      basis: 'global',
      token_count: 1000,
      partial: false,
      fallback: false,
      limitations: [],
    })
    apiMocks.getDispersionOffsets.mockResolvedValue({
      offsets: [1, 10, 50],
      basis: 'global',
      token_count: 1000,
      limitations: [],
    })
    seedSessionAndContract()
    const queryStore = useQueryStore()
    queryStore.filters = { corpus: 'demo' }
    queryStore.setTerm('Hase')
  })

  it('consumes the offsets ProductOperation as focused Offset-Evidence', async () => {
    const uiStore = useUiStore()
    uiStore.focusProductOperation('analysis.dispersion.offsets', {
      capabilityId: 'analysis.dispersion',
      surfaceSlot: 'analysis.dispersion.offsets',
      preferredMode: 'offset_evidence',
    })

    const wrapper = mountTab()
    await flushPromises()

    const offsetPanel = wrapper.find('.offset-evidence-panel')
    expect(offsetPanel.exists()).toBe(true)
    expect(offsetPanel.classes()).toContain('focused')
    expect(offsetPanel.text()).toContain('Offset-Evidence')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('shows document basis separately from positional-window comparison', async () => {
    const wrapper = mountTab()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Positionsfenster')
    expect(text).toContain('Dokumentbasis: 3 Dokumentpartitionen')
    expect(text).toContain('Positionsfenster-DP')
    expect(text).toContain('3 Positionsfenster')
    expect(text).toContain('Dokumentverteilung im aktuellen Scope')
  })

  it('exports whole-corpus docs and tokens from the corpus catalogue, not empty docset stats', async () => {
    const capturedBlob = captureCsvBlob()
    const wrapper = mountTab()
    await flushPromises()

    await wrapper.get('button[aria-label="Dispersion als CSV exportieren"]').trigger('click')

    const blob = capturedBlob()
    expect(blob).not.toBeNull()
    const csv = await blobText(blob!)
    expect(csv).toContain('# Docset: all')
    expect(csv).toContain('# Docs: 10')
    expect(csv).toContain('# Tokens: 1000')
    expect(csv).toContain('# DispersionTokenBasis: 1000')
    expect(csv).not.toContain('# Docs: 0')
    expect(csv).not.toContain('# Tokens: 0')
  })
})
