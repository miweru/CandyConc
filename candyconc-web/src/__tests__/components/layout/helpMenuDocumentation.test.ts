/**
 * erprobung B17: the help button showed only the keyboard shortcuts. The help
 * menu now opens the bundled manual under /docs/ when the package holds it,
 * says clearly that it is missing otherwise, and keeps the shortcuts.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/client'
import HeaderActions from '@/components/layout/HeaderActions.vue'
import { useUiStore } from '@/stores/ui'

function mountHeader() {
  return mount(HeaderActions, {
    shallow: true,
    global: {
      stubs: {
        Dropdown: { template: '<div class="dd"><slot name="trigger" :triggerProps="{}" /><slot /></div>' },
        DropdownItem: {
          emits: ['click'],
          template: '<button class="dd-item" v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
        },
        SettingsPanel: true,
        ExportDialog: true,
        BookmarksPanel: true,
        WorkspaceManager: true,
        AuthSessionPanel: true,
      },
    },
  })
}

describe('help menu', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('opens the bundled documentation when the package holds it', async () => {
    vi.spyOn(api, 'getHelpStatus').mockResolvedValue({ docsAvailable: true, docsUrl: '/docs/' })
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    const wrapper = mountHeader()
    await wrapper.get('[data-testid="help-documentation"]').trigger('click')
    await flushPromises()
    expect(open).toHaveBeenCalledWith('/docs/', '_blank', 'noopener')
  })

  it('says that the documentation is missing instead of opening an empty page', async () => {
    vi.spyOn(api, 'getHelpStatus').mockResolvedValue({ docsAvailable: false, docsUrl: null })
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    const wrapper = mountHeader()
    await wrapper.get('[data-testid="help-documentation"]').trigger('click')
    await flushPromises()
    expect(open).not.toHaveBeenCalled()
    const ui = useUiStore()
    expect(ui.toasts.at(-1)?.message).toContain('keine eingebaute Dokumentation')
  })

  it('keeps the keyboard shortcuts in the menu', async () => {
    const wrapper = mountHeader()
    await wrapper.get('[data-testid="help-shortcuts"]').trigger('click')
    expect(useUiStore().shortcutsOpen).toBe(true)
  })
})
