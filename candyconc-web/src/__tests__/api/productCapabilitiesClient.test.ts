import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { getAuthSession, getProductCapabilities, loginUser, logoutUser } from '@/api/client'


let captured: Array<{ method: string; url: string }> = []

function stubFetch(payload: unknown, status = 200) {
  captured = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = input instanceof Request ? input.method : (init?.method ?? 'GET')
      const url = input instanceof Request ? input.url : String(input)
      captured.push({ method, url })
      return new Response(JSON.stringify(payload), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

const productCapabilityContract = {
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
      id: 'query.kwic',
      title: 'KWIC search and pagination',
      area: 'search',
      maturity: 'stable',
      visibility: 'first_class_ui',
      backend_routes: ['/api/v1/query'],
      backend_route_descriptors: [{
        path: '/api/v1/query',
        methods: ['GET'],
        mutates: false,
        requires_corpus_features: [],
      }],
      frontend_evidence: [{ path: 'candyconc-web/src/App.vue', contains: 'KwicTable' }],
      action_types: ['query/execute'],
      copilot_tools: ['run_cqlf_query'],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
      operations: [{
        id: 'query.kwic.page',
        capability_id: 'query.kwic',
        label: 'KWIC laden',
        description: 'Lädt eine KWIC-Seite.',
        route: {
          path: '/api/v1/query',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
        },
        effects: ['read'],
        handler_key: 'query_kwic_page',
        surface_slot: 'query.kwic.page',
        priority: 10,
        input_schema_ref: 'query.kwic.request',
        required_context: ['active_query'],
        response_shape: 'data',
        run_semantics: 'instant',
        ui_execution_policy: 'contextual_ui',
        requires_parameters: true,
      }],
    },
  ],
}

describe('product capability contract API client', () => {
  beforeEach(() => {
    stubFetch(productCapabilityContract)
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('fetches and validates the product capability contract', async () => {
    const result = await getProductCapabilities()

    expect(result.version).toBe('product-capabilities-v1')
    expect(result.cqlf_capability_contract.current_level).toBe('2-')
    expect(result.capabilities[0]?.id).toBe('query.kwic')
    expect(result.capabilities[0]?.backend_route_descriptors[0]).toMatchObject({
      path: '/api/v1/query',
      methods: ['GET'],
      mutates: false,
    })
    expect(captured).toHaveLength(1)
    expect(captured[0]?.method).toBe('GET')
    expect(captured[0]?.url).toContain('/api/v1/capabilities')
  })

  it('rejects malformed product capability contracts', async () => {
    stubFetch({ version: 'product-capabilities-v1', capabilities: [] })

    await expect(getProductCapabilities()).rejects.toThrow()
  })

  it('fetches and validates the auth session contract', async () => {
    stubFetch({
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
    })

    const result = await getAuthSession()

    expect(result.schema_version).toBe('auth-session-v1')
    expect(result.effective_role).toBe('user')
    expect(captured).toHaveLength(1)
    expect(captured[0]?.method).toBe('GET')
    expect(captured[0]?.url).toContain('/api/v1/auth/session')
  })

  it('uses the backend login and logout routes without inventing token transport', async () => {
    stubFetch({ token: 'token-123' })

    const login = await loginUser({ username: 'admin', password: 'pw' })

    expect(login.token).toBe('token-123')
    expect(captured[0]).toMatchObject({ method: 'POST' })
    expect(captured[0]?.url).toContain('/api/v1/login')

    stubFetch({ status: 'ok' })
    const logout = await logoutUser()

    expect(logout.status).toBe('ok')
    expect(captured[0]).toMatchObject({ method: 'POST' })
    expect(captured[0]?.url).toContain('/api/v1/logout')
  })
})
