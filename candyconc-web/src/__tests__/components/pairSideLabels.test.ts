/**
 * Paired imports from builder revision 2 on record the two sides of a pair in
 * text_type as anchor and version. Older paired imports and the human/AI
 * research layout record human and ai. The interface knew only the old
 * values: KWIC chips and the corpus evidence panel showed the raw value, the
 * document panel appended the anchor's role to its title, the copilot context
 * filtered on text_type human/ai, and every saved subcorpus carried the tags
 * "AI" and "Human", paired or not.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CorpusFeatureEvidence from '@/components/corpus/CorpusFeatureEvidence.vue'
import DocDetailDrawer from '@/components/search/DocDetailDrawer.vue'
import KwicTable from '@/components/search/KwicTable.vue'
import SubcorpusPanel from '@/components/search/SubcorpusPanel.vue'
import WorkspaceSubcorporaPanel from '@/components/workspace/WorkspaceSubcorporaPanel.vue'
import { useContextSnapshot } from '@/composables/useContextSnapshot'
import { applyLocale } from '@/i18n/locale'
import {
  isAnchorSide,
  isVersionSide,
  pairSideValues,
  pairSideValuesFromTextTypes,
  textTypeLabel,
} from '@/lib/pairSides'
import {
  useCorpusCapabilitiesStore,
  useDocsetStore,
  useProductCapabilitiesStore,
  useQueryStore,
  useSubcorporaStore,
  useUiStore,
} from '@/stores'
import type { CorpusSummary } from '@/api/client'
import type { KwicRow } from '@/stores/query'
import type { SubcorpusSnapshot } from '@/stores/subcorpora'

const documentMocks = vi.hoisted(() => ({
  loadDocument: vi.fn(),
  loadDocSnippet: vi.fn(),
}))

vi.mock('@/composables/useDocumentAccessOperations', () => ({
  useDocumentAccessOperations: () => ({
    loadDocument: documentMocks.loadDocument,
    loadDocSnippet: documentMocks.loadDocSnippet,
  }),
}))

vi.mock('@/composables/useParallelOperations', async () => {
  const { computed, ref } = await import('vue')
  const off = computed(() => false)
  const noReason = ref<string | null>(null)
  const availability = ref({ visible: false })
  return {
    useParallelOperations: () => ({
      groupsAvailability: availability,
      parallelKwicAvailability: availability,
      canLoadParallelGroups: off,
      canOpenAlignment: off,
      canLoadParallelKwic: off,
      parallelGroupsBlockReason: noReason,
      alignmentBlockReason: noReason,
      parallelKwicBlockReason: noReason,
      loadParallelGroups: vi.fn(),
      loadAlignmentRefDoc: vi.fn(),
      loadParallelKwic: vi.fn(),
    }),
  }
})

vi.mock('@tanstack/vue-virtual', () => ({
  useVirtualizer: (optionsRef: { value: { count: number } }) => ({
    value: {
      options: { estimateSize: () => 48 },
      getVirtualItems: () =>
        Array.from({ length: optionsRef.value.count }, (_, index) => ({ index, key: index, start: index * 48, size: 48 })),
      getTotalSize: () => optionsRef.value.count * 48,
      scrollToIndex: vi.fn(),
      measure: vi.fn(),
      measureElement: vi.fn(),
    },
  }),
}))

class TestResizeObserver {
  constructor(private callback: ResizeObserverCallback) {}
  observe() { this.callback([], this as unknown as ResizeObserver) }
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof TestResizeObserver }).ResizeObserver = TestResizeObserver
if (!('scrollIntoView' in HTMLElement.prototype)) {
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

function pairedSummary(anchorRole: 'anchor' | 'human', name = 'paired'): CorpusSummary {
  return {
    name,
    path: `/tmp/${name}`,
    active: true,
    token_count: 1200,
    doc_count: 12,
    import_mode: 'prealigned',
    paired: true,
    pair_axes: ['variant'],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      alignment: {
        paired: true,
        pair_axes: ['variant'],
        pairing_schema: {
          schema_id: 'legacy_ref_doc_v1',
          group_key_field: 'ref_doc',
          anchor_role_field: 'text_type',
          default_anchor_role: anchorRole,
          variant_axis_fields: ['variant'],
          legacy_variant_filter_field: 'model',
          generic_axis_filters: false,
        },
        parallel_groups: true,
        parallel_kwic: true,
      },
    },
  }
}

const wrappers: Array<ReturnType<typeof mount>> = []

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  applyLocale('de')
})

describe('pair side values', () => {
  it('reads both pairs of values', () => {
    for (const value of ['anchor', 'human', 'Human', ' anchor ']) expect(isAnchorSide(value)).toBe(true)
    for (const value of ['version', 'ai', 'AI']) expect(isVersionSide(value)).toBe(true)
    expect(isAnchorSide('standalone')).toBe(false)
    expect(isVersionSide('standalone')).toBe(false)
  })

  it('takes the values of a corpus from its pairing schema or its text types', () => {
    expect(pairSideValues(pairedSummary('anchor'))).toEqual({ anchor: 'anchor', version: 'version' })
    expect(pairSideValues(pairedSummary('human'))).toEqual({ anchor: 'human', version: 'ai' })
    expect(pairSideValues(null)).toEqual({ anchor: 'human', version: 'ai' })
    expect(pairSideValuesFromTextTypes(['anchor', 'version'])).toEqual({ anchor: 'anchor', version: 'version' })
    expect(pairSideValuesFromTextTypes(['ai', 'human'])).toEqual({ anchor: 'human', version: 'ai' })
  })

  it('labels anchor and version neutrally and keeps human and AI for their own values', () => {
    expect(['anchor', 'version', 'human', 'ai', 'standalone'].map(textTypeLabel)).toEqual(['Anker', 'Fassung', 'Mensch', 'KI', 'standalone'])
    applyLocale('en')
    expect(['anchor', 'version', 'human', 'ai', 'standalone'].map(textTypeLabel)).toEqual(['Anchor', 'Version', 'Human', 'AI', 'standalone'])
  })
})

describe('KWIC metadata chips', () => {
  function rows(): KwicRow[] {
    return [
      { position: 0, left: 'a', match: 'Hase', right: 'b', docId: 'doc0', metadata: { source: 'leicht', text_type: 'anchor', model: 'source' } },
      { position: 5, left: 'c', match: 'Hase', right: 'd', docId: 'doc1', metadata: { source: 'paired-sample', text_type: 'human', model: 'human' } },
    ]
  }

  it('names the side of a pair in the interface language', async () => {
    documentMocks.loadDocSnippet.mockRejectedValue(new Error('offline'))
    useUiStore().setActiveTab('kwic')
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(rows(), 2, true, false)
    const wrapper = mount(KwicTable, {
      global: {
        stubs: {
          Modal: { template: '<div><slot /></div>' },
          DocDetailDrawer: { template: '<div />' },
          AnnotationSchemeEditor: { template: '<div />' },
        },
      },
    })
    wrappers.push(wrapper)
    await flushPromises()
    for (const button of wrapper.findAll('button[title="Kontext erweitern"]')) await button.trigger('click')
    await flushPromises()
    const chips = wrapper.findAll('.meta-chip').map((chip) => chip.text())
    expect(chips).toContain('text_type: Anker')
    expect(chips).toContain('text_type: Mensch')
    expect(chips).not.toContain('text_type: anchor')
  })
})

describe('document panel title', () => {
  function mountDrawer() {
    const wrapper = mount(DocDetailDrawer, {
      props: { modelValue: true, docId: '0', highlight: '' },
      global: {
        stubs: {
          SlideOver: { props: ['title'], template: '<section :data-title="title"><slot /></section>' },
          ClipboardList: true,
          Columns2: true,
          AlignmentComparison: true,
        },
      },
    })
    wrappers.push(wrapper)
    return wrapper
  }

  it('gives the anchor of a pair no version suffix, old and new values alike', async () => {
    documentMocks.loadDocSnippet.mockResolvedValue(null)
    documentMocks.loadDocument.mockResolvedValue({
      doc_id: 0, doc: 'p1', text: 'Text', meta: { source: 'leicht', origin_id: 'leicht:p1', text_type: 'anchor', model: 'source' },
    })
    const anchor = mountDrawer()
    await flushPromises()
    expect(anchor.get('section').attributes('data-title')).toBe('leicht · p1')

    documentMocks.loadDocument.mockResolvedValue({
      doc_id: 1, doc: 'p1-easy', text: 'Text', meta: { source: 'leicht', origin_id: 'leicht:p1', text_type: 'version', model: 'easy' },
    })
    const version = mountDrawer()
    await flushPromises()
    expect(version.get('section').attributes('data-title')).toBe('leicht · p1 — easy')

    documentMocks.loadDocument.mockResolvedValue({
      doc_id: 2, doc: 'p2', text: 'Text', meta: { source: 'paired-sample', origin_id: 'paired-sample:p2', text_type: 'human', model: 'human' },
    })
    const human = mountDrawer()
    await flushPromises()
    expect(human.get('section').attributes('data-title')).toBe('paired-sample · p2')
  })
})

describe('corpus evidence panel', () => {
  it('names the default anchor role with its stored value', () => {
    const anchor = mount(CorpusFeatureEvidence, { props: { summary: pairedSummary('anchor') } })
    wrappers.push(anchor)
    expect(anchor.text()).toContain('Anker (anchor)')
    applyLocale('en')
    const human = mount(CorpusFeatureEvidence, { props: { summary: pairedSummary('human') } })
    wrappers.push(human)
    expect(human.text()).toContain('Human (human)')
  })
})

describe('copilot context filters', () => {
  it('filters on the side values the active corpus has', () => {
    useCorpusCapabilitiesStore().corpora = [pairedSummary('anchor')]
    useQueryStore().setFilters({ corpus: 'paired' })
    const docset = useDocsetStore()
    docset.setIncludeAi(false)
    const filters = useContextSnapshot().buildSnapshotSync().corpus.subcorpus.filters
    expect(filters).toContainEqual({ field: 'text_type', op: 'eq', value: 'anchor' })
    docset.setIncludeAi(true)
    docset.setIncludeHuman(false)
    expect(useContextSnapshot().buildSnapshotSync().corpus.subcorpus.filters)
      .toContainEqual({ field: 'text_type', op: 'eq', value: 'version' })
  })
})

describe('include switches of the paired filter tree', () => {
  it.each([
    ['anchor', 'Fassungen einbeziehen', 'Anker einbeziehen'],
    ['human', 'KI einbeziehen', 'Mensch einbeziehen'],
  ] as const)('names the sides of a corpus with %s anchors', async (anchorRole, versions, anchors) => {
    useCorpusCapabilitiesStore().corpora = [pairedSummary(anchorRole)]
    useQueryStore().setFilters({ corpus: 'paired' })
    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    wrappers.push(wrapper)
    await flushPromises()
    const labels = wrapper.findAll('.toggle-row label').map((label) => label.text())
    expect(labels).toEqual([versions, anchors])
  })
})

describe('saved subcorpora', () => {
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

  it('tags a subcorpus with a side only when it leaves the other side out', async () => {
    const product = useProductCapabilitiesStore()
    product.status = 'ready'
    product.contract = {
      version: 'product-capabilities-v1',
      scope: 'test',
      fingerprint_sha256: 'a'.repeat(64),
      cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
      capabilities: [],
    } as never
    useQueryStore().setFilters({ corpus: 'sotu_en' })
    useCorpusCapabilitiesStore().corpora = [
      { name: 'sotu_en', active: true, doc_count: 65, token_count: 403284, capabilities: {}, features: { alignment: { paired: false } } } as never,
      pairedSummary('anchor'),
    ]
    const subcorpora = useSubcorporaStore()
    vi.spyOn(subcorpora, 'init').mockResolvedValue()
    subcorpora.snapshots = [
      snapshot(),
      snapshot({ id: 'snap-2', name: 'Anker', corpus: 'paired', includeAi: false }),
    ]
    const wrapper = mount(WorkspaceSubcorporaPanel, { props: { active: true }, global: { stubs: { Modal: true } } })
    wrappers.push(wrapper)
    await flushPromises()
    const tags = wrapper.findAll('.snapshot-tags .tag').map((tag) => tag.text())
    expect(tags).not.toContain('KI')
    expect(tags).not.toContain('Mensch')
    expect(tags).toContain('Anker')
  })
})
