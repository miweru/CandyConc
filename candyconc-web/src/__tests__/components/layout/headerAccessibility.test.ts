import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

import Modal from '@/components/ui/Modal.vue'
import AppShell from '@/components/layout/AppShell.vue'
import { useUiStore } from '@/stores/ui'

describe('Modal accessible name (DESIGN-A11Y-05)', () => {
  it('names the dialog via aria-label when a custom #header slot replaces the default title', () => {
    // ShortcutsOverlay passes title + a custom #header slot; the default
    // <h2 id=titleId> never renders, so aria-labelledby would dangle. The dialog
    // must instead fall back to aria-label so it still has an accessible name.
    const wrapper = mount(Modal, {
      props: { modelValue: true, title: 'Tastenkürzel' },
      slots: { header: '<div><h2>Tastenkürzel</h2></div>' },
      attachTo: document.body,
    })
    const dialog = document.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog).toBeTruthy()
    expect(dialog.getAttribute('aria-label')).toBe('Tastenkürzel')
    expect(dialog.getAttribute('aria-labelledby')).toBeNull()
    wrapper.unmount()
  })

  it('uses aria-labelledby (not aria-label) when the default title header renders', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true, title: 'Export' },
      attachTo: document.body,
    })
    const dialog = document.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog.getAttribute('aria-labelledby')).toBeTruthy()
    expect(dialog.getAttribute('aria-label')).toBeNull()
    // The referenced title element actually exists (no dangling reference).
    const id = dialog.getAttribute('aria-labelledby')!
    expect(document.getElementById(id)?.textContent).toContain('Export')
    wrapper.unmount()
  })
})

describe('theme persistence (DESIGN-A11Y-03)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(localStorage.getItem).mockReset().mockReturnValue(null)
    vi.mocked(localStorage.setItem).mockReset()
  })

  it('persists the chosen theme to localStorage so dark mode survives a reload', () => {
    const ui = useUiStore()
    ui.setTheme('dark')
    expect(localStorage.setItem).toHaveBeenCalledWith('candyconc_theme', 'dark')
  })

  it('reads the persisted theme as the initial value on store creation', () => {
    vi.mocked(localStorage.getItem).mockReturnValue('dark')
    setActivePinia(createPinia())
    const ui = useUiStore()
    expect(ui.theme).toBe('dark')
  })
})

describe('skip-to-content link (DESIGN-A11Y-07)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders a skip link targeting the main content region', () => {
    const wrapper = mount(AppShell, { attachTo: document.body })
    const skip = wrapper.find('a.skip-link')
    expect(skip.exists()).toBe(true)
    expect(skip.attributes('href')).toBe('#main-content')
    // The target it points at must exist and be focusable.
    const main = wrapper.find('#main-content')
    expect(main.exists()).toBe(true)
    expect(main.attributes('tabindex')).toBe('-1')
    wrapper.unmount()
  })
})
