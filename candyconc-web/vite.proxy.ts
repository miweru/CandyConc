// Single source of truth for the dev-server proxy table.
//
// Kept in its own pure module (no Vite/plugin/esbuild imports) so both
// vite.config.ts and unit tests can read the exact same table directly,
// in-process and deterministically — without spawning a Vite-resolve
// subprocess. `/api` and `/mcp` must share the same backend target so the
// copilot's MCP tool-registry calls reach the same server as the REST API.
export interface DevProxyEntry {
  target: string
  changeOrigin?: boolean
  ws?: boolean
}

export function createDevProxy(
  backendPort: string = process.env.CANDYCONC_BACKEND_PORT ?? '8010'
): Record<string, DevProxyEntry> {
  const http = `http://localhost:${backendPort}`
  return {
    // Alle realen WebSocket-Pfade liegen unter /api/v1/ws/*; ohne ws:true
    // nimmt Vite den Browser-Socket an, leitet ihn aber nie an FastAPI weiter.
    '/api': { target: http, changeOrigin: true, ws: true },
    '/mcp': { target: http, changeOrigin: true },
    // Bundled user documentation (help menu). Only paths below /docs/, the
    // API page /docs of FastAPI stays out of the dev server.
    '/docs/': { target: http, changeOrigin: true }
  }
}
