/**
 * Research-/Blocked-Events: das Backend sendet `copilot.research`,
 * `copilot.research_context` und `copilot.action_blocked` — das Frontend
 * macht sie sichtbar (Statusanzeige bzw. Systemmeldung mit Grund) und sendet
 * die Hintergrund-Recherche-Präferenz als ui_context-Flag.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSettingsStore } from '@/stores/settings'
import { withCopilotGroundingCapability } from '@/__tests__/fixtures/copilotGroundingContract'
import type { ProductCapabilityContract } from '@/api/client'
import type {
  CopilotActionBlockedEvent,
  CopilotResearchContextEvent,
  CopilotResearchEvent,
} from '@/api/sse'

function flushAsyncCopilot(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

interface StreamHandlers {
  onResearch?: (event: CopilotResearchEvent) => void
  onResearchContext?: (event: CopilotResearchContextEvent) => void
  onActionBlocked?: (event: CopilotActionBlockedEvent) => void
  onDone: (content: string) => void
}

const sseMocks = vi.hoisted(() => ({
  streamCopilotMessage: vi.fn(),
  approveAction: vi.fn(),
  rejectAction: vi.fn(),
  answerClarification: vi.fn(),
  updateCopilotContext: vi.fn(),
  getCurrentSessionId: vi.fn(() => null),
  continueCopilotExecution: vi.fn(),
}))

vi.mock('@/api/sse', () => sseMocks)

vi.mock('@/composables/useContextSnapshot', () => ({
  useContextSnapshot: () => ({
    buildSnapshotSync: () => ({ version: '1.0', ts: 1 }),
  }),
}))

import { useCopilot } from '@/composables/useCopilot'

function productContractFixture(): ProductCapabilityContract {
  return withCopilotGroundingCapability({
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [],
  })
}

describe('useCopilot research/blocked events + background-research toggle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractFixture()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    vi.restoreAllMocks()
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.getCurrentSessionId.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
    sseMocks.continueCopilotExecution.mockReset()
    sseMocks.continueCopilotExecution.mockReturnValue(vi.fn())
  })

  it('renders copilot.action_blocked as a system message including the backend reason', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionBlocked?.({
        request: {
          requestId: 'blocked-1',
          type: 'export/data',
          payload: { format: 'csv' },
        },
        meta: {
          summary: 'Export anstoßen',
          status: 'blocked',
          reason: 'Action is not visible in Product-Capability-Contract',
        },
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Bitte exportieren.')
    await flushAsyncCopilot()

    const systemMessages = useCopilotStore().messages.filter((m) => m.role === 'system')
    const blockedNotice = systemMessages.find((m) => m.content.includes('blockiert'))
    expect(blockedNotice).toBeDefined()
    expect(blockedNotice!.content).toContain('export/data')
    expect(blockedNotice!.content).toContain('Action is not visible in Product-Capability-Contract')
  })

  it('collects research and research_context events into the status timeline', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onResearch?.({
        researchId: 'r-1',
        phase: 'started',
        query: 'Belege zu Klimawandel',
        ts: 1000,
      })
      handlers.onResearchContext?.({ keep: ['r-1'], ts: 2000 })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Recherchiere im Hintergrund.')
    await flushAsyncCopilot()

    expect(copilot.researchEvents.value).toHaveLength(2)
    expect(copilot.researchEvents.value[0]).toMatchObject({ kind: 'research' })
    expect(copilot.researchEvents.value[0]!.text).toContain('started')
    expect(copilot.researchEvents.value[0]!.text).toContain('Belege zu Klimawandel')
    expect(copilot.researchEvents.value[1]).toMatchObject({ kind: 'context' })
    expect(copilot.researchEvents.value[1]!.text).toContain('r-1')
    // Recherche-Status ist eine Statusanzeige, KEINE Chat-Systemmeldung.
    const systemMessages = useCopilotStore().messages.filter((m) => m.role === 'system')
    expect(systemMessages.filter((m) => m.content.includes('Recherche'))).toHaveLength(0)
  })

  it('sends disable_background_research=true in ui_context when the toggle is off', async () => {
    const settingsStore = useSettingsStore()
    settingsStore.preferences.backgroundResearch = false

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onDone('ok')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Ohne Hintergrund-Recherche.')

    const options = sseMocks.streamCopilotMessage.mock.calls[0]![1] as {
      snapshot?: Record<string, unknown>
    }
    expect(options.snapshot?.disable_background_research).toBe(true)
  })

  it('omits the flag when background research stays enabled (default)', async () => {
    // Default der Präferenz ist AN.
    expect(useSettingsStore().preferences.backgroundResearch).toBe(true)

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onDone('ok')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Mit Hintergrund-Recherche.')

    const options = sseMocks.streamCopilotMessage.mock.calls[0]![1] as {
      snapshot?: Record<string, unknown>
    }
    expect(options.snapshot).toBeDefined()
    expect('disable_background_research' in (options.snapshot ?? {})).toBe(false)
  })
})
