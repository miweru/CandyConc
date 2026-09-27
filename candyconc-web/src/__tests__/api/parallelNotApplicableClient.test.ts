import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { getParallelGroups, getParallelKwic, NotApplicableError } from '@/api/client'

function stubFetch(payload: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
  )
}

describe('parallel client not_applicable envelopes', () => {
  beforeEach(() => {
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('throws a typed non-success instead of turning corpus_not_paired into empty data', async () => {
    stubFetch({
      status: 'not_applicable',
      reason: 'corpus_not_paired',
      feature: 'parallel_groups',
      detail: 'Dieses Korpus ist nicht gepaart.',
    })

    await expect(getParallelGroups({ corpus: 'flat-corpus' })).rejects.toMatchObject({
      name: 'NotApplicableError',
      envelope: expect.objectContaining({ reason: 'corpus_not_paired' }),
    })
    await expect(getParallelGroups({ corpus: 'flat-corpus' })).rejects.toBeInstanceOf(NotApplicableError)
  })

  it('accepts generic pair-axis labels while keeping legacy model responses compatible', async () => {
    stubFetch({
      total: 1,
      groups: [{
        ref_doc: 7,
        doc_count: 2,
        doc_ids: [7, 8],
        human_doc_id: 7,
        variant_doc_ids: [8],
        models: [{ model: 'en', axis: 'language', axis_value: 'English', label: 'English', count: 1 }],
        text_types: { reference: 1, variant: 1 },
        sources: ['fixture'],
        label: 'language: English',
      }],
    })

    await expect(getParallelGroups({ corpus: 'parallel-demo' })).resolves.toMatchObject({
      groups: [{
        models: [{ model: 'en', axis: 'language', axis_value: 'English', label: 'English', count: 1 }],
      }],
    })

    stubFetch({
      ref_doc: 7,
      base_doc_id: 7,
      variants: [{
        doc_id: 8,
        axis: 'language',
        axis_value: 'English',
        label: 'English',
        text_type: 'variant',
        left: 'links',
        kw: 'Hase',
        right: 'rechts',
        matched: true,
        med: null,
        norm_med: null,
        similarity: null,
      }],
    })

    await expect(getParallelKwic({ corpus: 'parallel-demo', pos: 42 })).resolves.toMatchObject({
      variants: [{ model: '', axis: 'language', axis_value: 'English', label: 'English' }],
    })
  })
})
