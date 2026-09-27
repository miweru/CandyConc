import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/client'
import CopilotPanel from '@/components/copilot/CopilotPanel.vue'
import { useCopilotStore } from '@/stores/copilot'
import { useUiStore } from '@/stores/ui'

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
  Settings: true,
}

/**
 * erprobung B13: without a configured model the panel looked ready, with an
 * input field and example questions, and the chat answered 424
 * copilot_not_configured only after a question was sent.
 */
describe('CopilotPanel without a configured model', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  async function openPanel(configured: boolean) {
    vi.spyOn(api, 'getCopilotStatus').mockResolvedValue({ configured, model: configured ? 'm' : null })
    useCopilotStore().open()
    const wrapper = mount(CopilotPanel, { props: { mode: 'docked' }, global: { stubs } })
    await flushPromises()
    return wrapper
  }

  it('names the missing model, disables input and example questions, and opens the model settings', async () => {
    const wrapper = await openPanel(false)
    const notice = wrapper.get('[data-testid="copilot-setup-notice"]')
    expect(notice.text()).toContain('Kein Sprachmodell eingerichtet')
    expect(wrapper.get('.message-input').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.starter-chip').exists()).toBe(false)

    await notice.get('button').trigger('click')
    const ui = useUiStore()
    expect(ui.settingsOpen).toBe(true)
    expect(ui.settingsTab).toBe('modelroute')
  })

  it('stays ready when a model is configured', async () => {
    const wrapper = await openPanel(true)
    expect(wrapper.find('[data-testid="copilot-setup-notice"]').exists()).toBe(false)
    expect(wrapper.get('.message-input').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.starter-chip').exists()).toBe(true)
  })
})
