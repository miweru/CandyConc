/**
 * ParallelPresets Store - Save & reuse KWIC parallel projection presets
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface ParallelPreset {
  id: string
  name: string
  createdAt: number
  favorite: boolean
  models: string[]
  pinnedModels?: string[]
  maxVariants: number
  sentenceMargin: number
}

const STORAGE_KEY = 'candyconc_parallel_presets'

function parsePresets(raw: unknown): ParallelPreset[] {
  if (!raw) return []
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item) => item && typeof item.id === 'string') as ParallelPreset[]
  } catch {
    return []
  }
}

export const useParallelPresetsStore = defineStore('parallelPresets', () => {
  const presets = ref<ParallelPreset[]>([])
  const initialized = ref(false)

  const sortedPresets = computed(() =>
    [...presets.value].sort((a, b) => b.createdAt - a.createdAt)
  )

  const favorites = computed(() => sortedPresets.value.filter((p) => p.favorite))

  function persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(presets.value))
  }

  function init() {
    presets.value = parsePresets(localStorage.getItem(STORAGE_KEY))
    initialized.value = true
  }

  function ensureInit() {
    if (!initialized.value) init()
  }

  function createPreset(input: Omit<ParallelPreset, 'id' | 'createdAt'>): ParallelPreset {
    return {
      ...input,
      id: crypto.randomUUID(),
      createdAt: Date.now(),
    }
  }

  function add(preset: ParallelPreset) {
    ensureInit()
    presets.value.unshift(preset)
    persist()
  }

  function update(id: string, updates: Partial<ParallelPreset>) {
    ensureInit()
    const idx = presets.value.findIndex((p) => p.id === id)
    if (idx === -1) return
    presets.value[idx] = { ...presets.value[idx], ...updates } as ParallelPreset
    persist()
  }

  function remove(id: string) {
    ensureInit()
    presets.value = presets.value.filter((p) => p.id !== id)
    persist()
  }

  return {
    presets,
    sortedPresets,
    favorites,
    init,
    createPreset,
    add,
    update,
    remove,
  }
})
