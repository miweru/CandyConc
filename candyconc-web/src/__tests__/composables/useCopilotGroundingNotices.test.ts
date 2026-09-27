/**
 * The notices of `copilot.grounding` and `copilot.recovery` in words.
 *
 * Englischprobe 2026-09-27, run c2 in the interface: below the answer stood
 * "Grounding check: deutungs_synthese" (09:14, six minutes before the answer
 * arrived), "Grounding check: final_polish · Analysis: collocation" and
 * "Copilot recovery: deutung_abgegeben · … · retryable". The first event is the
 * evidence map of the answer that is still being written, not a check of an
 * answer. The notices name what happened, in the interface language.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { copilotGroundingContract } from '@/__tests__/fixtures/copilotGroundingContract'
import { applyLocale } from '@/i18n/locale'
import type { CopilotGroundingEvent, CopilotRecoveryEvent } from '@/api/sse'

interface StreamHandlers {
  onGrounding?: (event: CopilotGroundingEvent) => void
  onRecovery?: (event: CopilotRecoveryEvent) => void
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

async function startTurn(): Promise<StreamHandlers> {
  let handlers: StreamHandlers | undefined
  sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, incoming: StreamHandlers) => {
    handlers = incoming
    return vi.fn()
  })
  await useCopilot().sendMessage('What are the collocates of economy?')
  return handlers!
}

function notices(): string[] {
  return useCopilotStore().messages.filter((m) => m.role === 'system').map((m) => m.content)
}

const EVIDENCE = [
  { id: 'E_collocate_stats_1', tool: 'collocate_stats', query: '{}', status: 'success' },
  { id: 'E_collocate_stats_2', tool: 'collocate_stats', query: '{}', status: 'success' },
  { id: 'E_deutung_abgeben_3', tool: 'deutung_abgeben', query: '{}', status: 'success' },
]

describe('copilot notices name what happened', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = copilotGroundingContract()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
  })

  it('the evidence map before the answer claims no check (English)', async () => {
    const handlers = await startTurn()
    // After the turn started: the settings store applies its language on first use.
    applyLocale('en')
    handlers.onGrounding?.({ verdict: 'deutungs_synthese', analysis_family: '', evidence: EVIDENCE })
    handlers.onGrounding?.({
      verdict: 'final_polish',
      analysis_family: 'collocation',
      annotations: [{ rule: 'nachtrag', note: 'logDice for growing …' }, { rule: 'filter', note: 'Three rows …' }],
    })
    handlers.onRecovery?.({ kind: 'deutung_abgegeben', message: 'The model declared the hand-over itself.', retryable: true })
    expect(notices()).toEqual([
      'Evidence for the answer: 3 tool results. The answer is being written.',
      'Answer finished · Analysis: collocations · 2 notes below the answer',
      'Copilot recovery: investigation complete · The model declared the hand-over itself. · retry possible',
    ])
  })

  it('in German as well, and an unknown kind shows no code', async () => {
    const handlers = await startTurn()
    handlers.onGrounding?.({ verdict: 'deutungs_synthese', evidence: EVIDENCE.slice(0, 1) })
    handlers.onGrounding?.({ verdict: 'final_polish', analysis_family: 'trend_analysis', annotations: [] })
    handlers.onRecovery?.({ kind: 'stream_replay', message: 'Der Strom wurde neu gelesen.' })
    handlers.onGrounding?.({ verdict: 'pass', analysis_family: 'contrast_keyness' })
    expect(notices()).toEqual([
      'Evidenz für die Antwort: 1 Werkzeugergebnis. Die Antwort wird geschrieben.',
      'Antwort fertiggestellt · Analyse: Verlauf',
      'Copilot-Recovery · Der Strom wurde neu gelesen.',
      'Grounding geprüft: geerdet · Analyse: Kontrast',
    ])
  })
})
