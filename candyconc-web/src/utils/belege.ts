/**
 * Beleg-Chips: die klickbaren Referenzen des Deutungspfads.
 *
 * Der Modelltext traegt fuer jede Fundstelle eine Marke `[[beleg:ID]]`.
 * Diese Datei setzt die Marken gegen die Beleg-Map des Turns
 * (`copilot.grounding.evidence`: id, tool, query, status) in klickbare
 * Chips um. DIESELBE Sicherheitslinie wie der Markdown-Renderer: die ID
 * im Text wird nie direkt in ein Attribut uebernommen — ein Chip entsteht
 * nur fuer eine ID, die in der servergelieferten Beleg-Map steht, und die
 * Attributwerte kommen aus dieser Map, nicht aus dem Modelltext. Ohne
 * Treffer bleibt ehrlich `[Beleg fehlt]` stehen.
 */

import { t } from '@/i18n'

export interface BelegQuelle {
  id: string
  tool: string
  query: string
  status: string
}

const CHIP_MUSTER = /\[\[beleg:([^\[\]\n]+)\]\]/g // i18n-ignore: marker the server writes into the answer text

function attribut(wert: string): string {
  return wert.replace(/[&<>"']/g, z => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[z] ?? z))
}

export function belegChipsEinsetzen(html: string, evidence?: BelegQuelle[]): string {
  const karte = new Map<string, BelegQuelle>()
  for (const quelle of evidence ?? []) {
    if (quelle && typeof quelle.id === 'string' && quelle.id) karte.set(quelle.id, quelle)
  }
  // One number per source: the evidence IDs are numbered in the order of
  // their first mark in the answer, and every mark of a source shows its
  // number. Numbering per mark gave "Evidence 1" to several sources.
  const nummern = new Map<string, number>()
  return html.replace(CHIP_MUSTER, (_ganze: string, rohId: string) => {
    const id = rohId.trim()
    const quelle = karte.get(id)
    if (!quelle) return t('copilot.evidence.missing')
    let nr = nummern.get(id)
    if (nr === undefined) {
      nr = nummern.size + 1
      nummern.set(id, nr)
    }
    return (
      `<button type="button" class="ev-chip" data-ev="${attribut(id)}"` +
      ` data-query="${attribut(quelle.query)}" data-tool="${attribut(quelle.tool)}"` +
      ` title="${attribut(quelle.query || quelle.tool)}">${attribut(t('copilot.evidence.chip', { n: nr }))}</button>`
    )
  })
}
