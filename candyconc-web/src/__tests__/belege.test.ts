import { describe, expect, it } from 'vitest'
import { belegChipsEinsetzen, type BelegQuelle } from '../utils/belege'

const EVIDENZ: BelegQuelle[] = [
  { id: 'ev1', tool: 'frequency_list', query: 'Klima', status: 'success' },
  { id: 'ev2', tool: 'kwic', query: '"starke Regenfälle"', status: 'success' },
]

describe('belegChipsEinsetzen', () => {
  it('setzt valide Marken in klickbare Chips um', () => {
    const html = belegChipsEinsetzen('Vorher [[beleg:ev1]] nachher.', EVIDENZ)
    expect(html).toContain('class="ev-chip"')
    expect(html).toContain('data-ev="ev1"')
    expect(html).toContain('data-query="Klima"')
    expect(html).toContain('Beleg 1')
    expect(html).not.toContain('[[beleg:ev1]]')
  })

  it('laesst unbekannte IDs ehrlich als Beleg fehlt stehen', () => {
    const html = belegChipsEinsetzen('Ohne Deckung [[beleg:ev99]].', EVIDENZ)
    expect(html).toContain('[Beleg fehlt]')
    expect(html).not.toContain('ev-chip')
  })

  // Eine Nummer bezeichnet eine Quelle (Englischprobe c2: "Evidence 1" stand
  // fuer E_collocate_stats_1 und fuer E_collocate_stats_2). Bis dahin zaehlte
  // dieser Test Wiederholungen derselben Quelle fort (Beleg 1, Beleg 2).
  it('gibt jeder Quelle eine Nummer, in der Folge ihrer ersten Marke', () => {
    const html = belegChipsEinsetzen(
      'A [[beleg:ev2]] B [[beleg:ev1]] C [[beleg:ev2]] D [[beleg:ev99]] E [[beleg:ev1]]',
      EVIDENZ,
    )
    const chips = [...html.matchAll(/data-ev="([^"]+)"[^>]*>([^<]+)</g)].map(m => [m[1], m[2]])
    expect(chips).toEqual([
      ['ev2', 'Beleg 1'],
      ['ev1', 'Beleg 2'],
      ['ev2', 'Beleg 1'],
      ['ev1', 'Beleg 2'],
    ])
    expect(html).toContain('[Beleg fehlt]')
  })

  it('nummeriert in der englischen Oberflaeche ebenso', async () => {
    const { applyLocale } = await import('@/i18n/locale')
    applyLocale('en')
    const html = belegChipsEinsetzen('A [[beleg:ev1]] B [[beleg:ev2]] C [[beleg:ev1]]', EVIDENZ)
    expect([...html.matchAll(/>(Evidence \d+)</g)].map(m => m[1])).toEqual(['Evidence 1', 'Evidence 2', 'Evidence 1'])
  })

  it('escaped Attributwerte aus der Beleg-Map', () => {
    const boese: BelegQuelle[] = [
      { id: 'evx', tool: 'kwic', query: '" onclick="alert(1)', status: 'success' },
    ]
    const html = belegChipsEinsetzen('[[beleg:evx]]', boese)
    expect(html).not.toContain('" onclick')
    expect(html).toContain('&quot;')
  })

  it('ohne Beleg-Map bleibt der Textleser nicht mit Chips allein', () => {
    const html = belegChipsEinsetzen('[[beleg:ev1]]', undefined)
    expect(html).toContain('[Beleg fehlt]')
  })
})
