/**
 * Die Zeitleiste einer Antwort.
 *
 * Sie beantwortet die Frage, die die Fusszeile offen liess: wo ist die Zeit
 * geblieben. Am 273M-Korpus gemessen liegen in einem Turn 2530 s
 * Verifikation gegen 233 s Werkzeuge, und der Anteil Modellzeit an der
 * Werkzeugschleife schwankt zwischen 7 und 56 Prozent.
 *
 * Der schwierigste Fall ist nicht der gelungene Turn, sondern der offene:
 * eine laufende Stufe hat kein Ende, und eine Null waere dort eine
 * Falschaussage. Ein abgebrochener Turn hat auch keines, laeuft aber nicht
 * mehr. Beide stehen hier.
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMessage from '@/components/copilot/ChatMessage.vue'
import type { ChatMessage as Nachricht } from '@/stores'

function nachricht(teil: Partial<Nachricht>): Nachricht {
  return {
    id: 'm1',
    role: 'assistant',
    content: 'Antwort.',
    timestamp: 1_700_000_000_000,
    ...teil,
  } as Nachricht
}

function text(w: ReturnType<typeof mount>): string {
  return w.find('.zeitleiste').text().replace(/\s+/g, ' ')
}

describe('Zeitleiste: abgeschlossener Turn', () => {
  const fertig = nachricht({
    isStreaming: false,
    stages: [
      { stage: 'Werkzeuge', von: 0, bis: 233.2, modellSekunden: 216.31 },
      { stage: 'Verifikation', von: 233.2, bis: 2763.9, modellSekunden: 2529.83 },
    ],
    usage: { elapsedS: 2763.9, llmSeconds: 2746.14 },
  })

  it('nennt je Stufe Dauer und Modellzeit', () => {
    const w = mount(ChatMessage, { props: { message: fertig } })
    const t = text(w)
    expect(t).toContain('Werkzeuge')
    expect(t).toContain('233,2 s')
    expect(t).toContain('216,3 s Modell')
    expect(t).toContain('Verifikation')
    expect(t).toContain('2.529,8 s Modell')
  })

  it('die Summe ist keine Untergrenze und nicht unvollstaendig', () => {
    const t = text(mount(ChatMessage, { props: { message: fertig } }))
    expect(t).not.toContain('ab ')
    expect(t).not.toContain('unvollständig')
    expect(t).not.toContain('läuft')
  })

  it('der Modellbalken sitzt im Stufenbalken', () => {
    const w = mount(ChatMessage, { props: { message: fertig } })
    expect(w.findAll('.zeitleiste-balken').length).toBe(2)
    expect(w.findAll('.zeitleiste-modell').length).toBe(2)
  })
})

describe('Zeitleiste: offene und abgebrochene Turns', () => {
  const stufen = [
    { stage: 'Werkzeuge', von: 0, bis: 19.3 },
    { stage: 'Verifikation', von: 19.3 },
  ]

  it('eine laufende Stufe sagt "läuft", nicht "0 s"', () => {
    // Der Fehler, den die Erstfassung hatte: ohne Ende fiel die Rechnung auf
    // den Anfang zurueck und behauptete 0 s fuer eine Stufe, die seit
    // Minuten lief.
    const w = mount(ChatMessage, {
      props: { message: nachricht({ isStreaming: true, stages: stufen }) },
    })
    const t = text(w)
    expect(t).toContain('läuft')
    expect(t).toContain('ab 19,3 s')
    expect(t).not.toMatch(/Verifikation 0 s/)
    expect(w.find('.zeitleiste-spur.ist-offen').exists()).toBe(true)
  })

  it('ein abgebrochener Turn sagt "ohne Ende" und laeuft nicht mehr', () => {
    // Ein Turn im Backstop schickt kein copilot.done mit elapsed_s.
    const w = mount(ChatMessage, {
      props: { message: nachricht({ isStreaming: false, stages: stufen }) },
    })
    const t = text(w)
    expect(t).toContain('ohne Ende')
    expect(t).toContain('unvollständig')
    expect(t).not.toContain('läuft')
    expect(w.find('.zeitleiste-spur.ist-offen').exists()).toBe(false)
  })

  it('die Summe zaehlt nur geschlossene Stufen', () => {
    const t = text(mount(ChatMessage, {
      props: { message: nachricht({ isStreaming: true, stages: stufen }) },
    }))
    expect(t).toContain('19,3 s')
  })
})

describe('Zeitleiste: ohne Daten kein Kasten', () => {
  it('ohne Stufen wird nichts gerendert', () => {
    // Positive Klasse: sonst stuende bei jeder Nachricht ein leerer Verlauf.
    const w = mount(ChatMessage, { props: { message: nachricht({}) } })
    expect(w.find('.zeitleiste').exists()).toBe(false)
  })

  it('ohne Modellzeit steht keine erfundene Null', () => {
    const w = mount(ChatMessage, {
      props: {
        message: nachricht({
          isStreaming: false,
          stages: [{ stage: 'Werkzeuge', von: 0, bis: 12 }],
          usage: { elapsedS: 12 },
        }),
      },
    })
    expect(text(w)).toContain('12 s')
    expect(text(w)).not.toContain('Modell')
    expect(w.find('.zeitleiste-modell').exists()).toBe(false)
  })
})

describe('Fusszeile nennt die Modellzeit', () => {
  it('Modellsekunden stehen neben der Turnzeit', () => {
    const w = mount(ChatMessage, {
      props: {
        message: nachricht({
          isStreaming: false,
          usage: { elapsedS: 17.4, llmCalls: 1, llmSeconds: 16.8, recipeId: 'frequenz' },
        }),
      },
    })
    const f = w.find('.usage-footer').text().replace(/\s+/g, ' ')
    expect(f).toContain('17,4 s')
    expect(f).toContain('16,8 s Modell')
  })

  it('ohne Modellzeit fehlt der Zusatz', () => {
    const w = mount(ChatMessage, {
      props: {
        message: nachricht({ isStreaming: false, usage: { elapsedS: 17.4, llmCalls: 1 } }),
      },
    })
    expect(w.find('.usage-footer').text()).not.toContain('Modell')
  })
})
