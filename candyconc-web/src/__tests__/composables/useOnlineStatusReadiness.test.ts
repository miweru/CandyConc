import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { clearAuthToken, setAuthToken } from '@/api/auth'
import { probeBackendReadiness } from '@/composables/useOnlineStatus'

function jsonResponse(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function fetchMock() {
  return globalThis.fetch as Mock
}

function pathsHit(): string[] {
  return fetchMock().mock.calls.map((call) => {
    const input = call[0]
    const url = input instanceof Request ? input.url : String(input)
    return new URL(url, 'http://localhost').pathname
  })
}

describe('backend readiness probe', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
    clearAuthToken()
    setAuthToken('test-token')
  })

  afterEach(() => {
    clearAuthToken()
    vi.unstubAllGlobals()
  })

  it('requires health, session and capabilities before reporting the backend ready', async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(200, { status: 'ok' }))
      .mockResolvedValueOnce(jsonResponse(200, { schema_version: 'auth-session-v1' }))
      .mockResolvedValueOnce(jsonResponse(200, {
        version: 'product-capabilities-v1',
        fingerprint_sha256: 'a'.repeat(64),
        scope: 'candyconc',
        cqlf_capability_contract: {
          version: 'cqlf-capabilities-v1',
          current_level: '2-',
          fingerprint_sha256: 'b'.repeat(64),
        },
        capabilities: [],
      }))

    await expect(probeBackendReadiness()).resolves.toEqual({
      readiness: 'ready',
      reachable: true,
      ready: true,
    })
    expect(pathsHit()).toEqual([
      '/api/v1/health',
      '/api/v1/auth/session',
      '/api/v1/capabilities',
    ])
  })

  it('does not treat health-only liveness as product readiness', async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(200, { status: 'ok' }))
      .mockResolvedValueOnce(jsonResponse(404, { detail: 'session route missing' }))

    await expect(probeBackendReadiness()).resolves.toEqual({
      readiness: 'contract_unavailable',
      reachable: true,
      ready: false,
    })
    expect(pathsHit()).toEqual([
      '/api/v1/health',
      '/api/v1/auth/session',
    ])
  })

  it('distinguishes missing auth from a missing capability contract', async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(200, { status: 'ok' }))
      .mockResolvedValueOnce(jsonResponse(200, { schema_version: 'auth-session-v1' }))
      .mockResolvedValueOnce(jsonResponse(403, { detail: 'forbidden' }))

    await expect(probeBackendReadiness()).resolves.toEqual({
      readiness: 'auth_required',
      reachable: true,
      ready: false,
    })
  })
})
