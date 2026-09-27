/**
 * The part-of-speech tags of the active corpus and their recognised tagset.
 *
 * Loads the corpus `pos` lexicon once per corpus (most frequent first) through
 * the lexicon suggestion operation. Search help and query builder use it to
 * describe and exemplify the tags the corpus really has, not a fixed tagset.
 */
import { computed, ref, watch } from 'vue'
import { useCqlfOperations } from '@/composables/useCqlfOperations'
import { detectPosTagset, examplePosTag, type PosTagset } from '@/lib/posTagset'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'

/**
 * The pos lexicon of a corpus holds a few dozen tags. 200 is the largest limit
 * the lexicon suggestion route accepts (LexiconSuggestRequest.limit, le=200).
 */
export const POS_LEXICON_LIMIT = 200

const cache = new Map<string, Promise<string[]>>()

/** Test hook: forget the loaded tag lists. */
export function clearCorpusPosTagCache(): void {
  cache.clear()
}

export interface CorpusPosTagsetOptions {
  /** Load as soon as the corpus is known. Otherwise only `ensureLoaded()` loads. */
  immediate?: boolean
}

export function useCorpusPosTagset(options: CorpusPosTagsetOptions = {}) {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const { canSuggestLexicon, loadLexiconSuggestions } = useCqlfOperations()
  const tags = ref<string[]>([])

  const hasPos = computed(() => corpusCapabilities.canUseTokenAttribute('pos'))
  const cacheKey = computed(() => {
    const summary = corpusCapabilities.activeSummary
    return `${corpusCapabilities.activeCorpus}:${summary?.token_count ?? ''}`
  })

  async function ensureLoaded(): Promise<void> {
    const key = cacheKey.value
    if (!hasPos.value || !canSuggestLexicon.value) {
      tags.value = []
      return
    }
    let pending = cache.get(key)
    if (!pending) {
      pending = loadLexiconSuggestions('pos', '', POS_LEXICON_LIMIT, undefined, corpusCapabilities.activeCorpus)
        .then((values) => (Array.isArray(values) ? values.map(String) : []))
      cache.set(key, pending)
      pending.catch(() => cache.delete(key))
    }
    try {
      const values = await pending
      if (key === cacheKey.value) tags.value = values
    } catch {
      if (key === cacheKey.value) tags.value = []
    }
  }

  if (options.immediate ?? true) {
    watch([cacheKey, hasPos, canSuggestLexicon], () => { void ensureLoaded() }, { immediate: true })
  } else {
    watch(cacheKey, () => { tags.value = [] })
  }

  const tagset = computed<PosTagset | null>(() => detectPosTagset(tags.value))
  const exampleTag = computed<string | null>(() => examplePosTag(tags.value, tagset.value))

  return { tags, tagset, exampleTag, ensureLoaded }
}
