import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { downloadEmbeddingModel, getOperationRun } from '@/api/client'

let captured: Array<{ method: string; url: string; body: unknown }> = []

function stubFetch(payload: unknown, status = 200) {
  captured = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      let method = init?.method ?? 'GET'
      let url = String(input)
      let body: unknown = null

      if (input instanceof Request) {
        method = input.method
        url = input.url
        const text = await input.clone().text()
        body = text ? JSON.parse(text) : null
      } else if (init?.body) {
        body = JSON.parse(String(init.body))
      }

      captured.push({ method, url, body })
      return new Response(JSON.stringify(payload), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

const operationRunSnapshot = {
  run_id: 'embedding-run-1',
  job_id: 'embedding-run-1',
  operation_id: 'settings.embedding_management.download',
  source_id: 'fasttext-de',
  kind: 'operation',
  label: 'Embedding-Download: fasttext-de',
  status: 'running',
  phase: 'download',
  progress: 40,
  message: 'Embedding-Paket wird heruntergeladen.',
  error: null,
  result_ref: null,
  readiness: 'pending',
  warnings: [],
  evidence: {},
  created_at: '2026-06-20T10:00:00.000Z',
  updated_at: '2026-06-20T10:01:00.000Z',
  finished_at: null,
}

const launchResponse = {
  status: 'queued',
  run_id: 'embedding-run-1',
  job_id: 'embedding-run-1',
  status_url: '/api/v1/operation-runs/embedding-run-1',
  operation_id: 'settings.embedding_management.download',
}

describe('operation run API client', () => {
  beforeEach(() => {
    stubFetch(operationRunSnapshot)
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('validates backend-owned OperationRun snapshots at the API boundary', async () => {
    const result = await getOperationRun('embedding-run-1')

    expect(result).toEqual(operationRunSnapshot)
    expect(captured).toHaveLength(1)
    expect(captured[0]).toMatchObject({
      method: 'GET',
      url: expect.stringContaining('/api/v1/operation-runs/embedding-run-1'),
    })
  })

  it('rejects malformed OperationRun snapshots before stores can treat them as provenance', async () => {
    stubFetch({
      status: 'running',
      operation_id: 'settings.embedding_management.download',
    })

    await expect(getOperationRun('embedding-run-1')).rejects.toThrow()
  })

  it('validates OperationRun launch responses for embedding downloads', async () => {
    stubFetch(launchResponse)

    const result = await downloadEmbeddingModel(
      'fasttext-de',
      'https://example.invalid/fasttext-de.bin',
      'sha256:abc',
    )

    expect(result).toEqual(launchResponse)
    expect(captured[0]).toMatchObject({
      method: 'POST',
      url: expect.stringContaining('/api/v1/embeddings/download'),
      body: {
        name: 'fasttext-de',
        url: 'https://example.invalid/fasttext-de.bin',
        sha256: 'sha256:abc',
      },
    })
  })

  it('rejects launch acknowledgements without operation id and status url', async () => {
    stubFetch({
      status: 'queued',
      run_id: 'embedding-run-1',
      job_id: 'embedding-run-1',
    })

    await expect(
      downloadEmbeddingModel('fasttext-de', 'https://example.invalid/fasttext-de.bin'),
    ).rejects.toThrow()
  })
})
