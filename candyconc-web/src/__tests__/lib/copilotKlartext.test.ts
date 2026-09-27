/**
 * Die Werkzeuge in Alltagssprache.
 *
 * Zwei Zusicherungen, beide gegen dieselbe Versuchung: eine gefaellige
 * Beschriftung zu erfinden, wo keine vorliegt, und eine beliebige Zahl
 * gross herauszustellen, die nichts bedeutet.
 */
import { describe, it, expect } from 'vitest'
import { KLARTEXT, abfrageFuer, kennzahlFuer, klartextFuer } from '@/lib/copilotKlartext'

describe('klartextFuer', () => {
  it('uebersetzt die Werkzeuge, die die Rezepte planen', () => {
    // Diese elf tragen die Masse der Aufrufe. Faellt eines heraus, sieht
    // die Mehrheit der Nutzer einen technischen Namen.
    const geplant = [
      'query_count', 'run_cqlf_query', 'frequency_list', 'metadata_values',
      'create_docset', 'collocate_stats', 'keyness', 'dispersion_offsets',
      'trend_analysis', 'word_sketch', 'semantic_search',
    ]
    for (const t of geplant) {
      const k = klartextFuer(t)
      expect(k.uebersetzt, t).toBe(true)
      expect(k.schritt.length, t).toBeGreaterThan(3)
      expect(k.erklaerung.length, t).toBeGreaterThan(20)
    }
  })

  it('erfindet keine Beschriftung fuer Unbekanntes', () => {
    // Positive Klasse: wer den technischen Namen sieht, weiss wenigstens,
    // dass hier nichts uebersetzt wurde.
    const k = klartextFuer('irgendein_neues_werkzeug')
    expect(k.uebersetzt).toBe(false)
    expect(k.schritt).toBe('irgendein_neues_werkzeug')
    expect(k.erklaerung).toMatch(/keine Beschreibung/)
  })

  it('fuehrt den technischen Namen immer mit', () => {
    expect(klartextFuer('query_count').technisch).toBe('query_count')
    expect(klartextFuer('fremd').technisch).toBe('fremd')
  })

  it('keine Anrede, keine Ausrufezeichen', () => {
    // Fachleute ihres eigenen Gebiets, nicht dieses Werkzeugs. Nicht
    // bevormunden, nicht verniedlichen.
    for (const [name, k] of Object.entries(KLARTEXT)) {
      const text = `${k.schritt} ${k.erklaerung}`
      expect(text, name).not.toMatch(/!/)
      expect(text, name).not.toMatch(/\b(du|dir|dich|Sie|Ihnen|Ihre|wir|uns)\b/)
    }
  })
})

describe('kennzahlFuer', () => {
  it('kein benanntes Feld ohne Beleg in der echten Ausgabe', () => {
    // Fuenf von zehn Feldnamen existierten in keiner Werkzeugantwort:
    // metadata_values und keyness haben gar keine Zahl auf oberster Ebene,
    // collocate_stats liefert result_count statt total, dispersion_offsets
    // n_documents statt document_count. Gemessen gegen die Wrapper.
    const gemessen: Record<string, string | null> = {
      query_count: 'total',
      run_cqlf_query: 'total',
      frequency_list: 'total',
      metadata_values: null,
      create_docset: 'doc_count',
      collocate_stats: 'result_count',
      keyness: null,
      dispersion_offsets: 'n_documents',
      trend_analysis: 'periods_total',
    }
    for (const [werkzeug, feld] of Object.entries(gemessen)) {
      expect(KLARTEXT[werkzeug]?.kennzahl?.feld ?? null, werkzeug).toBe(feld)
    }
  })

  it('liest das benannte Feld', () => {
    expect(kennzahlFuer('query_count', { total: 61 }))
      .toEqual({ wert: 61, einheit: 'Treffer' })
  })

  it('greift KEINE beliebige Zahl, wenn das Feld fehlt', () => {
    // Eine Zahl aus dem Ergebnis zu nehmen, nur weil sie da ist, waere
    // schlimmer als keine: sie stuende gross da und bedeutete nichts.
    expect(kennzahlFuer('query_count', { irgendwas: 999, count: 5 })).toBeNull()
  })

  it('ohne benannte Kennzahl gibt es keine', () => {
    expect(kennzahlFuer('word_sketch', { total: 42 })).toBeNull()
  })

  it('unbrauchbare Werte werden verworfen', () => {
    expect(kennzahlFuer('query_count', { total: 'viele' })).toBeNull()
    expect(kennzahlFuer('query_count', { total: NaN })).toBeNull()
    expect(kennzahlFuer('query_count', null)).toBeNull()
  })
})

describe('abfrageFuer', () => {
  it('findet die Abfrage in den ueblichen Feldern', () => {
    expect(abfrageFuer({ query: 'Kinder' })).toBe('Kinder')
    expect(abfrageFuer({ term: 'Migration' })).toBe('Migration')
    expect(abfrageFuer({ field: 'register' })).toBe('register')
  })

  it('ohne Argumente bleibt sie leer', () => {
    // Ein echter Zustand: eine Karte aus dem start-Ereignis kennt sie noch nicht.
    expect(abfrageFuer(undefined)).toBe('')
    expect(abfrageFuer({})).toBe('')
    expect(abfrageFuer({ limit: 20 })).toBe('')
  })
})
