/**
 * Query samples from the active corpus, with catalog words as fallback.
 * The studio provides them to the node and metadata editors.
 */
import { computed, inject, type Ref } from 'vue'
import { useCorpusExamples } from '@/composables/useCorpusExamples'
import { fallbackQuerySamples, QUERY_SAMPLES_KEY, type QuerySamples } from '@/lib/queryBuilder/samples'

export function useQuerySamples(): Readonly<Ref<QuerySamples>> {
  const { examples, posTagset } = useCorpusExamples()
  return computed(() => {
    const fallback = fallbackQuerySamples()
    const nouns = examples.value.nouns
    const tagset = posTagset.tagset.value
    return {
      noun: nouns[0] ?? fallback.noun,
      nounB: nouns[1] ?? fallback.nounB,
      nounC: nouns[2] ?? fallback.nounC,
      adjective: examples.value.adjectives[0] ?? fallback.adjective,
      verb: examples.value.verbLemmas[0] ?? fallback.verb,
      posNoun: tagset === 'stts' ? 'NN' : posTagset.exampleTag.value ?? fallback.posNoun,
      posAdj: tagset === 'stts' ? 'ADJA' : fallback.posAdj,
      metaValue: fallback.metaValue,
    }
  })
}

/** Samples provided by the studio, or the catalog fallback outside of it. */
export function injectQuerySamples(): Readonly<Ref<QuerySamples>> {
  return inject(QUERY_SAMPLES_KEY, computed(() => fallbackQuerySamples()))
}
