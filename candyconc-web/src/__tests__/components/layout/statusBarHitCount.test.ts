import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import StatusBar from '@/components/layout/StatusBar.vue'
import { useQueryStore } from '@/stores/query'

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

const rows = [
  { position: 1, left: 'the', match: 'freedom', right: 'of', docId: 'd1' },
  { position: 9, left: 'our', match: 'freedom', right: 'and', docId: 'd2' },
]

// erprobung B11: an exact count over a partly loaded window was shown as the
// lower bound "≥ 495 Treffer (partiell)".
describe('StatusBar hit count', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows an exact count as exact while only part of the rows is loaded', () => {
    const query = useQueryStore()
    query.setResults(rows, 495, true, true)
    const text = mount(StatusBar).text()
    expect(text).toMatch(/495 Treffer · 2 geladen/)
    expect(text).not.toContain('≥')
  })

  it('keeps the lower bound when the count itself is not exact', () => {
    const query = useQueryStore()
    query.setResults(rows, 495, false, true)
    expect(mount(StatusBar).text()).toContain('≥ 495 Treffer')
  })

  it('shows the plain count when every row is loaded', () => {
    const query = useQueryStore()
    query.setResults(rows, 2, true, false)
    const text = mount(StatusBar).text()
    expect(text).toContain('2 Treffer')
    expect(text).not.toContain('· 2 geladen')
  })
})
