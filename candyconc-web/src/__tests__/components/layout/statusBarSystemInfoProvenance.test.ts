import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import StatusBar from '@/components/layout/StatusBar.vue'
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
      copilotAvailable: ref(true),
      isChecking: ref(false),
      lastCheckTimestamp: ref(1770883200000),
      forceCheck: vi.fn(),
    }),
  }
})

describe('StatusBar system-info provenance', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('does not present default system-info values as current corpus truth', async () => {
    const settings = useSettingsStore()
    const wrapper = mount(StatusBar)

    expect(wrapper.text()).toContain('Systeminfo nicht geladen')
    expect(wrapper.text()).not.toContain('Kein Korpus geladen')
    expect(wrapper.text()).not.toContain('0 Tokens')

    settings.systemInfo = {
      backendVersion: '0.1.0',
      uptime: '1m',
      faissStatus: 'ready',
      vectorCount: 10,
      cacheSize: '1 MB',
      corpusName: 'fresh-demo',
      tokenCount: 12000,
      documentCount: 12,
    }
    settings.systemInfoProvenance = {
      freshness: 'fresh',
      source: 'backend',
      message: 'Systeminformationen wurden vom Backend geladen.',
    }
    await nextTick()

    expect(wrapper.text()).toContain('fresh-demo')
    expect(wrapper.text()).toMatch(/12[.,]000 Tokens/)
  })

  it('uses the active corpus catalogue summary before stale system-info defaults', async () => {
    const query = useQueryStore()
    query.setFilters({ corpus: 'default' })
    const corpus = useCorpusCapabilitiesStore()
    corpus.corpora = [{
      name: 'default',
      path: '/corpora/default',
      active: true,
      token_count: 56_191,
      doc_count: 2_000,
      import_mode: 'registered',
      paired: false,
      pair_axes: [],
      is_legacy: false,
      capabilities: {},
    }]
    const settings = useSettingsStore()
    settings.systemInfo = {
      backendVersion: '0.1.0',
      uptime: '',
      faissStatus: 'unavailable',
      vectorCount: 0,
      cacheSize: '0 MB',
      corpusName: 'Kein Korpus geladen',
      tokenCount: 0,
      documentCount: 0,
    }

    const wrapper = mount(StatusBar)

    expect(wrapper.text()).toContain('default')
    expect(wrapper.text()).toMatch(/56[.,]191 Tokens/)
    expect(wrapper.text()).not.toContain('Kein Korpus geladen')
    expect(wrapper.text()).not.toContain('0 Tokens')
  })
})
