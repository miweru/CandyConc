/**
 * Ein kleiner, absichtlich unvollstaendiger Markdown-Renderer.
 *
 * Der Chat gab die Antwort bisher als `{{ message.content }}` aus, also roh
 * interpoliert, ohne `white-space: pre-wrap`. Der Methodensteckbrief, den
 * das Backend deterministisch an jede Landung haengt, kollabierte damit zu
 * Fliesstext mit sichtbaren Rautenzeichen, und jede Tabelle und jede
 * Aufzaehlung verlor ihre Struktur. Genau die Angaben, wegen derer der
 * Steckbrief gebaut wurde, waren am schwersten zu lesen.
 *
 * SICHERHEIT. Der Text kommt aus einem Sprachmodell. Zuerst wird ALLES
 * escaped, danach werden nur die unten aufgezaehlten Formen wieder zu
 * Auszeichnung. Rohes HTML kann diese Reihenfolge nicht ueberleben, es gibt
 * keinen Durchlassweg und keine Attribut-Injektion. Deshalb auch keine
 * Bibliothek: `marked` plus `dompurify` waeren zwei Abhaengigkeiten fuer
 * eine Aufgabe, die hier aus einer Handvoll Ersetzungen besteht, und jede
 * Sanitizer-Konfiguration ist eine weitere Stelle, an der man sich irren
 * kann.
 *
 * Bewusst NICHT unterstuetzt: Links, Bilder, rohes HTML, Fussnoten,
 * verschachtelte Listen. Ein Link in einer Antwort waere ein Ziel, das das
 * Modell gewaehlt hat, und das gehoert nicht anklickbar in die Oberflaeche.
 */

const ESCAPE: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escape(text: string): string {
  return text.replace(/[&<>"']/g, z => ESCAPE[z] ?? z)
}

/** Fett, kursiv und Code innerhalb einer Zeile. Reihenfolge zaehlt. */
function inline(text: string): string {
  return text
    // Code zuerst: was in Backticks steht, soll nicht noch fett werden.
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
}

function istTrennzeile(zeile: string): boolean {
  return /^\|?[\s:|-]+\|[\s:|-]*$/.test(zeile) && zeile.includes('-')
}

function zellen(zeile: string): string[] {
  return zeile.replace(/^\||\|$/g, '').split('|').map(z => z.trim())
}

/**
 * Markdown zu HTML. Die Eingabe wird als unsicher behandelt.
 */
export function renderMarkdown(quelle: string): string {
  const zeilen = escape(String(quelle ?? '')).split('\n')
  const teile: string[] = []
  let i = 0

  const listeSchliessen = (art: 'ul' | 'ol' | null) => {
    if (art) teile.push(`</${art}>`)
  }
  let liste: 'ul' | 'ol' | null = null

  while (i < zeilen.length) {
    const zeile = zeilen[i] ?? ''
    const roh = zeile.trim()

    // Codeblock
    if (roh.startsWith('```')) {
      const inhalt: string[] = []
      i++
      while (i < zeilen.length && !(zeilen[i] ?? '').trim().startsWith('```')) {
        inhalt.push(zeilen[i] ?? '')
        i++
      }
      i++
      listeSchliessen(liste); liste = null
      teile.push(`<pre><code>${inhalt.join('\n')}</code></pre>`) // i18n-ignore: HTML markup, no text
      continue
    }

    // Tabelle: Kopfzeile plus Trennzeile
    if (roh.includes('|') && istTrennzeile((zeilen[i + 1] ?? '').trim())) {
      const kopf = zellen(roh)
      i += 2
      const koerper: string[][] = []
      while (i < zeilen.length && (zeilen[i] ?? '').includes('|')) {
        koerper.push(zellen((zeilen[i] ?? '').trim()))
        i++
      }
      listeSchliessen(liste); liste = null
      const kopfHtml = kopf.map(z => `<th>${inline(z)}</th>`).join('')
      const koerperHtml = koerper
        .map(r => `<tr>${r.map(z => `<td>${inline(z)}</td>`).join('')}</tr>`)
        .join('')
      teile.push(
        `<div class="md-table-scroll"><table><thead><tr>${kopfHtml}</tr></thead>` // i18n-ignore: HTML markup, no text
        + `<tbody>${koerperHtml}</tbody></table></div>`, // i18n-ignore: HTML markup, no text
      )
      continue
    }

    // Ueberschrift
    const ueber = /^(#{1,6})\s+(.*)$/.exec(roh)
    if (ueber) {
      listeSchliessen(liste); liste = null
      // Auf h3 bis h6 begrenzt: die Antwort steht in einer Chat-Blase und
      // darf die Ueberschriftenhierarchie der Seite nicht uebernehmen.
      const tiefe = Math.min(6, 2 + (ueber[1] ?? '#').length)
      teile.push(`<h${tiefe}>${inline(ueber[2] ?? '')}</h${tiefe}>`)
      i++
      continue
    }

    // Aufzaehlung
    const punkt = /^[-*]\s+(.*)$/.exec(roh)
    const nummer = /^(\d+)\.\s+(.*)$/.exec(roh)
    if (punkt || nummer) {
      const art: 'ul' | 'ol' = punkt ? 'ul' : 'ol'
      if (liste !== art) {
        listeSchliessen(liste)
        teile.push(`<${art}>`)
        liste = art
      }
      teile.push(`<li>${inline((punkt ? punkt[1] : nummer?.[2]) ?? '')}</li>`)
      i++
      continue
    }

    if (!roh) {
      listeSchliessen(liste); liste = null
      i++
      continue
    }

    listeSchliessen(liste); liste = null
    // Fortlaufende Zeilen bilden einen Absatz, Zeilenumbrueche bleiben
    // erhalten: eine Aufzaehlung ohne Bindestrich ist im Methodensteckbrief
    // haeufig, und sie darf nicht zu einer Zeile verschmelzen.
    const absatz: string[] = []
    while (i < zeilen.length) {
      const z = (zeilen[i] ?? '').trim()
      if (!z || z.startsWith('```') || /^(#{1,6})\s/.test(z)
          || /^[-*]\s/.test(z) || /^\d+\.\s/.test(z)) break
      absatz.push(inline(z))
      i++
    }
    teile.push(`<p>${absatz.join('<br>')}</p>`)
  }
  listeSchliessen(liste)
  return teile.join('')
}
