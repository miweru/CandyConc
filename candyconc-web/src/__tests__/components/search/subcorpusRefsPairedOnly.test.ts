/**
 * Reference documents exist only in paired corpora. The subcorpus panel and
 * the workspace listed "0 refs" for every subcorpus of an unpaired corpus,
 * a count of something the corpus cannot have.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SubcorpusPanel from '@/components/search/SubcorpusPanel.vue'
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
import type { SubcorpusSnapshot } from '@/stores/subcorpora'

vi.mock('@/actions/bus', () => ({
  actionBus: { dispatch: vi.fn(async () => ({ success: true })) },
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(async () => { throw new Error('offline') }),
    getAuthSession: vi.fn(async () => { throw new Error('offline') }),
    getMcpTools: vi.fn(async () => ({ tools: [] })),
    getMetaSchema: vi.fn(async () => ({ metadataSchemaHash: 'fp', metadataFields: [] })),
    getMetaValues: vi.fn(async () => ({})),
    getMetaCounts: vi.fn(async () => ({})),
    listSubcorpora: vi.fn(async () => []),
    updatePrefs: vi.fn(async () => ({ ok: true })),
  }
})

async function seed(paired: boolean) {
  setActivePinia(createPinia())
  // The settings store owns the language, a panel that reads it would reset it otherwise.
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
  useQueryStore().setFilters({ corpus: 'sotu_en' })
  useCorpusCapabilitiesStore().corpora = [{
    name: 'sotu_en',
    active: true,
    doc_count: 65,
    token_count: 403284,
    capabilities: {},
    features: { alignment: { paired, parallel_groups: paired, parallel_kwic: paired, pair_axes: [] } },
  } as any]
  const docset = useDocsetStore()
  docset.activeDocsetId = 'meta-scope'
  docset.stats = { docCount: 36, hitDocCount: 0, refDocCount: paired ? 12 : 0, tokenCount: 199379 }
}

function snapshot(overrides: Partial<SubcorpusSnapshot> = {}): SubcorpusSnapshot {
  return {
    id: 'snap-1',
    name: 'Republican',
    status: 'parked',
    createdAt: Date.UTC(2026, 8, 26, 12, 0, 0),
    corpus: 'sotu_en',
    stats: { docCount: 36, tokenCount: 199379, refDocCount: 0 },
    statsResolved: true,
    filters: { prompting_method: [], model: [], register: [], source: [] },
    includeAi: true,
    includeHuman: true,
    origin: { type: 'filter' },
    resolution: { status: 'fresh', stale: false, resolvedAt: Date.UTC(2026, 8, 26, 12, 5, 0) },
    ...overrides,
  }
}

const wrappers: Array<ReturnType<typeof mount>> = []

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  applyLocale('de')
})

describe('reference documents only for paired corpora', () => {
  it('subcorpus panel: no refs for an unpaired corpus', async () => {
    await seed(false)
    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    wrappers.push(wrapper)
    await flushPromises()
    const status = wrapper.get('.status-text').text()
    expect(status).toBe('36 docs · 199,379 tokens')
  })

  it('subcorpus panel: refs for a paired corpus', async () => {
    await seed(true)
    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.get('.status-text').text()).toBe('36 docs · 199,379 tokens · 12 refs')
  })

  it('workspace: no refs for the active scope and the saved subcorpora of an unpaired corpus', async () => {
    await seed(false)
    const subcorpora = useSubcorporaStore()
    vi.spyOn(subcorpora, 'init').mockResolvedValue()
    subcorpora.snapshots = [snapshot()]
    const wrapper = mount(WorkspaceSubcorporaPanel, {
      props: { active: true },
      global: { stubs: { Modal: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()
    const text = wrapper.text()
    expect(wrapper.get('.scope-stats').text()).toBe('36 docs · 199,379 tokens')
    expect(text).toContain('36 docs · 199,379 tokens ·')
    expect(text).not.toContain('refs')
    expect(text).not.toContain('reference documents')
  })

  it('workspace: refs for a paired corpus', async () => {
    await seed(true)
    const subcorpora = useSubcorporaStore()
    vi.spyOn(subcorpora, 'init').mockResolvedValue()
    subcorpora.snapshots = [snapshot({ stats: { docCount: 36, tokenCount: 199379, refDocCount: 12 } })]
    const wrapper = mount(WorkspaceSubcorporaPanel, {
      props: { active: true },
      global: { stubs: { Modal: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.get('.scope-stats').text()).toBe('36 docs · 199,379 tokens · 12 reference documents')
    expect(wrapper.text()).toContain('36 docs · 199,379 tokens · 12 refs')
  })
})
