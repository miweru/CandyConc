import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { executeQuery, executeQueryStreaming } from '@/api/client'
import { clearAuthToken } from '@/api/auth'
import { kwicSpanDisplay } from '@/utils/kwicSpan'
import { readRowSpacing, spansFromTokenStarts } from '@/utils/sourceSpacing'

// A corpus with whitespace_after.bin: the server joins the tokens as written
// and sends token_starts, because "soul." is two tokens ("soul" and ".").
describe('spansFromTokenStarts', () => {
  it('splits attached punctuation into its own token', () => {
    const text = 'the soul. No words'
    const spans = spansFromTokenStarts(text, [0, 4, 8, 10, 13])!
    expect(spans.map((s) => text.slice(s.start, s.end))).toEqual(['the', 'soul', '.', 'No', 'words'])
  })

  it('keeps a line break token, so indices match the server positions', () => {
    const text = 'war.\nIn'
    const spans = spansFromTokenStarts(text, [0, 3, 4, 5])!
    expect(spans.map((s) => text.slice(s.start, s.end))).toEqual(['war', '.', '\n', 'In'])
  })

  it('counts code points like the server, not UTF-16 units', () => {
    const text = '😀 ok!'
    // Server offsets (code points): 😀=0, ok=2, !=4
    const spans = spansFromTokenStarts(text, [0, 2, 4])!
    expect(spans.map((s) => text.slice(s.start, s.end))).toEqual(['😀', 'ok', '!'])
  })

  it('rejects offsets that do not fit the text', () => {
    expect(spansFromTokenStarts('abc', [1])).toBeNull()
    expect(spansFromTokenStarts('abc', [0, 9])).toBeNull()
    expect(spansFromTokenStarts('abc', undefined)).toBeNull()
  })
})

describe('kwicSpanDisplay with the original spacing', () => {
  it('joins an attached match token without a space', () => {
    const out = kwicSpanDisplay({
      left: 'PRESIDENT HARRY S.',
      match: 'TRUMAN',
      right: "'S ADDRESS BEFORE",
      matchOffsets: [1],
      tokenStarts: { left: [0, 10, 16], kw: [0], right: [0, 3, 11] },
      wsBeforeKw: true,
      wsAfterKw: false,
    })
    expect(out.match).toBe("TRUMAN'S")
    expect(out.right).toBe('ADDRESS BEFORE')
    expect(out.rightSpans!.map((s) => out.right.slice(s.start, s.end))).toEqual(['ADDRESS', 'BEFORE'])
  })

  it('shifts collocate offsets over attached tokens', () => {
    const out = kwicSpanDisplay({
      left: 'of the common',
      match: 'people',
      right: '.\nIn the war',
      matchOffsets: [-2, -1],
      collocateOffsets: [-3, 4],
      tokenStarts: { left: [0, 3, 7], kw: [0], right: [0, 1, 2, 5, 9] },
      wsBeforeKw: true,
      wsAfterKw: false,
    })
    expect(out.match).toBe('the common people')
    expect(out.left).toBe('of')
    // offset 4 is the fourth token right of the node: ".", "\n", "In", "the"
    const spans = out.rightSpans!
    expect(out.right.slice(spans[3]!.start, spans[3]!.end)).toBe('the')
    expect(out.collocateOffsets).toEqual([-1, 4])
  })

  it('without token_starts keeps the legacy whitespace split', () => {
    const out = kwicSpanDisplay({ left: 'a b', match: 'x', right: 'y z', matchOffsets: [1] })
    expect(out.match).toBe('x y')
    expect(out.rightSpans).toBeUndefined()
  })
})

describe('readRowSpacing', () => {
  it('reads valid fields and ignores malformed ones', () => {
    expect(readRowSpacing({ token_starts: { left: [0], kw: [0], right: [0, 2] }, ws_before_kw: true, ws_after_kw: false }))
      .toEqual({ tokenStarts: { left: [0], kw: [0], right: [0, 2] }, wsBeforeKw: true, wsAfterKw: false })
    expect(readRowSpacing({ token_starts: { left: ['x'], kw: [0], right: [] } })).toEqual({})
    expect(readRowSpacing({})).toEqual({})
  })
})

describe('API client keeps the spacing fields', () => {
  const row = {
    left: 'can soothe the',
    kw: 'soul',
    right: '. No words',
    pos: 12,
    doc_id: 3,
    token_starts: { left: [0, 4, 11], kw: [0], right: [0, 2, 5] },
    ws_before_kw: true,
    ws_after_kw: false,
  }

  beforeEach(() => {
    vi.clearAllMocks()
    clearAuthToken()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('executeQuery passes token_starts and the kw flags through', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify([row]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))))
    const result = await executeQuery({ term: 'soul' })
    expect(result.hits[0]).toMatchObject({
      right: '. No words',
      token_starts: row.token_starts,
      ws_before_kw: true,
      ws_after_kw: false,
    })
  })

  it('executeQueryStreaming passes them through', async () => {
    const payload = `event: batch\ndata: ${JSON.stringify([row])}\n\nevent: done\ndata: {"total":1}\n\n`
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(payload, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }))))
    const events = []
    for await (const event of executeQueryStreaming({ term: 'soul' })) events.push(event)
    const batch = events.find((event) => event.type === 'batch')!
    expect(batch.hits![0]).toMatchObject({ token_starts: row.token_starts, ws_after_kw: false })
  })
})
