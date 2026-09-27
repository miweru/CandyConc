/**
 * Every preference in the settings dialog must take effect outside the dialog.
 *
 * Before this change highlight colour, typeface, text size, keyboard shortcuts
 * and "confirm deletion" were stored and read by nobody (inventar 3.18, Anhang
 * B 4). The autonomy level was lost on every reload.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import { useCopilotStore } from '@/stores/copilot'

describe('display and behaviour preferences take effect', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(localStorage.getItem).mockReset()
    vi.mocked(localStorage.setItem).mockReset()
    vi.mocked(window.confirm).mockReset()
    vi.mocked(window.confirm).mockReturnValue(true)
    delete document.documentElement.dataset.kwicHighlight
    delete document.documentElement.dataset.fontFamily
    delete document.documentElement.dataset.fontSize
  })

  it('writes highlight colour, typeface and text size to the document root', async () => {
    const settings = useSettingsStore()
    const root = document.documentElement
    expect(root.dataset.kwicHighlight).toBe('yellow')
    expect(root.dataset.fontFamily).toBe('system')
    expect(root.dataset.fontSize).toBe('medium')

    settings.preferences.highlightColor = 'green'
    settings.preferences.fontFamily = 'mono'
    settings.preferences.fontSize = 'large'
    await nextTick()
    expect(root.dataset.kwicHighlight).toBe('green')
    expect(root.dataset.fontFamily).toBe('mono')
    expect(root.dataset.fontSize).toBe('large')
  })

  it('applies stored display preferences at start and drops the former Inter choice', () => {
    vi.mocked(localStorage.getItem).mockImplementation((key: string) =>
      key === 'candyconc_preferences'
        ? JSON.stringify({ highlightColor: 'purple', fontFamily: 'inter', fontSize: 'small' })
        : null,
    )
    const settings = useSettingsStore()
    settings.loadLocalPreferences()
    const root = document.documentElement
    expect(root.dataset.kwicHighlight).toBe('purple')
    expect(root.dataset.fontSize).toBe('small')
    expect(settings.preferences.fontFamily).toBe('system')
    expect(root.dataset.fontFamily).toBe('system')
  })

  it('switches the global keyboard shortcuts', async () => {
    const settings = useSettingsStore()
    const ui = useUiStore()
    expect(ui.shortcutsEnabled).toBe(true)
    settings.preferences.enableShortcuts = false
    await nextTick()
    expect(ui.shortcutsEnabled).toBe(false)
    settings.preferences.enableShortcuts = true
    await nextTick()
    expect(ui.shortcutsEnabled).toBe(true)
  })

  it('asks before a deletion only while "confirm deletion" is on', () => {
    const settings = useSettingsStore()
    vi.mocked(window.confirm).mockReturnValue(false)
    expect(settings.confirmDeletion('republican_addresses')).toBe(false)
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('republican_addresses'))

    vi.mocked(window.confirm).mockClear()
    settings.preferences.confirmDelete = false
    expect(settings.confirmDeletion('republican_addresses')).toBe(true)
    expect(window.confirm).not.toHaveBeenCalled()
  })

  it('keeps the copilot autonomy level across a reload', () => {
    const copilot = useCopilotStore()
    copilot.setAutonomyStep(4)
    return nextTick().then(() => {
      const stored = vi.mocked(localStorage.setItem).mock.calls.find(([key]) => key === 'candyconc_copilot_autonomy')
      expect(stored?.[1]).toBe(String(copilot.autonomyLevel))

      vi.mocked(localStorage.getItem).mockImplementation((key: string) =>
        key === 'candyconc_copilot_autonomy' ? String(copilot.autonomyLevel) : null,
      )
      setActivePinia(createPinia())
      expect(useCopilotStore().autonomyLevel).toBe(copilot.autonomyLevel)
    })
  })
})
