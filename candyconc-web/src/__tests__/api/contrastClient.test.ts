import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createContrastJob } from '@/api/client'

interface Captured {
  url: string
  body: Record<string, unknown> | null
}

let captured: Captured[]

function installFetch(payload: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string, init?: RequestInit) => {
      if (input instanceof Request) {
        const text = await input.clone().text()
        captured.push({ url: input.url, body: text ? JSON.parse(text) : null })
      } else {
        captured.push({
          url: String(input),
          body: init?.body ? JSON.parse(String(init.body)) : null,
        })
      }
      return new Response(JSON.stringify(payload), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

describe('createContrastJob (free A-vs-B)', () => {
  beforeEach(() => {
    captured = []
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts docset-based sides to /analysis/contrast', async () => {
    installFetch({ job_id: 'job-1', status_url: '/x' })

    const result = await createContrastJob({
      term: 'Haus',
      targetDocsetId: 'ds-a',
      referenceDocsetId: 'ds-b',
      corpus: 'demo',
      limit: 50,
    })

    expect(captured[0].url).toContain('/api/v1/analysis/contrast')
    expect(captured[0].body).toMatchObject({
      term: 'Haus',
      target_docset_id: 'ds-a',
      reference_docset_id: 'ds-b',
      corpus: 'demo',
      limit: 50,
    })
    expect(result.job_id).toBe('job-1')
  })

  it('supports subcorpus-named sides', async () => {
    installFetch({ job_id: 'job-2' })

    await createContrastJob({
      term: 'Haus',
      targetSubcorpus: 'news',
      referenceSubcorpus: 'blog',
    })

    expect(captured[0].body).toMatchObject({
      term: 'Haus',
      target_subcorpus: 'news',
      reference_subcorpus: 'blog',
    })
  })

  it('rejects when a side is missing before hitting the network', async () => {
    installFetch({ job_id: 'x' })

    await expect(
      createContrastJob({ term: 'Haus', targetDocsetId: 'ds-a' })
    ).rejects.toThrow(/referenceDocsetId/)
    expect(captured).toHaveLength(0)
  })
})
