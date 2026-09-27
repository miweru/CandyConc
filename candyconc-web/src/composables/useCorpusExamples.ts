/**
 * Example search terms taken from the active corpus.
 *
 * Examples in the query builder used to be fixed German words, useless for an
 * English corpus and not a fact about any corpus. Here they are the most
 * frequent nouns and adjectives (word forms) and verbs (lemmas) of the active
 * corpus, read from its frequency list with the part-of-speech filter of the
 * recognised tagset. Without a recognised tagset or without the frequency list
 * there are no examples, rather than function words or invented ones.
 */
import { computed, ref, watch } from 'vue'
import { useCorpusPosTagset } from '@/composables/useCorpusPosTagset'
import { useFrequencyOperations } from '@/composables/useFrequencyOperations'
import type { PosTagset } from '@/lib/posTagset'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'

export interface CorpusExamples {
  nouns: string[]
  adjectives: string[]
  verbLemmas: string[]
}

const EXAMPLE_COUNT = 3
const NOUN_PREFIX: Record<PosTagset, string> = { upos: 'NOUN', stts: 'NN' }
const VERB_PREFIX: Record<PosTagset, string> = { upos: 'VERB', stts: 'VV' }
const ADJ_PREFIX: Record<PosTagset, string> = { upos: 'ADJ', stts: 'ADJA' }
const EMPTY: CorpusExamples = { nouns: [], adjectives: [], verbLemmas: [] }

const cache = new Map<string, Promise<CorpusExamples>>()

/** Test hook: forget loaded examples. */
export function clearCorpusExampleCache(): void {
  cache.clear()
}

function words(rows: Array<{ item: string }>): string[] {
  return rows.map((row) => row.item).filter((item) => /\p{L}/u.test(item)).slice(0, EXAMPLE_COUNT)
}

export function useCorpusExamples() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const posTagset = useCorpusPosTagset()
  const { canLoadFrequencyList, loadFrequencyResult } = useFrequencyOperations()
  const examples = ref<CorpusExamples>(EMPTY)

  const hasLemma = computed(() => corpusCapabilities.canUseTokenAttribute('lemma'))
  const cacheKey = computed(() => {
    const summary = corpusCapabilities.activeSummary
    return `${corpusCapabilities.activeCorpus}:${summary?.token_count ?? ''}:${posTagset.tagset.value ?? ''}`
  })

  async function fetchExamples(tagset: PosTagset, corpus: string): Promise<CorpusExamples> {
    const nouns = await loadFrequencyResult({ groupBy: 'word', posPrefix: NOUN_PREFIX[tagset], limit: EXAMPLE_COUNT * 2, corpus })
    const adjectives = await loadFrequencyResult({ groupBy: 'word', posPrefix: ADJ_PREFIX[tagset], limit: EXAMPLE_COUNT * 2, corpus })
    const verbs = hasLemma.value
      ? await loadFrequencyResult({ groupBy: 'lemma', posPrefix: VERB_PREFIX[tagset], limit: EXAMPLE_COUNT * 2, corpus })
      : { rows: [] }
    return {
      nouns: words(nouns.rows ?? []),
      adjectives: words(adjectives.rows ?? []),
      verbLemmas: words(verbs.rows ?? []),
    }
  }

  async function load() {
    const key = cacheKey.value
    const tagset = posTagset.tagset.value
    if (!tagset || !canLoadFrequencyList.value) {
      examples.value = EMPTY
      return
    }
    let pending = cache.get(key)
    if (!pending) {
      pending = fetchExamples(tagset, corpusCapabilities.activeCorpus)
      cache.set(key, pending)
      pending.catch(() => cache.delete(key))
    }
    try {
      const loaded = await pending
      if (key === cacheKey.value) examples.value = loaded
    } catch {
      if (key === cacheKey.value) examples.value = EMPTY
    }
  }

  watch([cacheKey, canLoadFrequencyList], () => { void load() }, { immediate: true })

  return { examples, posTagset }
}
