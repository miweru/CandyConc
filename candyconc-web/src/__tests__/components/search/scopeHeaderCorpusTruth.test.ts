import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import ScopeHeader from '@/components/search/ScopeHeader.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSettingsStore } from '@/stores/settings'

vi.mock('@/composables/useOnlineStatus', async () => {
  const { ref } = await import('vue')
  return {
    useGlobalOnlineStatus: () => ({
      isOnline: ref(true),
      isBackendReachable: ref(true),
      isBackendReady: ref(true),
      backendReadiness: ref('ready'),
      isChecking: ref(false),
      lastCheckTimestamp: ref(1770883200000),
      forceCheck: vi.fn(),
    }),
  }
})

function corpusSummary(name = 'default') {
  return {
    name,
    path: `/corpora/${name}`,
    active: true,
    token_count: 56_191,
    doc_count: 2_000,
    import_mode: 'registered',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
  }
}

describe('ScopeHeader corpus truth', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('names the pinned corpus by its display name', async () => {
    useQueryStore().setFilters({ corpus: 'default' })
    useCorpusCapabilitiesStore().corpora = [{ ...corpusSummary(), display_name: 'sotu_en' }]
    const wrapper = mount(ScopeHeader, {
      global: {
        stubs: {
          Dropdown: { template: '<div><slot name="trigger" /><slot /></div>' },
          DropdownItem: { template: '<button type="button"><slot /></button>' },
        },
      },
    })
    expect(wrapper.text()).toContain('sotu_en')
    await wrapper.find('button[title="Details einblenden"]').trigger('click')
    expect(wrapper.text()).toContain('Korpus: sotu_en')
    expect(wrapper.text()).not.toContain('Korpus: default')
  })

  it('shows the active corpus catalogue counts instead of stale system-info defaults', async () => {
    const queryStore = useQueryStore()
    queryStore.setFilters({ corpus: 'default' })
    const corpusStore = useCorpusCapabilitiesStore()
    corpusStore.corpora = [corpusSummary()]

    const settingsStore = useSettingsStore()
    settingsStore.systemInfo = {
      backendVersion: '0.1.0',
      uptime: '',
      faissStatus: 'unavailable',
      vectorCount: 0,
      cacheSize: '0 MB',
      corpusName: 'Kein Korpus geladen',
      tokenCount: 0,
      documentCount: 0,
    }

    const wrapper = mount(ScopeHeader, {
      global: {
        stubs: {
          Dropdown: { template: '<div><slot name="trigger" /><slot /></div>' },
          DropdownItem: { template: '<button type="button"><slot /></button>' },
        },
      },
    })

    expect(wrapper.text()).toContain('default')
    expect(wrapper.text()).not.toContain('Kein Korpus geladen')

    await wrapper.find('button[title="Details einblenden"]').trigger('click')

    expect(wrapper.text()).toContain('Korpus: default')
    expect(wrapper.text()).toMatch(/Docs\s+2\.000/)
    expect(wrapper.text()).toMatch(/Tokens\s+56\.191/)
  })
})
