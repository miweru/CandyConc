import { computed, ref, watch, type Ref } from 'vue'
import { useDocsetStore } from '@/stores'
import { activeSimpleFilters, isSimpleFilterField, type SimpleSearchState } from '@/lib/queryBuilder/simple'
import { t } from '@/i18n'

/**
 * Metadata filters of the quick search.
 *
 * One select per field of the active corpus that tells documents apart: an
 * enumerable field of the metadata schema with more than one value and no
 * document identifier. The reader and the subcorpus panel read the same
 * schema. Values load when the filter area is open.
 */
export function useSimpleSearchFilters(options: {
  state: Ref<SimpleSearchState>
  open: Ref<boolean>
}) {
  const docsetStore = useDocsetStore()
  const values = ref<Record<string, string[]>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)
  let requestId = 0

  const schemaFields = computed(() =>
    docsetStore.enumFields
      .map((field) => field.name)
      .filter((name) => {
        if (!isSimpleFilterField(name)) return false
        const count = docsetStore.metaFieldValueCounts[name]
        return typeof count !== 'number' || count > 1
      }),
  )

  /** Schema fields plus fields of an opened query that the schema does not list. */
  const fields = computed(() => {
    const list = [...schemaFields.value]
    for (const [field] of activeSimpleFilters(options.state.value)) {
      if (!list.includes(field)) list.push(field)
    }
    return list
  })

  const activeCount = computed(() => activeSimpleFilters(options.state.value).length)

  /** Whether the schema of the active corpus is known, so an empty field list is a finding. */
  const schemaKnown = computed(() => docsetStore.metaFields.length > 0 || docsetStore.metaSchemaHash !== null)

  /** Loaded values of a field, with the selected value kept when it is not among them. */
  function choices(field: string): string[] {
    const loaded = values.value[field] ?? []
    const current = (options.state.value.filters[field] ?? '').trim()
    return current && !loaded.includes(current) ? [current, ...loaded] : loaded
  }

  async function load() {
    const names = schemaFields.value
    const id = ++requestId
    error.value = null
    if (!names.length) {
      values.value = {}
      loading.value = false
      return
    }
    loading.value = true
    try {
      const result = await docsetStore.fetchMetaValues(
        { fields: names, corpus: docsetStore.activeCorpus },
        {},
        t('querybuilder.simple.filtersOperation'),
      )
      if (id !== requestId) return
      if (!result) {
        error.value = docsetStore.error ?? t('querybuilder.simple.filtersFailed')
        return
      }
      values.value = Object.fromEntries(names.map((name) => [name, [...(result[name] ?? [])].sort()]))
    } catch {
      if (id !== requestId) return
      error.value = t('querybuilder.simple.filtersFailed')
    } finally {
      if (id === requestId) loading.value = false
    }
  }

  watch(
    () => [options.open.value, docsetStore.activeCorpus, schemaFields.value.join('|')] as const,
    ([open], previous) => {
      if (previous && previous[1] !== docsetStore.activeCorpus) values.value = {}
      if (open) void load()
    },
    { immediate: true },
  )

  return { fields, schemaFields, schemaKnown, values, loading, error, activeCount, choices }
}
