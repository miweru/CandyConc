import { describe, expect, it } from 'vitest'
import { getRegistry } from '@/actions/registry'
import type { ScientificRisk } from '@/types/copilot-protocol'

/**
 * Gate-Klassifikation: Der ScientificRisk-Typ darf ausschliesslich Klassen
 * enthalten, die die Action-Registry tatsaechlich vergibt. Phantom-Klassen
 * (frueher: 'p_hacking_like', 'data_leak') sind ausgebaut und duerfen nicht
 * zurueckkehren, ohne dass eine Aktion sie produziert.
 */

// Compile-time exhaustiveness: erweitert jemand den ScientificRisk-Typ,
// ohne diese Liste anzupassen, bricht der Typcheck.
const DECLARED_CLASSES: Record<ScientificRisk, true> = {
  none: true,
  parameter_drift: true,
  interpretation_leap: true,
  export_privacy: true,
}

const declared = Object.keys(DECLARED_CLASSES) as ScientificRisk[]

describe('ScientificRisk gate classes', () => {
  const registry = getRegistry()
  const entries = Object.values(registry)

  it('registry entries only use declared classes', () => {
    for (const meta of entries) {
      for (const risk of meta.scientificRisk) {
        expect(declared, `${meta.type} vergibt undeklarierte Klasse "${risk}"`).toContain(risk)
      }
    }
  })

  it('every declared non-none class is produced by at least one registry entry', () => {
    const produced = new Set(
      entries.flatMap(meta => meta.scientificRisk).filter(r => r !== 'none')
    )
    for (const cls of declared.filter(c => c !== 'none')) {
      expect(produced.has(cls), `Klasse "${cls}" wird von keinem Registry-Eintrag produziert (Phantom-Klasse)`).toBe(true)
    }
  })

  it('retired phantom classes are gone from the registry', () => {
    const allAssigned = entries.flatMap(meta => meta.scientificRisk as string[])
    expect(allAssigned).not.toContain('p_hacking_like')
    expect(allAssigned).not.toContain('data_leak')
  })
})
