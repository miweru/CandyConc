import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AlignmentComparison from '@/components/search/AlignmentComparison.vue'
import type { AlignmentRefDocResult } from '@/api/client'

const result: AlignmentRefDocResult = {
  ref_doc: 10,
  corpus: 'paired-fixture',
  focus_pos: 8,
  focus_doc_id: 10,
  alignment_scope: 'complete_document',
  confidence_threshold: 0.5,
  reference: {
    doc_id: 10,
    doc: 'Referenz',
    meta: {},
    sentence_count: 3,
    window_start: 0,
    window_end: 3,
    focus_sentence_index: 1,
    sentences: [
      { index: 0, start_pos: 0, end_pos: 2, text: 'Der Hase läuft.', token_count: 3 },
      { index: 1, start_pos: 3, end_pos: 5, text: 'Der Hase springt.', token_count: 3 },
      { index: 2, start_pos: 6, end_pos: 8, text: 'Der Hase ruht.', token_count: 3 },
    ],
  },
  variants: [{
    doc_id: 11,
    doc: 'Variante A',
    meta: { model: 'Modell A' },
    model: 'Modell A',
    label: 'Variante A',
    text_type: 'ai',
    sentence_count: 3,
    window_start: 0,
    window_end: 3,
    summary: { alignment_cost: 1, aligned_pairs: 3, avg_med: 0.3, avg_similarity: 0.9 },
    pairs: [
      { ref_index: 0, var_index: 0, ref_text: 'Der Hase läuft.', var_text: 'Der Hase läuft.', ref_start: 0, ref_end: 2, var_start: 0, var_end: 2, med: 0, similarity: 1, norm_med: 0 },
      { ref_index: 1, var_index: 1, ref_text: 'Der Hase springt.', var_text: 'Der Hase hoppelt.', ref_start: 3, ref_end: 5, var_start: 3, var_end: 5, med: 1, similarity: 0.67, norm_med: 0.33 },
      { ref_index: 2, var_index: 2, ref_text: 'Der Hase ruht.', var_text: 'Der Hase ruht.', ref_start: 6, ref_end: 8, var_start: 6, var_end: 8, med: 0, similarity: 1, norm_med: 0 },
    ],
  }],
  variant_count: 1,
}

describe('AlignmentComparison', () => {
  it('shows a focused side-by-side comparison and distinguishes display diffs from backend scores', () => {
    const wrapper = mount(AlignmentComparison, {
      props: { result, maxRows: 1 },
    })

    expect(wrapper.get('[data-testid="alignment-comparison"]').text()).toContain('Referenz')
    expect(wrapper.text()).toContain('Variante A')
    expect(wrapper.text()).toContain('Satz #1')
    expect(wrapper.text()).not.toContain('Satz #0')
    expect(wrapper.text()).not.toContain('Satz #2')
    expect(wrapper.get('.diff-token-replace').text()).toBe('hoppelt.')
    expect(wrapper.text()).toContain('Ähnlichkeit 67 %')
    expect(wrapper.text()).toContain('Alignment-Kennzahlen stammen vollständig aus dem Backend')
  })

  it('states clearly when the backend returned a reference without variants', () => {
    const wrapper = mount(AlignmentComparison, {
      props: { result: { ...result, variants: [], variant_count: 0 } },
    })

    expect(wrapper.text()).toContain('keine Varianten geliefert')
  })

  it('keeps variant-only and reference-only sentences visible instead of turning them into a token diff', () => {
    const comparisonWithGaps: AlignmentRefDocResult = {
      ...result,
      variants: [{
        ...result.variants[0]!,
        sentence_count: 4,
        pairs: [
          result.variants[0]!.pairs[0]!,
          {
            ref_index: null,
            var_index: 1,
            ref_text: '',
            var_text: 'Dieser Zusatzsatz existiert nur in Variante A.',
            ref_start: null,
            ref_end: null,
            var_start: 3,
            var_end: 9,
            med: null,
            similarity: null,
            norm_med: null,
          },
          {
            ref_index: 1,
            var_index: null,
            ref_text: 'Der Hase springt.',
            var_text: '',
            ref_start: 3,
            ref_end: 5,
            var_start: null,
            var_end: null,
            med: null,
            similarity: null,
            norm_med: null,
          },
          result.variants[0]!.pairs[2]!,
        ],
      }],
    }

    const wrapper = mount(AlignmentComparison, {
      props: { result: comparisonWithGaps },
    })

    expect(wrapper.text()).toContain('Dieser Zusatzsatz existiert nur in Variante A.')
    expect(wrapper.text()).toContain('Nur in Variante vorhanden')
    expect(wrapper.text()).toContain('Keine Entsprechung in Variante')
    expect(wrapper.text()).toContain('Referenzsatz ohne Variante')
    expect(wrapper.findAll('.diff-token-delete')).toHaveLength(0)
  })

  it('states when a variant KWIC anchor resolved the reference window', () => {
    const wrapper = mount(AlignmentComparison, {
      props: {
        result: { ...result, focus_resolution: 'variant_sentence_resolved' },
      },
    })

    expect(wrapper.text()).toContain('angeklickten Variantenstelle')
    expect(wrapper.text()).toContain('vollständige Dokument')
    expect(wrapper.text()).toContain('mindestens 50 % lexikalischer Token-Evidenz')
  })

  it('uses the profile name so same-model variants remain distinguishable', () => {
    const wrapper = mount(AlignmentComparison, {
      props: {
        result: {
          ...result,
          variants: [{
            ...result.variants[0]!,
            label: 'gpt-5.5',
            model: 'gpt-5.5',
            meta: { model: 'gpt-5.5', profile_name: 'Präzise Paraphrase' },
          }],
        },
      },
    })

    expect(wrapper.text()).toContain('Präzise Paraphrase')
  })

  it('keeps the reference beside one chosen variant instead of pushing it off-screen', async () => {
    const secondVariant = {
      ...result.variants[0]!,
      doc_id: 12,
      doc: 'Variante B',
      label: 'Variante B',
      meta: { model: 'Modell B' },
      model: 'Modell B',
      pairs: result.variants[0]!.pairs.map((pair) => ({
        ...pair,
        var_text: pair.var_text.replace('hoppelt', 'rennt'),
      })),
    }
    const wrapper = mount(AlignmentComparison, {
      props: { result: { ...result, variants: [result.variants[0]!, secondVariant], variant_count: 2 } },
    })

    expect(wrapper.get('[role="tabpanel"]').text()).toContain('Referenz')
    expect(wrapper.get('[role="tabpanel"]').text()).toContain('Variante A')
    expect(wrapper.text()).toContain('Variante 1 von 2')

    await wrapper.get('[role="tab"]:nth-child(2)').trigger('click')

    expect(wrapper.get('[role="tabpanel"]').text()).toContain('Referenz')
    expect(wrapper.get('[role="tabpanel"]').text()).toContain('Variante B')
    expect(wrapper.text()).toContain('Variante 2 von 2')
  })
})
