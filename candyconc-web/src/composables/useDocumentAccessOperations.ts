import { computed } from 'vue'
import {
  getDocSnippet,
  getDocument,
  type DocSnippet,
  type DocSnippetParams,
  type Document,
} from '@/api/client'
import { useProductOperation } from '@/composables/useProductOperation'
import { t } from '@/i18n'

export const DOCUMENT_ACCESS_OPERATIONS = {
  snippet: 'query.document_access.snippet',
  fullText: 'query.document_access.full_text',
} as const

export const DOCUMENT_ACCESS_ROUTES = {
  snippet: '/api/v1/doc/snippet',
  fullText: '/api/v1/document/{doc_id}',
} as const

export function useDocumentAccessOperations() {
  const snippetOperation = useProductOperation<
    [DocSnippetParams],
    DocSnippet
  >(
    DOCUMENT_ACCESS_OPERATIONS.snippet,
    getDocSnippet,
    {
      fallbackCapabilityId: 'query.document_access',
      fallbackLabel: t('kwic.operations.snippet'),
      fallbackOperation: { path: DOCUMENT_ACCESS_ROUTES.snippet, method: 'GET' },
      fallbackReason: t('kwic.operations.snippetNotEnabled'),
    },
  )

  const documentOperation = useProductOperation<
    [string, string?],
    Document
  >(
    DOCUMENT_ACCESS_OPERATIONS.fullText,
    getDocument,
    {
      fallbackCapabilityId: 'query.document_access',
      fallbackLabel: t('kwic.operations.openDocument'),
      fallbackOperation: { path: DOCUMENT_ACCESS_ROUTES.fullText, method: 'GET' },
      fallbackReason: t('kwic.operations.documentNotEnabled'),
    },
  )

  return {
    snippetAvailability: snippetOperation.availability,
    documentAvailability: documentOperation.availability,
    canLoadDocSnippet: computed(() => snippetOperation.canUse.value),
    canLoadDocument: computed(() => documentOperation.canUse.value),
    docSnippetBlockReason: snippetOperation.blockReason,
    documentBlockReason: documentOperation.blockReason,
    loadDocSnippet: snippetOperation.run,
    loadDocument: documentOperation.run,
  }
}
