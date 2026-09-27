import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { actionBus } from '@/actions'
import DocumentSearchRenderer from '@/components/copilot/tools/DocumentSearchRenderer.vue'
import { useUiStore } from '@/stores/ui'

describe('DocumentSearchRenderer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('opens the shared document drawer through nav/openDocument when a row has doc_id', async () => {
    const dispatch = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
    const wrapper = mount(DocumentSearchRenderer, {
      props: {
        data: {
          rows: [
            { doc_id: 42, title: 'Dokument 42', snippet: 'Kontext' },
          ],
        },
      },
    })

    await wrapper.get('button.document-item').trigger('click')

    expect(dispatch).toHaveBeenCalledWith(
      { type: 'nav/openDocument', payload: { docId: '42', fallbackLabel: 'Dokument 42' } },
      { source: 'copilot' }
    )
    dispatch.mockRestore()
  })

  it('does not dispatch document navigation when a row has no document id', async () => {
    const dispatch = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
    const wrapper = mount(DocumentSearchRenderer, {
      props: {
        data: {
          rows: [
            { title: 'Treffer ohne doc_id', snippet: 'Nur Snippet' },
          ],
        },
      },
    })

    await wrapper.get('button.document-item').trigger('click')

    expect(dispatch).not.toHaveBeenCalled()
    dispatch.mockRestore()
  })

  it('shows feedback when document navigation is blocked', async () => {
    const dispatch = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: false,
      blocked: true,
      error: 'Dokumentzugriff nicht freigegeben',
    })
    const uiStore = useUiStore()
    const wrapper = mount(DocumentSearchRenderer, {
      props: {
        data: {
          rows: [
            { doc_id: 42, title: 'Dokument 42', snippet: 'Kontext' },
          ],
        },
      },
    })

    await wrapper.get('button.document-item').trigger('click')

    expect(uiStore.toasts.at(-1)?.message).toBe('Dokumentzugriff nicht freigegeben')
    expect(uiStore.toasts.at(-1)?.type).toBe('warning')
    dispatch.mockRestore()
  })
})
