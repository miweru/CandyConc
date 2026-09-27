import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAnnotationsStore } from '@/stores/annotations'
import { useDocsetStore } from '@/stores/docset'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import {
  getAnnotationAgreement,
} from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAnnotations: vi.fn(async () => ({ annotations: {}, scheme: { categories: [], revision: 0 } })),
    getAnnotationScheme: vi.fn(async () => ({ categories: [], revision: 0 })),
    getAnnotationSettings: vi.fn(async () => ({ multiCoder: false })),
    getAnnotationAgreement: vi.fn(),
  }
})

function route(path: string, method = 'GET') {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function seedAgreementContract() {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [{
      id: 'research.annotations',
      title: 'KWIC annotation workflow',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: ['/api/v1/annotations/agreement'],
      backend_route_descriptors: [route('/api/v1/annotations/agreement', 'GET')],
      operations: [{
        id: 'research.annotations.agreement',
        capability_id: 'research.annotations',
        label: 'Übereinstimmung laden',
        description: '',
        route: route('/api/v1/annotations/agreement', 'GET'),
        effects: ['read'],
        handler_key: 'research_annotations_agreement',
        surface_slot: 'research.annotations.agreement',
        priority: 10,
      }],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as never
  productCapabilities.status = 'ready'
}

const corpusWideResult = {
  comparableRows: 4,
  annotators: ['alice', 'bob'],
  percentAgreement: 0.75,
  cohensKappa: 0.6,
  fleissKappa: null,
  perCategory: [],
}

describe('annotation agreement — corpus scope is explicit (ANNOTATION-03)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedAgreementContract()
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'doc-set-7'
  })

  it('does not request an unsupported docset scope and labels the corpus-wide result', async () => {
    vi.mocked(getAnnotationAgreement).mockResolvedValueOnce(corpusWideResult)

    const store = useAnnotationsStore()
    await store.loadAgreement()

    // No raw red error.
    expect(store.agreementError).toBeNull()
    // A clear informational notice.
    expect(store.agreementNotice).toContain('gesamte aktive Korpus')
    // The corpus-wide result is shown.
    expect(store.agreement?.comparableRows).toBe(4)
    // The backend cannot compute a scoped agreement, so never make a request
    // that pretends it can. This prevents an avoidable 422 in the live product.
    expect(getAnnotationAgreement).toHaveBeenCalledTimes(1)
    expect(getAnnotationAgreement).toHaveBeenCalledWith({ corpus: 'default' })
  })

  it('still surfaces a genuine error (non-422) as an error, not a notice', async () => {
    vi.mocked(getAnnotationAgreement).mockRejectedValue(new Error('boom 500'))

    const store = useAnnotationsStore()
    await store.loadAgreement()

    expect(store.agreementError).toContain('boom 500')
    expect(store.agreementNotice).toBeNull()
  })
})
