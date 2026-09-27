/**
 * Der Markdown-Renderer der Chat-Antwort.
 *
 * Die Antwort kommt aus einem Sprachmodell. Der Renderer escaped zuerst
 * ALLES und laesst danach nur eine feste Menge Auszeichnung wieder zu.
 * Beide Richtungen stehen hier: was gerendert werden MUSS, und was auf
 * keinen Fall durchkommen darf. Ohne die zweite Klasse waere ein Renderer,
 * der alles escaped und nichts formatiert, gruen.
 */
import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

describe('renderMarkdown: nichts kommt als HTML durch', () => {
  const angriffe = [
    '<script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '<iframe src="evil"></iframe>',
    '<a href="javascript:alert(1)">klick</a>',
    '<div onclick="alert(1)">x</div>',
    '<svg/onload=alert(1)>',
    '`<script>alert(1)</script>`',
    '**<script>alert(1)</script>**',
    '| <script>alert(1)</script> |\n|---|\n| x |',
  ]

  /**
   * Die Weissliste ist die eigentliche Zusicherung, nicht eine Liste
   * verbotener Zeichenketten. `onerror=` DARF im Ergebnis stehen, naemlich
   * als escaped Klartext: `&lt;img src=x onerror=alert(1)&gt;` ist sichtbarer
   * Text und kein Attribut. Verboten ist, dass ueberhaupt ein Tag entsteht,
   * das der Renderer nicht selbst gesetzt hat.
   */
  const ERLAUBT = new RegExp(
    '^(?:'
    + '</?(?:p|br|strong|em|code|pre|ul|ol|li|h[3-6]'
    + '|table|thead|tbody|tr|th|td|div)>'
    + '|<div class="md-table-scroll">'
    + ')$',
  )

  function fremdeTags(html: string): string[] {
    return (html.match(/<[^>]*>/g) ?? []).filter(t => !ERLAUBT.test(t))
  }

  it.each(angriffe)('%s bleibt inert', (roh) => {
    const html = renderMarkdown(roh)
    expect(fremdeTags(html)).toEqual([])
    // Und die Gefahr steht als lesbarer Text da, statt verschluckt zu werden.
    expect(html).toMatch(/&lt;|&quot;|\[klick\]/)
  })

  it('die Weissliste ist streng genug, um etwas zu fangen', () => {
    // Kontrollmessung: ohne sie waere jede Zusicherung oben wertlos.
    expect(fremdeTags('<img src=x>')).toEqual(['<img src=x>'])
    expect(fremdeTags('<p>ok</p>')).toEqual([])
  })

  it('ein Link wird NICHT anklickbar', () => {
    // Ein Link in einer Antwort waere ein Ziel, das das Modell gewaehlt hat.
    expect(renderMarkdown('[klick](https://example.com)')).not.toMatch(/<a\b/i)
  })
})

describe('renderMarkdown: der Methodensteckbrief wird lesbar', () => {
  it('Ueberschrift, Aufzaehlung, Code und Fett', () => {
    const html = renderMarkdown(
      '### Methodensteckbrief\n'
      + '- Abfrage: `[lemma="Recht"]`\n'
      + '- Fenster: **10**\n',
    )
    expect(html).toContain('<h5>Methodensteckbrief</h5>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<code>[lemma=&quot;Recht&quot;]</code>')
    expect(html).toContain('<strong>10</strong>')
  })

  it('Tabellen scrollen in sich, nie die Blase', () => {
    const html = renderMarkdown('| Wahlperiode | Reden |\n|---|---|\n| 10 | 65116 |')
    expect(html).toContain('md-table-scroll')
    expect(html).toContain('<th>Wahlperiode</th>')
    expect(html).toContain('<td>65116</td>')
  })

  it('nummerierte Listen', () => {
    expect(renderMarkdown('1. eins\n2. zwei')).toContain('<ol>')
  })

  it('Codebloecke', () => {
    expect(renderMarkdown('```\nx = 1\n```')).toContain('<pre><code>x = 1</code></pre>')
  })

  it('Zeilenumbrueche im Absatz bleiben erhalten', () => {
    // Eine Aufzaehlung ohne Bindestrich ist im Steckbrief haeufig und darf
    // nicht zu einer Zeile verschmelzen.
    expect(renderMarkdown('Zeile eins\nZeile zwei')).toContain('<br>')
  })

  it('leerer Text ergibt leeres HTML', () => {
    expect(renderMarkdown('')).toBe('')
  })

  it('Klartext ohne Auszeichnung bleibt Klartext', () => {
    expect(renderMarkdown('Die Zahl betraegt 110210.')).toBe('<p>Die Zahl betraegt 110210.</p>')
  })
})
