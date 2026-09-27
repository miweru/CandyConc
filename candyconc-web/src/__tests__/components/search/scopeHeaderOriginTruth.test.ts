/**
 * BLOCKER d (SUBC origin label) — the always-visible scope chip and its details
 * line must label a subcorpus by HOW IT WAS BUILT, not by whatever is currently
 * typed in the search box.
 *
 * Repro: commit a search for 'und', then build a metadata (split=test)
 * subcorpus. The docset origin is `{ kind: 'meta' }`, but queryStore.term still
 * holds 'und'. Before the fix ScopeHeader.suggestName()/originLabel read
 * queryStore.term, so the 683-doc metadata scope was mislabelled "Query und" /
 * "Query: und". After the fix the provenance comes from activeDocsetOrigin: a
 * meta scope reads its FILTER provenance, never the stale term.
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import ScopeHeader from '@/components/search/ScopeHeader.vue'
import { useDocsetStore } from '@/stores/docset'
import { useUiStore } from '@/stores/ui'
import { useQueryStore } from '@/stores/query'

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

const stubs = {
  Dropdown: { template: '<div><slot name="trigger" /><slot /></div>' },
  DropdownItem: { template: '<button type="button"><slot /></button>' },
}

describe('ScopeHeader subcorpus origin truth', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('labels a metadata-built subcorpus by its filter provenance, not the stale search term', async () => {
    // A previously committed (now unrelated) search term lingers in the box.
    const queryStore = useQueryStore()
    queryStore.setTerm('und')

    // A metadata (split=test) subcorpus is the ACTIVE scope.
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-meta'
    docsetStore.activeDocsetOrigin = { kind: 'meta' }
    docsetStore.activeFilterSpec = { split: { op: 'eq', value: 'test' } }
    docsetStore.stats = { docCount: 683, hitDocCount: 0, refDocCount: 0, tokenCount: 12_345 }

    const wrapper = mount(ScopeHeader, { global: { stubs } })

    // The always-visible chip must NOT bake the stale term into the name.
    expect(wrapper.text()).not.toContain('Query und')

    // The details line shows FILTER provenance, never "Query: und".
    await wrapper.find('button[title="Details einblenden"]').trigger('click')
    expect(wrapper.text()).not.toContain('Query: und')
    expect(wrapper.text()).toContain('Filter')
  })

  it('still labels a search-built subcorpus by its real build query', async () => {
    const queryStore = useQueryStore()
    // The live box may hold something else entirely; provenance is the BUILD query.
    queryStore.setTerm('etwas anderes')

    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-search'
    docsetStore.activeDocsetOrigin = { kind: 'search', query: 'Haus' }
    docsetStore.stats = { docCount: 10, hitDocCount: 10, refDocCount: 0, tokenCount: 200 }

    const wrapper = mount(ScopeHeader, { global: { stubs } })
    await wrapper.find('button[title="Details einblenden"]').trigger('click')

    expect(wrapper.text()).toContain('Query: Haus')
    expect(wrapper.text()).not.toContain('etwas anderes')
  })

  it('makes the current register scope visible and opens its existing editor from the compact workbar', async () => {
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-register'
    docsetStore.filters.register = ['Presse']
    docsetStore.activeFilterSpec = { register: ['Presse'] }

    const wrapper = mount(ScopeHeader, {
      props: { inline: true, minimal: true },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('Suchbereich')
    expect(wrapper.text()).toContain('Register: Presse')

    await wrapper.get('.scope-chip-button').trigger('click')
    expect(useUiStore().subcorpusOpen).toBe(true)
  })
})
