/**
 * Values used in query builder examples, explanations and starter templates.
 *
 * The query builder fills them from the active corpus (see
 * composables/queryBuilder/useQuerySamples). Without corpus values the words
 * come from the catalog in the interface language, and the tags are Universal
 * POS, the tagset every spaCy import writes.
 */
import type { InjectionKey, Ref } from 'vue'
import { t } from '@/i18n'

export interface QuerySamples {
  /** Frequent nouns (word forms). */
  noun: string
  nounB: string
  nounC: string
  /** A frequent adjective (word form). */
  adjective: string
  /** A frequent verb lemma. */
  verb: string
  /** Noun and adjective tag of the corpus tagset. */
  posNoun: string
  posAdj: string
  /** Illustrative metadata value for the field `genre`. */
  metaValue: string
}

export function fallbackQuerySamples(): QuerySamples {
  return {
    noun: t('querybuilder.samples.noun'),
    nounB: t('querybuilder.samples.nounB'),
    nounC: t('querybuilder.samples.nounC'),
    adjective: t('querybuilder.samples.adjective'),
    verb: t('querybuilder.samples.verb'),
    posNoun: 'NOUN',
    posAdj: 'ADJ',
    metaValue: t('querybuilder.samples.metaValue'),
  }
}

export const QUERY_SAMPLES_KEY: InjectionKey<Readonly<Ref<QuerySamples>>> = Symbol('querySamples')
