import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import KwicTable from '@/components/search/KwicTable.vue'
import { actionBus } from '@/actions'
import { executeSampledQuery } from '@/api/client'
import { useDocsetStore } from '@/stores/docset'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import type { KwicRow } from '@/stores/query'

/**
 * KWIC-Zufallsstichprobe (Messlatte S3, T1):
 *  - Aktivieren zieht eine Stichprobe mit sample+seed (Seed sichtbar, Pflicht).
 *  - Provenienz-Chip 'Stichprobe N von TOTAL · Seed S' speist sich NUR aus der
 *    Server-Provenienz (X-CandyConc-Sample) — nie fabriziert.
 *  - Deaktivieren lädt die Vollmenge über den regulären query/execute-Pfad.
 *  - Aktives Subkorpus nutzt den docset-fähigen Stream (GET /query kennt kein
 *    docset_id) mit gespiegelten sample/seed-Parametern.
 */

const apiMocks = vi.hoisted(() => ({
  executeSampledQuery: vi.fn(),
}))

const queryOperationMocks = vi.hoisted(() => ({
  executeKwicPage: vi.fn(),
  streamKwic: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    executeSampledQuery: apiMocks.executeSampledQuery,
  }
})

vi.mock('@/composables/useQueryOperations', () => ({
  useQueryOperations: () => ({
    executeKwicPage: queryOperationMocks.executeKwicPage,
    streamKwic: queryOperationMocks.streamKwic,
  }),
}))

const parallelOperationMocks = vi.hoisted(() => ({
  loadParallelKwic: vi.fn(),
}))

vi.mock('@/composables/useParallelOperations', async () => {
  const { computed, ref } = await import('vue')
  const ready = computed(() => false)
  const noReason = ref<string | null>(null)
  const availability = ref({ visible: false })
  return {
    useParallelOperations: () => ({
      groupsAvailability: availability,
      parallelKwicAvailability: availability,
      canLoadParallelGroups: ready,
      canOpenAlignment: ready,
      canLoadParallelKwic: ready,
      parallelGroupsBlockReason: noReason,
      alignmentBlockReason: noReason,
      parallelKwicBlockReason: noReason,
      loadParallelGroups: vi.fn(),
      loadAlignmentRefDoc: vi.fn(),
      loadParallelKwic: parallelOperationMocks.loadParallelKwic,
    }),
  }
})

vi.mock('@tanstack/vue-virtual', () => ({
  useVirtualizer: (optionsRef: { value: { count: number } }) => ({
    value: {
      options: { estimateSize: () => 48 },
      getVirtualItems: () =>
        Array.from({ length: optionsRef.value.count }, (_, index) => ({
          index,
          key: index,
          start: index * 48,
          size: 48,
        })),
      getTotalSize: () => optionsRef.value.count * 48,
      scrollToIndex: vi.fn(),
      measure: vi.fn(),
      measureElement: vi.fn(),
    },
  }),
}))

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof TestResizeObserver }).ResizeObserver =
  TestResizeObserver

if (!('scrollIntoView' in HTMLElement.prototype)) {
  // @ts-expect-error test environment shim
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

const mountedWrappers: Array<ReturnType<typeof mount>> = []
afterEach(() => {
  while (mountedWrappers.length) mountedWrappers.pop()?.unmount()
  vi.restoreAllMocks()
})

function makeRows(n: number): KwicRow[] {
  return Array.from({ length: n }, (_, i) => ({
    position: i,
    left: `left ${i}`,
    match: `match ${i}`,
    right: `right ${i}`,
    docId: `doc${i}`,
  }))
}

const PROVENANCE = {
  requested: 50,
  drawn: 50,
  seed: 42,
  population: 9740,
  populationPartial: false,
}

function sampledResult() {
  return {
    hits: Array.from({ length: 3 }, (_, i) => ({
      position: i * 10,
      left: `s-left ${i}`,
      match: `s-match ${i}`,
      right: `s-right ${i}`,
      doc_id: `sdoc${i}`,
    })),
    total: 50,
    query_time_ms: 5,
    next_offset: null,
    truncated: false,
    sortApproximate: false,
    sample: PROVENANCE,
  }
}

function mountTable() {
  const wrapper = mount(KwicTable, {
    global: {
      stubs: {
        Modal: { template: '<div><slot /></div>' },
        AnnotationSchemeEditor: { template: '<div />' },
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('KWIC random sample control (T1)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
    apiMocks.executeSampledQuery.mockReset()
    queryOperationMocks.executeKwicPage.mockReset()
    queryOperationMocks.streamKwic.mockReset()
  })

  it('activating the toggle draws a seeded sample and shows the provenance chip', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Haus')
    queryStore.setResults(makeRows(4), 4, true, false)
    queryStore.sampleSize = 50
    queryStore.sampleSeed = 42
    apiMocks.executeSampledQuery.mockResolvedValue(sampledResult())

    const wrapper = mountTable()
    await flushPromises()
    expect(wrapper.find('[data-testid="kwic-sample-chip"]').exists()).toBe(false)

    await wrapper.find('[data-testid="kwic-sample-toggle"]').trigger('change')
    await flushPromises()

    expect(executeSampledQuery as Mock).toHaveBeenCalledTimes(1)
    const [params] = apiMocks.executeSampledQuery.mock.calls[0]
    expect(params).toMatchObject({ term: 'Haus', sample: 50, seed: 42 })

    // Ergebnisse ersetzt, Server-Provenienz übernommen, Chip sichtbar.
    expect(queryStore.results).toHaveLength(3)
    expect(queryStore.sampleProvenance).toEqual(PROVENANCE)
    const chip = wrapper.find('[data-testid="kwic-sample-chip"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('Stichprobe 50 von 9.740')
    expect(chip.text()).toContain('Seed 42')

    // Seed-Feld bleibt sichtbar und trägt den Wert (Reproduzierbarkeit).
    const seedInput = wrapper.find('[data-testid="kwic-sample-seed"]')
    expect(seedInput.exists()).toBe(true)
    expect((seedInput.element as HTMLInputElement).value).toBe('42')
  })

  it('activation without a stored seed prefills a random seed before drawing', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Haus')
    queryStore.sampleSeed = null
    apiMocks.executeSampledQuery.mockResolvedValue(sampledResult())

    const wrapper = mountTable()
    await wrapper.find('[data-testid="kwic-sample-toggle"]').trigger('change')
    await flushPromises()

    expect(queryStore.sampleSeed).not.toBeNull()
    expect(queryStore.sampleSeed).toBeGreaterThanOrEqual(0)
    const [params] = apiMocks.executeSampledQuery.mock.calls[0]
    expect(params.seed).toBe(queryStore.sampleSeed)
  })

  it('refuses to draw without a seed (Pflichtfeld) instead of sending an implicit one', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Haus')
    queryStore.setSampleConfig(true)
    queryStore.sampleSeed = null

    const wrapper = mountTable()
    await flushPromises()
    await wrapper.find('[data-testid="kwic-sample-draw"]').trigger('click')
    await flushPromises()

    expect(apiMocks.executeSampledQuery).not.toHaveBeenCalled()
    expect(queryOperationMocks.streamKwic).not.toHaveBeenCalled()
  })

  it('drops a server result without provenance instead of fabricating a sample', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Haus')
    queryStore.setResults(makeRows(4), 4, true, false)
    queryStore.sampleSeed = 7
    apiMocks.executeSampledQuery.mockResolvedValue({ ...sampledResult(), sample: null })

    const wrapper = mountTable()
    await wrapper.find('[data-testid="kwic-sample-toggle"]').trigger('change')
    await flushPromises()

    // Alte Vollmenge bleibt stehen; kein Chip, keine Provenienz.
    expect(queryStore.results).toHaveLength(4)
    expect(queryStore.sampleProvenance).toBeNull()
    expect(wrapper.find('[data-testid="kwic-sample-chip"]').exists()).toBe(false)
  })

  it('deactivating reloads the full result set via query/execute', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Haus')
    queryStore.setSampleConfig(true, 50, 42)
    queryStore.setResults(makeRows(3), 3, true, false)
    queryStore.setSampleProvenance(PROVENANCE)
    const dispatchSpy = vi
      .spyOn(actionBus, 'dispatch')
      .mockResolvedValue({ ok: true } as never)

    const wrapper = mountTable()
    await flushPromises()
    expect(wrapper.find('[data-testid="kwic-sample-chip"]').exists()).toBe(true)

    await wrapper.find('[data-testid="kwic-sample-toggle"]').trigger('change')
    await flushPromises()

    expect(queryStore.sampleActive).toBe(false)
    expect(queryStore.sampleProvenance).toBeNull()
    const executeCall = dispatchSpy.mock.calls.find(
      ([action]) => (action as { type?: string }).type === 'query/execute'
    )
    expect(executeCall).toBeTruthy()
    expect((executeCall?.[0] as { payload?: { term?: string } }).payload?.term).toBe('Haus')
  })

  it('samples an active docset through the docset-capable stream with sample+seed', async () => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    queryStore.setTerm('Haus')
    queryStore.sampleSize = 25
    queryStore.sampleSeed = 9
    docsetStore.activeDocsetId = 'ds1'

    const docsetProvenance = { ...PROVENANCE, requested: 25, drawn: 25, seed: 9, population: 120 }
    queryOperationMocks.streamKwic.mockImplementation(async function* () {
      yield {
        type: 'batch',
        hits: [
          { position: 1, left: 'l', match: 'm', right: 'r', doc_id: 'd1' },
        ],
      }
      yield { type: 'done', total: 25, sample: docsetProvenance }
    })

    const wrapper = mountTable()
    await wrapper.find('[data-testid="kwic-sample-toggle"]').trigger('change')
    await flushPromises()

    expect(apiMocks.executeSampledQuery).not.toHaveBeenCalled()
    expect(queryOperationMocks.streamKwic).toHaveBeenCalledTimes(1)
    const [streamParams] = queryOperationMocks.streamKwic.mock.calls[0]
    expect(streamParams).toMatchObject({
      term: 'Haus',
      docsetId: 'ds1',
      sample: 25,
      seed: 9,
    })
    expect(queryStore.sampleProvenance).toEqual(docsetProvenance)
    expect(wrapper.find('[data-testid="kwic-sample-chip"]').text()).toContain('Seed 9')
  })
})
