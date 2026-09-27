import { describe, expect, it } from 'vitest'
import { csvEscape, csvRow, buildCsv, csvMeta } from '@/utils/csv'

describe('csvEscape — formula injection guard', () => {
  it('prefixes a quote on leading formula characters', () => {
    expect(csvEscape('=SUM(A1:A2)')).toBe("'=SUM(A1:A2)")
    expect(csvEscape('+1')).toBe("'+1")
    expect(csvEscape('-2')).toBe("'-2")
    expect(csvEscape('@cmd')).toBe("'@cmd")
  })

  it('guards leading TAB/CR (which spreadsheets strip before re-parsing)', () => {
    // TAB leads, then needs quoting because TAB is structural too.
    expect(csvEscape('\t=evil')).toBe('"\'\t=evil"')
    expect(csvEscape('\r=evil')).toBe('"\'\r=evil"')
  })

  it('does not mangle ordinary values', () => {
    expect(csvEscape('Hase')).toBe('Hase')
    expect(csvEscape('läuft')).toBe('läuft')
    expect(csvEscape(42)).toBe('42')
    expect(csvEscape(0)).toBe('0')
    expect(csvEscape(true)).toBe('true')
  })

  it('coerces null/undefined to empty', () => {
    expect(csvEscape(null)).toBe('')
    expect(csvEscape(undefined)).toBe('')
  })
})

describe('csvEscape — column-corruption guard', () => {
  it('quote-wraps cells containing commas', () => {
    expect(csvEscape('a,b')).toBe('"a,b"')
  })

  it('doubles embedded quotes', () => {
    expect(csvEscape('he said "hi"')).toBe('"he said ""hi"""')
  })

  it('quote-wraps newlines, CR and TAB', () => {
    expect(csvEscape('line1\nline2')).toBe('"line1\nline2"')
    expect(csvEscape('a\tb')).toBe('"a\tb"')
  })

  it('combines formula + structural guards', () => {
    // Leading "=" AND an embedded comma: guard then quote-wrap.
    expect(csvEscape('=a,b')).toBe('"\'=a,b"')
  })
})

describe('buildCsv / csvRow roundtrip', () => {
  it('round-trips a simple table by parsing back to cells', () => {
    const rows = [
      ['Hase, der', 1, 0.5],
      ['=danger', 2, 0.25],
    ]
    const csv = buildCsv({ headers: ['word', 'freq', 'rel'], rows })
    const lines = csv.split('\n')
    expect(lines[0]).toBe('word,freq,rel')
    // First data row: comma-containing word is quote-wrapped.
    expect(lines[1]).toBe('"Hase, der",1,0.5')
    // Second data row: formula word is neutralised.
    expect(lines[2]).toBe("'=danger,2,0.25")
  })

  it('emits verbatim meta/comment lines before the header', () => {
    const csv = buildCsv({
      meta: ['# CandyConc Export', '# Corpus: demo'],
      headers: ['a', 'b'],
      rows: [['x', 'y']],
    })
    const lines = csv.split('\n')
    expect(lines[0]).toBe('# CandyConc Export')
    expect(lines[1]).toBe('# Corpus: demo')
    expect(lines[2]).toBe('a,b')
    expect(lines[3]).toBe('x,y')
  })

  it('csvRow escapes each cell consistently with csvEscape', () => {
    expect(csvRow(['=x', 'a,b', 'ok'])).toBe("'=x,\"a,b\",ok")
  })
})

describe('csvMeta — comment-line injection guard', () => {
  it('emits a plain `# label: value` for benign values', () => {
    expect(csvMeta('Suchterm', 'Hase')).toBe('# Suchterm: Hase')
    expect(csvMeta('Kontextgröße', 5)).toBe('# Kontextgröße: 5')
    expect(csvMeta('Docset', null)).toBe('# Docset: ')
  })

  it('neutralises a leading formula trigger in the value', () => {
    // A spreadsheet ignores the leading `#`, so the first real char of the value
    // could still be parsed as a formula — guard it.
    expect(csvMeta('Suchterm', '=cmd|/c calc')).toBe("# Suchterm: '=cmd|/c calc")
    expect(csvMeta('Filter.model', '@evil')).toBe("# Filter.model: '@evil")
    expect(csvMeta('x', '-2+3')).toBe("# x: '-2+3")
  })

  it('collapses embedded newlines so the value cannot break out of the line', () => {
    const out = csvMeta('Suchterm', 'erste Zeile\n=INJECT()\r\nrow2,evil')
    // Single physical line: no raw newline / CR escapes the comment.
    expect(out).not.toContain('\n')
    expect(out).not.toContain('\r')
    expect(out.split('\n')).toHaveLength(1)
    // The injected formula no longer sits at the start of a fresh row.
    expect(out).toBe('# Suchterm: erste Zeile =INJECT() row2,evil')
  })

  it('collapses unicode line/paragraph separators (U+2028/U+2029)', () => {
    const ls = String.fromCharCode(0x2028)
    const ps = String.fromCharCode(0x2029)
    const out = csvMeta('Suchterm', `a${ls}b${ps}c`)
    expect(out).toBe('# Suchterm: a b c')
    expect(out).not.toContain(ls)
    expect(out).not.toContain(ps)
  })
})
