import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import {
  productOperationFocusIs,
  productOperationFocusMatches,
  useProductOperationFocus,
} from '@/composables/useProductOperationFocus'
import { useUiStore, type ProductOperationFocus } from '@/stores/ui'

function focus(overrides: Partial<ProductOperationIntent>): ProductOperationIntent {
  return {
    operationId: 'operation.test',
    capabilityId: 'capability.test',
    surfaceSlot: 'capability.test.operation',
    openTarget: null,
    preferredMode: null,
    responseShape: 'unknown',
    inputSchemaRef: '',
    timestamp: 1,
    ...overrides,
  }
}

describe('product operation focus helpers', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('matches focused operations by exact operation id', () => {
    expect(productOperationFocusIs(focus({
      operationId: 'analysis.contrast.collocations_diff_job',
      capabilityId: 'analysis.contrast',
      surfaceSlot: 'analysis.contrast.collocations',
    }), 'analysis.contrast.free_job', 'analysis.contrast.collocations_diff_job')).toBe(true)
  })

  it('matches focused surface slots by normalized prefix', () => {
    expect(productOperationFocusMatches(focus({
      operationId: 'corpus.import.start',
      capabilityId: 'corpus.import',
      surfaceSlot: 'corpus.import.start',
    }), 'corpus.import')).toBe(true)
    expect(productOperationFocusMatches(focus({
      operationId: 'corpus.import.start',
      capabilityId: 'corpus.import',
      surfaceSlot: 'corpus.import.start',
    }), 'analysis.contrast')).toBe(false)
  })

  it('consumes matching operation focus and clears the global sticky focus', async () => {
    const uiStore = useUiStore()
    const {
      consumedProductOperation,
      consumeFocusFor,
      focusMatches,
    } = useProductOperationFocus()
    const handled: string[] = []

    consumeFocusFor(['analysis.semantic_similarity'], (item) => {
      handled.push(item.operationId)
    })
    uiStore.focusProductOperation('analysis.semantic_similarity.similar_words', {
      capabilityId: 'analysis.semantic_similarity',
      surfaceSlot: 'analysis.semantic_similarity.words',
      preferredMode: 'words',
    })
    await nextTick()

    expect(handled).toEqual(['analysis.semantic_similarity.similar_words'])
    expect(uiStore.focusedProductOperation).toBeNull()
    expect(consumedProductOperation.value?.operationId).toBe('analysis.semantic_similarity.similar_words')
    expect(focusMatches('analysis.semantic_similarity.words')).toBe(true)
  })
})
