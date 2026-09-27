import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * GUARD (Produktinhaber wörtlich: "(empfohlen) bei Maßen ist Bevormundung"):
 * KEINE Empfehlungs-/Wertungslabels in nutzersichtbaren Strings. Der Sweep
 * läuft grep-artig über sämtliche .vue-Single-File-Components — dort leben
 * alle gerenderten Optionen/Labels/Tooltips — und schlägt bei jedem
 * 'empfohlen'/'recommended' an (auch Kommentare: die nächste Person kopiert
 * sonst die Rhetorik zurück ins Template).
 *
 * Die fachliche Alternative sind die MeasureInfo-Formel-Tooltips
 * (Formel + Erklärung + Referenz aus dem Backend-Methodenkatalog).
 */

const here = dirname(fileURLToPath(import.meta.url))
const srcRoot = resolve(here, '..', '..', '..')

function collectVueFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const stats = statSync(full)
    if (stats.isDirectory()) collectVueFiles(full, out)
    else if (entry.endsWith('.vue')) out.push(full)
  }
  return out
}

describe('no recommendation labels in rendered components', () => {
  it('finds zero empfohlen/recommended occurrences across all .vue files', () => {
    const files = collectVueFiles(srcRoot)
    // Plausibilitätsanker: der Sweep muss die echte Komponentenmenge sehen.
    expect(files.length).toBeGreaterThan(50)

    const offenders: string[] = []
    for (const file of files) {
      const content = readFileSync(file, 'utf8')
      const lines = content.split('\n')
      lines.forEach((line, index) => {
        if (/empfohlen|recommended/i.test(line)) {
          offenders.push(`${file.slice(srcRoot.length + 1)}:${index + 1}: ${line.trim()}`)
        }
      })
    }
    expect(offenders, `Empfehlungslabels gefunden:\n${offenders.join('\n')}`).toEqual([])
  })

  it('the collocation pickers offer MI3 and plain logDice', () => {
    const collocations = readFileSync(
      resolve(srcRoot, 'components', 'analysis', 'CollocationsTab.vue'),
      'utf8'
    )
    const network = readFileSync(
      resolve(srcRoot, 'components', 'analysis', 'CollocationNetworkTab.vue'),
      'utf8'
    )
    // The option labels live in the message catalog since the interface is
    // translated. The German label keeps its wording there.
    const germanCatalog = readFileSync(resolve(srcRoot, 'locales', 'de', 'analysis.ts'), 'utf8')
    expect(germanCatalog, 'deutscher Katalog ohne MI3-Beschriftung').toContain("mi3: 'MI3 (kubische MI)'")
    for (const [name, source] of [
      ['CollocationsTab', collocations],
      ['CollocationNetworkTab', network],
    ] as const) {
      expect(source, `${name} ohne MI3-Option`).toContain('analysis.measureOptions.mi3')
      expect(source, `${name} ohne nüchterne logDice-Option`).toMatch(/logDice/)
      // Zählattribut-Umschalter (Wortform | Lemma) ist vorhanden und gated.
      expect(source, `${name} ohne Zählattribut-Umschalter`).toContain('Zählattribut')
      expect(source, `${name} ohne Lemma-Capability-Gate`).toContain("canUseTokenAttribute('lemma')")
      // Formel-Tooltip ersetzt das Empfehlungslabel.
      expect(source, `${name} ohne MeasureInfo-Tooltip`).toContain('MeasureInfo')
    }
  })
})
