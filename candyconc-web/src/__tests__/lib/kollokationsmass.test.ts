/**
 * Die Kollokationstafel beschriftet, was sie zeigt.
 *
 * LIVE GESEHEN am 2026-08-31. "Zeige mir Kollokationen zu Nachhaltigkeit"
 * lieferte eine nach logDice sortierte Rangfolge, und die Evidenztafel
 * schrieb "Mutual Information" darueber und fuellte sie mit MI-Zahlen:
 *
 *   ökologische 7,910 / ökologischer 8,086 / Gerechtigkeit 5,977 /
 *   Digitalisierung 5,384 / Umweltschutz 6,541
 *
 * Eine sichtbar unsortierte Spalte ueber einer sortierten Liste. Zwei
 * Ursachen, beide in der Anzeige:
 *
 * 1. Das Mass wurde aus den AUFRUFARGUMENTEN gelesen. Ohne ausdrueckliches
 *    sort_by sind die leer, obwohl die ANTWORT das wirksame Mass fuehrt.
 * 2. Die Rueckfallkette begann bei `mi`, und `logdice` kam gar nicht darin
 *    vor, obwohl es die Vorgabe des Motors ist.
 *
 * Das ist die Verwechslung zweier Assoziationsmasse in der Anzeige.
 */
import { describe, it, expect } from 'vitest'
import { collocationRowsForDisplay, displayMeasureForRow } from '@/lib/collocationMeasure'

/** Eine echte collocate_stats-Zeile fuehrt ALLE Masse nebeneinander. */
function zeile(word: string, f: number, logdice: number, mi: number) {
  return { word, f, f2: f * 3, observed: f, logdice, mi, dice: 0.012, ll: 42, t: 3.1 }
}

const ZEILEN = [
  zeile('ökologische', 127, 9.45, 7.9104),
  zeile('ökologischer', 31, 9.12, 8.0863),
  zeile('Gerechtigkeit', 80, 8.94, 5.9769),
]

describe('Massauswahl der Kollokationstafel', () => {
  it('nimmt das wirksame Mass aus der ANTWORT, wenn der Aufruf keines nennt', () => {
    const rows = collocationRowsForDisplay(ZEILEN, { wirksamesMass: 'logdice' })
    expect(rows.map((r) => r.measure)).toEqual(['logdice', 'logdice', 'logdice'])
    expect(rows.map((r) => r.score)).toEqual([9.45, 9.12, 8.94])
  })

  it('faellt ohne jede Angabe auf logDice, nicht auf MI', () => {
    // Die Rueckfallkette spiegelt COLLOCATE_SORT_PREFERENCE des Motors.
    expect(displayMeasureForRow(ZEILEN[0])).toBe('logdice')
    expect(collocationRowsForDisplay(ZEILEN)[0].score).toBe(9.45)
  })

  it('die Werte fallen monoton, so wie die Rangfolge es behauptet', () => {
    const werte = collocationRowsForDisplay(ZEILEN, { wirksamesMass: 'logdice' }).map((r) => r.score)
    for (let i = 1; i < werte.length; i += 1) {
      expect(werte[i]).toBeLessThanOrEqual(werte[i - 1])
    }
  })

  it('unter MI waeren dieselben Zeilen NICHT monoton, der Unterschied ist also sichtbar', () => {
    const werte = collocationRowsForDisplay(ZEILEN, { wirksamesMass: 'mi' }).map((r) => r.score)
    expect(werte).toEqual([7.9104, 8.0863, 5.9769])
    expect(werte[1]).toBeGreaterThan(werte[0])
  })

  it('ein ausdruecklich angefordertes Mass gewinnt ueber die Vorzugsreihenfolge', () => {
    const rows = collocationRowsForDisplay(ZEILEN, { angefordertesMass: 'mi' })
    expect(rows[0].measure).toBe('mi')
    expect(rows[0].score).toBe(7.9104)
  })

  it('die Antwort schlaegt den Aufruf, denn sie nennt das ANGEWANDTE Mass', () => {
    const rows = collocationRowsForDisplay(ZEILEN, {
      wirksamesMass: 'logdice',
      angefordertesMass: 'mi',
    })
    expect(rows[0].measure).toBe('logdice')
  })

  it('was die Zeile selbst sagt, schlaegt alles', () => {
    const rows = collocationRowsForDisplay(
      [{ ...ZEILEN[0], measure: 'll' }],
      { wirksamesMass: 'logdice' },
    )
    expect(rows[0].measure).toBe('ll')
    expect(rows[0].score).toBe(42)
  })

  it('mi2 bleibt als zurueckgezogenes Altmass kenntlich', () => {
    expect(displayMeasureForRow({ measure: 'mi2', f: 3 })).toBe('retired-mi2')
  })
})
