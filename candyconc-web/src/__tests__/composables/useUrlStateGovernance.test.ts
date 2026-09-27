import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'

const mocks = vi.hoisted(() => {
  const queryStore = {
    term: '',
    filters: {} as Record<string, unknown>,
    contextSize: 200,
    setTerm: vi.fn((term: string) => {
      queryStore.term = term
    }),
    setFilters: vi.fn((filters: Record<string, unknown>) => {
      queryStore.filters = { ...queryStore.filters, ...filters }
    }),
  }

  const uiStore = {
    activeTab: 'kwic',
    setActiveTab: vi.fn((tab: string) => {
      uiStore.activeTab = tab
    }),
    showToast: vi.fn(),
  }

  const docsetStore = {
    filters: {
      prompting_method: [] as string[],
      model: [] as string[],
      register: [] as string[],
      source: [] as string[],
    },
    includeAi: true,
    includeHuman: true,
    activeDocsetId: null as string | null,
    filtersActive: false,
    clearFilters: vi.fn(() => {
      docsetStore.filters = {
        prompting_method: [],
        model: [],
        register: [],
        source: [],
      }
      docsetStore.includeAi = true
      docsetStore.includeHuman = true
      docsetStore.filtersActive = false
    }),
    setIncludeAi: vi.fn((value: boolean) => {
      docsetStore.includeAi = value
      docsetStore.filtersActive = docsetStore.filtersActive || !value
    }),
    setIncludeHuman: vi.fn((value: boolean) => {
      docsetStore.includeHuman = value
      docsetStore.filtersActive = docsetStore.filtersActive || !value
    }),
    setFilter: vi.fn((
      field: 'prompting_method' | 'model' | 'register' | 'source',
      values: string[]
    ) => {
      docsetStore.filters[field] = values
      docsetStore.filtersActive = docsetStore.filtersActive || values.length > 0
    }),
    buildDocset: vi.fn(async () => true),
  }

  const subcorporaStore = {
    snapshots: [] as Array<{
      id: string
      corpus: string
      filters: {
        prompting_method: string[]
        model: string[]
        register: string[]
        source: string[]
      }
      includeAi: boolean
      includeHuman: boolean
      origin: { query?: string }
    }>,
    initialized: false,
    init: vi.fn(() => {
      subcorporaStore.initialized = true
    }),
  }

  const productCapabilitiesStore = {
    hasContract: true,
    ensureAccessContext: vi.fn(async () => null),
    isVisible: vi.fn(() => true),
  }

  return {
    dispatch: vi.fn(),
    queryStore,
    uiStore,
    docsetStore,
    subcorporaStore,
    productCapabilitiesStore,
    resetStores: () => {
      queryStore.term = ''
      queryStore.filters = {}
      queryStore.contextSize = 200
      queryStore.setTerm.mockClear()
      queryStore.setFilters.mockClear()

      uiStore.activeTab = 'kwic'
      uiStore.setActiveTab.mockClear()
      uiStore.showToast.mockClear()

      docsetStore.filters = {
        prompting_method: [],
        model: [],
        register: [],
        source: [],
      }
      docsetStore.includeAi = true
      docsetStore.includeHuman = true
      docsetStore.activeDocsetId = null
      docsetStore.filtersActive = false
      docsetStore.clearFilters.mockClear()
      docsetStore.setIncludeAi.mockClear()
      docsetStore.setIncludeHuman.mockClear()
      docsetStore.setFilter.mockClear()
      docsetStore.buildDocset.mockClear()

      subcorporaStore.snapshots = []
      subcorporaStore.initialized = false
      subcorporaStore.init.mockClear()

      productCapabilitiesStore.hasContract = true
      productCapabilitiesStore.ensureAccessContext.mockClear()
      productCapabilitiesStore.isVisible.mockReset()
      productCapabilitiesStore.isVisible.mockReturnValue(true)
    },
  }
})

vi.mock('@/actions', () => ({
  actionBus: {
    dispatch: mocks.dispatch,
  },
}))

vi.mock('@/stores', () => ({
  useQueryStore: () => mocks.queryStore,
  useUiStore: () => mocks.uiStore,
  useDocsetStore: () => mocks.docsetStore,
  useSubcorporaStore: () => mocks.subcorporaStore,
  useProductCapabilitiesStore: () => mocks.productCapabilitiesStore,
  // Passthrough des Trend-Handoff-Adapters (stores/ui.ts): reine Identität.
  asSwitchTabId: (tab: string) => tab,
}))

import { useUrlState } from '@/composables/useUrlState'

describe('useUrlState restore governance', () => {
  beforeEach(() => {
    mocks.resetStores()
    mocks.dispatch.mockReset()
    mocks.dispatch.mockResolvedValue({ success: true, source: 'restore' })
    window.history.replaceState({}, '', '/')
  })

  it('builds restored docset scope before query execution and uses restore source', async () => {
    let restoreFromUrl!: ReturnType<typeof useUrlState>['restoreFromUrl']
    const wrapper = mount(defineComponent({
      setup() {
        restoreFromUrl = useUrlState().restoreFromUrl
        return () => null
      },
    }))
    await nextTick()
    mocks.dispatch.mockClear()

    window.history.replaceState(
      {},
      '',
      '/?q=Klimawandel&run=1&tab=kwic&corpus=test-corpus&model=qwen&human=0'
    )

    await restoreFromUrl()

    const queryDispatches = mocks.dispatch.mock.calls.filter(([action]) => action.type === 'query/execute')
    expect(queryDispatches).toHaveLength(1)
    expect(mocks.productCapabilitiesStore.ensureAccessContext).toHaveBeenCalled()
    expect(mocks.productCapabilitiesStore.ensureAccessContext.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.subcorporaStore.init.mock.invocationCallOrder[0]
    )
    expect(mocks.docsetStore.buildDocset).toHaveBeenCalledWith(true, 'Klimawandel')
    expect(mocks.docsetStore.buildDocset.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.dispatch.mock.invocationCallOrder[mocks.dispatch.mock.calls.findIndex(([action]) => action.type === 'query/execute')]
    )
    const [action, dispatchContext] = queryDispatches[0]!
    expect(action).toMatchObject({
      type: 'query/execute',
      payload: {
        term: 'Klimawandel',
        contextSize: 200,
        filters: { corpus: 'test-corpus' },
      },
    })
    expect(dispatchContext).not.toBe('system')
    expect(dispatchContext).toEqual(expect.objectContaining({
      source: 'restore',
      requestId: expect.stringMatching(/^url-restore:/),
    }))

    wrapper.unmount()
  })

  it('does not restore or execute raw q parameters without explicit run consent', async () => {
    let restoreFromUrl!: ReturnType<typeof useUrlState>['restoreFromUrl']
    const wrapper = mount(defineComponent({
      setup() {
        restoreFromUrl = useUrlState().restoreFromUrl
        return () => null
      },
    }))
    await nextTick()
    mocks.dispatch.mockClear()
    mocks.queryStore.setTerm.mockClear()

    window.history.replaceState(
      {},
      '',
      '/?q=vertrauliche-suche&tab=kwic&corpus=test-corpus'
    )

    await restoreFromUrl()

    expect(mocks.queryStore.setTerm).not.toHaveBeenCalled()
    expect(mocks.dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'query/execute' }),
      expect.anything()
    )
    expect(mocks.docsetStore.buildDocset).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('blocks CQLF URL restore before mutating query term or building docset when hidden', async () => {
    mocks.productCapabilitiesStore.isVisible.mockReturnValue(false)
    let restoreFromUrl!: ReturnType<typeof useUrlState>['restoreFromUrl']
    const wrapper = mount(defineComponent({
      setup() {
        restoreFromUrl = useUrlState().restoreFromUrl
        return () => null
      },
    }))
    await nextTick()
    mocks.dispatch.mockClear()

    window.history.replaceState(
      {},
      '',
      '/?q=%5Bword%3D%22Hase%22%5D&run=1&tab=kwic&corpus=test-corpus&model=qwen'
    )

    await restoreFromUrl()

    expect(mocks.queryStore.setTerm).not.toHaveBeenCalled()
    expect(mocks.docsetStore.buildDocset).not.toHaveBeenCalled()
    expect(mocks.dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'query/execute' }),
      expect.anything()
    )
    expect(mocks.uiStore.showToast).toHaveBeenCalledWith(
      expect.stringContaining('CQLF-Query aus der URL wurde blockiert'),
      'warning'
    )

    wrapper.unmount()
  })

  it('drops a pending URL update when its component unmounts', async () => {
    // The update timer outlived the component. In the full suite it fired
    // after the jsdom window of this file was gone ("window is not defined").
    vi.useFakeTimers()
    const replaceState = vi.spyOn(window.history, 'replaceState')
    try {
      let restoreFromUrl!: ReturnType<typeof useUrlState>['restoreFromUrl']
      const wrapper = mount(defineComponent({
        setup() {
          restoreFromUrl = useUrlState().restoreFromUrl
          return () => null
        },
      }))
      await nextTick()
      window.history.replaceState({}, '', '/?tab=kwic')
      replaceState.mockClear()
      // A restore schedules the URL update when it ends.
      await restoreFromUrl()
      wrapper.unmount()
      vi.advanceTimersByTime(1000)

      expect(replaceState).not.toHaveBeenCalled()
    } finally {
      replaceState.mockRestore()
      vi.useRealTimers()
    }
  })

  it('drops the URL update of a restore that ends after the unmount', async () => {
    vi.useFakeTimers()
    const replaceState = vi.spyOn(window.history, 'replaceState')
    let finishAccess: () => void = () => {}
    mocks.productCapabilitiesStore.ensureAccessContext.mockImplementationOnce(
      () => new Promise<null>((resolve) => { finishAccess = () => resolve(null) }),
    )
    try {
      let restoreFromUrl!: ReturnType<typeof useUrlState>['restoreFromUrl']
      const wrapper = mount(defineComponent({
        setup() {
          restoreFromUrl = useUrlState().restoreFromUrl
          return () => null
        },
      }))
      await nextTick()
      window.history.replaceState({}, '', '/?tab=kwic')
      replaceState.mockClear()
      const restore = restoreFromUrl()
      wrapper.unmount()
      finishAccess()
      await restore
      vi.advanceTimersByTime(1000)

      expect(replaceState).not.toHaveBeenCalled()
    } finally {
      replaceState.mockRestore()
      vi.useRealTimers()
    }
  })

  it('blocks plain KWIC URL restore before mutating query term when KWIC is hidden', async () => {
    mocks.productCapabilitiesStore.isVisible.mockImplementation((id: string) => id !== 'query.kwic')
    let restoreFromUrl!: ReturnType<typeof useUrlState>['restoreFromUrl']
    const wrapper = mount(defineComponent({
      setup() {
        restoreFromUrl = useUrlState().restoreFromUrl
        return () => null
      },
    }))
    await nextTick()
    mocks.dispatch.mockClear()

    window.history.replaceState(
      {},
      '',
      '/?q=Klimawandel&run=1&tab=kwic&corpus=test-corpus'
    )

    await restoreFromUrl()

    expect(mocks.queryStore.setTerm).not.toHaveBeenCalled()
    expect(mocks.docsetStore.buildDocset).not.toHaveBeenCalled()
    expect(mocks.dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'query/execute' }),
      expect.anything()
    )
    expect(mocks.uiStore.showToast).toHaveBeenCalledWith(
      expect.stringContaining('KWIC-Suche aus der URL wurde blockiert'),
      'warning'
    )

    wrapper.unmount()
  })
})
