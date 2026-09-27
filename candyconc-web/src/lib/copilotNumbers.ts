import { formatNumber, formatPercent } from '@/i18n/format'

/** A duration in milliseconds with a unit that fits its size: 250 µs, 12 ms, 1.23 s. */
export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms)) return '—'
  if (ms < 1) return `${formatNumber(ms * 1000, { maximumFractionDigits: 0 })} µs`
  if (ms < 1000) return `${formatNumber(ms, { maximumFractionDigits: 0 })} ms`
  return `${formatNumber(ms / 1000, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} s`
}

/** Share of successful attempts as a whole percentage (67 % or 67%). */
export function formatSuccessRate(successes: number, attempts: number): string {
  return formatPercent(successes / attempts, 0)
}
