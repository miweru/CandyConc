import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CopilotPanel from '@/components/copilot/CopilotPanel.vue'
import { useCopilotStore } from '@/stores/copilot'

// The panel pulls in the SSE layer transitively via useCopilot; mock it so no
// real network/stream is started during the test.
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

const stubs = {
  ChatMessage: { template: '<div class="chat-message-stub" />' },
  ClarificationCard: true,
  AutonomySlider: { template: '<div />' },
  PlanDisplay: true,
  ClarifyModal: true,
  ActionPreviewPanel: true,
  RunHistoryPanel: { template: '<div />' },
  ResearchToolsPanel: { template: '<div />' },
  // lucide icons
  X: true,
  Send: true,
  Square: true,
  Minimize2: true,
  Dock: true,
  Sparkles: true,
  History: true,
  Beaker: true,
}

describe('CopilotPanel stop button (DT-FE-UX-CORE)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows a Stop button while thinking and hides the Send button', async () => {
    const copilotStore = useCopilotStore()
    copilotStore.setStreaming(true)

    const wrapper = mount(CopilotPanel, { props: { mode: 'docked' }, global: { stubs } })
    await flushPromises()

    expect(wrapper.find('.stop-btn').exists()).toBe(true)
    expect(wrapper.find('.send-btn').exists()).toBe(false)
  })

  it('clicking Stop cancels streaming (isThinking → false, Send returns)', async () => {
    const copilotStore = useCopilotStore()
    copilotStore.setStreaming(true)

    const wrapper = mount(CopilotPanel, { props: { mode: 'docked' }, global: { stubs } })
    await flushPromises()

    await wrapper.find('.stop-btn').trigger('click')
    await flushPromises()

    expect(copilotStore.isThinking).toBe(false)
    expect(wrapper.find('.stop-btn').exists()).toBe(false)
    expect(wrapper.find('.send-btn').exists()).toBe(true)
  })

  it('re-enables the message input immediately after Stop (kein Ausknocken)', async () => {
    const copilotStore = useCopilotStore()
    copilotStore.setStreaming(true)

    const wrapper = mount(CopilotPanel, { props: { mode: 'docked' }, global: { stubs } })
    await flushPromises()

    const input = wrapper.find('textarea.message-input')
    expect(input.attributes('disabled')).toBeDefined()

    await wrapper.find('.stop-btn').trigger('click')
    await flushPromises()

    expect(wrapper.find('textarea.message-input').attributes('disabled')).toBeUndefined()
  })
})
