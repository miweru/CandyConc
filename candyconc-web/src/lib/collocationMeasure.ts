/**
 * Shared wire-to-UI mapping for the collocation measures the backend exposes.
 * Keeping it in one place prevents a Copilot request, a background job, and the
 * visible table from silently selecting different statistics.
 */
export const COLLOCATION_MEASURES = [
  'mi',
  'mi3',
  'logdice',
  'dice',
  'tscore',
  'lmi',
  'npmi',
  'z',
  'chi2_cell',
  'll',
  'f',
  'delta_p_nc',
  'delta_p_cn',
] as const

export type CollocationMeasure = (typeof COLLOCATION_MEASURES)[number]

export const COLLOCATION_SORT_KEYS = [
  'mi',
  'mi3',
  'lmi',
  'npmi',
  'z',
  'chi2_cell',
  'dice',
  'logdice',
  't',
  'll',
  'f',
  'delta_p_nc',
  'delta_p_cn',
] as const

export type CollocationSortKey = (typeof COLLOCATION_SORT_KEYS)[number]

export function collocationSortKeyForMeasure(measure: CollocationMeasure): CollocationSortKey {
  return measure === 'tscore' ? 't' : measure
}

/** Convert a tool/API spelling into the exact measure the UI can display. */
export function parseCollocationMeasure(value: unknown): CollocationMeasure | undefined {
  if (typeof value !== 'string') return undefined
  switch (value.trim().toLowerCase()) {
    case 't':
    case 'tscore':
      return 'tscore'
    case 'frequency':
    case 'freq':
    case 'f':
      return 'f'
    case 'mi':
    case 'mi3':
    case 'logdice':
    case 'dice':
    case 'lmi':
    case 'npmi':
    case 'z':
    case 'chi2_cell':
    case 'll':
    case 'delta_p_nc':
    case 'delta_p_cn':
      return value.trim().toLowerCase() as CollocationMeasure
    default:
      return undefined
  }
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** Read one row's selected statistic without substituting a different measure. */
export function collocationScoreForRow(
  row: Record<string, unknown>,
  measure: CollocationMeasure,
): number {
  if (measure === 'logdice') {
    const direct = finiteNumber(row.logdice ?? row.logDice)
    if (direct !== null) return direct
    const dice = finiteNumber(row.dice)
    return dice !== null && dice > 0 ? 14 + Math.log2(dice) : 0
  }

  const selected = finiteNumber(row[collocationSortKeyForMeasure(measure)])
  if (selected !== null) return selected
  if (measure === 'f') {
    return finiteNumber(row.observed ?? row.frequency) ?? 0
  }

  // Old saved rows can lack a requested column. Keep the row visible, but do
  // not relabel a fallback value as the requested statistic in new responses.
  return finiteNumber(
    row.mi ?? row.lmi ?? row.npmi ?? row.z ?? row.chi2_cell ?? row.t ?? row.ll ?? row.dice,
  ) ?? 0
}


/**
 * Vorzugsreihenfolge, wenn weder Zeile noch Aufruf ein Mass nennen.
 *
 * Spiegelt ``analysis_defaults.COLLOCATE_SORT_PREFERENCE`` des Motors
 * (logdice, dice, ll, t, f). Die Anzeige hatte eine EIGENE Kette, die bei
 * ``mi`` begann und ``logdice`` gar nicht enthielt.
 */
const ANZEIGE_VORZUG: CollocationMeasure[] = [
  'logdice', 'dice', 'll', 'tscore', 'mi', 'lmi', 'npmi', 'z', 'chi2_cell', 'f',
]

/** ``mi2`` ist ein zurueckgezogenes Altmass und wird als solches benannt. */
export function displayMeasureName(value: unknown): CollocationMeasure | 'retired-mi2' | null {
  if (typeof value !== 'string') return null
  if (value.trim().toLowerCase() === 'mi2') return 'retired-mi2'
  return parseCollocationMeasure(value) ?? null
}

/**
 * Das Mass EINER Kollokatzeile, in der Reihenfolge seiner Verbindlichkeit.
 *
 * 1. was die Zeile selbst sagt (``measure``/``score_key``)
 * 2. das WIRKSAME Mass aus der Werkzeugantwort (``result.sort_by``)
 * 3. was der Aufruf angefordert hatte
 * 4. die Vorzugsreihenfolge des Motors
 *
 * Punkt 2 fehlte, und das ist der Kern des Defekts: ohne ausdrueckliches
 * ``sort_by`` sind die Aufrufargumente leer, waehrend die Antwort das
 * angewandte Mass sehr wohl fuehrt. Die Anzeige fiel deshalb auf Punkt 4,
 * und Punkt 4 begann bei ``mi``.
 *
 * LIVE GESEHEN am 2026-08-31: "Kollokationen zu Nachhaltigkeit" ergab eine
 * nach logDice sortierte Liste unter der Ueberschrift "Mutual Information"
 * mit MI-Zahlen darin. Zwei verschiedene Assoziationsmasse in einer
 * Tabelle, ohne dass etwas darauf hinwies.
 */
export function displayMeasureForRow(
  row: Record<string, unknown>,
  wirksamesMass?: unknown,
  angefordertesMass?: unknown,
): CollocationMeasure | 'retired-mi2' {
  const ausZeile = displayMeasureName(row.measure ?? row.score_key)
  if (ausZeile) return ausZeile
  const ausAntwort = displayMeasureName(wirksamesMass)
  if (ausAntwort) return ausAntwort
  const ausAufruf = displayMeasureName(angefordertesMass)
  if (ausAufruf) return ausAufruf
  for (const kandidat of ANZEIGE_VORZUG) {
    if (row[collocationSortKeyForMeasure(kandidat)] != null) return kandidat
  }
  return 'f'
}

/** Die Zeilen der Kollokationstafel, mit dem Mass, das wirklich gerechnet wurde. */
export function collocationRowsForDisplay(
  rows: Array<Record<string, unknown>>,
  optionen: { wirksamesMass?: unknown; angefordertesMass?: unknown } = {},
) {
  return rows.map((row) => {
    const word = String(row.word ?? row.term ?? '\u2014')
    const frequency = Number(row.frequency ?? row.f ?? 0)
    const measure = displayMeasureForRow(row, optionen.wirksamesMass, optionen.angefordertesMass)
    const selectedScore = measure !== 'retired-mi2' ? collocationScoreForRow(row, measure) : null
    const scoreSource = row.score ?? selectedScore ?? row.chi2_cell ?? row.mi ?? frequency
    return {
      word,
      frequency,
      score: Number(scoreSource),
      measure,
      observed: typeof row.observed === 'number' ? row.observed : frequency,
      expected: typeof row.expected === 'number' ? row.expected : null,
      chi2Cell: typeof row.chi2_cell === 'number' ? row.chi2_cell : null,
    }
  })
}
