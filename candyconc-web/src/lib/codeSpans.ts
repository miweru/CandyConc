export interface CodeSpanSegment {
  code: boolean
  text: string
}

/**
 * Splits an explanation into plain text and code segments. Query syntax in
 * explanation texts stands between backticks. An unpaired backtick stays text.
 */
export function splitCodeSpans(text: string): CodeSpanSegment[] {
  const segments: CodeSpanSegment[] = []
  let rest = text
  while (rest) {
    const open = rest.indexOf('`')
    const close = open >= 0 ? rest.indexOf('`', open + 1) : -1
    if (open < 0 || close < 0) {
      segments.push({ code: false, text: rest })
      break
    }
    if (open > 0) segments.push({ code: false, text: rest.slice(0, open) })
    if (close > open + 1) segments.push({ code: true, text: rest.slice(open + 1, close) })
    rest = rest.slice(close + 1)
  }
  return segments
}
