import { describe, expect, it } from 'vitest'

import {
  formatKwicTsv,
  formatSampleProvenance,
  type KwicCitationRow,
} from '@/lib/kwicCitation'

/**
 * Zitation der KWIC-Zufallsstichprobe (T1): kopierte/exportierte Tabellen einer
 * Stichprobe tragen die Provenienz (drawn, population, seed) als Kommentarzeile,
 * damit die Teilmenge wissenschaftlich zitierbar bleibt. Ohne Stichprobe bleibt
 * die TSV-Ausgabe byte-identisch zum Altpfad.
 */
describe('KWIC sample provenance citation', () => {
  const rows: KwicCitationRow[] = [
    { position: 3, left: 'links', match: 'Treffer', right: 'rechts', docId: 'd1' },
  ]

  it('formats the provenance line with seed and de-DE numbers', () => {
    expect(
      formatSampleProvenance({
        requested: 200,
        drawn: 200,
        seed: 42,
        population: 9740,
        populationPartial: false,
      })
    ).toBe('Zufallsstichprobe: 200 von 9.740 Treffern · Seed 42')
  })

  it('marks a partially enumerable population honestly', () => {
    expect(
      formatSampleProvenance({
        requested: 500,
        drawn: 500,
        seed: 0,
        population: 100000,
        populationPartial: true,
      })
    ).toBe('Zufallsstichprobe: 500 von 100.000 Treffern (Grundgesamtheit partiell) · Seed 0')
  })

  it('prepends the provenance as a # comment line in TSV copies', () => {
    const tsv = formatKwicTsv(rows, {
      sample: { requested: 10, drawn: 10, seed: 7, population: 55, populationPartial: false },
    })
    const lines = tsv.split('\n')
    expect(lines[0]).toBe('# Zufallsstichprobe: 10 von 55 Treffern · Seed 7')
    expect(lines[1]).toBe('position\tleft\tnode\tright\tsource\tdoc\tmatch\tmatch_start\tmatch_end')
    expect(lines[2]).toContain('Treffer')
  })

  it('stays byte-identical to the legacy output without a sample', () => {
    expect(formatKwicTsv(rows)).toBe(formatKwicTsv(rows, { sample: null }))
    expect(formatKwicTsv(rows).startsWith('position\t')).toBe(true)
  })
})
