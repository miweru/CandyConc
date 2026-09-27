/**
 * The corpus switcher and the status bar show a corpus by its display name.
 *
 * The corpus pinned with CANDYCONC_INDEX_PATH has the identifier "default",
 * which the routes, docsets and caches use as a key. The server sends the
 * directory name as display_name. The interface showed "default" (erprobung B4).
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CorpusSwitcher from '@/components/layout/CorpusSwitcher.vue'
import StatusBar from '@/components/layout/StatusBar.vue'
import EmbeddingsManager from '@/components/settings/EmbeddingsManager.vue'
import { coerceCorpusSummary } from '@/api/client'
import { corpusDisplayName } from '@/lib/corpusDisplayName'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'

vi.mock('@/components/ui/Dropdown.vue', () => ({
  default: { template: '<div><slot name="trigger" /><slot /></div>' },
}))

vi.mock('@/components/ui/DropdownItem.vue', () => ({
  default: {
    props: ['disabled'],
    emits: ['click'],
    template: '<button class="dropdown-item" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
}))

function seed() {
  setActivePinia(createPinia())
  const product = useProductCapabilitiesStore()
  product.status = 'ready'
  product.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [],
  } as any
  product.ensureAccessContext = vi.fn(async () => {}) as any
  // Catalogue and activation enabled: the switcher lists the corpora.
  product.productOperationAvailability = vi.fn(() => ({ enabled: true, visible: true, disabledReason: null })) as any
  useQueryStore().setFilters({ corpus: 'default' })
  const corpora = useCorpusCapabilitiesStore()
  corpora.loaded = true
  corpora.corpora = [
    coerceCorpusSummary({ name: 'default', display_name: 'sotu_en', path: '/c/sotu_en', token_count: 403284, doc_count: 65, active: true }),
    coerceCorpusSummary({ name: 'dta_de', path: '/c/dta_de', token_count: 624227, doc_count: 30 }),
  ]
}

describe('corpus display name', () => {
  beforeEach(seed)

  it('keeps display_name from the catalogue and falls back to the identifier', () => {
    const [pinned, registered] = useCorpusCapabilitiesStore().corpora
    expect(pinned?.display_name).toBe('sotu_en')
    expect(corpusDisplayName(pinned)).toBe('sotu_en')
    expect(corpusDisplayName(registered)).toBe('dta_de')
    expect(coerceCorpusSummary({ name: 'x', display_name: '  ' }).display_name).toBeUndefined()
    expect(useCorpusCapabilitiesStore().activeDisplayName).toBe('sotu_en')
  })

  it('switcher: shows the display name, lists both corpora by their names to show', async () => {
    const wrapper = mount(CorpusSwitcher)
    await flushPromises()
    expect(wrapper.text()).toContain('sotu_en')
    expect(wrapper.findAll('.corpus-item-name').map((node) => node.text())).toEqual(['sotu_en', 'dta_de'])
    expect(wrapper.text()).not.toMatch(/\bdefault\b/)
  })

  it('status bar: shows the display name of the active corpus', async () => {
    const wrapper = mount(StatusBar)
    await flushPromises()
    expect(wrapper.text()).toContain('sotu_en')
    expect(wrapper.text()).not.toMatch(/\bdefault\b/)
  })

  it('embedding settings: name the corpus of the local index by its display name', async () => {
    const wrapper = mount(EmbeddingsManager, { global: { stubs: { LoadingSpinner: true } } })
    await flushPromises()
    const header = wrapper.get('[data-testid="local-semantic-index"] .local-index-heading').text()
    expect(header).toContain('sotu_en')
    expect(header).not.toMatch(/\bdefault\b/)
  })
})
