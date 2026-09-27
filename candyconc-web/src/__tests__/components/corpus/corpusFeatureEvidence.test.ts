import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import CorpusFeatureEvidence from '@/components/corpus/CorpusFeatureEvidence.vue'
import type { CorpusSummary } from '@/api/client'

function summary(): CorpusSummary {
  return {
    name: 'parallel-demo',
    path: '/tmp/parallel-demo',
    active: true,
    token_count: 1200,
    doc_count: 12,
    import_mode: 'prealigned_csv',
    paired: true,
    pair_axes: ['translation'],
    is_legacy: false,
    capabilities: { rel: true, custom_fast_index: true },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Wortform' },
        { id: 'rel', cql_attribute: 'rel', label: 'Relation' },
      ],
      frequency_groups: [
        { id: 'word', label: 'Wortform' },
        { id: 'lemma', label: 'Lemma' },
      ],
      semantic: { passage_search: true, word_similarity: false, sentence_alignment: true },
      alignment: {
        paired: true,
        pair_axes: ['translation'],
        pairing_schema: {
          schema_id: 'legacy_ref_doc_v1',
          group_key_field: 'ref_doc',
          anchor_role_field: 'text_type',
          default_anchor_role: 'human',
          variant_axis_fields: ['translation'],
          legacy_variant_filter_field: 'model',
          generic_axis_filters: false,
          legacy_response_fields: { reference_doc: 'ref_doc', variant_label: 'model' },
        },
        parallel_groups: true,
        parallel_kwic: true,
      },
    },
  }
}

describe('CorpusFeatureEvidence', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders corpus feature descriptors that explain product gates', () => {
    const wrapper = mount(CorpusFeatureEvidence, {
      props: { summary: summary() },
    })

    expect(wrapper.text()).toContain('corpus-features-v1')
    expect(wrapper.text()).toContain('Relation')
    expect(wrapper.text()).toContain('Lemma')
    expect(wrapper.text()).toContain('Passagen: ja')
    expect(wrapper.text()).toContain('Wortähnlichkeit: nein')
    expect(wrapper.text()).toContain('Parallel-KWIC: ja')
    expect(wrapper.text()).toContain('Achse: translation')
    expect(wrapper.text()).toContain('Pairing-Details')
    expect(wrapper.text()).toContain('legacy_ref_doc_v1')
    expect(wrapper.text()).toContain('Gruppenfeld')
    expect(wrapper.text()).toContain('ref_doc')
    expect(wrapper.text()).toContain('Default-Ankerrolle')
    expect(wrapper.text()).toContain('human')
    expect(wrapper.text()).toContain('Variantenfilter')
    expect(wrapper.text()).toContain('model')
    expect(wrapper.text()).toContain('Achsenfilter: legacy-begrenzt')
    expect(wrapper.text()).toContain('freie Achsenfilter sind in dieser Installation nicht allgemein ausführbar')
    expect(wrapper.text()).toContain('reference_doc → ref_doc')
    expect(wrapper.text()).toContain('custom_fast_index')
  })

  it('surfaces future generic axis filter support without legacy warnings', () => {
    const corpus = summary()
    corpus.features!.alignment = {
      paired: true,
      pair_axes: ['language'],
      pairing_schema: {
        schema_id: 'axis_pairing_v1',
        group_key_field: 'translation_unit',
        variant_axis_fields: ['language'],
        generic_axis_filters: true,
      },
      parallel_groups: true,
      parallel_kwic: true,
    }

    const wrapper = mount(CorpusFeatureEvidence, {
      props: { summary: corpus },
    })

    expect(wrapper.text()).toContain('axis_pairing_v1')
    expect(wrapper.text()).toContain('Achsenfilter: generisch ausführbar')
    expect(wrapper.text()).toContain('translation_unit')
    expect(wrapper.text()).not.toContain('freie Achsenfilter sind in dieser Installation nicht allgemein ausführbar')
  })

})
