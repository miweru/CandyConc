import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getCopilotRezepte } from '@/api/client'
import { useCopilotRezepteStore } from '@/stores/copilotRezepte'
import { useQueryStore } from '@/stores/query'
import { applyLocale } from '@/i18n/locale'
import CopilotPanel from '@/components/copilot/CopilotPanel.vue'

vi.mock('@/api/client', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/client')>(),
  getProductCapabilities: vi.fn(async () => { throw new Error('offline') }),
  getAuthSession: vi.fn(async () => { throw new Error('offline') }),
  getMcpTools: vi.fn(async () => ({ tools: [] })),
  getCopilotStatus: vi.fn(async () => ({ configured: true, model: 'test' })),
}))
vi.mock('@/api/sse', () => ({
  streamCopilotMessage: vi.fn(() => vi.fn()), approveAction: vi.fn(), rejectAction: vi.fn(),
  answerClarification: vi.fn(), updateCopilotContext: vi.fn(), getCurrentSessionId: vi.fn(() => null),
  continueCopilotExecution: vi.fn(() => vi.fn()),
}))
vi.mock('@/composables/useContextSnapshot', () => ({
  useContextSnapshot: () => ({ buildSnapshotSync: () => ({ version: '1.0', ts: 1 }) }),
}))

function recipe(question: string, source = 'korpus', answerable = true) {
  return {
    id: question, name: question, einsatz: '', beispiel_frage: question, schritte: [],
    beispiel_frage_quelle: source, im_korpus_beantwortbar: answerable,
  }
}
function response(recipes: ReturnType<typeof recipe>[]) {
  return new Response(JSON.stringify({ recipes }), { headers: { 'Content-Type': 'application/json' } })
}

const requests: Request[] = []
beforeEach(() => {
  setActivePinia(createPinia())
  applyLocale('de')
  requests.length = 0
  useQueryStore().setFilters({ corpus: 'speeches' })
  vi.stubGlobal('fetch', vi.fn(async (input: Request) => {
    requests.push(input)
    return response([recipe('How often does freedom occur?')])
  }))
})
afterEach(() => {
  useCopilotRezepteStore().$dispose()
  vi.unstubAllGlobals()
})

describe('corpus recipes', () => {
  it('sends the selected corpus to the recipes endpoint', async () => {
    await getCopilotRezepte('speeches')
    expect(new URL(requests[0]!.url).searchParams.get('corpus')).toBe('speeches')
  })

  it('reloads the recipe directory on corpus and interface language changes', async () => {
    const store = useCopilotRezepteStore()
    await store.laden()
    await store.laden()
    expect(requests).toHaveLength(1)
    expect(new URL(requests[0]!.url).searchParams.get('corpus')).toBe('speeches')

    useQueryStore().setFilters({ corpus: 'letters' })
    await flushPromises()
    expect(requests).toHaveLength(2)
    expect(new URL(requests[1]!.url).searchParams.get('corpus')).toBe('letters')

    applyLocale('en')
    await flushPromises()
    expect(requests).toHaveLength(3)
    expect(requests[2]!.headers.get('Accept-Language')).toMatch(/^en/)
  })

  it('ignores a late response from the previously selected corpus', async () => {
    const replies: Array<(value: Response) => void> = []
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => replies.push(resolve))))
    const store = useCopilotRezepteStore()
    const initial = store.laden()
    await flushPromises()
    useQueryStore().setFilters({ corpus: 'letters' })
    await flushPromises()
    replies[1]!(response([recipe('Question for letters')]))
    await flushPromises()
    replies[0]!(response([recipe('Question for speeches')]))
    await initial
    expect(Object.keys(store.rezepte)).toEqual(['Question for letters'])
  })

  it('shows answerable corpus questions in the empty chat and excludes static examples', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response([
      recipe('How often does freedom occur?'),
      recipe('Compare the invented groups.', 'statisch'),
      recipe('How does freedom change over time?', 'korpus', false),
    ])))
    const wrapper = mount(CopilotPanel, {
      props: { mode: 'docked' },
      global: { stubs: { RunHistoryPanel: true, ResearchToolsPanel: true, ChatMessage: true } },
    })
    await flushPromises()
    expect(wrapper.findAll('.starter-chip').map((chip) => chip.text())).toEqual([
      'How often does freedom occur?',
    ])
    wrapper.unmount()
  })
})
