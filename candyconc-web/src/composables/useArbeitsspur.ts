/**
 * Die Arbeitsspur eines Turns, ABGELEITET statt gespeichert.
 *
 * Die Nachricht traegt bereits `stages`, `toolCalls`, `annotations` und
 * `usage`. Eine zweite Sammlung daneben waere eine zweite Wahrheit, und
 * zwei Wahrheiten ueber denselben Sachverhalt laufen auseinander. Hier
 * wird nur gelesen.
 *
 * WAS HIER NICHT BEHAUPTET WIRD. Die Spur zeigt, was getan wurde, und was
 * die deterministischen Wachen entfernt haben. Sie vergibt keine Note, kein
 * Haekchen, keinen Prozentwert. Der Grund ist nicht Bescheidenheit: eine
 * Selbstnote erscheint auch dann, wenn die Antwort falsch ist, und ist
 * damit genau dort wertlos, wo sie gebraucht wuerde. Der Pruefstein fuer
 * jede Angabe hier lautet: stuende sie genauso da, wenn die Antwort falsch
 * waere? Wenn nein, gehoert sie nicht hierher.
 */

import { computed, type ComputedRef, type Ref } from 'vue'
import type { ChatMessage, ChatMessageStage, ToolCall } from '@/stores'
import { abfrageFuer, kennzahlFuer, klartextFuer } from '@/lib/copilotKlartext'
import { t } from '@/i18n'

/**
 * Die Stufen des Backends in der Reihenfolge, in der sie auftreten. The keys
 * are the stage names the server sends, the texts resolve on access.
 */
const STUFEN_TEXT: Record<string, { readonly titel: string; readonly was: string }> = {
  Vorlauf: {
    get titel() { return t('copilot.traceStages.preludeTitle') },
    get was() { return t('copilot.traceStages.preludeText') },
  },
  Werkzeuge: {
    get titel() { return t('copilot.traceStages.toolsTitle') },
    get was() { return t('copilot.traceStages.toolsText') },
  },
  Verifikation: {
    get titel() { return t('copilot.traceStages.verificationTitle') },
    get was() { return t('copilot.traceStages.verificationText') },
  },
  Antwort: {
    get titel() { return t('copilot.traceStages.answerTitle') },
    get was() { return t('copilot.traceStages.answerText') },
  },
}

export interface SpurWerkzeug {
  id: string
  /** Alltagssprachliche Beschriftung, etwa "Im Korpus gezählt". */
  schritt: string
  erklaerung: string
  /** Der technische Name, immer sichtbar. Nichts wird versteckt. */
  technisch: string
  uebersetzt: boolean
  /** Die konkrete Abfrage, leer wenn noch unbekannt. */
  abfrage: string
  kennzahl: { wert: number; einheit: string } | null
  status: ToolCall['status']
  fehler?: string
  dauerMs?: number
  ergebnis?: unknown
  argumente: Record<string, unknown>
  /**
   * Aus dem Zwischenspeicher bedient: es lief KEINE Abfrage gegen den
   * Index. Muss sichtbar sein, sonst zeigt die Spur Arbeit, die nicht
   * stattgefunden hat.
   */
  wiederverwendet: boolean
  /** Uebersprungen: der Schritt wurde nicht ausgefuehrt. */
  uebersprungen: boolean
}

export interface SpurStufe {
  stufe: string
  titel: string
  was: string
  von: number
  /** `undefined` heisst: laeuft noch oder wurde ohne Ende abgebrochen. */
  dauer?: number
  modellSekunden?: number
  werkzeuge: SpurWerkzeug[]
}

/** Eine Angabe des Methodensteckbriefs. */
export interface SteckbriefZeile {
  bezeichnung: string
  wert: string
  /**
   * Derselbe Wert, an Kommas in einzelne Angaben zerlegt.
   *
   * Das Backend schreibt eine Zeile wie "Korpus X, Abfragemodus: plain_word,
   * Attribut: word, Gross-/Kleinschreibung ignoriert: ja, Suche: Kinder,
   * Treffer: 21, Basis 56.191 Tokens". Als Fliesstext ist das eine Wand.
   * Zerlegt sind es sieben Angaben, die man einzeln lesen kann. Der
   * Wortlaut bleibt UNVERAENDERT, es wird nur umbrochen.
   */
  angaben: string[]
}

export interface Wachenbefund {
  /** Die Kennung der Wache, unveraendert aus `claim_id`. */
  regel: string
  text: string
  /** Hat die Wache etwas ENTFERNT? Dann ist es eine Zahl, kein Hinweis. */
  entfernung: boolean
}

/**
 * Kennungen, bei denen eine Wache etwas aus der Antwort GESTRICHEN hat.
 *
 * Nur diese duerfen als "entfernt" gezaehlt werden. Alles andere ist ein
 * beratender Hinweis, und ihn als Entfernung zu zaehlen waere eine
 * Uebertreibung in die vermeintlich sichere Richtung.
 */
const ENTFERNUNGEN = new Set([
  'zitat_ohne_deckung_entfernt',
  'rueckfrage_zitat_ohne_deckung',
  'rueckfrage_platzhalter',
  'rueckfrage_verworfen',
])

// i18n-ignore-start: headings the server writes into the answer text, parsed here
const STECKBRIEF_UEBERSCHRIFTEN = ['### Methodensteckbrief', '### Method card']
// i18n-ignore-end

export interface Arbeitsspur {
  stufen: ComputedRef<SpurStufe[]>
  werkzeuge: ComputedRef<SpurWerkzeug[]>
  laufenderSchritt: ComputedRef<string>
  fortschritt: ComputedRef<number>
  steckbrief: ComputedRef<SteckbriefZeile[]>
  wachen: ComputedRef<Wachenbefund[]>
  entfernungen: ComputedRef<number>
  laeuft: ComputedRef<boolean>
  abgebrochen: ComputedRef<boolean>
}

export function useArbeitsspur(nachricht: Ref<ChatMessage | undefined>): Arbeitsspur {
  const laeuft = computed(() => Boolean(nachricht.value?.isStreaming))

  const werkzeuge = computed<SpurWerkzeug[]>(() => {
    const tcs = nachricht.value?.toolCalls ?? []
    return tcs.map((tc, i) => {
      const k = klartextFuer(tc.name)
      return {
        id: tc.id || `${tc.name}-${i}`,
        schritt: k.schritt,
        erklaerung: k.erklaerung,
        technisch: k.technisch,
        uebersetzt: k.uebersetzt,
        abfrage: abfrageFuer(tc.arguments),
        kennzahl: kennzahlFuer(tc.name, tc.result),
        status: tc.status,
        fehler: tc.error,
        dauerMs: tc.durationMs,
        ergebnis: tc.result,
        argumente: tc.arguments ?? {},
        wiederverwendet: tc.wiederverwendet === true,
        uebersprungen: tc.uebersprungen === true,
      }
    })
  })

  const stufen = computed<SpurStufe[]>(() => {
    const roh: ChatMessageStage[] = nachricht.value?.stages ?? []
    if (!roh.length) return []
    const schluss = nachricht.value?.usage?.elapsedS
    const wz = werkzeuge.value
    return roh.map((a, i) => {
      const naechste = roh[i + 1]
      const bis = a.bis ?? (i === roh.length - 1 ? schluss : naechste?.von)
      const text = STUFEN_TEXT[a.stage]
      return {
        stufe: a.stage,
        titel: text?.titel ?? a.stage,
        was: text?.was ?? '',
        von: a.von,
        // `undefined` heisst LAEUFT oder OHNE ENDE. Eine Null waere eine
        // Falschaussage ueber eine Stufe, die gerade arbeitet.
        dauer: bis === undefined ? undefined : Math.max(bis - a.von, 0),
        modellSekunden: a.modellSekunden,
        // Die Werkzeuge haengen an der Werkzeugstufe. Sie tragen zwar eigene
        // Startmarken, aber die Zuordnung ueber Zeitfenster waere bei
        // mehreren Werkzeugrunden bruechig, und ein falsch einsortierter
        // Schritt ist schlimmer als ein pauschal richtig einsortierter.
        werkzeuge: a.stage === 'Werkzeuge' && i === ersteWerkzeugstufe(roh) ? wz : [],
      }
    })
  })

  const laufenderSchritt = computed(() => {
    if (!laeuft.value) return ''
    const offen = werkzeuge.value.find(w => w.status === 'running')
    if (offen) return offen.schritt
    const stufe = nachricht.value?.status?.stage
    return stufe ? (STUFEN_TEXT[stufe]?.titel ?? stufe) : ''
  })

  /**
   * Ein Fortschrittswert zwischen 0 und 1, oder -1 fuer "unbekannt".
   *
   * Die Zahl der Schritte steht NICHT vorher fest: der Copilot entscheidet
   * waehrend des Turns, was er noch braucht. Ein Balken, der eine feste
   * Gesamtzahl vortaeuscht, waere eine Erfindung. Deshalb gibt es hier
   * einen Anteil nur, wenn der Turn ABGESCHLOSSEN ist, und waehrenddessen
   * eine unbestimmte Anzeige.
   */
  const fortschritt = computed(() => {
    if (laeuft.value) return -1
    const alle = werkzeuge.value.length
    if (!alle) return 1
    return werkzeuge.value.filter(w => w.status !== 'running').length / alle
  })

  /**
   * Der Methodensteckbrief aus dem Antworttext.
   *
   * ER IST KEINE GARANTIE. Das Backend haengt ihn nur an, wenn der
   * Grundtext die Ueberschrift NICHT schon fuehrt
   * (recipe_runtime.py:2028). Der Waechter unterscheidet nicht, WER sie
   * geschrieben hat: schreibt das Modell die Ueberschrift selbst, tritt
   * das Backend zurueck, und der Block ist reiner Modelltext. Das Format
   * ist dem Modell bekannt, weil polierte Antworten samt Steckbrief in die
   * Sitzungshistorie gehen. Der Anhang entfaellt ausserdem bei fehlenden
   * Provenienzzeilen und bei jeder Ausnahme.
   *
   * Deshalb: LETZTES Vorkommen statt des ersten (der vom Backend
   * angehaengte steht am Ende), und eine harte Endmarke. Und die Ansicht
   * darf NICHT behaupten, der Harness haenge das an jede Antwort.
   */
  const steckbrief = computed<SteckbriefZeile[]>(() => {
    const text = nachricht.value?.content ?? ''
    // The last method card of the answer, in the language the answer uses.
    let i = -1
    let kopf = ''
    for (const u of STECKBRIEF_UEBERSCHRIFTEN) {
      const j = text.lastIndexOf(u)
      if (j > i) {
        i = j
        kopf = u
      }
    }
    if (i < 0) return []
    const rest = text.slice(i + kopf.length)
    const zeilen: SteckbriefZeile[] = []
    for (const roh of rest.split('\n')) {
      const z = roh.trim()
      if (!z) continue
      // Der Block endet an der naechsten Ueberschrift.
      if (z.startsWith('#')) break
      const m = /^[-*]\s*([^:]{2,60}):\s*(.+)$/.exec(z)
      if (!m) continue
      const wert = (m[2] ?? '').trim()
      zeilen.push({
        bezeichnung: (m[1] ?? '').trim(),
        wert,
        // Nur an Kommas, die von einem Leerzeichen gefolgt sind: eine
        // Tausendertrennung wie "56.191" bleibt damit heil, und ein
        // Dezimalkomma in "0,38" ebenso.
        angaben: wert.split(/,\s+/).map(teil => teil.trim().replace(/\.$/, '')).filter(Boolean),
      })
    }
    return zeilen
  })

  const wachen = computed<Wachenbefund[]>(() => {
    const roh = nachricht.value?.annotations ?? []
    return roh
      .filter(a => (a.note ?? '').trim())
      .map(a => {
        const regel = (a.rule ?? '').trim()
        return {
          regel,
          text: (a.note ?? '').trim(),
          entfernung: ENTFERNUNGEN.has(regel),
        }
      })
  })

  const entfernungen = computed(() => wachen.value.filter(w => w.entfernung).length)

  /**
   * Der Turn endete NICHT sauber.
   *
   * Drei Faelle, und der dritte fehlte: eine offene Stufe, gar keine Stufe
   * bei einem beendeten Turn, und ein gemeldeter Fehler. `some` auf einer
   * leeren Liste ist false, und `usage` entsteht nur aus `copilot.done` -
   * ein gescheiterter Turn hat weder Stufen noch usage. Ohne den dritten
   * Fall stand im Kopf "Abgeschlossen", waehrend die Chatblase "Fehler"
   * zeigte.
   */
  const abgebrochen = computed(() => {
    if (laeuft.value) return false
    const m = nachricht.value
    if (!m) return false
    if ((m as { error?: unknown }).error === true) return true
    if (stufen.value.some(a => a.dauer === undefined)) return true
    // Beendet, aber ohne jede Aufzeichnung UND ohne Abschlussbilanz: der
    // Stream ist gegangen, bevor irgendetwas gemeldet wurde.
    return !stufen.value.length && m.usage === undefined
  })

  return {
    stufen, werkzeuge, laufenderSchritt, fortschritt,
    steckbrief, wachen, entfernungen, laeuft, abgebrochen,
  }
}

function ersteWerkzeugstufe(roh: ChatMessageStage[]): number {
  return roh.findIndex(a => a.stage === 'Werkzeuge')
}
