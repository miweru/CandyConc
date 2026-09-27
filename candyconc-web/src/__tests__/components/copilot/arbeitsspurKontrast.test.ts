/**
 * Kontrast und Andeutung: die Befunde der Zugaenglichkeitspruefung.
 *
 * Gemessen gegen die Tokens aus style.css:
 *   neutral-400 auf neutral-50   2,42:1   durchgefallen
 *   neutral-500 auf neutral-900  3,78:1   durchgefallen
 *   neutral-500 auf neutral-50   4,54:1   besteht
 *   neutral-400 auf neutral-900  7,11:1   besteht
 * WCAG AA verlangt 4,5:1 fuer Text. Also hell 500, dunkel 400 - genau
 * andersherum als die erste Fassung.
 *
 * Deckkraft auf Text ist verboten: sie halbiert den Kontrast eines
 * ohnehin knappen Paares, und die Aussage "keine echte Arbeit" traegt sie
 * nicht, die steht im Wortlaut daneben.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Vitest laeuft aus dem Paketwurzelverzeichnis.
function quelle(datei: string): string {
  return readFileSync(resolve('src/components/copilot', datei), 'utf-8')
}

const GROSS = quelle('ArbeitsspurGross.vue')
const LEISTE = quelle('ArbeitsspurLeiste.vue')

/** Der Stilblock, ohne Vorlage und Skript. */
function stil(v: string): string {
  const i = v.indexOf('<style')
  return i < 0 ? '' : v.slice(i)
}

describe('Kontrast', () => {
  it('kein neutral-400 als Textfarbe im hellen Modus', () => {
    // Das war die durchgefallene Richtung: 2,42:1.
    for (const [name, v] of [['gross', GROSS], ['leiste', LEISTE]] as const) {
      const treffer = [...stil(v).matchAll(/@apply\s+([^;]*)/g)]
        .map(m => m[1] ?? '')
        .filter(z => /(^|\s)text-neutral-400(\s|$)/.test(z))
      expect(treffer, `${name}: ${treffer.join(' | ')}`).toEqual([])
    }
  })

  it('kein dark:text-neutral-500', () => {
    // 3,78:1 auf neutral-900.
    for (const [name, v] of [['gross', GROSS], ['leiste', LEISTE]] as const) {
      expect(stil(v), name).not.toMatch(/dark:text-neutral-500/)
    }
  })

  it('keine Deckkraft auf Textelementen', () => {
    // opacity-50 auf neutral-600 ergibt rechnerisch rund 3:1 und
    // widerspricht dem eigenen Versprechen "nichts wird versteckt".
    for (const [name, v] of [['gross', GROSS], ['leiste', LEISTE]] as const) {
      expect(stil(v), name).not.toMatch(/@apply[^;]*\bopacity-(40|50|60)\b/)
    }
  })

  it('keine Schriftgroessen unter text-xs', () => {
    // text-[0.68rem] sind rund 10,9 px und tragen ausgerechnet die
    // Angaben, auf die es ankommt.
    for (const [name, v] of [['gross', GROSS], ['leiste', LEISTE]] as const) {
      expect(stil(v), name).not.toMatch(/text-\[0\.[0-6]\d*rem\]/)
    }
  })
})

describe('Andeutung', () => {
  it('die aufklappbaren Schritte zeigen einen Pfeil', () => {
    // Ohne ihn deutet nichts an, dass die Zeile mehr traegt: der
    // Standardmarker ist ausgeblendet, und der Zeilenrahmen lag bei 1,21:1.
    expect(GROSS).toMatch(/ChevronRight/)
    expect(GROSS).toMatch(/schritt-pfeil/)
  })

  it('der Pfeil dreht sich beim Aufklappen und respektiert reduzierte Bewegung', () => {
    expect(stil(GROSS)).toMatch(/details\[open\][^{]*\.schritt-pfeil/)
    expect(stil(GROSS)).toMatch(/prefers-reduced-motion[\s\S]*schritt-pfeil/)
  })
})
