/**
 * Rezept-Transparenz + beratende Annotationen im Composable:
 *
 * - `copilot.status.recipe_id` landet als status.recipeId an der laufenden
 *   Message (null = freie Analyse, fehlend = Alt-Backend unveraendert).
 * - Die done-Bilanz spiegelt recipe_id als usage.recipeId.
 * - `copilot.grounding.annotations` haengen als beratende Hinweise an der
 *   Antwort-Message (einklappbar gerendert, nie blockierend). Die bestehende
 *   System-Notiz zum Grounding-Verdict bleibt erhalten.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { copilotGroundingContract } from '@/__tests__/fixtures/copilotGroundingContract'
import type { CopilotDoneMeta, CopilotGroundingEvent, CopilotStatusEvent } from '@/api/sse'

interface StreamHandlers {
  onContent?: (content: string) => void
  onStatus?: (status: CopilotStatusEvent) => void
  onGrounding?: (event: CopilotGroundingEvent) => void
  onDone?: (content: string, meta?: CopilotDoneMeta) => void
  onError?: (error: Error) => void
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

function lastAssistant() {
  const messages = useCopilotStore().messages
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]!.role === 'assistant') return messages[i]!
  }
  return undefined
}

async function startTurn(): Promise<StreamHandlers> {
  let handlers: StreamHandlers | undefined
  sseMocks.streamCopilotMessage.mockImplementationOnce(
    (_message: string, incoming: StreamHandlers) => {
      handlers = incoming
      return vi.fn()
    },
  )
  const copilot = useCopilot()
  await copilot.sendMessage('rezeptfrage')
  return handlers!
}

describe('useCopilot Rezept-Transparenz (recipe_id)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = copilotGroundingContract()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
  })

  it('spiegelt recipe_id aus copilot.status als status.recipeId', async () => {
    const handlers = await startTurn()

    handlers.onStatus?.({ stage: 'Werkzeuge', recipe_id: 'kontrast' })
    const assistant = lastAssistant()!
    expect(assistant.status).toEqual({ stage: 'Werkzeuge', recipeId: 'kontrast' })
  })

  it('recipe_id null (freie Analyse) wird als recipeId null gespiegelt', async () => {
    const handlers = await startTurn()

    handlers.onStatus?.({ stage: 'Antwort', recipe_id: null })
    expect(lastAssistant()!.status).toEqual({ stage: 'Antwort', recipeId: null })
  })

  it('ohne recipe_id bleibt der Status unveraendert (Alt-Backend gepinnt)', async () => {
    const handlers = await startTurn()

    handlers.onStatus?.({ stage: 'Werkzeuge' })
    const status = lastAssistant()!.status
    expect(status).toEqual({ stage: 'Werkzeuge' })
    expect(status).not.toHaveProperty('recipeId')
  })

  it('die done-Bilanz traegt recipe_id als usage.recipeId', async () => {
    const handlers = await startTurn()

    handlers.onDone?.('Fertig.', {
      recipe_id: 'frequenz',
      llm_calls_used: 2,
      elapsed_s: 9.1,
    })
    const assistant = lastAssistant()!
    expect(assistant.usage).toEqual({
      recipeId: 'frequenz',
      llmCalls: 2,
      elapsedS: 9.1,
    })
  })

  it('done mit recipe_id null erzeugt usage.recipeId null, ohne Feld gar keinen Eintrag', async () => {
    const handlersNull = await startTurn()
    handlersNull.onDone?.('Freie Antwort.', { recipe_id: null, llm_calls_used: 1 })
    expect(lastAssistant()!.usage).toEqual({ recipeId: null, llmCalls: 1 })

    const handlersLegacy = await startTurn()
    handlersLegacy.onDone?.('Alt-Antwort.', { llm_calls_used: 1 })
    expect(lastAssistant()!.usage).toEqual({ llmCalls: 1 })
    expect(lastAssistant()!.usage).not.toHaveProperty('recipeId')
  })
})

describe('useCopilot beratende Annotationen (copilot.grounding.annotations)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = copilotGroundingContract()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
  })

  it('haengt annotations an die Antwort-Message und behaelt die System-Notiz', async () => {
    const handlers = await startTurn()
    const assistantId = lastAssistant()!.id

    handlers.onGrounding?.({
      verdict: 'accepted',
      annotations: [
        { rule: 'per_million_normierung', note: 'Frequenzen sind pro Million Token normiert.' },
        { rule: 'docset_scope', note: 'Werte gelten nur fuer das aktive Subkorpus.' },
      ],
    })

    const store = useCopilotStore()
    const assistant = store.messages.find((m) => m.id === assistantId)!
    expect(assistant.annotations).toEqual([
      { rule: 'per_million_normierung', note: 'Frequenzen sind pro Million Token normiert.' },
      { rule: 'docset_scope', note: 'Werte gelten nur fuer das aktive Subkorpus.' },
    ])
    // Die bestehende Grounding-System-Notiz bleibt unveraendert erhalten.
    const systemNotice = store.messages.find(
      (m) => m.role === 'system' && m.content.includes('Grounding geprüft'),
    )
    expect(systemNotice).toBeDefined()
  })

  it('annotations ueberleben das done-Finalisieren der Message', async () => {
    const handlers = await startTurn()

    handlers.onGrounding?.({
      verdict: 'accepted',
      annotations: [{ rule: 'r1', note: 'Hinweis bleibt.' }],
    })
    handlers.onDone?.('Finale Antwort.', { llm_calls_used: 1 })

    const assistant = lastAssistant()!
    expect(assistant.isStreaming).toBe(false)
    expect(assistant.content).toBe('Finale Antwort.')
    expect(assistant.annotations).toEqual([{ rule: 'r1', note: 'Hinweis bleibt.' }])
  })

  it('mehrere Grounding-Events haengen ihre annotations an (append, kein Ersetzen)', async () => {
    const handlers = await startTurn()

    handlers.onGrounding?.({ annotations: [{ rule: 'a', note: 'Erster Hinweis.' }] })
    handlers.onGrounding?.({ annotations: [{ rule: 'b', note: 'Zweiter Hinweis.' }] })

    expect(lastAssistant()!.annotations).toEqual([
      { rule: 'a', note: 'Erster Hinweis.' },
      { rule: 'b', note: 'Zweiter Hinweis.' },
    ])
  })

  it('ohne annotations-Feld bleibt das Verhalten unveraendert (Alt-Backend gepinnt)', async () => {
    const handlers = await startTurn()

    handlers.onGrounding?.({
      analysis_family: 'exploratory',
      verdict: 'conservative_only',
      rejected_claim_count: 2,
    })

    const assistant = lastAssistant()!
    expect(assistant.annotations).toBeUndefined()
    const store = useCopilotStore()
    const systemNotice = store.messages.find(
      (m) => m.role === 'system' && m.content.includes('Grounding geprüft'),
    )
    expect(systemNotice).toBeDefined()
  })

  it('verwirft fehlerhafte Eintraege tolerant und blockiert nie', async () => {
    const handlers = await startTurn()

    handlers.onGrounding?.({
      annotations: [
        null as unknown as { rule: string; note: string },
        'kaputt' as unknown as { rule: string; note: string },
        { rule: '', note: '   ' },
        { note: 'Nur Note, keine Regel.' },
        { rule: 'nur_regel' },
      ],
    })

    expect(lastAssistant()!.annotations).toEqual([
      { note: 'Nur Note, keine Regel.' },
      { rule: 'nur_regel' },
    ])
  })

  it('Diagnose-Zeilen der Zitatwache erreichen die Nachrichtenblase nicht', async () => {
    // Gemessen an der Politur: aus 'Ein Korpusbeleg lautet
    // "ruecksichtslose Invasoren marschieren".' nimmt die Zitatwache das
    // Fabrikat aus dem Rumpf und meldet es als Stelle. ChatMessage.vue
    // rendert jede Annotation unter der Antwort ("Hinweise (n)"), also
    // stand das Fabrikat samt Traegersatz eine Zeile tiefer erneut in
    // derselben Blase. Ohne den channel-Filter ist diese Probe rot.
    const handlers = await startTurn()

    handlers.onGrounding?.({
      annotations: [
        { rule: 'zitat_ohne_deckung_entfernt', note: '1 Zitat(e) ohne Deckung entfernt' },
        {
          rule: 'zitat_ohne_deckung_stelle',
          channel: 'diagnostik',
          note: 'Satz: Ein Korpusbeleg lautet [Beleg fehlt]. | Zitat: rücksichtslose Invasoren marschieren',
        } as unknown as { rule: string; note: string },
      ],
    })

    const annotations = lastAssistant()!.annotations ?? []
    expect(annotations).toEqual([
      { rule: 'zitat_ohne_deckung_entfernt', note: '1 Zitat(e) ohne Deckung entfernt' },
    ])
    expect(JSON.stringify(annotations)).not.toContain('Invasoren')
  })
})
