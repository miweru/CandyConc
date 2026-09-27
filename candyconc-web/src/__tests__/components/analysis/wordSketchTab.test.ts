import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import WordSketchTab from '@/components/analysis/WordSketchTab.vue'
import { getWordSketch, getWordSketchDiff } from '@/api/client'
import { useCorpusCapabilitiesStore, useDocsetStore, useProductCapabilitiesStore, useSessionStore, useUiStore } from '@/stores'

const corpusFeatureMocks = vi.hoisted(() => ({ reasonOverride: undefined as string | null | undefined }))

// Pass-through, a test can replace the corpus feature reason.
vi.mock('@/lib/productCorpusFeatures', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/productCorpusFeatures')>()
  return {
    ...actual,
    corpusFeatureDecisionReason: (...args: Parameters<typeof actual.corpusFeatureDecisionReason>) =>
      corpusFeatureMocks.reasonOverride !== undefined
        ? corpusFeatureMocks.reasonOverride
        : actual.corpusFeatureDecisionReason(...args),
  }
})

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
    return {
      ...actual,
      getWordSketch: vi.fn(),
      getWordSketchDiff: vi.fn(),
    }
  })

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  Button: { emits: ['click'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  EmptyState: { props: ['description'], template: '<div class="empty-state">{{ description }}</div>' },
  JobStatusPill: { template: '<div />' },
  MethodPanel: { props: ['method'], template: '<div class="method-panel">{{ method?.family }}</div>' },
  SaveAnalysisButton: { template: '<div />' },
  Skeleton: { template: '<div />' },
}

function mountTab() {
  return mount(WordSketchTab, {
    global: { stubs },
  })
}

async function runSearch(wrapper: ReturnType<typeof mount>, term = 'alpha') {
  const input = wrapper.find('input.search-input')
  await input.setValue(term)
  await input.trigger('keyup.enter')
  await flushPromises()
}

function captureNextCsvDownload() {
  let blob: Blob | null = null
  let blobParts: BlobPart[] = []
  const OriginalBlob = globalThis.Blob
  class CapturingBlob extends OriginalBlob {
    constructor(parts?: BlobPart[], options?: BlobPropertyBag) {
      blobParts = parts ?? []
      super(parts, options)
    }
  }
  vi.stubGlobal('Blob', CapturingBlob)
  if (!('createObjectURL' in URL)) {
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
  }
  if (!('revokeObjectURL' in URL)) {
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
  }
  const createSpy = vi.spyOn(URL, 'createObjectURL').mockImplementation((nextBlob) => {
    blob = nextBlob as Blob
    return 'blob:wordsketch'
  })
  const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  return {
    createSpy,
    revokeSpy,
    async text() {
      expect(blob).not.toBeNull()
      return blobParts.map((part) => String(part)).join('')
    },
    restore() {
      vi.stubGlobal('Blob', OriginalBlob)
      createSpy.mockRestore()
      revokeSpy.mockRestore()
      clickSpy.mockRestore()
    },
  }
}

function activateDocset(dirty: boolean) {
  const docsetStore = useDocsetStore()
  docsetStore.activeDocsetId = 'docset-1'
  docsetStore.stats = { docCount: 2, hitDocCount: 2, refDocCount: 0, tokenCount: 100 }
  docsetStore.isDirty = dirty
}

function seedCorpusFeatures(canUseRel = true) {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: canUseRel ? { rel: true } : {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: canUseRel
        ? [{ id: 'rel', cql_attribute: 'rel', label: 'Relation' }]
        : [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
    },
  }]
  corpusCapabilities.loaded = true
}

function seedProductCapabilities() {
  const productCapabilities = useProductCapabilitiesStore()
  const wordSketchRoute = {
    path: '/api/v1/analysis/wordsketch',
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: ['token_attributes.rel'],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
  const wordSketchDiffRoute = {
    path: '/api/v1/analysis/wordsketch_diff',
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: ['token_attributes.rel'],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    capabilities: [
      {
        id: 'query.cqlf',
        title: 'CQLF',
        area: 'query',
        maturity: 'guarded',
          visibility: 'first_class_ui',
          backend_routes: [],
          backend_route_descriptors: [],
          operations: [],
          frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      {
        id: 'analysis.wordsketch',
          title: 'Word Sketch',
          area: 'analysis',
          maturity: 'guarded',
          visibility: 'first_class_ui',
          backend_routes: ['/api/v1/analysis/wordsketch', '/api/v1/analysis/wordsketch_diff'],
          backend_route_descriptors: [wordSketchRoute, wordSketchDiffRoute],
          operations: [
            {
              id: 'analysis.wordsketch.profile',
              capability_id: 'analysis.wordsketch',
              label: 'Word Sketch',
              description: '',
              route: wordSketchRoute,
              effects: ['read'],
              handler_key: 'word_sketch',
              surface_slot: 'analysis.wordsketch.profile',
              priority: 10,
            },
            {
              id: 'analysis.wordsketch.diff',
              capability_id: 'analysis.wordsketch',
              label: 'Word-Sketch-Vergleich',
              description: '',
              route: wordSketchDiffRoute,
              effects: ['read'],
              handler_key: 'word_sketch_diff',
              surface_slot: 'analysis.wordsketch.diff',
              priority: 20,
            },
          ],
          frontend_evidence: [],
        action_types: [],
        copilot_tools: ['word_sketch'],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
    ],
  }
  productCapabilities.status = 'ready'
}

function seedUserSession() {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'analyst',
    role: 'user',
    effective_role: 'user',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

describe('WordSketchTab docset scoping', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    ;(getWordSketch as Mock).mockReset()
    ;(getWordSketch as Mock).mockResolvedValue({ term: 'alpha', relations: [] })
    ;(getWordSketchDiff as Mock).mockReset()
    ;(getWordSketchDiff as Mock).mockResolvedValue({
      termA: 'alpha',
      termB: 'beta',
      relations: [],
      relationLabels: {},
    })
    seedCorpusFeatures(true)
    seedProductCapabilities()
    seedUserSession()
  })

  it('blocks scoped WordSketch requests when the active docset is dirty', async () => {
    activateDocset(true)
    const wrapper = mountTab()

    await runSearch(wrapper)

    expect(getWordSketch).not.toHaveBeenCalled()
    expect(useUiStore().toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Subkorpus ist veraltet'),
    })
    expect(wrapper.text()).toContain('Subkorpus ist veraltet')
  })

  it('sends the docset id for clean scoped WordSketch requests', async () => {
    activateDocset(false)
    const wrapper = mountTab()

    await runSearch(wrapper)

    expect(getWordSketch).toHaveBeenCalledWith(
      expect.objectContaining({ term: 'alpha', corpus: 'default', docsetId: 'docset-1' }),
      expect.any(Object)
    )
  })

  it('renders per-relation completeness metadata from the backend', async () => {
    ;(getWordSketch as Mock).mockResolvedValueOnce({
      term: 'alpha',
      relations: [{
        relation: 'sb_rev',
        rowLimit: 2,
        totalCandidates: 3,
        totalRows: 2,
        truncated: true,
        minFreq: 3,
        words: [
          { word: 'mag', score: 13.621488, frequency: 5 },
          { word: 'sieht', score: 8.1, frequency: 4 },
        ],
      }],
      relationLabels: { sb_rev: 'Subjekt von' },
      method: { family: 'wordsketch' },
    })
    const wrapper = mountTab()

    await runSearch(wrapper)

    expect(wrapper.text()).toContain('Subjekt von')
    expect(wrapper.text()).toContain('2 von 3 angezeigt')
    expect(wrapper.text()).toContain('gekappt')
    expect(wrapper.text()).toContain('13,621')
  })

  it('exports WordSketch CSV with relation completeness provenance', async () => {
    ;(getWordSketch as Mock).mockResolvedValueOnce({
      term: 'alpha',
      relations: [{
        relation: 'sb_rev',
        rowLimit: 2,
        totalCandidates: 3,
        totalRows: 2,
        truncated: true,
        minFreq: 3,
        words: [
          { word: 'mag', score: 13.6, frequency: 5 },
          { word: 'sieht', score: 8.1, frequency: 4 },
        ],
      }],
      relationLabels: { sb_rev: 'Subjekt von' },
      method: {
        family: 'wordsketch',
        default_sort: 'logdice',
        min_freq: 3,
        index_fingerprint: 'fp-ws',
      },
    })
    const download = captureNextCsvDownload()
    const wrapper = mountTab()

    await runSearch(wrapper)
    const csvButton = wrapper.findAll('button').find((button) => button.text().includes('CSV'))
    expect(csvButton).toBeTruthy()
    await csvButton!.trigger('click')

    expect(download.createSpy).toHaveBeenCalledOnce()
    expect(download.revokeSpy).toHaveBeenCalledWith('blob:wordsketch')
    const csv = await download.text()
    expect(csv).toContain('# Analysis: WordSketch')
    expect(csv).toContain('# Term: alpha')
    expect(csv).toContain('# Relation.sb_rev.label: Subjekt von')
    expect(csv).toContain('# Relation.sb_rev.total_candidates: 3')
    expect(csv).toContain('relation,label,word,frequency,score,row_limit,total_candidates,total_rows,truncated,min_freq')
    expect(csv).toContain('sb_rev,Subjekt von,mag,5,13.6000,2,3,2,true,3')
    download.restore()
  })

  it('allows dirty docsets only when Subkorpus scope is disabled', async () => {
    activateDocset(true)
    const wrapper = mountTab()
    // Target the Subkorpus-scope toggle specifically (the Vergleich/diff toggle
    // is also a checkbox now).
    await wrapper.find('[data-testid="scope-toggle"]').setValue(false)

    await runSearch(wrapper)

    expect(getWordSketch).toHaveBeenCalledWith(
      expect.objectContaining({ term: 'alpha', corpus: 'default', docsetId: undefined }),
      expect.any(Object)
    )
  })

  it('marks CQL WordSketch as first-token-anchored', async () => {
    const wrapper = mountTab()
    const query = 'cql:[lemma="gehen"] [pos="NOUN"]'

    await runSearch(wrapper, query)

    expect(wrapper.text()).toContain('CQL-WordSketch ist eingeschränkt')
    expect(wrapper.text()).toContain('first-token-anchored')
    expect(getWordSketch).toHaveBeenCalledWith(
      expect.objectContaining({ term: query, corpus: 'default' }),
      expect.any(Object)
    )
  })

  it('blocks WordSketch requests when the active corpus lacks relation attributes', async () => {
    seedCorpusFeatures(false)
    const wrapper = mountTab()

    await runSearch(wrapper)

    expect(getWordSketch).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Tokenattribut rel')
  })

  it('shows the rel attribute of the fallback message as code, not in raw backticks', async () => {
    seedCorpusFeatures(false)
    corpusFeatureMocks.reasonOverride = null
    try {
      const wrapper = mountTab()
      await flushPromises()
      const warning = wrapper.findAll('.method-warning').find((node) => node.text().includes('Word Sketch'))
      expect(warning).toBeTruthy()
      expect(warning!.text()).not.toContain('`')
      expect(warning!.find('code').text()).toBe('rel')
    } finally {
      corpusFeatureMocks.reasonOverride = undefined
    }
  })

  it('does not disable the input permanently while corpus capabilities are still unknown', () => {
    const corpusCapabilities = useCorpusCapabilitiesStore()
    corpusCapabilities.loaded = false
    corpusCapabilities.corpora = []

    const wrapper = mountTab()

    expect(wrapper.find('input.search-input').attributes('disabled')).toBeUndefined()
  })

  it('consumes the WordSketch profile ProductOperation as the profile input focus', async () => {
    const uiStore = useUiStore()
    uiStore.focusProductOperation('analysis.wordsketch.profile', {
      capabilityId: 'analysis.wordsketch',
      surfaceSlot: 'analysis.wordsketch.profile',
      preferredMode: 'profile',
    })

    const wrapper = mountTab()
    await flushPromises()

    expect((wrapper.find('[data-testid="diff-toggle"]').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find('.search-wrapper').classes()).toContain('operation-focused')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('consumes the WordSketch diff ProductOperation as comparison mode', async () => {
    const uiStore = useUiStore()
    uiStore.focusProductOperation('analysis.wordsketch.diff', {
      capabilityId: 'analysis.wordsketch',
      surfaceSlot: 'analysis.wordsketch.diff',
      preferredMode: 'diff',
    })

    const wrapper = mountTab()
    await flushPromises()

    const diffToggle = wrapper.find('[data-testid="diff-toggle"]')
    expect((diffToggle.element as HTMLInputElement).checked).toBe(true)
    expect(diffToggle.element.closest('label')?.classList.contains('operation-focused')).toBe(true)
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('blocks Sketch-Diff requests when the active docset is dirty', async () => {
    activateDocset(true)
    const wrapper = mountTab()
    await wrapper.find('[data-testid="diff-toggle"]').setValue(true)
    const inputs = wrapper.findAll('input.search-input')
    await inputs[0].setValue('alpha')
    await inputs[1].setValue('beta')
    await inputs[1].trigger('keyup.enter')
    await flushPromises()

    expect(getWordSketchDiff).not.toHaveBeenCalled()
    expect(useUiStore().toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Subkorpus ist veraltet'),
    })
  })

  it('renders Sketch-Diff relation labels and method provenance', async () => {
    ;(getWordSketchDiff as Mock).mockResolvedValueOnce({
      termA: 'alpha',
      termB: 'beta',
      relations: [{
        relation: 'obj',
        onlyA: [{ word: 'a-only', score: 3, frequency: 7 }],
        onlyB: [],
        common: [{ word: 'shared', scoreA: 4, scoreB: 2, frequencyA: 5, frequencyB: 9, delta: 2 }],
      }],
      relationLabels: { obj: 'Objekt von' },
      method: { family: 'wordsketch' },
    })
    const wrapper = mountTab()
    await wrapper.find('[data-testid="diff-toggle"]').setValue(true)
    await flushPromises()
    const inputs = wrapper.findAll('input.search-input')
    await inputs[0].setValue('alpha')
    await inputs[1].setValue('beta')
    await inputs[1].trigger('keyup.enter')
    await flushPromises()

    expect(wrapper.text()).toContain('Objekt von')
    expect(wrapper.text()).toContain('Top 30 je Gruppe und Relation')
    expect(getWordSketchDiff).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 30 }), expect.any(Object),
    )
    expect(wrapper.text()).toContain('f alpha')
    expect(wrapper.text()).toContain('f beta')
    expect(wrapper.text()).toContain('f=7')
    expect(wrapper.text()).toContain('5')
    expect(wrapper.text()).toContain('9')
    expect(wrapper.find('.method-panel').text()).toContain('wordsketch')
  })
})
