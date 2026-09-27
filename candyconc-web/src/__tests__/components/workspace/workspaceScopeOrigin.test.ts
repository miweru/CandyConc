/**
 * The workspace describes the active scope by how it was built.
 *
 * Before, the origin line read the live search box: a scope built from a
 * metadata filter was labelled "Source: query “freedom”" as soon as the
 * search box held "freedom". ScopeHeader, the saved snapshot and the name
 * suggestion already followed the build origin (SUBC-01).
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import WorkspaceSubcorporaPanel from '@/components/workspace/WorkspaceSubcorporaPanel.vue'
import { applyLocale } from '@/i18n/locale'
import {
  useCorpusCapabilitiesStore,
  useDocsetStore,
  useProductCapabilitiesStore,
  useQueryStore,
  useSubcorporaStore,
} from '@/stores'
import { useSettingsStore } from '@/stores/settings'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(async () => { throw new Error('offline') }),
    getAuthSession: vi.fn(async () => { throw new Error('offline') }),
    getMcpTools: vi.fn(async () => ({ tools: [] })),
    listSubcorpora: vi.fn(async () => []),
    updatePrefs: vi.fn(async () => ({ ok: true })),
  }
})

async function mountWith(origin: { kind: 'search'; query: string } | { kind: 'meta' } | null) {
  setActivePinia(createPinia())
  await useSettingsStore().setLanguage('en')
  const product = useProductCapabilitiesStore()
  product.status = 'ready'
  product.contract = {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [],
  } as any
  const query = useQueryStore()
  query.setFilters({ corpus: 'sotu_en' })
  // The search box holds a term that did not build the scope.
  query.setTerm('freedom')
  useCorpusCapabilitiesStore().corpora = [{
    name: 'sotu_en', active: true, doc_count: 65, token_count: 403284, capabilities: {},
    features: { alignment: { paired: false, parallel_groups: false, parallel_kwic: false, pair_axes: [] } },
  } as any]
  const docset = useDocsetStore()
  docset.activeDocsetId = 'scope-1'
  docset.stats = { docCount: 36, hitDocCount: 0, refDocCount: 0, tokenCount: 199379 }
  docset.activeDocsetOrigin = origin
  const subcorpora = useSubcorporaStore()
  vi.spyOn(subcorpora, 'init').mockResolvedValue()
  const wrapper = mount(WorkspaceSubcorporaPanel, {
    props: { active: true },
    global: { stubs: { Modal: true } },
  })
  await flushPromises()
  return wrapper
}

const wrappers: Array<ReturnType<typeof mount>> = []

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  applyLocale('de')
})

describe('workspace scope origin', () => {
  it('names a metadata scope a filter, whatever the search box holds', async () => {
    const wrapper = await mountWith({ kind: 'meta' })
    wrappers.push(wrapper)
    expect(wrapper.get('.scope-origin').text()).toBe('Source: filter')
  })

  it('names the query that built a search scope, not the current search box', async () => {
    const wrapper = await mountWith({ kind: 'search', query: 'liberty' })
    wrappers.push(wrapper)
    expect(wrapper.get('.scope-origin').text()).toBe('Source: query “liberty”')
  })

  it('names a scope of unknown origin a subcorpus', async () => {
    const wrapper = await mountWith(null)
    wrappers.push(wrapper)
    expect(wrapper.get('.scope-origin').text()).toBe('Source: subcorpus')
  })
})
