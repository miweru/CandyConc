/**
 * Waechter: keine Anrede, keine Bevormundung in nutzersichtbaren Texten.
 *
 * WARUM ES DIESE DATEI GIBT, und warum sie NICHT unter einem Feature liegt.
 *
 * Am 2026-07-02 wurden 72 Strings auf ein neutrales Register umgestellt.
 * Die Kampagne hatte einen Waechter-Test. Der lag unter
 * src/__tests__/components/search/query-builder/ und wurde am 2026-07-13
 * mit dem Commit "reduce query builder to CQLF core" geloescht, weil er im
 * Verzeichnis des abgebauten Features stand. Er bewachte aber den ganzen
 * Quellbaum.
 *
 * Vier Tage spaeter, am 2026-07-17, kam "So annotieren Sie Belege: ..."
 * herein. Der Auftraggeber hat es am 2026-08-31 beanstandet, zusammen mit
 * "Naechste Schritte: Subkorpus speichern oder Kontrast starten", und dazu
 * gesagt, er habe solche Dinge wiederholt gesagt.
 *
 * Deshalb liegt der Waechter jetzt unter __tests__/register/, gehoert also
 * keinem Feature, und scannt src/ vollstaendig statt zwei Verzeichnisse.
 *
 * ZWEI KLASSEN, getrennt gefuehrt:
 *   (1) ANREDE: du, dir, dein, Sie, Ihr in nutzersichtbarem Text.
 *   (2) RAHMUNG: Schrittfolgen, Tipps und Anleitungen ueber Bedienelemente,
 *       die daneben stehen und sich selbst beschriften.
 *
 * KEIN BEFUND ist eine Zustandsinformation. "Ohne aktivierten Ergebnisscope
 * oeffnet sich eine andere Ansicht" sagt, was der Fall ist. "Aktiviere
 * zuerst den Ergebnisscope" sagt, was zu tun ist. Nur das zweite faellt.
 *
 * SELBSTSCHUTZ: faellt die Zahl der gelesenen Dateien unter eine Schwelle,
 * ist der Scan kaputt und der Test rot. Ein Waechter, der nichts mehr
 * findet, weil er nichts mehr liest, ist schlimmer als keiner.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const HIER = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.resolve(HIER, '../..')
const ENDUNGEN = new Set(['.vue', '.ts'])

function dateienSammeln(verzeichnis: string): string[] {
  const heraus: string[] = []
  for (const eintrag of readdirSync(verzeichnis)) {
    const voll = path.join(verzeichnis, eintrag)
    if (statSync(voll).isDirectory()) {
      if (eintrag === '__tests__' || eintrag === 'node_modules') continue
      heraus.push(...dateienSammeln(voll))
      continue
    }
    if (ENDUNGEN.has(path.extname(eintrag))) heraus.push(voll)
  }
  return heraus
}

interface Fund {
  datei: string
  zeile: number
  text: string
  muster: string
}

/**
 * Nur nutzersichtbarer Text, nicht Code und nicht Kommentar.
 *
 * Der erste Entwurf dieses Waechters las ganze Zeilen und meldete elf
 * Stellen, davon NEUN Fehltreffer: "Sie steht im Wortlaut daneben" und
 * "Sie duerfen nicht clientseitig ergaenzt werden" sind dritte Person,
 * und `sortDir.value = dir` ist ein Bezeichner. Ein Waechter, der
 * Fehlalarm schlaegt, wird irgendwann geloescht. Genau so ist der
 * Vorgaenger dieses Tests verschwunden.
 *
 * Deshalb: aus .ts werden nur Zeichenkettenliterale gelesen, aus .vue
 * zusaetzlich der Text zwischen den Marken des template-Blocks.
 */
function textAnteile(inhalt: string, istVue: boolean): { text: string, zeile: number }[] {
  const heraus: { text: string, zeile: number }[] = []
  const zeilen = inhalt.split('\n')
  const vorlageStart = istVue ? zeilen.findIndex((z) => z.trim().startsWith('<template')) : -1
  // Das LETZTE </template>, nicht das erste. Der erste Entwurf nahm
  // findIndex und endete damit am Schluss des ersten inneren
  // <template v-if>-Blocks. In SubcorpusPanel.vue lag der bei Zeile 631,
  // und alles danach war fuer den Waechter unsichtbar, darunter der
  // Rahmungssatz bei 673. Ein Waechter, der die Haelfte der Datei nicht
  // liest, meldet gruen und prueft nichts.
  const vorlageEnde = istVue ? zeilen.map((z) => z.trim()).lastIndexOf('</template>') : -1

  zeilen.forEach((zeile, i) => {
    const t = zeile.trim()
    if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return
    if (t.startsWith('import ') || t.startsWith('from ')) return

    // Zeichenkettenliterale ueberall
    for (const treffer of zeile.matchAll(/'([^'\\]*(?:\\.[^'\\]*)*)'|"([^"\\]*(?:\\.[^"\\]*)*)"|`([^`]*)`/g)) {
      const wert = treffer[1] ?? treffer[2] ?? treffer[3] ?? ''
      if (wert.trim()) heraus.push({ text: wert, zeile: i + 1 })
    }

    // Freier Text im Vorlagenblock einer .vue, also alles ausserhalb von Marken
    if (vorlageStart >= 0 && i > vorlageStart && (vorlageEnde < 0 || i < vorlageEnde)) {
      const ohneMarken = zeile.replace(/<[^>]*>/g, ' ').replace(/\{\{[^}]*\}\}/g, ' ')
      if (ohneMarken.trim()) heraus.push({ text: ohneMarken, zeile: i + 1 })
    }
  })
  return heraus
}

function suchen(muster: { name: string, re: RegExp }[]): Fund[] {
  const funde: Fund[] = []
  for (const voll of dateienSammeln(SRC)) {
    const rel = path.relative(SRC, voll)
    const istVue = path.extname(voll) === '.vue'
    for (const anteil of textAnteile(readFileSync(voll, 'utf8'), istVue)) {
      for (const m of muster) {
        if (m.re.test(anteil.text)) {
          funde.push({ datei: rel, zeile: anteil.zeile, text: anteil.text.trim().slice(0, 140), muster: m.name })
        }
      }
    }
  }
  return funde
}

function melden(funde: Fund[]): string {
  return funde.map((f) => `  ${f.datei}:${f.zeile} [${f.muster}] ${f.text}`).join('\n')
}

describe('Register der Oberflaeche', () => {
  it('liest ueberhaupt genug Dateien, sonst ist der Waechter blind', () => {
    const anzahl = dateienSammeln(SRC).length
    expect(anzahl).toBeGreaterThan(200)
  })

  it('kennt keine Duz- oder Siez-Anrede in nutzersichtbarem Text', () => {
    const funde = suchen([
      { name: 'du', re: /(?<![\wäöüß])(du|dich|dir|dein\w*|Dein\w*)(?![\wäöüß])/ },
      // "Sie" nur MITTEN im Satz: am Satzanfang ist es von der
      // grossgeschriebenen dritten Person nicht zu unterscheiden
      // ("Sie beschreiben, welchen Zielkorpus ..." meint die Zielwerte).
      // Grossgeschriebenes "Ihr..." ist dagegen immer Anrede, ausser am
      // Satzanfang.
      { name: 'Sie', re: /[a-zäöüß,]\s+(Sie|Ihre?[nmrs]?|Ihnen)(?![\wäöüß])/ },
    ])
    expect(funde, `Anrede gefunden:\n${melden(funde)}`).toEqual([])
  })

  it('rahmt Handlungen nicht als Schrittfolge, Tipp oder Anleitung', () => {
    const funde = suchen([
      { name: 'schrittfolge', re: /Nächste[rn]? (methodische[rn]? )?Schritt/i },
      { name: 'tipp', re: /(?<![\wäöüß])Tipps?(?![\wäöüß])/ },
      { name: 'anleitung', re: /(?<![\wäöüß])So (annotier|erstell|find|such|leg|nutz)\w*/i },
      { name: 'jederzeit', re: /lässt sich jederzeit|kannst du jederzeit/i },
      { name: 'zuerst-dann', re: /Zuerst .{0,60}, dann /i },
      { name: 'klickfolge', re: /1\.\s*\w+.{0,80}2\.\s*\w+.{0,80}3\.\s*\w+/ },
    ])
    expect(funde, `Rahmung gefunden:\n${melden(funde)}`).toEqual([])
  })
})
