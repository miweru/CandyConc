/**
 * Die Werkzeuge des Copiloten in Alltagssprache.
 *
 * Neben `COPILOT_TOOL_METADATA`, nicht anstelle. Jene Tabelle ist richtig
 * fuer die Werkzeugkarten im Chat, die Fachleute lesen: "Keyness",
 * "Word Sketch", "CQLF-/KWIC-Suche" sind dort die korrekten Namen. Fuer
 * jemanden, der das Verfahren nicht kennt, sind sie eine Mauer.
 *
 * TONLAGE. Die Leserinnen und Leser sind Fachleute ihres eigenen Gebiets,
 * nur nicht der Korpuslinguistik. Also keine Anrede, kein Verniedlichen,
 * keine Ausrufezeichen, kein "wir haben fuer Sie". Praezise und knapp wie
 * eine gute Bildunterschrift.
 *
 * UMFANG. 32 Werkzeuge sind registriert, aber die acht Rezepte planen nur
 * elf davon, und die tragen die Masse der Aufrufe: metadata_values,
 * frequency_list, run_cqlf_query, create_docset, collocate_stats, keyness,
 * query_count, trend_analysis, word_sketch, dispersion_offsets,
 * semantic_search. Dort muss die Uebersetzung sitzen. Fuer alles andere
 * gibt es einen ehrlichen Rueckfall, der den technischen Namen zeigt statt
 * eine Beschriftung zu erfinden.
 */

import { t } from '@/i18n'

export interface Klartext {
  /** Zwei bis vier Woerter fuer die Schrittliste. */
  schritt: string
  /** Ein Satz ohne Fachjargon: was der Schritt tatsaechlich tut. */
  erklaerung: string
  /**
   * Der Feldname im Ergebnis, der den Schritt zusammenfasst, und wie er
   * benannt wird. Ohne Eintrag zeigt der Schritt keine Zahl, statt eine
   * beliebige aus dem Ergebnis zu greifen.
   */
  kennzahl?: { feld: string; einheit: string }
}

/** Catalog keys of one entry. Texts resolve on access, never at module load. */
interface KlartextKeys {
  stepKey: string
  explanationKey: string
  kennzahl?: { feld: string; unitKey: string }
}

const KLARTEXT_KEYS: Record<string, KlartextKeys> = {
  // --- Die elf, die die Rezepte planen -------------------------------------
  query_count: {
    stepKey: 'copilot.plainText.queryCountStep',
    explanationKey: 'copilot.plainText.queryCountText',
    kennzahl: { feld: 'total', unitKey: 'copilot.plainText.unitHits' },
  },
  run_cqlf_query: {
    stepKey: 'copilot.plainText.runQueryStep',
    explanationKey: 'copilot.plainText.runQueryText',
    kennzahl: { feld: 'total', unitKey: 'copilot.plainText.unitHits' },
  },
  frequency_list: {
    stepKey: 'copilot.plainText.frequencyListStep',
    explanationKey: 'copilot.plainText.frequencyListText',
    kennzahl: { feld: 'total', unitKey: 'copilot.plainText.unitEntries' },
  },
  metadata_values: {
    stepKey: 'copilot.plainText.metadataValuesStep',
    explanationKey: 'copilot.plainText.metadataValuesText',
    // No key figure: the tool answer has no number at the top level. A
    // field that never appears gives the impression it is merely empty.
  },
  create_docset: {
    stepKey: 'copilot.plainText.createDocsetStep',
    explanationKey: 'copilot.plainText.createDocsetText',
    kennzahl: { feld: 'doc_count', unitKey: 'copilot.plainText.unitTexts' },
  },
  collocate_stats: {
    stepKey: 'copilot.plainText.collocateStatsStep',
    explanationKey: 'copilot.plainText.collocateStatsText',
    // result_count, NICHT total. Gemessen gegen den Wrapper.
    kennzahl: { feld: 'result_count', unitKey: 'copilot.plainText.unitCollocates' },
  },
  keyness: {
    // "Zwei Bestaende verglichen" war falsch: das Werkzeug vergleicht den
    // KONTEXT eines Knotens gegen den REST des Korpus, nicht zwei vom
    // Nutzer gewaehlte Bestaende.
    stepKey: 'copilot.plainText.keynessStep',
    explanationKey: 'copilot.plainText.keynessText',
    // Keine Kennzahl: die Antwort traegt auf oberster Ebene keine Zahl.
  },
  dispersion_offsets: {
    stepKey: 'copilot.plainText.dispersionStep',
    explanationKey: 'copilot.plainText.dispersionText',
    // n_documents, NICHT document_count. Gemessen gegen den Wrapper.
    kennzahl: { feld: 'n_documents', unitKey: 'copilot.plainText.unitTexts' },
  },
  trend_analysis: {
    stepKey: 'copilot.plainText.trendStep',
    explanationKey: 'copilot.plainText.trendText',
    kennzahl: { feld: 'periods_total', unitKey: 'copilot.plainText.unitPeriods' },
  },
  word_sketch: {
    stepKey: 'copilot.plainText.wordSketchStep',
    explanationKey: 'copilot.plainText.wordSketchText',
  },
  semantic_search: {
    stepKey: 'copilot.plainText.semanticSearchStep',
    explanationKey: 'copilot.plainText.semanticSearchText',
    kennzahl: { feld: 'total', unitKey: 'copilot.plainText.unitPassages' },
  },

  // --- Haeufig genug, um eine eigene Beschriftung zu verdienen --------------
  similar_words: {
    stepKey: 'copilot.plainText.similarWordsStep',
    explanationKey: 'copilot.plainText.similarWordsText',
  },
  collocation_network: {
    stepKey: 'copilot.plainText.collocationNetworkStep',
    explanationKey: 'copilot.plainText.collocationNetworkText',
  },
  contrast_collocates: {
    stepKey: 'copilot.plainText.contrastCollocatesStep',
    explanationKey: 'copilot.plainText.contrastCollocatesText',
  },
  compare_collocates: {
    stepKey: 'copilot.plainText.contrastCollocatesStep',
    explanationKey: 'copilot.plainText.contrastCollocatesText',
  },
  parallel_kwic: {
    stepKey: 'copilot.plainText.parallelKwicStep',
    explanationKey: 'copilot.plainText.parallelKwicText',
  },
  lexical_diversity: {
    stepKey: 'copilot.plainText.lexicalDiversityStep',
    explanationKey: 'copilot.plainText.lexicalDiversityText',
  },
  corpus_info: {
    stepKey: 'copilot.plainText.corpusInfoStep',
    explanationKey: 'copilot.plainText.corpusInfoText',
  },
}

function klartextEntry(keys: KlartextKeys): Klartext {
  const entry: Klartext = {
    get schritt() { return t(keys.stepKey) },
    get erklaerung() { return t(keys.explanationKey) },
  }
  const kennzahl = keys.kennzahl
  if (kennzahl) {
    entry.kennzahl = {
      feld: kennzahl.feld,
      get einheit() { return t(kennzahl.unitKey, 2) },
    }
  }
  return entry
}

export const KLARTEXT: Record<string, Klartext> = Object.fromEntries(
  Object.entries(KLARTEXT_KEYS).map(([name, keys]) => [name, klartextEntry(keys)]),
)

/**
 * Display name of a backend stage (`copilot.status` stage). The stage name is
 * protocol and stays as it is for comparisons, only the label is translated.
 * Unknown stages are shown unchanged.
 */
export function copilotStageLabel(stage: string): string {
  // i18n-ignore-start: stage names sent by the server
  if (stage === 'Vorlauf') return t('copilot.stages.prelude')
  if (stage === 'Werkzeuge') return t('copilot.stages.tools')
  if (stage === 'Verifikation') return t('copilot.stages.verification')
  if (stage === 'Antwort') return t('copilot.stages.answer')
  // i18n-ignore-end
  return stage
}

/** Die Argumente, die als konkrete Abfrage taugen, in Anzeigereihenfolge. */
const ABFRAGE_FELDER = [
  'query', 'term', 'word', 'node', 'pattern', 'field', 'attribute', 'search',
] as const

export interface KlartextSchritt {
  schritt: string
  erklaerung: string
  /** Der technische Name, immer mitgeführt. Nichts wird versteckt. */
  technisch: string
  /** Ob eine Übersetzung vorlag oder der Rückfall greift. */
  uebersetzt: boolean
}

export function klartextFuer(werkzeug: string): KlartextSchritt {
  const name = String(werkzeug || '').trim()
  const k = KLARTEXT[name]
  if (k) {
    return { schritt: k.schritt, erklaerung: k.erklaerung, technisch: name, uebersetzt: true }
  }
  // Kein erfundenes Label. Wer den technischen Namen sieht, weiss wenigstens,
  // dass hier nichts uebersetzt wurde, statt eine gefaellige Umschreibung zu
  // lesen, die vielleicht das Falsche behauptet.
  return {
    schritt: name || t('copilot.plainText.stepFallback'),
    erklaerung: t('copilot.plainText.noDescription'),
    technisch: name,
    uebersetzt: false,
  }
}

/**
 * Die eine Zahl, die den Schritt zusammenfasst, samt Einheit.
 *
 * `null`, wenn das Werkzeug keine benannte Kennzahl hat oder das Feld im
 * Ergebnis fehlt. Eine beliebige Zahl aus dem Ergebnis zu greifen waere
 * schlimmer als keine: sie stuende gross da und bedeutete nichts.
 */
export function kennzahlFuer(
  werkzeug: string,
  ergebnis: unknown,
): { wert: number; einheit: string } | null {
  const k = KLARTEXT_KEYS[String(werkzeug || '').trim()]
  if (!k?.kennzahl) return null
  if (!ergebnis || typeof ergebnis !== 'object') return null
  const roh = (ergebnis as Record<string, unknown>)[k.kennzahl.feld]
  if (typeof roh !== 'number' || !Number.isFinite(roh)) return null
  return { wert: roh, einheit: t(k.kennzahl.unitKey, roh) }
}

/**
 * Die konkrete Abfrage eines Aufrufs, als kurzer Text.
 *
 * Leer, wenn keine Argumente vorliegen. Das ist ein echter Zustand: eine
 * Karte, die aus dem `start`-Ereignis stammt, kennt sie noch nicht.
 */
export function abfrageFuer(argumente: Record<string, unknown> | undefined): string {
  if (!argumente) return ''
  for (const feld of ABFRAGE_FELDER) {
    const wert = argumente[feld]
    if (typeof wert === 'string' && wert.trim()) return wert.trim()
  }
  return ''
}
