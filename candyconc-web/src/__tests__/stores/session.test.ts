import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useSessionStore } from '@/stores/session'
import type { AuthSession, ProductCapability } from '@/api/client'
import { clearAuthToken, getAuthToken, setAuthToken } from '@/api/auth'

const getAuthSession = vi.fn()
const loginUser = vi.fn()
const logoutUser = vi.fn()

vi.mock('@/api/client', () => ({
  getAuthSession: (...args: unknown[]) => getAuthSession(...args),
  loginUser: (...args: unknown[]) => loginUser(...args),
  logoutUser: (...args: unknown[]) => logoutUser(...args),
}))

function session(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
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
    ...overrides,
  }
}

function localDevSession(overrides: Partial<AuthSession> = {}): AuthSession {
  return session({
    username: 'local-dev',
    role: 'admin',
    effective_role: 'admin',
    rbac_enabled: false,
    security_mode: 'local_dev_unsafe',
    release_mode: false,
    unsafe_token_transport: true,
    dev_token_available: true,
    can_access_all_roles: true,
    ...overrides,
  })
}

function capability(requiredRole: string): ProductCapability {
  return {
    id: 'corpus.import',
    title: 'Korpusimport',
    area: 'corpus',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: ['/api/v1/corpora/imports'],
    backend_route_descriptors: [{
      path: '/api/v1/corpora/imports',
      methods: ['POST'],
      mutates: true,
      requires_corpus_features: [],
      access: requiredRole,
      required_role: requiredRole,
      transport: 'http',
      route_class: requiredRole === 'admin' ? 'admin_surface' : 'product_surface',
    }],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

describe('session capability access', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    clearAuthToken()
    window.sessionStorage.clear()
    window.localStorage.clear()
  })

  afterEach(() => {
    clearAuthToken()
    vi.unstubAllGlobals()
  })

  it('fails closed for role-gated routes before the session is authoritative', () => {
    const store = useSessionStore()

    expect(store.canAccessAnyRoute(capability('admin'))).toBe(false)
    expect(store.accessBlockReason(capability('admin'), 'Korpusimport')).toContain('Sitzungsdaten')
  })

  it('blocks admin routes for user sessions and explains the required role', async () => {
    getAuthSession.mockResolvedValue(session({ role: 'user', effective_role: 'user' }))
    const store = useSessionStore()
    await store.load()

    expect(store.canAccessAnyRoute(capability('admin'))).toBe(false)
    expect(store.accessBlockReason(capability('admin'), 'Korpusimport')).toContain('Rolle Admin')
  })

  it('treats backend annotator sessions as eligible for user-level routes only', async () => {
    getAuthSession.mockResolvedValue(session({ role: 'annotator', effective_role: 'annotator' }))
    const store = useSessionStore()
    await store.load()

    expect(store.roleDisplay).toBe('Annotator')
    expect(store.canAccessAnyRoute(capability('user'))).toBe(true)
    expect(store.canAccessAnyRoute(capability('manager'))).toBe(false)
  })

  it('allows admin routes for local-dev all-role sessions', async () => {
    getAuthSession.mockResolvedValue(session({
      authenticated: false,
      token_present: false,
      username: 'guest',
      role: null,
      effective_role: 'admin',
      rbac_enabled: false,
      security_mode: 'local_dev_unsafe',
      release_mode: false,
      unsafe_token_transport: true,
      dev_token_available: true,
      can_access_all_roles: true,
    }))
    const store = useSessionStore()
    await store.load()

    expect(store.canAccessAnyRoute(capability('admin'))).toBe(true)
    expect(store.accessBlockReason(capability('admin'), 'Korpusimport')).toBeNull()
  })

  it('refreshes a stale local dev token after a backend restart', async () => {
    setAuthToken('stale-dev-token')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      token: 'fresh-dev-token',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    getAuthSession
      .mockResolvedValueOnce(localDevSession({
        authenticated: false,
        username: null,
        role: null,
        effective_role: null,
        can_access_all_roles: false,
      }))
      .mockResolvedValueOnce(localDevSession())
    const store = useSessionStore()

    await store.load()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/dev-token', expect.objectContaining({
      headers: { Accept: 'application/json' },
    }))
    expect(getAuthSession).toHaveBeenCalledTimes(2)
    expect(getAuthToken()).toBe('fresh-dev-token')
    expect(store.isLocalDevAllRoles).toBe(true)
  })

  it('does not replace an invalid release token with a local dev token', async () => {
    setAuthToken('stale-release-token')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    getAuthSession.mockResolvedValue(session({
      authenticated: false,
      username: null,
      role: null,
      effective_role: null,
    }))
    const store = useSessionStore()

    await store.load()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(getAuthToken()).toBe('stale-release-token')
    expect(store.hasInvalidToken).toBe(true)
  })

  it('stores a login token and refreshes the authoritative session', async () => {
    loginUser.mockResolvedValue({ token: 'runtime-token' })
    getAuthSession.mockResolvedValue(session({ username: 'admin', role: 'admin', effective_role: 'admin' }))
    const store = useSessionStore()

    await store.login('admin', 'pw')

    expect(loginUser).toHaveBeenCalledWith({ username: 'admin', password: 'pw' })
    expect(window.sessionStorage.getItem('auth_token')).toBe('runtime-token')
    expect(store.isAuthenticated).toBe(true)
    expect(store.effectiveRole).toBe('admin')
  })

  it('clears the local token on logout even when backend logout is already expired', async () => {
    window.sessionStorage.setItem('auth_token', 'expired-token')
    logoutUser.mockRejectedValue(new Error('expired'))
    getAuthSession.mockResolvedValue(session({
      authenticated: false,
      token_present: false,
      username: null,
      role: null,
      effective_role: null,
    }))
    const store = useSessionStore()

    await store.logout()

    expect(window.sessionStorage.getItem('auth_token')).toBeNull()
    expect(store.isAuthenticated).toBe(false)
  })
})
