import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { MEASURE_CATALOG, MEASURE_CATALOG_EN, measureCatalogEntry } from '@/lib/measureCatalog'

/**
 * KONTRAKT-TEST (Messlatte S3, Formel-Tooltips): der statische Frontend-Spiegel
 * `lib/measureCatalog.ts` MUSS byte-identisch zu den Methodenkatalog-Feldern des
 * Backends sein (candyconc.analysis_defaults.METHOD_META, Track T4). Der Spiegel
 * existiert nur, damit die Mass-Picker Formel/Erklärung/Referenz schon VOR der
 * ersten Analyse zeigen können; die Server-Wahrheit bleibt der method-Block.
 *
 * Der Test lädt METHOD_META über den Projekt-venv-Python-Interpreter und
 * vergleicht Feld für Feld. Ohne auffindbaren Interpreter (z. B. nacktes CI ohne
 * Backend-venv) wird die Suite mit sichtbarem Skip übersprungen — der Spiegel
 * wird dann ausschließlich durch die Backend-Tests (test_method_catalog_t4.py)
 * gedeckt.
 */

const here = dirname(fileURLToPath(import.meta.url))
// candyconc-web/src/__tests__/lib -> vier Ebenen hoch = Repo-Root.
const repoRoot = resolve(here, '..', '..', '..', '..')
const appSrc = resolve(repoRoot, 'app', 'src')

function resolvePython(): string | null {
  const candidates = [
    process.env.CANDYCONC_PYTHON,
    resolve(repoRoot, '.venv', 'bin', 'python'),
    resolve(repoRoot, '.venv', 'Scripts', 'python.exe'),
  ].filter((value): value is string => Boolean(value))
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate
  }
  return null
}

const python = resolvePython()

type BackendEntry = Record<string, string>

function loadBackendMethodMeta(interpreter: string, language: 'de' | 'en' = 'de'): Record<string, BackendEntry> {
  const script = [
    'import json, sys',
    `sys.path.insert(0, ${JSON.stringify(appSrc)})`,
    'from candyconc.analysis_defaults import METHOD_META',
    'from candyconc.i18n import localize',
    `print(json.dumps(localize(METHOD_META, ${JSON.stringify(language)}), ensure_ascii=False))`,
  ].join('\n')
  const stdout = execFileSync(interpreter, ['-c', script], {
    encoding: 'utf8',
    timeout: 60_000,
  })
  return JSON.parse(stdout) as Record<string, BackendEntry>
}

const CONTRACT_FIELDS = [
  'name',
  'latex_formula',
  'smoothing',
  'sort_key',
  'formula_mathml',
  'explanation',
  'reference',
] as const

describe.skipIf(python === null)('measureCatalog mirror == backend METHOD_META', () => {
  it('pins every entry byte-identically to the backend catalog fields', () => {
    const backend = loadBackendMethodMeta(python as string)

    // Gleiche Schlüsselmenge: kein verwaister Frontend-Eintrag, kein
    // ungespiegelter Backend-Eintrag.
    expect(Object.keys(MEASURE_CATALOG).sort()).toEqual(Object.keys(backend).sort())

    for (const [key, backendEntry] of Object.entries(backend)) {
      const mirror = MEASURE_CATALOG[key]
      expect(mirror, `Frontend-Spiegel fehlt für '${key}'`).toBeTruthy()
      for (const field of CONTRACT_FIELDS) {
        expect(
          mirror[field],
          `measureCatalog['${key}'].${field} weicht vom Backend ab`
        ).toBe(backendEntry[field])
      }
    }
  })

  it('pins the English mirror to the English backend rendering', () => {
    const backend = loadBackendMethodMeta(python as string, 'en')
    expect(Object.keys(MEASURE_CATALOG_EN).sort()).toEqual(Object.keys(backend).sort())
    for (const [key, backendEntry] of Object.entries(backend)) {
      for (const field of CONTRACT_FIELDS) {
        expect(
          MEASURE_CATALOG_EN[key]?.[field],
          `MEASURE_CATALOG_EN['${key}'].${field} differs from the backend`
        ).toBe(backendEntry[field])
      }
    }
  })

  it('backend MathML stays well-formed enough for the MeasureInfo guard', () => {
    const backend = loadBackendMethodMeta(python as string)
    for (const [key, entry] of Object.entries(backend)) {
      const mathml = entry.formula_mathml?.trim() ?? ''
      expect(/^<math[\s>]/.test(mathml), `formula_mathml('${key}') beginnt nicht mit <math>`).toBe(true)
      expect(mathml.endsWith('</math>'), `formula_mathml('${key}') endet nicht mit </math>`).toBe(true)
    }
  })
})

describe('measureCatalogEntry lookup', () => {
  it('resolves UI spellings and rejects unknowns', () => {
    expect(measureCatalogEntry('tscore')?.name).toBe(MEASURE_CATALOG.t.name)
    expect(measureCatalogEntry('f')?.name).toBe(MEASURE_CATALOG.frequency.name)
    expect(measureCatalogEntry('MI3')?.reference).toBe('Oakes 1998')
    expect(measureCatalogEntry('unbekannt')).toBeNull()
    expect(measureCatalogEntry('')).toBeNull()
    expect(measureCatalogEntry(null)).toBeNull()
  })

  it('follows the interface language', () => {
    expect(measureCatalogEntry('lrc', 'de')?.name).toBe('Konservatives Log Ratio (Evert 2022)')
    expect(measureCatalogEntry('lrc', 'en')?.name).toBe('Conservative Log Ratio (Evert 2022)')
    expect(measureCatalogEntry('tscore', 'en')?.name).toBe(MEASURE_CATALOG_EN.t.name)
    expect(Object.keys(MEASURE_CATALOG_EN).sort()).toEqual(Object.keys(MEASURE_CATALOG).sort())
  })

  it('keeps every mirrored entry free of recommendation rhetoric', () => {
    for (const [key, entry] of Object.entries(MEASURE_CATALOG)) {
      const text = `${entry.name} ${entry.explanation}`.toLowerCase()
      expect(text.includes('empfohlen'), `'${key}' enthält Empfehlungsrhetorik`).toBe(false)
      expect(text.includes('recommended'), `'${key}' enthält Empfehlungsrhetorik`).toBe(false)
    }
  })
})
