import { describe, expect, it } from 'vitest'

import {
  alignmentExecutionContractLabel,
  alignmentGenericAxisFiltersSupported,
  alignmentPairAxesLabel,
  alignmentVariantControlLabel,
  frequencyGroupOptions,
  hasParallelGroups,
  hasParallelKwic,
  hasPassageSearch,
  hasSemanticSearch,
  isCqlSuggestionSupported,
  isCorpusPaired,
  queryAttributeOptions,
  simpleIntentOptions,
  supportsFrequencyGroup,
  supportsTokenAttribute,
  unsupportedCqlAttributes,
} from '@/lib/corpusFeatureOptions'
import type { CorpusSummary, SuggestionItem } from '@/api/client'

function summary(capabilities: Record<string, boolean>): CorpusSummary {
  return {
    name: 'demo',
    path: '/corpora/demo',
    token_count: 100,
    doc_count: 2,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities,
  }
}

function summaryWithFeatures(capabilities: Record<string, boolean>, features: CorpusSummary['features']): CorpusSummary {
  return {
    ...summary(capabilities),
    features,
  }
}

function suggestion(text: string, hint: string): SuggestionItem {
  return { text, hint, kind: 'complete' }
}

describe('corpus feature options', () => {
  it('fails closed to word-only UI options when optional artifacts are absent', () => {
    const corpus = summary({})

    expect(queryAttributeOptions(corpus).map((option) => option.attr)).toEqual(['word'])
    expect(frequencyGroupOptions(corpus).map((option) => option.value)).toEqual(['word'])
    expect(simpleIntentOptions(corpus).map((option) => option.intent)).toEqual(['exact'])
    expect(supportsTokenAttribute(corpus, 'lemma')).toBe(false)
    expect(supportsFrequencyGroup(corpus, 'pos')).toBe(false)
    expect(hasPassageSearch(summary({ embeddings: true, word_faiss: true }))).toBe(false)
    expect(hasSemanticSearch(corpus)).toBe(false)
  })

  it('exposes only the corpus-backed query, frequency and semantic surfaces', () => {
    const corpus = summaryWithFeatures(
      { lemma_lex: true, pos_lex: true, ent_lex: true },
      {
        schema_version: 'corpus-features-v1',
        token_attributes: [
          { id: 'word', cql_attribute: 'word', label: 'Wortform' },
          { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma' },
          { id: 'pos', cql_attribute: 'pos', label: 'POS' },
          { id: 'ner', cql_attribute: 'ner', label: 'NER' },
          { id: 'sim', cql_attribute: 'sim', label: 'Semantik' },
        ],
        frequency_groups: [
          { id: 'word', label: 'Wortform' },
          { id: 'lemma', label: 'Lemma' },
          { id: 'pos', label: 'POS-Tag' },
        ],
        semantic: { passage_search: true, word_similarity: true, sentence_alignment: false },
      }
    )

    expect(queryAttributeOptions(corpus).map((option) => option.attr)).toEqual(['word', 'lemma', 'pos', 'ner', 'sim'])
    expect(frequencyGroupOptions(corpus).map((option) => option.value)).toEqual(['word', 'lemma', 'pos'])
    expect(simpleIntentOptions(corpus).map((option) => option.intent)).toEqual(['exact', 'lemma', 'similar'])
    expect(hasPassageSearch(corpus)).toBe(true)
    expect(hasSemanticSearch(corpus)).toBe(true)
  })

  it('supports descriptor-backed generic token attributes beyond lemma/POS/NER', () => {
    const corpus = summaryWithFeatures(
      {},
      {
        schema_version: 'corpus-features-v1',
        token_attributes: [
          { id: 'word', cql_attribute: 'word', label: 'Wortform' },
          { id: 'morph', cql_attribute: 'morph', label: 'Morphologie' },
          { id: 'rel', cql_attribute: 'rel', label: 'Relation' },
        ],
        frequency_groups: [{ id: 'word', label: 'Wortform' }],
      }
    )

    expect(queryAttributeOptions(corpus).map((option) => option.attr)).toEqual(['word', 'morph', 'rel'])
    expect(supportsTokenAttribute(corpus, 'morph')).toBe(true)
    expect(supportsTokenAttribute(corpus, 'rel')).toBe(true)
    expect(unsupportedCqlAttributes(corpus, 'cql:[morph="Case=Nom"] [lemma="gehen"]')).toEqual(['lemma'])
  })

  it('uses explicit alignment feature flags instead of broad legacy pairing', () => {
    const corpus = summaryWithFeatures(
      { parallel: true },
      {
        schema_version: 'corpus-features-v1',
        token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
        frequency_groups: [{ id: 'word', label: 'Wortform' }],
        alignment: {
          paired: true,
          pair_axes: ['model'],
          parallel_groups: true,
          parallel_kwic: false,
        },
      }
    )

    expect(isCorpusPaired(corpus)).toBe(true)
    expect(hasParallelGroups(corpus)).toBe(true)
    expect(hasParallelKwic(corpus)).toBe(false)
  })

  it('labels alignment axes generically instead of assuming model variants', () => {
    const corpus = summaryWithFeatures(
      {},
      {
        schema_version: 'corpus-features-v1',
        token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
        frequency_groups: [{ id: 'word', label: 'Wortform' }],
        alignment: {
          paired: true,
          pair_axes: ['language', 'edition_type'],
          pairing_schema: {
            schema_id: 'legacy_ref_doc_v1',
            group_key_field: 'ref_doc',
            anchor_role_field: 'text_type',
            default_anchor_role: 'human',
            variant_axis_fields: ['language', 'edition_type'],
            legacy_variant_filter_field: 'model',
            generic_axis_filters: false,
          },
          parallel_groups: true,
          parallel_kwic: true,
        },
      }
    )

    expect(alignmentPairAxesLabel(corpus)).toBe('language, edition type')
    expect(alignmentVariantControlLabel(corpus)).toBe('Varianten (language, edition type)')
    expect(alignmentGenericAxisFiltersSupported(corpus)).toBe(false)
    expect(alignmentExecutionContractLabel(corpus)).toContain('legacy_ref_doc_v1')
    expect(alignmentExecutionContractLabel(corpus)).toContain('Legacy-Feld model')
    expect(alignmentVariantControlLabel(summary({}))).toBe('Varianten')
  })

  it('surfaces when a future pairing schema really supports generic axis filters', () => {
    const corpus = summaryWithFeatures(
      {},
      {
        schema_version: 'corpus-features-v1',
        alignment: {
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
        },
      }
    )

    expect(alignmentGenericAxisFiltersSupported(corpus)).toBe(true)
    expect(alignmentExecutionContractLabel(corpus)).toContain('Generische Achsenfilter sind ausführbar')
  })

  it('filters CQL suggestions that require unavailable corpus artifacts', () => {
    const corpus = summary({ pos_lex: true })

    expect(isCqlSuggestionSupported(corpus, suggestion('cql:[pos="NN"]', 'POS: NN'))).toBe(true)
    expect(isCqlSuggestionSupported(corpus, suggestion('cql:[lemma="gehen"]', 'Lemma: gehen'))).toBe(false)
    expect(isCqlSuggestionSupported(corpus, suggestion('cql:[sim="Krise"]', 'Semantik-Makro'))).toBe(false)
    expect(isCqlSuggestionSupported(corpus, suggestion('cql:[morph="Case=Nom"]', 'Morphologie'))).toBe(false)
  })
})
