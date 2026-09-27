/**
 * The language selection in Settings > General switches the interface.
 * Before this change the choice was stored and never read (finding B5): every
 * label stayed German and <html lang> stayed "de".
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsGeneral from '@/components/settings/SettingsGeneral.vue'
import KwicTable from '@/components/search/KwicTable.vue'
import { currentLocale } from '@/i18n/locale'
import { useQueryStore } from '@/stores/query'
import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import type { KwicRow } from '@/stores/query'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(async () => { throw new Error('offline') }),
    getCorpora: vi.fn(async () => ({ corpora: [] })),
    updatePrefs: vi.fn(async () => ({ ok: true })),
  }
})

vi.mock('@tanstack/vue-virtual', () => ({
  useVirtualizer: (optionsRef: { value: { count: number } }) => ({
    value: {
      options: { estimateSize: () => 48 },
      getVirtualItems: () =>
        Array.from({ length: optionsRef.value.count }, (_, index) => ({
          index,
          key: index,
          start: index * 48,
          size: 48,
        })),
      getTotalSize: () => optionsRef.value.count * 48,
      scrollToIndex: vi.fn(),
      measure: vi.fn(),
      measureElement: vi.fn(),
    },
  }),
}))

if (!('scrollIntoView' in HTMLElement.prototype)) {
  // @ts-expect-error augmenting prototype for jsdom
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

const wrappers: Array<ReturnType<typeof mount>> = []
afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
})

describe('language switch in Settings > General', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('relabels the settings view, sets <html lang> and keeps the choice', async () => {
    const wrapper = mount(SettingsGeneral)
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.text()).toContain('Allgemeine Einstellungen')
    expect(wrapper.text()).toContain('Sprache')
    expect(document.documentElement.lang).toBe('de')

    await wrapper.find('#language').setValue('en')
    await flushPromises()

    expect(currentLocale()).toBe('en')
    expect(document.documentElement.lang).toBe('en')
    expect(useSettingsStore().preferences.language).toBe('en')
    expect(wrapper.text()).toContain('General settings')
    expect(wrapper.text()).toContain('Language')
    expect(wrapper.text()).toContain('Concordance load size')
    expect(wrapper.text()).not.toContain('Allgemeine Einstellungen')
    expect(wrapper.text()).not.toContain('Ladegröße der Konkordanz')
  })
})

describe('language switch in the KWIC view', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
  })

  function rows(n: number): KwicRow[] {
    return Array.from({ length: n }, (_, i) => ({
      position: 12345 + i,
      left: `left ${i}`,
      match: 'freedom',
      right: `right ${i}`,
      docId: `doc${i}`,
    }))
  }

  it('relabels the table and switches the number format', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('freedom')
    queryStore.setResults(rows(2), 1495, true, false)

    const wrapper = mount(KwicTable, {
      global: {
        stubs: {
          Modal: { template: '<div><slot /></div>' },
          AnnotationSchemeEditor: { template: '<div />' },
        },
      },
    })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.text()).toContain('1.495 Treffer')
    expect(wrapper.text()).toContain('Zeilen kopieren')
    expect(wrapper.text()).toContain('Linker Kontext')
    expect(wrapper.find('[data-testid="kwic-row-0"]').text()).toContain('12.345')

    await useSettingsStore().setLanguage('en')
    await flushPromises()

    expect(wrapper.text()).toContain('1,495 hits')
    expect(wrapper.text()).toContain('Copy lines')
    expect(wrapper.text()).toContain('Left context')
    expect(wrapper.text()).toContain('Sort left')
    expect(wrapper.find('[data-testid="kwic-row-0"]').text()).toContain('12,345')
    expect(wrapper.text()).not.toContain('Treffer')
    expect(wrapper.text()).not.toContain('Zeilen kopieren')
  })
})
