/**
 * Die KETTE: SSE-Frame rein, Store-Feld raus.
 *
 * Der erste Anlauf hat die Flags nur im Merge-Zweig angewandt. Ein
 * wiederverwendeter Aufruf erreicht aber ausschliesslich den Push-Zweig:
 * der Orchestrator sendet sein copilot.tool_result in der Filterschleife
 * und macht `continue`, bevor `_dispatch` laeuft, und das `start`-Ereignis
 * entsteht nur in `_dispatch`. Es gibt also keine laufende Karte zum
 * Hineinmergen.
 *
 * Der Zwischenspeicher-Treffer erschien dadurch als vollwertige Karte MIT
 * Kennzahl, in voller Deckkraft, und wurde als weitere Abfrage gezaehlt.
 * Genau die Arbeit, die nicht stattgefunden hat.
 *
 * Der alte Test setzte `wiederverwendet: true` VON HAND auf die ToolCall
 * und prueft damit nur die Ableitung, nie die Ankunft. Dieser hier faehrt
 * den ganzen Weg.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { withCopilotGroundingCapability } from '@/__tests__/fixtures/copilotGroundingContract'
import type { ProductCapabilityContract } from '@/api/client'
import type { ToolResultV1 } from '@/types/copilot-protocol'

function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

interface StreamHandlers {
  onToolResultV1?: (result: ToolResultV1) => void
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
  useContextSnapshot: () => ({ buildSnapshotSync: () => ({ version: '1.0', ts: 1 }) }),
}))

import { useCopilot } from '@/composables/useCopilot'

function vertrag(): ProductCapabilityContract {
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
  }, { copilot_tools: ['document_search'] })
}

async function turnMit(frame: ToolResultV1) {
  sseMocks.streamCopilotMessage.mockImplementationOnce(
    (_m: string, h: StreamHandlers) => {
      h.onToolResultV1?.(frame)
      h.onDone('fertig')
      return vi.fn()
    },
  )
  const copilot = useCopilot()
  await copilot.sendMessage('Frage.')
  await flush()
  const m = useCopilotStore().messages.find(x => x.role === 'assistant')
  return m?.toolCalls?.[0]
}

describe('reused und skipped erreichen den Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const caps = useProductCapabilitiesStore()
    caps.contract = vertrag()
    caps.status = 'ready'
    caps.error = null
    vi.restoreAllMocks()
    Object.values(sseMocks).forEach(m => m.mockReset())
    sseMocks.getCurrentSessionId.mockReturnValue(null)
    sseMocks.continueCopilotExecution.mockReturnValue(vi.fn())
  })

  it('ein Zwischenspeicher-Treffer OHNE vorheriges start ist gekennzeichnet', async () => {
    const tc = await turnMit({
      toolName: 'document_search', ok: true, ts: 1,
      input: { query: 'Kinder' }, output: { total: 21 }, reused: true,
    })
    expect(tc?.wiederverwendet).toBe(true)
  })

  it('ein uebersprungener Aufruf ist gekennzeichnet', async () => {
    const tc = await turnMit({
      toolName: 'document_search', ok: true, ts: 1,
      input: {}, output: { status: 'skipped' }, skipped: true,
    })
    expect(tc?.uebersprungen).toBe(true)
  })

  it('ein regulaerer Aufruf traegt KEINE der beiden Marken', async () => {
    // Positive Klasse: ohne sie waere ein bedingungsloses true gruen.
    const tc = await turnMit({
      toolName: 'document_search', ok: true, ts: 1,
      input: { query: 'Kinder' }, output: { total: 21 },
    })
    expect(tc?.wiederverwendet).toBeUndefined()
    expect(tc?.uebersprungen).toBeUndefined()
  })

  it('die Abfrage aus input landet in arguments', async () => {
    // Sie ging beim Zusammenfuehren verloren, und damit genau die Angabe,
    // mit der jemand nachvollziehen kann, WONACH gesucht wurde.
    const tc = await turnMit({
      toolName: 'document_search', ok: true, ts: 1,
      input: { query: 'Kinder' }, output: { total: 21 },
    })
    expect(tc?.arguments).toMatchObject({ query: 'Kinder' })
  })
})
