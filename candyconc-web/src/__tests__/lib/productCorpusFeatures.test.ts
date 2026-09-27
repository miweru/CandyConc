import { describe, expect, it } from 'vitest'

import {
  corpusFeatureDecisionPartialReason,
  corpusFeatureDecisionReason,
  evaluateCapabilityCorpusFeatures,
} from '@/lib/productCorpusFeatures'
import type { CorpusSummary, ProductCapability } from '@/api/client'

function capability(id: string): ProductCapability {
  if (id === 'analysis.wordsketch') {
    return {
      id,
      title: 'Word Sketch',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: ['/api/v1/analysis/wordsketch'],
      backend_route_descriptors: [{
        path: '/api/v1/analysis/wordsketch',
        methods: ['POST'],
        mutates: false,
        requires_corpus_features: ['token_attributes.rel'],
      }],
      operations: [],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      limits: [],
    } as ProductCapability
  }
  if (id === 'analysis.semantic_similarity') {
    return {
      id,
      title: 'Semantik',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: ['/api/v1/semantic/similar_words', '/api/v1/analysis/embedding_search'],
      backend_route_descriptors: [
        {
          path: '/api/v1/semantic/similar_words',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: ['semantic.word_similarity'],
        },
        {
          path: '/api/v1/analysis/embedding_search',
          methods: ['POST'],
          mutates: false,
          requires_corpus_features: ['semantic.passage_search'],
        },
      ],
      operations: [],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      limits: [],
    } as ProductCapability
  }
  throw new Error(`Missing test capability: ${id}`)
}

function corpus(features: Partial<NonNullable<CorpusSummary['features']>>): CorpusSummary {
  return {
    name: 'demo',
    path: '/corpora/demo',
    token_count: 100,
    doc_count: 2,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
      ...features,
    },
  }
}

describe('product corpus feature requirements', () => {
  it('blocks Word Sketch without relation token attributes', () => {
    const decision = evaluateCapabilityCorpusFeatures(capability('analysis.wordsketch'), corpus({}))

    expect(decision.status).toBe('blocked')
    expect(decision.missing).toEqual(['token_attributes.rel'])
    expect(corpusFeatureDecisionReason('Word Sketch', decision)).toContain('Tokenattribut rel')
  })

  it('allows Word Sketch when the corpus exposes rel token attributes', () => {
    const decision = evaluateCapabilityCorpusFeatures(
      capability('analysis.wordsketch'),
      corpus({
        token_attributes: [
          { id: 'word', cql_attribute: 'word', label: 'Wortform' },
          { id: 'rel', cql_attribute: 'rel', label: 'Relation' },
        ],
      }),
    )

    expect(decision.status).toBe('pass')
    expect(decision.missing).toEqual([])
  })

  it('treats semantic passage search and word similarity as route-level alternatives', () => {
    const semantic = capability('analysis.semantic_similarity')
    const passageOnlyDecision = evaluateCapabilityCorpusFeatures(semantic, corpus({
      semantic: { passage_search: true, word_similarity: false, sentence_alignment: false },
    }))
    const wordOnlyDecision = evaluateCapabilityCorpusFeatures(semantic, corpus({
      semantic: { passage_search: false, word_similarity: true, sentence_alignment: false },
    }))

    expect(passageOnlyDecision.status).toBe('pass')
    expect(corpusFeatureDecisionPartialReason('Semantik', passageOnlyDecision)).toContain('Wort-Embedding-Index')
    expect(wordOnlyDecision.status).toBe('pass')
    expect(corpusFeatureDecisionPartialReason('Semantik', wordOnlyDecision)).toContain('Passage-Embedding-Index')
    expect(evaluateCapabilityCorpusFeatures(semantic, corpus({
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
    })).status).toBe('blocked')
  })

  it('honors method-specific route feature requirements', () => {
    const semantic = capability('analysis.semantic_similarity')
    const passageOnly = corpus({
      semantic: { passage_search: true, word_similarity: false, sentence_alignment: false },
    })
    const wordOnly = corpus({
      semantic: { passage_search: false, word_similarity: true, sentence_alignment: false },
    })
    const similarWordsRoute = (route: { path: string; methods?: string[] }) =>
      route.path === '/api/v1/semantic/similar_words' &&
      (route.methods ?? []).includes('GET')
    const embeddingRoute = (route: { path: string; methods?: string[] }) =>
      route.path === '/api/v1/analysis/embedding_search' &&
      (route.methods ?? []).includes('POST')

    expect(evaluateCapabilityCorpusFeatures(semantic, passageOnly, similarWordsRoute).status).toBe('blocked')
    expect(evaluateCapabilityCorpusFeatures(semantic, wordOnly, similarWordsRoute).status).toBe('pass')
    expect(evaluateCapabilityCorpusFeatures(semantic, passageOnly, embeddingRoute).status).toBe('pass')
    expect(evaluateCapabilityCorpusFeatures(semantic, wordOnly, embeddingRoute).status).toBe('blocked')
  })

  it('does not fall back to capability-level unions for matched routes without corpus requirements', () => {
    const mixedCapability = {
      id: 'analysis.mixed',
      title: 'Mixed',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [],
      requires_corpus_features: ['semantic.passage_search'],
      backend_route_descriptors: [
        {
          path: '/api/v1/mixed/public',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
        },
        {
          path: '/api/v1/mixed/semantic',
          methods: ['POST'],
          mutates: false,
          requires_corpus_features: ['semantic.passage_search'],
        },
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      limits: [],
    } as ProductCapability
    const wordOnly = corpus({
      semantic: { passage_search: false, word_similarity: true, sentence_alignment: false },
    })

    const decision = evaluateCapabilityCorpusFeatures(
      mixedCapability,
      wordOnly,
      (route) => route.path === '/api/v1/mixed/public' && (route.methods ?? []).includes('GET'),
    )

    expect(decision.status).toBe('pass')
    expect(decision.alternatives).toEqual([
      {
        routePath: '/api/v1/mixed/public',
        methods: ['GET'],
        requirements: [],
        missing: [],
      },
    ])
  })
})
