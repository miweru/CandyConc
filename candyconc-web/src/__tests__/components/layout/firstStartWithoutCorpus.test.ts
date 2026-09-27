/**
 * First start with an empty data folder. The corpus switcher and the scope chip
 * showed "default", an internal name, the status bar showed "System
 * information not loaded" as a warning next to "Server READY", and the
 * interface asked the server three times for the metadata schema of a corpus
 * that does not exist (503).
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/client'
import CorpusSwitcher from '@/components/layout/CorpusSwitcher.vue'
import StatusBar from '@/components/layout/StatusBar.vue'
import ScopeHeader from '@/components/search/ScopeHeader.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useDocsetStore } from '@/stores/docset'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'

vi.mock('@/components/ui/Dropdown.vue', () => ({
  default: { template: '<div><slot name="trigger" :trigger-props="{}" /><slot /></div>' },
}))

function emptyCatalog() {
  const corpora = useCorpusCapabilitiesStore()
  corpora.corpora = []
  corpora.loaded = true
  corpora.error = null
}

describe('first start without a corpus', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.spyOn(useProductCapabilitiesStore(), 'ensureAccessContext').mockResolvedValue(undefined as never)
  })

  it('the corpus switcher says there is no corpus instead of "default"', async () => {
    emptyCatalog()
    const wrapper = mount(CorpusSwitcher)
    await flushPromises()
    expect(wrapper.get('.corpus-switcher-label').text()).toBe('Kein Korpus')
  })

  it('the scope chip names no corpus', async () => {
    emptyCatalog()
    const wrapper = mount(ScopeHeader, { props: { inline: true, minimal: true } })
    await flushPromises()
    expect(wrapper.get('.scope-chip-name').text()).toBe('kein Korpus')
    expect(wrapper.get('.scope-chip-label').text()).toBe('Suchbereich')
  })

  it('the status bar states that there is no corpus yet, without a warning', async () => {
    emptyCatalog()
    const wrapper = mount(StatusBar)
    await flushPromises()
    const info = wrapper.get('.corpus-info')
    expect(info.text()).toBe('Noch kein Korpus')
    expect(info.classes()).not.toContain('corpus-info--unverified')
  })

  it('does not request a metadata schema before or without a corpus', async () => {
    const schema = vi.spyOn(api, 'getMetaSchema').mockRejectedValue(new Error('503'))
    vi.spyOn(useProductCapabilitiesStore(), 'assertProductOperationAccess').mockResolvedValue({
      visible: true, enabled: true, disabledReason: null, operations: [],
    })
    const docset = useDocsetStore()
    await flushPromises()
    expect(schema).not.toHaveBeenCalled()
    emptyCatalog()
    await flushPromises()
    await docset.loadMetaSchema(true)
    expect(await docset.fetchMetaSchema()).toBeNull()
    expect(schema).not.toHaveBeenCalled()
  })
})
