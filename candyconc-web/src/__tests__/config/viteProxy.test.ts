import { describe, expect, it } from 'vitest'
import { createDevProxy } from '../../../vite.proxy'

// Read the dev proxy table from its shared pure module — no Vite/esbuild import
// and no `vite.resolveConfig` subprocess. (The previous version spawned a Node
// subprocess via execFileSync, which is CPU-bound and flaked under full-suite
// parallelism by exceeding the default 5s test timeout; in isolation it passed
// in ~1.2s.) vite.config.ts builds its `server.proxy` from this same function,
// so this is the single source of truth and tests the identical invariant.
describe('Vite development proxy', () => {
  it('routes MCP tool registry requests through the same backend proxy as the API', () => {
    const proxy = createDevProxy()

    expect(proxy['/mcp']).toMatchObject({
      target: proxy['/api'].target,
      changeOrigin: true
    })
  })

  it('forwards analysis-job WebSocket upgrades on the API path', () => {
    const proxy = createDevProxy()

    expect(proxy['/api']).toMatchObject({
      target: 'http://localhost:8010',
      changeOrigin: true,
      ws: true,
    })
  })

  it('honours CANDYCONC_BACKEND_PORT for all proxied routes', () => {
    const proxy = createDevProxy('9123')

    expect(proxy['/api'].target).toBe('http://localhost:9123')
    expect(proxy['/mcp'].target).toBe('http://localhost:9123')
  })

  it('has no dead top-level /ws entry (all WS paths live under /api/v1/ws/*)', () => {
    const proxy = createDevProxy()

    // /docs/ serves the bundled user documentation (help menu).
    expect(Object.keys(proxy).sort()).toEqual(['/api', '/docs/', '/mcp'])
  })
})
