import { ref, type Ref } from 'vue'
import { collectMetaFields, type CqlBuilderMode, type CqlBuilderNode } from '@/lib/queryBuilder/ast'
import { useDocsetStore } from '@/stores'
import { t } from '@/i18n'

/**
 * Debounced loading of meta-field value options for the advanced builder.
 *
 * Extracted verbatim from QueryBuilderStudio.vue (Phase 2 split). Owns the
 * metaValueOptions cache plus the debounce timer / abort controller / request
 * id used to keep only the latest in-flight request.
 */
export function useMetaValueOptions(options: {
  rootNode: Ref<CqlBuilderNode>
  mode: Ref<CqlBuilderMode>
  activeCorpus: Ref<string>
}) {
  const { rootNode, mode, activeCorpus } = options
  const docsetStore = useDocsetStore()

  const metaValueOptions = ref<Record<string, string[]>>({})
  const metaValueError = ref<string | null>(null)

  let metaTimer: ReturnType<typeof setTimeout> | null = null
  let metaAbort: AbortController | null = null
  let metaRequestId = 0

  function metaValueChoices(field: string): string[] {
    const trimmed = field.trim()
    if (!trimmed) return []
    const storeValues = (docsetStore.metaOptions as Record<string, string[]>)[trimmed] ?? []
    const apiValues = metaValueOptions.value[trimmed] ?? []
    return Array.from(new Set([...storeValues, ...apiValues])).sort((left, right) =>
      left.localeCompare(right, 'de')
    )
  }

  function clearMetaTimer() {
    if (metaTimer) {
      clearTimeout(metaTimer)
      metaTimer = null
    }
  }

  function cancelMetaRequest() {
    if (metaAbort) {
      metaAbort.abort()
      metaAbort = null
    }
  }

  function scheduleMetaValueLoad() {
    clearMetaTimer()
    cancelMetaRequest()

    const fields = collectMetaFields(rootNode.value)
    if (!fields.length || mode.value !== 'advanced') {
      metaValueOptions.value = {}
      metaValueError.value = null
      return
    }

    metaRequestId += 1
    const requestId = metaRequestId
    metaAbort = new AbortController()

    metaTimer = setTimeout(async () => {
      try {
        const page = await docsetStore.fetchMetaValuesPage(
          { fields, corpus: activeCorpus.value },
          { signal: metaAbort?.signal },
          t('querybuilder.metaValues.operationLabel'),
        )
        if (requestId !== metaRequestId) return
        if (!page) {
          metaValueOptions.value = {}
          metaValueError.value = docsetStore.error ?? t('querybuilder.metaValues.notEnabled')
          return
        }
        metaValueOptions.value = page.values
        metaValueError.value = page.truncatedFields.length
          ? t('querybuilder.metaValues.truncated', { fields: page.truncatedFields.join(', ') })
          : null
      } catch {
        if (requestId !== metaRequestId) return
        metaValueOptions.value = {}
        metaValueError.value = t('querybuilder.metaValues.loadFailed')
      }
    }, 300)
  }

  return {
    metaValueOptions,
    metaValueError,
    metaValueChoices,
    clearMetaTimer,
    cancelMetaRequest,
    scheduleMetaValueLoad,
  }
}
