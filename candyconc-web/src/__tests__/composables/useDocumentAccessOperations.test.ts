import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useDocumentAccessOperations } from '@/composables/useDocumentAccessOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getDocSnippet: vi.fn(),
  getDocument: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getDocSnippet: (...args: unknown[]) => apiMocks.getDocSnippet(...args),
    getDocument: (...args: unknown[]) => apiMocks.getDocument(...args),
  }
})

function route(path: string, method: string) {
  return {
    path,
    methods: [method],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
}


function operationsForDocumentCapability(
  descriptors: ReturnType<typeof route>[],
): ProductCapabilityOperation[] {
  const byPath = new Map(descriptors.map((descriptor) => [descriptor.path, descriptor]))
  const operations: ProductCapabilityOperation[] = []
  const snippetRoute = byPath.get('/api/v1/doc/snippet')
  if (snippetRoute) {
    operations.push({
      id: 'query.document_access.snippet',
      capability_id: 'query.document_access',
      label: 'Dokument-Snippet',
      description: '',
      route: snippetRoute,
      effects: ['read'],
      handler_key: 'doc_snippet',
      surface_slot: 'query.document_access.snippet',
      priority: 10,
    })
  }
  const documentRoute = byPath.get('/api/v1/document/{doc_id}')
  if (documentRoute) {
    operations.push({
      id: 'query.document_access.full_text',
      capability_id: 'query.document_access',
      label: 'Dokument öffnen',
      description: '',
      route: documentRoute,
      effects: ['read'],
      handler_key: 'document_text',
      surface_slot: 'query.document_access.full_text',
      priority: 20,
    })
  }
  return operations
}

function documentCapability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const backendRouteDescriptors = overrides.backend_route_descriptors ?? []
  return {
    id: 'query.document_access',
    title: 'Document access',
    area: 'search',
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: backendRouteDescriptors,
    operations: overrides.operations ?? operationsForDocumentCapability(backendRouteDescriptors),
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

function contract(capability: ProductCapability): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [capability],
  }
}

function seedUserSession() {
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
}

describe('useDocumentAccessOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks snippet loading when the concrete snippet route is not offered', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(documentCapability({
      backend_routes: ['/api/v1/document/{doc_id}'],
      backend_route_descriptors: [route('/api/v1/document/{doc_id}', 'GET')],
    }))
    productCapabilities.status = 'ready'

    const { loadDocSnippet } = useDocumentAccessOperations()

    await expect(loadDocSnippet({ pos: 42 })).rejects.toThrow('Serverfunktion')
    expect(apiMocks.getDocSnippet).not.toHaveBeenCalled()
  })

  it('blocks document loading when document access is not first-class visible', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(documentCapability({
      visibility: 'expert_api',
      backend_routes: ['/api/v1/document/{doc_id}'],
      backend_route_descriptors: [route('/api/v1/document/{doc_id}', 'GET')],
    }))
    productCapabilities.status = 'ready'

    const { loadDocument } = useDocumentAccessOperations()

    await expect(loadDocument('doc-1')).rejects.toThrow('nicht als Oberfläche freigegeben')
    expect(apiMocks.getDocument).not.toHaveBeenCalled()
  })

  it('calls the backend only after the concrete document route is available', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(documentCapability({
      backend_routes: ['/api/v1/document/{doc_id}', '/api/v1/doc/snippet'],
      backend_route_descriptors: [
        route('/api/v1/document/{doc_id}', 'GET'),
        route('/api/v1/doc/snippet', 'GET'),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.getDocument.mockResolvedValue({
      doc_id: 7,
      doc: 'doc-7',
      meta: {},
      text: 'Hase läuft.',
    })

    const { loadDocument } = useDocumentAccessOperations()

    await expect(loadDocument('7', 'demo')).resolves.toMatchObject({ doc_id: 7 })
    expect(apiMocks.getDocument).toHaveBeenCalledWith('7', 'demo')
  })
})
