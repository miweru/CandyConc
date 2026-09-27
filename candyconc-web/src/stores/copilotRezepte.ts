import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { getCopilotRezepte, type CopilotRezept } from '@/api/client'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { currentLocale } from '@/i18n/locale'

export const useCopilotRezepteStore = defineStore('copilotRezepte', () => {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const contextKey = computed(() => JSON.stringify([corpusCapabilities.activeCorpus, currentLocale()]))
  const rezepte = ref<Record<string, CopilotRezept>>({})
  const geladen = ref(false)
  let activeKey: string | null = null
  let requestId = 0
  let pending: Promise<void> | null = null

  async function laden(): Promise<void> {
    const key = contextKey.value
    if (activeKey === key && geladen.value) return
    if (activeKey === key && pending) return pending
    activeKey = key
    const id = ++requestId
    geladen.value = false
    rezepte.value = {}
    pending = (async () => {
      try {
        const list = await getCopilotRezepte(corpusCapabilities.activeCorpus)
        if (id !== requestId) return
        rezepte.value = Object.fromEntries(list.filter((recipe) => recipe?.id).map((recipe) => [recipe.id, recipe]))
      } catch {
        // A missing directory leaves the corpus-independent starter questions available.
      } finally {
        if (id === requestId) {
          geladen.value = true
          pending = null
        }
      }
    })()
    return pending
  }

  watch(contextKey, () => {
    if (activeKey !== null) void laden()
  }, { flush: 'sync' })

  function rezept(id: string | null | undefined): CopilotRezept | undefined {
    return id ? rezepte.value[id] : undefined
  }

  return { rezepte, geladen, laden, rezept }
})
