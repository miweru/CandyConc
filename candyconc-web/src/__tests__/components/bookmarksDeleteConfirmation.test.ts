/**
 * "Confirm deletion" in the settings asks before a bookmark is deleted. Before
 * this change the preference had no reader and the bookmark was deleted at
 * once.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BookmarksPanel from '@/components/bookmarks/BookmarksPanel.vue'
import { actionBus } from '@/actions'
import { useBookmarksStore } from '@/stores/bookmarks'
import { useSettingsStore } from '@/stores/settings'

function mountPanel() {
  return mount(BookmarksPanel, {
    props: { modelValue: true },
    global: {
      stubs: {
        SlideOver: { template: '<div><slot /><slot name="footer" /></div>' },
      },
    },
  })
}

describe('bookmark deletion follows the confirm-deletion preference', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.mocked(window.confirm).mockReset()
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
    const bookmarks = useBookmarksStore()
    bookmarks.bookmarks = [
      { id: 'b1', name: 'freedom 1945', query: 'freedom', timestamp: 1, selectedRows: [] },
    ] as typeof bookmarks.bookmarks
  })

  it('keeps the bookmark when the question is declined', async () => {
    vi.mocked(window.confirm).mockReturnValue(false)
    const wrapper = mountPanel()
    await wrapper.get('.delete-btn').trigger('click')
    await flushPromises()
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('freedom 1945'))
    expect(actionBus.dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'bookmark/remove' }),
      expect.anything(),
    )
  })

  it('deletes without a question when the preference is off', async () => {
    useSettingsStore().preferences.confirmDelete = false
    const wrapper = mountPanel()
    await wrapper.get('.delete-btn').trigger('click')
    await flushPromises()
    expect(window.confirm).not.toHaveBeenCalled()
    expect(actionBus.dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'bookmark/remove', payload: { id: 'b1' } }),
      expect.anything(),
    )
  })
})
