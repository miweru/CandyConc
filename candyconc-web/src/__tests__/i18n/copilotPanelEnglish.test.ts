/**
 * The copilot panel, a chat message with a tool card and the tool result
 * renderers in the English interface. No model, no network: the SSE layer and
 * the context snapshot are mocked as in copilotStopButton.test.ts, the tool
 * status request returns a fixed list.
 *
 * Besides the expected English wording, every German copilot catalog text
 * that differs from its English counterpart is searched for in the visible
 * text and in title, placeholder and aria-label attributes. The language is
 * switched through the settings store, as the language selection does.
 * The starter prompts of the empty panel are checked too: they come from the
 * catalog and name metadata fields of the active corpus (lib/copilotStarters).
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CopilotPanel from '@/components/copilot/CopilotPanel.vue'
import ChatMessage from '@/components/copilot/ChatMessage.vue'
import FrequencyRenderer from '@/components/copilot/tools/FrequencyRenderer.vue'
import QueryResultsRenderer from '@/components/copilot/tools/QueryResultsRenderer.vue'
import KeynessRenderer from '@/components/copilot/tools/KeynessRenderer.vue'
import de from '@/locales/de'
import en from '@/locales/en'
import { currentLocale } from '@/i18n/locale'
import { useCopilotStore, type ChatMessage as ChatMessageType } from '@/stores/copilot'
import { useSettingsStore } from '@/stores/settings'

vi.mock('@/api/sse', () => ({
  streamCopilotMessage: vi.fn(() => vi.fn()),
  approveAction: vi.fn(),
  rejectAction: vi.fn(),
  answerClarification: vi.fn(),
  updateCopilotContext: vi.fn(),
  getCurrentSessionId: vi.fn(() => null),
  continueCopilotExecution: vi.fn(() => vi.fn()),
}))

vi.mock('@/composables/useContextSnapshot', () => ({
  useContextSnapshot: () => ({ buildSnapshotSync: () => ({ version: '1.0', ts: 1 }) }),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(async () => { throw new Error('offline') }),
    updatePrefs: vi.fn(async () => ({ ok: true })),
    getMcpTools: vi.fn(async () => ({
      tools: [],
      tool_statuses: [
        { name: 'frequency_list', dispatchable: true, status: 'operation_bound', product_operation_ids: [] },
      ],
    })),
  }
})

type Tree = { [key: string]: string | Tree }

function leaves(tree: Tree, prefix = ''): Map<string, string> {
  const out = new Map<string, string>()
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out.set(path, value)
    else for (const [k, v] of leaves(value, path)) out.set(k, v)
  }
  return out
}

/**
 * Static parts of every German copilot message that the English catalog
 * words differently. Placeholders split a message into parts; parts shorter
 * than four characters or without a letter say nothing about the language.
 */
function germanFragments(): string[] {
  const deLeaves = leaves((de as unknown as Tree).copilot as Tree)
  const enLeaves = leaves((en as unknown as Tree).copilot as Tree)
  const fragments = new Set<string>()
  for (const [key, message] of deLeaves) {
    if (enLeaves.get(key) === message) continue
    for (const form of message.split(' | ')) {
      for (const part of form.split(/\{[^}]*\}/)) {
        const trimmed = part.trim()
        if (trimmed.length >= 4 && /[A-Za-zÄÖÜäöüß]/.test(trimmed)) fragments.add(trimmed)
      }
    }
  }
  return [...fragments]
}

const GERMAN = germanFragments()

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** German fragments found as whole words in the given text. */
function germanRemnants(text: string): string[] {
  const normalized = text.replace(/\s+/g, ' ')
  return GERMAN.filter((fragment) =>
    new RegExp(`(?<![A-Za-zÄÖÜäöüß])${escapeRegExp(fragment)}(?![A-Za-zÄÖÜäöüß])`).test(normalized),
  )
}

/** Visible text plus the texts of title, placeholder and aria-label attributes. */
function visibleTexts(root: Element): string {
  const attributes = [...root.querySelectorAll('[title], [placeholder], [aria-label]')]
    .flatMap((el) => ['title', 'placeholder', 'aria-label'].map((name) => el.getAttribute(name) ?? ''))
  return [root.textContent ?? '', ...attributes].join(' \n ')
}

const lucideStubs = {
  X: true,
  Send: true,
  Square: true,
  Minimize2: true,
  Dock: true,
  Sparkles: true,
  History: true,
  Beaker: true,
  AlertTriangle: true,
  RotateCcw: true,
  MessageSquarePlus: true,
}

const wrappers: VueWrapper[] = []
afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
})

function assistantTurn(): ChatMessageType {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: 'The corpus contains the term [[beleg:ev1]] and more [[beleg:ev-unknown]].',
    timestamp: Date.UTC(2026, 8, 27, 10, 30),
    evidence: [{ id: 'ev1', tool: 'frequency_list', query: 'climate', status: 'ok' }],
    toolCalls: [{
      id: 'tool-1',
      name: 'frequency_list',
      arguments: { query: 'climate' },
      status: 'success',
      result: { rows: [{ word: 'climate', f: 12 }], total: 1 },
    }],
    stages: [
      { stage: 'Vorlauf', von: 0, bis: 1.5 },
      { stage: 'Werkzeuge', von: 1.5, bis: 4, modellSekunden: 1.2 },
      { stage: 'Antwort', von: 4, bis: 6 },
    ],
    usage: { llmCalls: 3, elapsedS: 6, llmSeconds: 2.5, recipeId: 'kontrast', transportRetries: 1 },
    annotations: [{ rule: 'per_million_note', note: 'Frequencies are per million tokens.' }],
  }
}

describe('copilot panel in English', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    // The settings store owns the interface language: switching through it
    // keeps English when a component creates the store during mount.
    await useSettingsStore().setLanguage('en')
    expect(currentLocale()).toBe('en')
  })

  it('shows the empty panel in English, including the starter prompts', async () => {
    const wrapper = mount(CopilotPanel, {
      props: { mode: 'docked' },
      global: { stubs: { ...lucideStubs, RunHistoryPanel: true, ResearchToolsPanel: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('What should the copilot start with?')
    expect(text).toContain('I can start searches and analyses.')
    expect(text).toContain('Chat')
    expect(wrapper.find('textarea.message-input').attributes('placeholder')).toBe('Message the copilot...')
    expect(wrapper.find('button[title="New chat"]').exists()).toBe(true)
    expect(wrapper.find('button[title="Close (Esc)"]').exists()).toBe(true)
    // Docked mode offers the switch back to the floating window.
    expect(wrapper.find('button[title="Undock"]').exists()).toBe(true)

    // Without a metadata schema the starters are general corpus questions.
    expect(wrapper.findAll('.starter-chip').map((chip) => chip.text())).toEqual([
      'Which words are most frequent in this corpus?',
      'Which words typically occur with the most frequent content word in this corpus?',
      'How does the query language work? Please give an example from this corpus.',
    ])
    expect(text).not.toMatch(/Klimawandel|Nachhaltigkeit|KI- und menschliche|CQLF/)
    expect(germanRemnants(visibleTexts(wrapper.element))).toEqual([])
  })

  it('shows a conversation with a tool card, evidence chips and retry notice in English', async () => {
    const copilotStore = useCopilotStore()
    copilotStore.messages.push(
      { id: 'user-1', role: 'user', content: 'How often does climate occur?', timestamp: Date.UTC(2026, 8, 27, 10, 29) },
      assistantTurn(),
      {
        id: 'assistant-2',
        role: 'assistant',
        content: 'Error: Server not reachable.',
        timestamp: Date.UTC(2026, 8, 27, 10, 31),
        error: true,
        retryPrompt: 'How often does climate occur?',
      },
    )

    const wrapper = mount(CopilotPanel, {
      props: { mode: 'docked' },
      global: { stubs: { ...lucideStubs, RunHistoryPanel: true, ResearchToolsPanel: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    // Claim labels and the evidence chips
    expect(text).toContain('AI interpretation')
    expect(text).toContain('AI error status')
    expect(text).toContain('Evidence 1')
    expect(text).toContain('[evidence missing]')
    // Tool card
    expect(text).toContain('Frequency list')
    expect(text).toContain('Tool available')
    expect(text).toContain('Show parameters')
    expect(text).toContain('not released as evidence')
    expect(text).toContain('The tool result cannot be used as evidence yet because the available functions are still loading.')
    // Notes, timeline with translated stage names, usage footer
    expect(text).toContain('Notes (1)')
    expect(text).toContain('Timeline')
    expect(text).toContain('Preparation')
    expect(text).toContain('Tools')
    expect(text).toContain('Answer')
    expect(text).toContain('1.2 s model')
    expect(text).toContain('Contrast')
    expect(text).toContain('3 LLM calls')
    expect(wrapper.find('.usage-footer').attributes('title')).toBe('Transport retries: 1')
    // Retry notice of the failed turn
    expect(text).toContain('The answer could not be completed.')
    expect(text).toContain('Try again')

    expect(germanRemnants(visibleTexts(wrapper.element))).toEqual([])
  })

  it('shows the running turn with recipe, progress and provisional marker in English', async () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'assistant-3',
          role: 'assistant',
          content: 'Draft answer',
          timestamp: Date.UTC(2026, 8, 27, 10, 32),
          isStreaming: true,
          vorlaeufig: true,
          status: { stage: 'Werkzeuge', recipeId: 'kontrast', fortschritt: { schritt: 2, von: 5, anteil: 0.4 } } as ChatMessageType['status'],
          stages: [{ stage: 'Vorlauf', von: 0, bis: 1 }, { stage: 'Werkzeuge', von: 1 }],
          usage: { llmCalls: 1, partial: true, timeout: '120 s' },
        },
      },
    })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.find('.stream-status').text()).toBe('Analysis recipe: Contrast · Tools…')
    expect(wrapper.text()).toContain('Provisional, check still running')
    expect(wrapper.find('[role="progressbar"]').attributes('aria-label')).toBe('Step 2 of 5')
    expect(wrapper.text()).toContain('2 of 5')
    expect(wrapper.text()).toContain('at least 1 s')
    expect(wrapper.text()).toContain('running')
    expect(wrapper.text()).toContain('1 LLM call')
    expect(wrapper.text()).toContain('Partial answer')
    expect(wrapper.find('.usage-footer').attributes('title')).toBe('Time limit: 120 s')
    expect(germanRemnants(visibleTexts(wrapper.element))).toEqual([])
  })

  it('renders frequency, query and keyness results in English', async () => {
    const frequency = mount(FrequencyRenderer, {
      props: { data: { rows: [{ word: 'climate', f: 1234, per_million: 12.5 }], total: 40, truncated: true }, limit: 20 },
    })
    const query = mount(QueryResultsRenderer, {
      props: { data: { total: 1, sampleCount: 1, truncated: true, queryTime: 12 } },
    })
    const sample = mount(QueryResultsRenderer, {
      props: { data: { total: null, sampleCount: 2, truncated: true } },
    })
    const keyness = mount(KeynessRenderer, {
      props: { data: { rows: [{ word: 'climate', ll_signed: 10.2, log_ratio: 1.5, log_ratio_ci_low: 0.8, log_ratio_ci_high: 2.1, q_value: 0.001 }] } },
    })
    wrappers.push(frequency, query, sample, keyness)
    await flushPromises()

    expect(frequency.text()).toContain('Frequency list')
    expect(frequency.text()).toContain('1 of 40 types')
    expect(frequency.text()).toContain('1,234')
    expect(frequency.text()).toContain('List truncated by the server (40 types in total).')
    expect(query.text()).toContain('Search succeeded')
    expect(query.text()).toContain('1 hit')
    expect(query.text()).not.toContain('1 hits')
    expect(query.text()).toContain('(partial)')
    expect(sample.text()).toContain('2 loaded concordance lines')
    expect(sample.text()).toContain('(sample, not a total count)')
    expect(keyness.text()).toContain('1 word')
    expect(keyness.text()).toContain('Log ratio [CI]')
    expect(keyness.text()).toContain('Sorted by signed LL.')

    for (const wrapper of [frequency, query, sample, keyness]) {
      expect(germanRemnants(visibleTexts(wrapper.element))).toEqual([])
    }
  })
})
