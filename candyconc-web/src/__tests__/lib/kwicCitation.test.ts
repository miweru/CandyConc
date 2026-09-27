import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  copyTextToClipboard,
  escapeTsvField,
  formatCitationSuffix,
  formatKwicLine,
  formatKwicLineWithCitation,
  formatKwicTsv,
  kwicHitSpan,
  stripLeftEllipsis,
  stripRightEllipsis,
  type KwicCitationRow,
} from '@/lib/kwicCitation'

function row(overrides: Partial<KwicCitationRow> = {}): KwicCitationRow {
  return {
    position: 1337,
    left: 'der schnelle braune',
    match: 'Fuchs',
    right: 'springt über den Hund',
    docId: '42',
    docTitle: undefined,
    metadata: { source: 'reddit' },
    ...overrides,
  }
}

describe('stripLeftEllipsis / stripRightEllipsis', () => {
  it('removes a leading ellipsis marker but keeps the rest', () => {
    expect(stripLeftEllipsis('...der Fuchs')).toBe('der Fuchs')
    expect(stripLeftEllipsis('…der Fuchs')).toBe('der Fuchs')
  })

  it('removes a trailing ellipsis marker but keeps the rest', () => {
    expect(stripRightEllipsis('den Hund...')).toBe('den Hund')
    expect(stripRightEllipsis('den Hund…')).toBe('den Hund')
  })

  it('leaves interior ellipsis-like text untouched', () => {
    expect(stripLeftEllipsis('a ... b')).toBe('a ... b')
    expect(stripRightEllipsis('a ... b')).toBe('a ... b')
  })

  it('returns empty string for empty input', () => {
    expect(stripLeftEllipsis('')).toBe('')
    expect(stripRightEllipsis('')).toBe('')
  })
})

describe('formatKwicLine — whitespace preservation', () => {
  it('formats as left | node | right', () => {
    expect(formatKwicLine(row())).toBe(
      'der schnelle braune | Fuchs | springt über den Hund'
    )
  })

  it('preserves interior whitespace inside each segment verbatim', () => {
    const line = formatKwicLine(
      row({
        left: 'zwei   Leerzeichen',
        match: 'Tab\there',
        right: 'und\tnoch  eins',
      })
    )
    expect(line).toBe('zwei   Leerzeichen | Tab\there | und\tnoch  eins')
    // The doubled spaces and the tab must survive untouched.
    expect(line).toContain('zwei   Leerzeichen')
    expect(line).toContain('Tab\there')
    expect(line).toContain('und\tnoch  eins')
  })

  it('strips display ellipsis markers from clipped context', () => {
    const line = formatKwicLine(
      row({ left: '...der schnelle', right: 'den Hund…' })
    )
    expect(line).toBe('der schnelle | Fuchs | den Hund')
  })

  it('handles empty context segments', () => {
    expect(formatKwicLine(row({ left: '', right: '' }))).toBe(' | Fuchs | ')
  })
})

describe('formatCitationSuffix / formatKwicLineWithCitation', () => {
  it('builds a citation from source, doc and position', () => {
    expect(formatCitationSuffix(row())).toBe('reddit, doc 42, pos 1337')
  })

  it('prefers docTitle over docId when present', () => {
    expect(formatCitationSuffix(row({ docTitle: 'Thread A', docId: '42' }))).toBe(
      'reddit, doc Thread A, pos 1337'
    )
  })

  it('omits missing fields', () => {
    expect(
      formatCitationSuffix(row({ metadata: null, docId: null, docTitle: undefined }))
    ).toBe('pos 1337')
  })

  it('returns empty suffix when nothing is citable', () => {
    expect(
      formatCitationSuffix(
        row({ metadata: null, docId: null, docTitle: undefined, position: undefined })
      )
    ).toBe('')
  })

  it('appends the citation in brackets', () => {
    expect(formatKwicLineWithCitation(row())).toBe(
      'der schnelle braune | Fuchs | springt über den Hund  [reddit, doc 42, pos 1337]'
    )
  })

  it('falls back to the plain line when no citation is available', () => {
    const bare = row({ metadata: null, docId: null, docTitle: undefined, position: undefined })
    expect(formatKwicLineWithCitation(bare)).toBe(formatKwicLine(bare))
  })
})

describe('formatKwicTsv / escapeTsvField', () => {
  it('collapses tabs and newlines but keeps other whitespace', () => {
    expect(escapeTsvField('a\tb\nc\r\nd')).toBe('a b c d')
    expect(escapeTsvField('zwei  spaces')).toBe('zwei  spaces')
  })

  it('renders a header plus one row per hit', () => {
    const tsv = formatKwicTsv([
      row(),
      row({ position: 2, left: 'x', match: 'y', right: 'z', docId: '7', metadata: { source: 'news' } }),
    ])
    const lines = tsv.split('\n')
    // match, match_start and match_end are appended like in the server exports.
    expect(lines[0]).toBe('position\tleft\tnode\tright\tsource\tdoc\tmatch\tmatch_start\tmatch_end')
    expect(lines[1]).toBe('1337\tder schnelle braune\tFuchs\tspringt über den Hund\treddit\t42\tFuchs\t1337\t1337')
    expect(lines[2]).toBe('2\tx\ty\tz\tnews\t7\ty\t2\t2')
    expect(lines).toHaveLength(3)
  })

  it('names the whole hit of a line whose hit covers several tokens', () => {
    const tsv = formatKwicTsv([
      row({
        position: 1104,
        left: 'of religious tolerance , political',
        match: 'freedom',
        right: 'and economic opportunity . For',
        matchOffsets: [-1],
      }),
    ])
    const fields = tsv.split('\n')[1]!.split('\t')
    expect(fields.slice(0, 4)).toEqual(['1104', 'of religious tolerance , political', 'freedom', 'and economic opportunity . For'])
    expect(fields.slice(6)).toEqual(['political freedom', '1103', '1104'])
  })

  it('keeps every row on a single physical line even with embedded newlines', () => {
    const tsv = formatKwicTsv([row({ left: 'line1\nline2', right: 'r' })])
    expect(tsv.split('\n')).toHaveLength(2) // header + one row
    expect(tsv.split('\n')[1]).toContain('line1 line2')
  })
})

// The server exports name the whole hit (match, match_start, match_end).
// Loaded lines carry only the node and the offsets of the other hit tokens.
describe('kwicHitSpan', () => {
  it('is the node for a hit of one token', () => {
    expect(kwicHitSpan(row())).toEqual({ match: 'Fuchs', matchStart: 1337, matchEnd: 1337 })
  })

  it('takes the hit tokens before the node from the left context', () => {
    const span = kwicHitSpan(row({
      position: 1104,
      left: 'of religious tolerance , political',
      match: 'freedom',
      right: 'and economic opportunity . For',
      matchOffsets: [-1],
    }))
    expect(span).toEqual({ match: 'political freedom', matchStart: 1103, matchEnd: 1104 })
  })

  it('takes the hit tokens after the node from the right context', () => {
    const span = kwicHitSpan(row({
      position: 1103,
      left: 'search of religious tolerance ,',
      match: 'political',
      right: 'freedom and economic opportunity .',
      matchOffsets: [1],
    }))
    expect(span).toEqual({ match: 'political freedom', matchStart: 1103, matchEnd: 1104 })
  })

  it('covers the tokens between the outermost offsets, like the server export', () => {
    // A hit such as [word="a"] []{0,2} [word="c"] lists only its outer tokens.
    const span = kwicHitSpan(row({ position: 10, left: 'x y', match: 'a', right: 'b c d', matchOffsets: [2] }))
    expect(span).toEqual({ match: 'a b c', matchStart: 10, matchEnd: 12 })
  })

  it('ignores display ellipses at the edges of the context', () => {
    const span = kwicHitSpan(row({ position: 5, left: '… eins zwei', match: 'drei', right: 'vier …', matchOffsets: [-2, 1] }))
    expect(span.match).toBe('eins zwei drei vier')
  })

  it('marks hit tokens that lie outside the loaded context', () => {
    const span = kwicHitSpan(row({ position: 20, left: 'b', match: 'c', right: 'd', matchOffsets: [-2, -1, 1, 2] }))
    expect(span).toEqual({ match: '… b c d …', matchStart: 18, matchEnd: 22 })
  })

  it('has no positions when the line has none', () => {
    const span = kwicHitSpan(row({ position: undefined, matchOffsets: [1] }))
    expect(span).toEqual({ match: 'Fuchs springt', matchStart: null, matchEnd: null })
  })
})

describe('copyTextToClipboard', () => {
  const originalClipboard = navigator.clipboard

  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      configurable: true,
    })
    vi.restoreAllMocks()
  })

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('uses the async clipboard API when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    const ok = await copyTextToClipboard('hello')
    expect(ok).toBe(true)
    expect(writeText).toHaveBeenCalledWith('hello')
  })

  it('falls back to execCommand when the clipboard API rejects', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('blocked'))
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    const execCommandMock = vi.fn().mockReturnValue(true)
    // jsdom does not implement execCommand by default.
    ;(document as unknown as { execCommand: unknown }).execCommand = execCommandMock
    const ok = await copyTextToClipboard('hello')
    expect(ok).toBe(true)
    expect(execCommandMock).toHaveBeenCalledWith('copy')
  })

  it('returns false when no copy mechanism succeeds', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
    })
    ;(document as unknown as { execCommand: unknown }).execCommand = vi
      .fn()
      .mockReturnValue(false)
    const ok = await copyTextToClipboard('hello')
    expect(ok).toBe(false)
  })
})
