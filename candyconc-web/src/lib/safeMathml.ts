/**
 * Presentation MathML from the method catalog, checked before it is rendered
 * with v-html. The markup comes from the own backend catalog
 * (candyconc.analysis_defaults). The check keeps a malformed method block
 * from injecting arbitrary HTML.
 */
export function safeMathml(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed) return null
  if (!/^<math[\s>]/.test(trimmed) || !trimmed.endsWith('</math>')) return null
  if (/<\s*(script|iframe|img|style)\b/i.test(trimmed) || /\son\w+\s*=/i.test(trimmed)) return null
  return trimmed
}
