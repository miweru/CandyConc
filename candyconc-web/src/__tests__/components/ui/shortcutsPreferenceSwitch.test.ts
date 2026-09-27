/**
 * "Enable keyboard shortcuts" switched useKeyboard only. The "?" key of the
 * shortcuts overlay and undo/redo had their own listeners and kept working
 * with the preference off (seen in the browser after the preference was wired).
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ShortcutsOverlay from '@/components/ui/ShortcutsOverlay.vue'
import { useUndoRedo } from '@/composables/useUndoRedo'
import { useHistoryStore } from '@/stores/history'
import { useUiStore } from '@/stores/ui'

describe('keyboard shortcut preference', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('the question mark opens the overlay only while shortcuts are enabled', async () => {
    const wrapper = mount(ShortcutsOverlay, {
      props: { modelValue: false },
      global: { stubs: { Modal: { template: '<div><slot /></div>' } } },
    })
    const ui = useUiStore()
    ui.setShortcutsEnabled(false)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }))
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    ui.setShortcutsEnabled(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }))
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([true])
    wrapper.unmount()
  })

  it('undo follows the preference', () => {
    const history = useHistoryStore()
    Object.defineProperty(history, 'canUndo', { get: () => true, configurable: true })
    const undo = vi.spyOn(history, 'undo').mockReturnValue(false)
    const host = mount(defineComponent({ setup() { useUndoRedo({ showToast: false }); return () => h('div') } }))
    const ui = useUiStore()
    ui.setShortcutsEnabled(false)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', metaKey: true }))
    expect(undo).not.toHaveBeenCalled()
    ui.setShortcutsEnabled(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', metaKey: true }))
    expect(undo).toHaveBeenCalledTimes(1)
    host.unmount()
  })
})
