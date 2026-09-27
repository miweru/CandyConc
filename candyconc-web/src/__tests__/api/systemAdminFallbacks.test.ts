import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { clearCache, getSystemInfo, rebuildIndex } from '@/api/client'

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

describe('system/admin API fallbacks', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not mask system-info authorization failures with health fallback', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(403, { detail: 'forbidden' }))

    await expect(getSystemInfo()).rejects.toThrow()

    expect(pathsHit()).toEqual(['/api/v1/system/info'])
  })

  it('uses health fallback only when the system-info endpoint is absent', async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(404, { detail: 'missing' }))
      .mockResolvedValueOnce(jsonResponse(200, { status: 'ok' }))

    const info = await getSystemInfo()

    expect(pathsHit()).toEqual(['/api/v1/system/info', '/api/v1/health'])
    expect(info.indexStatus).toBe('ready')
    expect(info.faissStatus).toBe('unavailable')
    expect(info.source).toBe('legacy_health_fallback')
  })

  it('does not fallback from rebuild-index authorization failures to admin/faiss/build', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(403, { detail: 'forbidden' }))

    await expect(rebuildIndex()).rejects.toThrow()

    expect(pathsHit()).toEqual(['/api/v1/system/rebuild-index'])
  })

  it('does not hide an absent first-class rebuild endpoint behind the expert FAISS API', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(404, { detail: 'missing' }))

    await expect(rebuildIndex()).rejects.toThrow()

    expect(pathsHit()).toEqual(['/api/v1/system/rebuild-index'])
  })

  it('keeps the first-class rebuild job websocket URL as lifecycle evidence', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(200, {
      jobId: 'system-job-1',
      wsUrl: '/api/v1/ws/faiss/system-job-1',
    }))

    await expect(rebuildIndex()).resolves.toEqual({
      jobId: 'system-job-1',
      wsUrl: '/api/v1/ws/faiss/system-job-1',
    })

    expect(pathsHit()).toEqual(['/api/v1/system/rebuild-index'])
  })

  it('propagates clear-cache failures instead of treating them as no-op success', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(500, { detail: 'boom' }))

    await expect(clearCache()).rejects.toThrow()

    expect(pathsHit()).toEqual(['/api/v1/system/clear-cache'])
  })
})
