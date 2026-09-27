/**
 * Jeder faehigkeitsgebundene Einstellungsreiter braucht einen Eintrag im
 * Oberflaechen-Verzeichnis.
 *
 * Am 2026-08-30 war der Reiter "Modellweg" fertig gebaut, die Faehigkeit war
 * deklariert, die Route lief, und der Reiter blieb trotzdem unsichtbar. Es
 * fehlte allein der Eintrag in productCapabilitySurfaces, weil
 * surfaceAvailability ohne ihn "hat keine freigegebene Produktoberflaeche"
 * zurueckgibt. Kein Unittest sah das, nur der Lauf im Browser.
 *
 * Dieser Test ZAEHLT die Reiter aus der Quelle aus, statt sie aufzuzaehlen,
 * damit ein kuenftiger neuer Reiter dieselbe Luecke nicht wiederholen kann.
 */
import { describe, expect, it } from 'vitest'

import panelQuelle from '@/components/settings/SettingsPanel.vue?raw'
import { surfaceForCapability } from '@/lib/productCapabilities'

interface Reiter {
  tab: string
  faehigkeiten: string[]
}

function reiterAusQuelle(): Reiter[] {
  const quelle = panelQuelle
  const muster = /capabilityTab\(\s*'([^']+)'\s*,\s*'[^']*'\s*,\s*\w+\s*,\s*\[([^\]]*)\]/g
  const gefunden: Reiter[] = []
  for (const treffer of quelle.matchAll(muster)) {
    const faehigkeiten = [...treffer[2].matchAll(/'([^']+)'/g)].map((m) => m[1])
    gefunden.push({ tab: treffer[1], faehigkeiten })
  }
  return gefunden
}

describe('Einstellungsreiter und Oberflaechen-Verzeichnis', () => {
  it('findet die Reiter ueberhaupt', () => {
    const reiter = reiterAusQuelle()
    expect(reiter.length).toBeGreaterThanOrEqual(4)
    expect(reiter.map((r) => r.tab)).toContain('modelroute')
  })

  it('jeder Reiter hat mindestens eine Faehigkeit mit eingetragener Oberflaeche', () => {
    const ohne: string[] = []
    for (const { tab, faehigkeiten } of reiterAusQuelle()) {
      const hat = faehigkeiten.some((id) => surfaceForCapability(id) !== undefined)
      if (!hat) ohne.push(`${tab} (${faehigkeiten.join(', ')})`)
    }
    expect(ohne, 'Diese Reiter bleiben unsichtbar, weil keine ihrer Faehigkeiten '
      + 'in productCapabilitySurfaces eingetragen ist').toEqual([])
  })

  it('die eingetragene Oberflaeche zeigt auf denselben Reiter', () => {
    const falsch: string[] = []
    for (const { tab, faehigkeiten } of reiterAusQuelle()) {
      for (const id of faehigkeiten) {
        const flaeche = surfaceForCapability(id)
        if (!flaeche) continue
        const ziel = flaeche.open as { kind?: string; tab?: string } | undefined
        if (ziel?.kind === 'settings' && ziel.tab !== tab) {
          falsch.push(`${id}: Verzeichnis sagt '${ziel.tab}', Panel sagt '${tab}'`)
        }
      }
    }
    expect(falsch).toEqual([])
  })
})
