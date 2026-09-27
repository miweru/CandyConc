/**
 * Die Ableitung der Arbeitsspur.
 *
 * Der Pruefstein fuer jede Angabe: stuende sie genauso da, wenn die Antwort
 * falsch waere? Deshalb pruefen diese Tests vor allem, was die Spur NICHT
 * behauptet.
 */
import { describe, it, expect } from 'vitest'
import { ref } from 'vue'
import { useArbeitsspur } from '@/composables/useArbeitsspur'
import type { ChatMessage } from '@/stores'

function nachricht(teil: Partial<ChatMessage>): ChatMessage {
  return {
    id: 'm1', role: 'assistant', content: '', timestamp: 0, ...teil,
  } as ChatMessage
}

describe('Stufen', () => {
  const m = ref(nachricht({
    isStreaming: false,
    stages: [
      { stage: 'Vorlauf', von: 0, bis: 189.5 },
      { stage: 'Werkzeuge', von: 189.5, bis: 422.7 },
      { stage: 'Verifikation', von: 422.7, bis: 2953.4 },
    ],
    usage: { elapsedS: 2953.4 },
  }))

  it('uebersetzt die Stufennamen', () => {
    const { stufen } = useArbeitsspur(m)
    expect(stufen.value.map(s => s.titel)).toEqual([
      'Frage eingeordnet', 'Im Korpus nachgeschlagen', 'Antwort gegengelesen',
    ])
  })

  it('rechnet die Dauern aus den Marken', () => {
    const { stufen } = useArbeitsspur(m)
    // Gleitkomma: 2953.4 - 422.7 ergibt 2530.7000000000003.
    const dauern = stufen.value.map(s => s.dauer ?? 0)
    expect(dauern[0]).toBeCloseTo(189.5, 4)
    expect(dauern[1]).toBeCloseTo(233.2, 4)
    expect(dauern[2]).toBeCloseTo(2530.7, 4)
  })

  it('der Vorlauf faellt NICHT unter den Tisch', () => {
    // Die Summe muss auch die Zeit vor dem ersten Werkzeug enthalten.
    const { stufen } = useArbeitsspur(m)
    const summe = stufen.value.reduce((s, a) => s + (a.dauer ?? 0), 0)
    expect(summe).toBeCloseTo(2953.4, 1)
  })

  it('eine laufende Stufe hat KEINE Dauer, nicht null', () => {
    const laufend = ref(nachricht({
      isStreaming: true,
      stages: [{ stage: 'Werkzeuge', von: 0 }],
    }))
    const { stufen, laeuft } = useArbeitsspur(laufend)
    expect(laeuft.value).toBe(true)
    expect(stufen.value[0]?.dauer).toBeUndefined()
  })

  it('ein abgebrochener Turn wird als solcher erkannt', () => {
    const ab = ref(nachricht({
      isStreaming: false,
      stages: [{ stage: 'Werkzeuge', von: 0, bis: 12 }, { stage: 'Verifikation', von: 12 }],
    }))
    const { abgebrochen } = useArbeitsspur(ab)
    expect(abgebrochen.value).toBe(true)
  })
})

describe('Werkzeuge', () => {
  it('Zwischenspeicher und Uebersprungenes sind gekennzeichnet', () => {
    // Eine Spur, die einen Zwischenspeicher-Treffer als geleistete Arbeit
    // zeigt, erzeugt Belege fuer Arbeit, die nicht stattgefunden hat.
    const m = ref(nachricht({
      toolCalls: [
        { id: 'a', name: 'query_count', arguments: { query: 'Kinder' }, status: 'success', result: { total: 21 } },
        { id: 'b', name: 'query_count', arguments: {}, status: 'success', result: {}, wiederverwendet: true },
        { id: 'c', name: 'keyness', arguments: {}, status: 'success', result: {}, uebersprungen: true },
      ],
    }))
    const { werkzeuge } = useArbeitsspur(m)
    expect(werkzeuge.value.map(w => [w.wiederverwendet, w.uebersprungen]))
      .toEqual([[false, false], [true, false], [false, true]])
  })

  it('die Kennzahl kommt aus dem benannten Feld', () => {
    const m = ref(nachricht({
      toolCalls: [{ id: 'a', name: 'query_count', arguments: {}, status: 'success', result: { total: 21 } }],
    }))
    expect(useArbeitsspur(m).werkzeuge.value[0]?.kennzahl).toEqual({ wert: 21, einheit: 'Treffer' })
  })
})

describe('Fortschritt', () => {
  it('bleibt waehrend der Arbeit unbestimmt', () => {
    // Die Zahl der Schritte steht nicht vorher fest. Ein Anteil waere eine
    // Erfindung, und eine, die man an der Wanduhr messen kann.
    const m = ref(nachricht({ isStreaming: true, toolCalls: [] }))
    expect(useArbeitsspur(m).fortschritt.value).toBe(-1)
  })

  it('ist nach dem Turn vollstaendig', () => {
    const m = ref(nachricht({
      isStreaming: false,
      toolCalls: [{ id: 'a', name: 'query_count', arguments: {}, status: 'success' }],
    }))
    expect(useArbeitsspur(m).fortschritt.value).toBe(1)
  })
})

describe('Methodensteckbrief', () => {
  const inhalt = 'Antwort.\n\n### Methodensteckbrief\n'
    + '- Zählung: Korpus bench, Abfragemodus: plain_word, Treffer: 21, Basis 56.191 Tokens.\n'
    + '- Dispersion: Suchform „Kinder", 21 Treffer\n\n## Weiteres\n- nicht mehr Teil davon: x'

  it('liest die Zeilen aus dem Antworttext', () => {
    const m = ref(nachricht({ content: inhalt }))
    const { steckbrief } = useArbeitsspur(m)
    expect(steckbrief.value.map(z => z.bezeichnung)).toEqual(['Zählung', 'Dispersion'])
  })

  it('reads the method card of an English answer', () => {
    const m = ref(nachricht({
      content: 'Answer.\n\n### Method card\n- Count: corpus sotu_en, hits: 330',
    }))
    expect(useArbeitsspur(m).steckbrief.value.map(x => x.bezeichnung)).toEqual(['Count'])
  })

  it('endet an der naechsten Ueberschrift', () => {
    const m = ref(nachricht({ content: inhalt }))
    expect(useArbeitsspur(m).steckbrief.value).toHaveLength(2)
  })

  it('zerlegt an Kommas, ohne Tausendertrennung zu zerreissen', () => {
    const m = ref(nachricht({ content: inhalt }))
    const angaben = useArbeitsspur(m).steckbrief.value[0]?.angaben ?? []
    expect(angaben).toContain('Basis 56.191 Tokens')
    expect(angaben).toContain('Treffer: 21')
  })

  it('ohne Steckbrief bleibt die Liste leer', () => {
    const m = ref(nachricht({ content: 'Nur Text.' }))
    expect(useArbeitsspur(m).steckbrief.value).toEqual([])
  })
})

describe('Wachen', () => {
  it('trennt Entfernungen von beratenden Hinweisen', () => {
    // Einen Hinweis als Entfernung zu zaehlen waere eine Uebertreibung in
    // die vermeintlich sichere Richtung.
    const m = ref(nachricht({
      annotations: [
        { rule: 'zitat_ohne_deckung_entfernt', note: '2 Zitat(e) ohne Deckung entfernt' },
        { rule: 'recipe_routing', note: 'stage=trigger recipe=frequenz' },
      ],
    }))
    const { wachen, entfernungen } = useArbeitsspur(m)
    expect(entfernungen.value).toBe(1)
    expect(wachen.value.map(w => w.entfernung)).toEqual([true, false])
  })

  it('ohne Annotationen ist nichts entfernt worden', () => {
    const m = ref(nachricht({}))
    expect(useArbeitsspur(m).entfernungen.value).toBe(0)
  })
})

describe('Nicht sauber beendete Turns', () => {
  it('ein gemeldeter Fehler gilt als nicht sauber beendet', () => {
    // "Abgeschlossen" stand im Kopf, waehrend die Chatblase "Fehler" zeigte:
    // `some` auf einer leeren Stufenliste ist false, und `usage` entsteht
    // nur aus copilot.done, das ein gescheiterter Turn nie bekommt.
    const m = ref(nachricht({ isStreaming: false, error: true } as never))
    expect(useArbeitsspur(m).abgebrochen.value).toBe(true)
  })

  it('beendet ohne jede Aufzeichnung und ohne Bilanz gilt als nicht sauber', () => {
    const m = ref(nachricht({ isStreaming: false }))
    expect(useArbeitsspur(m).abgebrochen.value).toBe(true)
  })

  it('ein sauberer Turn gilt NICHT als abgebrochen', () => {
    // Positive Klasse: sonst waere ein bedingungsloses true gruen.
    const m = ref(nachricht({
      isStreaming: false,
      stages: [{ stage: 'Werkzeuge', von: 0, bis: 12 }],
      usage: { elapsedS: 12 },
    }))
    expect(useArbeitsspur(m).abgebrochen.value).toBe(false)
  })

  it('ein laufender Turn gilt nie als abgebrochen', () => {
    const m = ref(nachricht({ isStreaming: true, stages: [{ stage: 'Werkzeuge', von: 0 }] }))
    expect(useArbeitsspur(m).abgebrochen.value).toBe(false)
  })
})

describe('Methodensteckbrief: der Block ist keine Garantie', () => {
  it('nimmt das LETZTE Vorkommen, nicht das erste', () => {
    // Das Backend haengt seinen Block ans ENDE an, und nur dann, wenn der
    // Text die Ueberschrift nicht schon fuehrt. Schreibt das Modell sie
    // selbst, steht sein Block VORNE. Das erste Vorkommen zu nehmen hiesse,
    // Modelltext als Messprovenienz auszugeben.
    const m = ref(nachricht({
      content: '### Methodensteckbrief\n- Pruefung: alles verifiziert\n\n'
        + 'Text.\n\n### Methodensteckbrief\n- Zaehlung: Korpus bench, Treffer: 21',
    }))
    const z = useArbeitsspur(m).steckbrief.value
    expect(z.map(x => x.bezeichnung)).toEqual(['Zaehlung'])
  })

  it('endet an der naechsten Ueberschrift', () => {
    const m = ref(nachricht({
      content: '### Methodensteckbrief\n- Zaehlung: x\n\n## Danach\n- Fremd: y',
    }))
    expect(useArbeitsspur(m).steckbrief.value.map(x => x.bezeichnung)).toEqual(['Zaehlung'])
  })
})

describe('Kennzahlen zeigen nur Felder, die es gibt', () => {
  it('die benannten Felder stimmen mit der Werkzeugausgabe ueberein', () => {
    // Nur Felder aus den Werkzeugantworten als Kennzahlen verwenden.
    const echt: Record<string, Record<string, number>> = {
      query_count: { total: 21 },
      run_cqlf_query: { total: 21 },
      frequency_list: { total: 100 },
      create_docset: { doc_count: 19 },
      collocate_stats: { result_count: 40 },
      dispersion_offsets: { n_documents: 19 },
      trend_analysis: { periods_total: 7 },
    }
    for (const [werkzeug, ergebnis] of Object.entries(echt)) {
      const m = ref(nachricht({
        toolCalls: [{ id: 'a', name: werkzeug, arguments: {}, status: 'success', result: ergebnis }],
      }))
      expect(useArbeitsspur(m).werkzeuge.value[0]?.kennzahl, werkzeug).not.toBeNull()
    }
  })

  it('Werkzeuge ohne Zahl auf oberster Ebene tragen keine Kennzahl', () => {
    // metadata_values und keyness liefern keine. Ein Feld, das nie
    // erscheint, erweckt den Eindruck, es sei nur gerade leer.
    for (const werkzeug of ['metadata_values', 'keyness']) {
      const m = ref(nachricht({
        toolCalls: [{ id: 'a', name: werkzeug, arguments: {}, status: 'success', result: { rows: [] } }],
      }))
      expect(useArbeitsspur(m).werkzeuge.value[0]?.kennzahl, werkzeug).toBeNull()
    }
  })
})
