import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import {
  toolRenderers,
  FrequencyRenderer,
  KeynessRenderer,
} from '@/components/copilot/tools'

/**
 * Fixture: the tool names actually registered in the backend registry
 * (candyconc.tooling.registry.REGISTRY via @llm_tool in
 * app/src/candyconc/candyconc_copilot/tool_wrappers.py).
 * Extracted from the tool specs' function.name fields. If a backend tool is
 * added or renamed, update this list from the registry — never invent keys.
 */
const REGISTERED_BACKEND_TOOLS = [
  'cluster_export_md',
  'cluster_save',
  'collocate_stats',
  'collocation_network',
  'compare_collocates',
  'contrast_collocates',
  'create_docset',
  'dispersion_offsets',
  'document_search',
  'document_text',
  'documentation_search',
  'frequency_list',
  'keyness',
  'kwic_context',
  'lexical_diversity',
  'list_docsets',
  'metadata_values',
  'ngram_contrast',
  'ngram_frequency',
  'parallel_groups',
  'parallel_kwic',
  'query_count',
  'refine_cluster_label',
  'resolve_subcorpus',
  'run_cqlf_query',
  'semantic_cluster',
  'semantic_cluster_words',
  'semantic_recluster',
  'semantic_search',
  'similar_words',
  'word_sketch',
] as const

describe('toolRenderers registry truth', () => {
  it('maps only real registered backend tools (no phantom keys)', () => {
    const phantoms = Object.keys(toolRenderers).filter(
      (name) => !REGISTERED_BACKEND_TOOLS.includes(name as (typeof REGISTERED_BACKEND_TOOLS)[number])
    )
    expect(phantoms).toEqual([])
  })

  it('routes frequency_list and keyness to their bespoke renderers', () => {
    expect(toolRenderers['frequency_list']).toBe(FrequencyRenderer)
    expect(toolRenderers['keyness']).toBe(KeynessRenderer)
  })

  it('FrequencyRenderer renders the real frequency_list response schema', () => {
    // Shape per tool_wrappers.FREQUENCY_RESPONSE: rows of {word, f, per_million}
    // plus {total, truncated, corpus_tokens}.
    const wrapper = mount(FrequencyRenderer, {
      props: {
        data: {
          status: 'success',
          rows: [
            { word: 'und', f: 797, per_million: 14346.1 },
            { word: 'die', f: 640, per_million: 11520.0 },
          ],
          total: 9740,
          truncated: true,
          corpus_tokens: 55550,
        },
      },
    })
    expect(wrapper.text()).toContain('und')
    expect(wrapper.text()).toContain('797')
    expect(wrapper.text()).toContain('2 von 9.740 Typen')
    expect(wrapper.text()).toContain('Serverseitig gekürzte Liste')
  })

  it('KeynessRenderer renders the real keyness response schema', () => {
    // Shape per tool_wrappers.KEYNESS_RESPONSE: {status, rows:[{word, ll_signed, ...}]}
    const wrapper = mount(KeynessRenderer, {
      props: {
        data: {
          status: 'success',
          rows: [
            {
              word: 'Kinder',
              ll: 12.4,
              ll_signed: 12.4,
              chi2_cell: 8.1,
              log_ratio: 1.62,
              log_ratio_ci_low: 0.9,
              log_ratio_ci_high: 2.3,
              q_value: 0.003,
              direction: 'target',
            },
          ],
        },
      },
    })
    expect(wrapper.text()).toContain('Kinder')
    // German interface: decimal commas (copilotRendererNumbers.test.ts).
    expect(wrapper.text()).toContain('1,62 (0,9 bis 2,3)')
    expect(wrapper.text()).toContain('0,003')
  })
})
