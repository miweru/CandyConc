import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { getCorpora } from '@/api/client'

function stubFetch(payload: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
  )
}

describe('corpora API client', () => {
  beforeEach(() => {
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('preserves the versioned alignment pairing schema from the catalogue', async () => {
    stubFetch({
      corpora: [{
        name: 'parallel-demo',
        path: '/corpora/parallel-demo',
        token_count: 100,
        doc_count: 10,
        import_mode: 'prealigned',
        paired: true,
        pair_axes: ['language'],
        is_legacy: false,
        capabilities: { parallel: true },
        features: {
          schema_version: 'corpus-features-v1',
          alignment: {
            paired: true,
            pair_axes: ['language'],
            pairing_schema: {
              schema_id: 'legacy_ref_doc_v1',
              group_key_field: 'ref_doc',
              anchor_role_field: 'text_type',
              default_anchor_role: 'human',
              variant_axis_fields: ['language'],
              legacy_variant_filter_field: 'model',
              generic_axis_filters: false,
              legacy_response_fields: {
                anchor_doc_id: 'human_doc_id',
              },
            },
            parallel_groups: true,
            parallel_kwic: true,
          },
        },
      }],
      count: 1,
    })

    await expect(getCorpora()).resolves.toMatchObject({
      corpora: [{
        features: {
          alignment: {
            pairing_schema: {
              schema_id: 'legacy_ref_doc_v1',
              variant_axis_fields: ['language'],
              generic_axis_filters: false,
              legacy_response_fields: { anchor_doc_id: 'human_doc_id' },
            },
          },
        },
      }],
    })
  })
})
