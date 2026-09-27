import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import SettingsGeneral from '@/components/settings/SettingsGeneral.vue'
import { applyLocale } from '@/i18n/locale'
import { kwicLoadWindow } from '@/lib/kwicLoadWindow'
import { useSettingsStore } from '@/stores/settings'

// "Results per page" was described as the number of concordance lines shown.
// The table shows every loaded line, and a search loads three times the
// value (at least 200, at most 2000): 300 lines at 100, 200 at 50.

const wrappers: Array<ReturnType<typeof mount>> = []

beforeEach(() => {
  setActivePinia(createPinia())
})

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  applyLocale('de')
})

describe('concordance load size', () => {
  it('loads three times the value within 200 and 2000 lines', () => {
    expect([50, 100, 200, 500, 1000].map(kwicLoadWindow)).toEqual([200, 300, 600, 1500, 2000])
  })

  it('describes the lines a search actually loads', async () => {
    const settings = useSettingsStore()
    settings.preferences.resultsPerPage = 100
    const wrapper = mount(SettingsGeneral)
    wrappers.push(wrapper)
    await flushPromises()
    const row = wrapper.get('#resultsPerPage').element.closest('.setting-row')!
    expect(row.textContent).toContain('Ladegröße der Konkordanz')
    expect(row.textContent).toContain('Eine Suche lädt 300 KWIC-Zeilen auf einmal')
    expect(row.textContent).not.toContain('Anzahl der angezeigten')

    settings.preferences.resultsPerPage = 50
    await flushPromises()
    expect(row.textContent).toContain('Eine Suche lädt 200 KWIC-Zeilen auf einmal')

    applyLocale('en')
    settings.preferences.resultsPerPage = 500
    await flushPromises()
    expect(row.textContent).toContain('Concordance load size')
    expect(row.textContent).toContain('A search loads 1,500 concordance lines at once')
  })
})
