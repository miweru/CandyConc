import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAnalysisJobsStore } from '@/stores/analysisJobs'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useProductOperationRunsStore } from '@/stores/productOperationRuns'
import { useSessionStore } from '@/stores/session'

const apiMocks = vi.hoisted(() => ({
  cancelAnalysisJob: vi.fn(),
  getAnalysisJob: vi.fn(),
  getAnalysisJobRows: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  cancelAnalysisJob: (...args: unknown[]) => apiMocks.cancelAnalysisJob(...args),
  getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
  getAnalysisJobRows: (...args: unknown[]) => apiMocks.getAnalysisJobRows(...args),
}))

function route(path: string, method: string) {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(id: string, label: string, routeDescriptor: ReturnType<typeof route>) {
  return {
    id,
    capability_id: 'analysis.async_jobs',
    label,
    description: '',
    route: routeDescriptor,
    effects: routeDescriptor.methods[0] === 'GET' ? ['read'] : ['write'],
    handler_key: id.endsWith('.status')
      ? 'analysis_job_status'
      : id.endsWith('.cancel')
        ? 'analysis_job_cancel'
        : 'analysis_job_rows',
    surface_slot: id.endsWith('.status')
      ? 'analysis.jobs.status'
      : id.endsWith('.cancel')
        ? 'analysis.jobs.cancel'
        : 'analysis.jobs.rows',
    priority: id.endsWith('.status') ? 10 : id.endsWith('.cancel') ? 20 : 30,
  }
}

function seedAsyncJobsCapability() {
  const statusRoute = route('/api/v1/analysis/jobs/{job_id}', 'GET')
  const cancelRoute = route('/api/v1/analysis/jobs/{job_id}/cancel', 'POST')
  const rowsRoute = route('/api/v1/analysis/jobs/{job_id}/rows', 'GET')
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [{
      id: 'analysis.async_jobs',
      title: 'Analysis jobs',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [statusRoute.path, cancelRoute.path, rowsRoute.path],
      backend_route_descriptors: [statusRoute, cancelRoute, rowsRoute],
      operations: [
        operation('analysis.async_jobs.status', 'Analysejob-Status', statusRoute),
        operation('analysis.async_jobs.cancel', 'Analysejob abbrechen', cancelRoute),
        operation('analysis.async_jobs.rows', 'Analysejob-Zeilen', rowsRoute),
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
      notes: '',
    }],
  } as never

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
}

function installMemoryLocalStorage(): void {
  const storage = new Map<string, string>()
  vi.mocked(window.localStorage.getItem).mockImplementation((key: string) => storage.get(key) ?? null)
  vi.mocked(window.localStorage.setItem).mockImplementation((key: string, value: string) => {
    storage.set(key, String(value))
  })
  vi.mocked(window.localStorage.removeItem).mockImplementation((key: string) => {
    storage.delete(key)
  })
  vi.mocked(window.localStorage.clear).mockImplementation(() => {
    storage.clear()
  })
}

describe('analysisJobs store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    installMemoryLocalStorage()
    localStorage.clear()
    seedAsyncJobsCapability()
  })

  it('runs an analysis job through start, status and rows with one scope-owned lifecycle', async () => {
    apiMocks.getAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-frequency-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'done',
      progress: 100,
      message: 'Fertig',
      result_available: true,
      result_readiness: 'available',
      rows_state: 'available',
    })
    apiMocks.getAnalysisJobRows.mockResolvedValueOnce({
      job_id: 'job-frequency-1',
      status: 'done',
      rows: [{ word: 'Hase', f: 7 }],
    })
    const start = vi.fn(async () => ({ job_id: 'job-frequency-1' }))
    const onStarted = vi.fn()
    const onSnapshot = vi.fn()
    const store = useAnalysisJobsStore()

    const result = await store.runJobRows<{ word: string; f: number }>({
      scope: 'frequency',
      kind: 'frequency_list',
      corpus: 'demo',
      rowsLimit: 50,
      queuedMessage: 'Frequenzjob gestartet',
      productOperation: {
        operationId: 'analysis.frequency.job',
        surfaceId: 'analysis.frequency',
        label: 'Frequenzjob',
        detail: 'word',
      },
      start,
      onStarted,
      onSnapshot,
    })

    expect(start).toHaveBeenCalledOnce()
    expect(onStarted).toHaveBeenCalledWith({ job_id: 'job-frequency-1' })
    expect(onSnapshot).toHaveBeenCalledWith(expect.objectContaining({
      job_id: 'job-frequency-1',
      status: 'queued',
      message: 'Frequenzjob gestartet',
    }))
    expect(onSnapshot).toHaveBeenCalledWith(expect.objectContaining({
      job_id: 'job-frequency-1',
      status: 'done',
    }))
    expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-frequency-1')
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-frequency-1', 0, 50)
    expect(result.rows).toEqual([{ word: 'Hase', f: 7 }])
    expect(store.activeJobId('frequency')).toBeNull()
    expect(store.snapshotFor('job-frequency-1')).toMatchObject({
      status: 'done',
      progress: 100,
      message: 'Fertig',
    })
    expect(store.recentJobIds[0]).toBe('job-frequency-1')
    expect(store.monitorJobs[0]).toMatchObject({
      jobId: 'job-frequency-1',
      scope: 'frequency',
      active: false,
      snapshot: expect.objectContaining({ status: 'done' }),
    })
    expect(useProductOperationRunsStore().records[0]).toMatchObject({
      operationId: 'analysis.frequency.job',
      sourceId: 'job-frequency-1',
      kind: 'analysis',
      surfaceId: 'analysis.frequency',
      status: 'succeeded',
      progress: 100,
      message: 'Analyseergebnis geladen.',
    })
  })

  it('monitors analysis jobs over WebSocket before falling back to polling', async () => {
    const originalFetch = globalThis.fetch
    const originalWebSocket = globalThis.WebSocket
    const sockets: Array<{
      url: string
      onmessage: ((event: { data: string }) => void) | null
      onclose: (() => void) | null
      close: () => void
    }> = []
    const controller = new AbortController()
    class FakeWebSocket {
      url: string
      onmessage: ((event: { data: string }) => void) | null = null
      onclose: (() => void) | null = null

      constructor(url: string) {
        this.url = url
        sockets.push(this)
      }

      close() {
        this.onclose?.()
      }
    }
    let resultPromise: Promise<{ rows: Array<{ word: string; f: number }> }> | null = null
    try {
      vi.stubGlobal('fetch', vi.fn(async () => new Response(
        JSON.stringify({ ticket: 'ticket-ws-1', expires_in: 30 }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )))
      vi.stubGlobal('WebSocket', FakeWebSocket)
      apiMocks.getAnalysisJobRows.mockResolvedValueOnce({
        job_id: 'job-ws-1',
        status: 'done',
        rows: [{ word: 'Hase', f: 7 }],
      })
      const store = useAnalysisJobsStore()
      const onSnapshot = vi.fn()

      resultPromise = store.runJobRows<{ word: string; f: number }>({
        scope: 'frequency',
        kind: 'frequency_list',
        corpus: 'demo',
        rowsLimit: 20,
        signal: controller.signal,
        start: async () => ({ job_id: 'job-ws-1', ws_url: '/api/v1/ws/analysis/job-ws-1' }),
        onSnapshot,
      })
      for (let i = 0; i < 20 && sockets.length === 0; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 0))
      }
      if (sockets.length === 0) {
        controller.abort()
        await resultPromise.catch(() => undefined)
      }

      expect(sockets).toHaveLength(1)
      expect(sockets[0]!.url).toContain('/api/v1/ws/analysis/job-ws-1')
      expect(sockets[0]!.url).toContain('ticket=ticket-ws-1')
      // The interface language travels with the upgrade (Accept-Language of
      // a browser WebSocket is the browser's own).
      expect(sockets[0]!.url).toMatch(/[?&]lang=(de|en)(&|$)/)
      sockets[0]!.onmessage?.({
        data: JSON.stringify({
          job_id: 'job-ws-1',
          kind: 'frequency_list',
          corpus: 'demo',
          status: 'running',
          progress: 40,
          message: 'Zähle',
        }),
      })
      sockets[0]!.onmessage?.({
        data: JSON.stringify({
          job_id: 'job-ws-1',
          kind: 'frequency_list',
          corpus: 'demo',
          status: 'done',
          progress: 100,
          message: 'Fertig',
          result_available: true,
          result_readiness: 'available',
          rows_state: 'available',
        }),
      })

      const result = await resultPromise

      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/ws-ticket', expect.objectContaining({
        method: 'POST',
      }))
      expect(apiMocks.getAnalysisJob).not.toHaveBeenCalled()
      expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-ws-1', 0, 20)
      expect(onSnapshot).toHaveBeenCalledWith(expect.objectContaining({ status: 'running' }))
      expect(onSnapshot).toHaveBeenCalledWith(expect.objectContaining({ status: 'done' }))
      expect(result.rows).toEqual([{ word: 'Hase', f: 7 }])
    } finally {
      controller.abort()
      if (resultPromise) await resultPromise.catch(() => undefined)
      vi.stubGlobal('fetch', originalFetch)
      vi.stubGlobal('WebSocket', originalWebSocket)
    }
  })

  it('falls back to HTTP polling when a WebSocket never yields its first snapshot', async () => {
    const originalFetch = globalThis.fetch
    const originalWebSocket = globalThis.WebSocket
    const controller = new AbortController()
    const sockets: Array<{ close: () => void }> = []
    class StalledWebSocket {
      onopen: (() => void) | null = null
      onmessage: ((event: { data: string }) => void) | null = null
      onerror: (() => void) | null = null
      onclose: (() => void) | null = null

      constructor(_url: string) {
        sockets.push(this)
      }

      close() {
        this.onclose?.()
      }
    }

    let resultPromise: Promise<{ rows: Array<{ word: string; f: number }> }> | null = null
    try {
      vi.stubGlobal('fetch', vi.fn(async () => new Response(
        JSON.stringify({ ticket: 'ticket-stalled', expires_in: 30 }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )))
      vi.stubGlobal('WebSocket', StalledWebSocket)
      apiMocks.getAnalysisJob.mockResolvedValueOnce({
        job_id: 'job-stalled-ws',
        kind: 'frequency_list',
        corpus: 'demo',
        status: 'done',
        progress: 100,
        message: 'Fertig',
        result_available: true,
        result_readiness: 'available',
        rows_state: 'available',
      })
      apiMocks.getAnalysisJobRows.mockResolvedValueOnce({
        job_id: 'job-stalled-ws',
        status: 'done',
        rows: [{ word: 'Hase', f: 7 }],
      })

      resultPromise = useAnalysisJobsStore().runJobRows<{ word: string; f: number }>({
        scope: 'frequency',
        kind: 'frequency_list',
        corpus: 'demo',
        signal: controller.signal,
        start: async () => ({ job_id: 'job-stalled-ws', ws_url: '/api/v1/ws/analysis/job-stalled-ws' }),
      })
      for (let i = 0; i < 20 && sockets.length === 0; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 0))
      }

      expect(sockets).toHaveLength(1)
      await new Promise((resolve) => setTimeout(resolve, 2_050))

      await expect(resultPromise).resolves.toMatchObject({
        rows: [{ word: 'Hase', f: 7 }],
      })
      expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-stalled-ws')
    } finally {
      controller.abort()
      if (resultPromise) await resultPromise.catch(() => undefined)
      vi.stubGlobal('fetch', originalFetch)
      vi.stubGlobal('WebSocket', originalWebSocket)
    }
  })

  it('does not request rows when a completed job reports unavailable result storage', async () => {
    apiMocks.getAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-too-large',
      kind: 'ngrams',
      corpus: 'demo',
      status: 'done',
      progress: 100,
      total_rows: 1,
      result_available: false,
      result_discarded: true,
      result_discard_reason: 'result_size_exceeds_storage_cap',
      result_readiness: 'discarded',
      rows_state: 'discarded',
      result_warnings: ['Analyse abgeschlossen, aber das Ergebnis wurde wegen der Speichergrenze nicht im Job gespeichert.'],
    })
    const store = useAnalysisJobsStore()

    const result = await store.runJobRows({
      scope: 'ngrams',
      kind: 'ngrams',
      corpus: 'demo',
      start: async () => ({ job_id: 'job-too-large' }),
      productOperation: {
        operationId: 'analysis.ngrams.frequency_job',
        surfaceId: 'analysis.ngrams',
        label: 'N-Gramm-Job',
      },
    })

    expect(apiMocks.getAnalysisJobRows).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      job_id: 'job-too-large',
      status: 'done',
      rows: [],
      total_rows: 1,
      result_discarded: true,
      rows_state: 'discarded',
    })
    expect(useProductOperationRunsStore().records[0]).toMatchObject({
      status: 'succeeded',
      message: 'Analyse abgeschlossen. Ergebnis wurde wegen der Speichergrenze nicht geladen.',
    })
  })

  it('restores terminal job snapshots from the local recent-job monitor', async () => {
    apiMocks.getAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-manual-1',
      kind: 'keyness',
      corpus: 'demo',
      status: 'done',
      progress: 100,
      total_rows: 2,
    })
    const store = useAnalysisJobsStore()

    await store.refreshJob('job-manual-1')
    expect(store.monitorJobs.map((job) => job.jobId)).toContain('job-manual-1')
    expect(localStorage.getItem('candyconc.analysisJobs.recent.v1')).toContain('job-manual-1')

    setActivePinia(createPinia())
    seedAsyncJobsCapability()
    const restored = useAnalysisJobsStore()

    expect(restored.snapshotFor('job-manual-1')).toMatchObject({ status: 'done' })
    expect(restored.monitorJobs[0]).toMatchObject({
      jobId: 'job-manual-1',
      active: false,
      snapshot: expect.objectContaining({ total_rows: 2 }),
    })
  })

  it('updates the retained snapshot when rows are loaded for a completed job', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValueOnce({
      job_id: 'job-rows-1',
      status: 'done',
      progress: 100,
      total_rows: 1,
      rows: [{ word: 'Hase', f: 7 }],
    })
    const store = useAnalysisJobsStore()
    store.setSnapshot({
      job_id: 'job-rows-1',
      kind: 'frequency_list',
      status: 'done',
      progress: 50,
    }, 'frequency')

    const response = await store.rows<{ word: string; f: number }>('job-rows-1', 0, 5)

    expect(response.rows).toEqual([{ word: 'Hase', f: 7 }])
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-rows-1', 0, 5)
    expect(store.snapshotFor('job-rows-1')).toMatchObject({
      status: 'done',
      progress: 100,
      total_rows: 1,
    })
  })

  it('does not start a backend job when job row loading is not offered', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    const capability = productCapabilities.contract!.capabilities[0]!
    capability.operations = capability.operations.filter(
      (item) => item.id !== 'analysis.async_jobs.rows',
    )
    const start = vi.fn(async () => ({ job_id: 'job-should-not-start' }))
    const store = useAnalysisJobsStore()

    await expect(store.runJobRows({
      scope: 'frequency',
      kind: 'frequency_list',
      start,
    })).rejects.toThrow('Serverfunktion')
    expect(start).not.toHaveBeenCalled()
    expect(apiMocks.getAnalysisJob).not.toHaveBeenCalled()
    expect(apiMocks.getAnalysisJobRows).not.toHaveBeenCalled()
  })

  it('cancels the active job for a scope and clears that scope', async () => {
    apiMocks.cancelAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-ngram-1',
      kind: 'ngrams',
      status: 'cancelled',
      progress: 20,
      message: 'Abgebrochen',
    })
    const store = useAnalysisJobsStore()
    store.setSnapshot({
      job_id: 'job-ngram-1',
      kind: 'ngrams',
      status: 'running',
      progress: 20,
    })
    store.activeJobIdsByScope = { ngrams: 'job-ngram-1' }

    const result = await store.cancelScope('ngrams')

    expect(apiMocks.cancelAnalysisJob).toHaveBeenCalledWith('job-ngram-1')
    expect(result).toMatchObject({ status: 'cancelled' })
    expect(store.activeJobId('ngrams')).toBeNull()
    expect(store.snapshotFor('job-ngram-1')).toMatchObject({ status: 'cancelled' })
  })

  it('resumes an existing job id without starting a duplicate backend job', async () => {
    apiMocks.getAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-ngram-2',
      kind: 'ngrams',
      status: 'done',
      progress: 100,
      result_available: true,
      result_readiness: 'available',
      rows_state: 'available',
    })
    apiMocks.getAnalysisJobRows.mockResolvedValueOnce({
      job_id: 'job-ngram-2',
      status: 'done',
      rows: [{ ngram: 'in der', f: 12 }],
    })
    const onSnapshot = vi.fn()
    const store = useAnalysisJobsStore()

    const result = await store.resumeJobRows<{ ngram: string; f: number }>({
      scope: 'ngrams',
      jobId: 'job-ngram-2',
      rowsLimit: 500,
      productOperation: {
        operationId: 'analysis.ngrams.frequency_job',
        surfaceId: 'analysis.ngrams',
        label: 'N-Gramm-Frequenzjob',
        detail: '2-Gramme',
      },
      onSnapshot,
    })

    expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-ngram-2')
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-ngram-2', 0, 500)
    expect(onSnapshot).toHaveBeenCalledWith(expect.objectContaining({ status: 'done' }))
    expect(result.rows).toEqual([{ ngram: 'in der', f: 12 }])
    expect(store.activeJobId('ngrams')).toBeNull()
    expect(useProductOperationRunsStore().records[0]).toMatchObject({
      operationId: 'analysis.ngrams.frequency_job',
      sourceId: 'job-ngram-2',
      kind: 'analysis',
      surfaceId: 'analysis.ngrams',
      status: 'succeeded',
    })
  })

  it('clears the active scope when a signal aborts immediately after job start', async () => {
    apiMocks.cancelAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-aborted-1',
      kind: 'frequency_list',
      status: 'cancelled',
      progress: 0,
    })
    const controller = new AbortController()
    const start = vi.fn(async () => {
      controller.abort()
      return { job_id: 'job-aborted-1' }
    })
    const store = useAnalysisJobsStore()

    await expect(store.runJobRows({
      scope: 'frequency',
      kind: 'frequency_list',
      signal: controller.signal,
      start,
    })).rejects.toThrow('Aborted')

    expect(start).toHaveBeenCalledOnce()
    expect(store.activeJobId('frequency')).toBeNull()
    expect(store.snapshotFor('job-aborted-1')).toMatchObject({ status: 'cancelled' })
  })

})
