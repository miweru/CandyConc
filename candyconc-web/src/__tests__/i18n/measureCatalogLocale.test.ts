/**
 * The measure pickers read name, explanation and reference from the catalog
 * generated from the backend METHOD_META pairs (scripts/generate_measure_catalog.py).
 * German must equal the German mirror, English must resolve for every measure.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { applyLocale } from '@/i18n/locale'
import { MEASURE_CATALOG, measureCatalogEntry } from '@/lib/measureCatalog'

afterEach(() => {
  applyLocale('de')
})

describe('measure catalog in the interface language', () => {
  it('German shows the mirrored backend text unchanged', () => {
    applyLocale('de')
    for (const [key, entry] of Object.entries(MEASURE_CATALOG)) {
      const localized = measureCatalogEntry(key)
      expect(localized?.name, `${key}.name`).toBe(entry.name)
      expect(localized?.explanation, `${key}.explanation`).toBe(entry.explanation)
      expect(localized?.reference, `${key}.reference`).toBe(entry.reference)
      expect(localized?.formula_mathml, `${key}.formula_mathml`).toBe(entry.formula_mathml)
    }
  })

  it('English translates every explanation and keeps formulas and sort keys', () => {
    applyLocale('en')
    for (const [key, entry] of Object.entries(MEASURE_CATALOG)) {
      const localized = measureCatalogEntry(key)
      expect(localized, key).not.toBeNull()
      expect(localized!.explanation, `${key}.explanation`).not.toBe(entry.explanation)
      expect(localized!.explanation, `${key}.explanation`).not.toMatch(/[äöüß]/)
      // The backend translates the words inside \text{} and the abbreviation KI (CI), the math stays identical.
      const mathOnly = (latex: string) =>
        latex.replace(/\\text\{[^}]*\}/g, '\\text{}').replace(/\\mathrm\{KI\}/g, '\\mathrm{CI}')
      expect(mathOnly(localized!.latex_formula)).toBe(mathOnly(entry.latex_formula))
      expect(localized!.sort_key).toBe(entry.sort_key)
    }
    expect(measureCatalogEntry('mi3')?.name).toBe('MI3 (cubic MI)')
    expect(measureCatalogEntry('tscore')?.name).toBe('t-score')
    expect(measureCatalogEntry('frequency')?.formula_mathml).toContain('<mtext>occurrences</mtext>')
    expect(measureCatalogEntry('lrc')?.explanation).toContain('O11/|W(u)|')
  })
})
