/**
 * Locale-aware number and date formatting for the active interface language.
 *
 * Every function reads `currentLocale()` at call time, so a computed or
 * template that formats a value re-renders when the language changes.
 * Components use the same functions through `useLocaleFormat()`.
 */
import { currentLocale, intlLocale } from './locale'
import { t } from './index'

type DateInput = Date | number | string

function toDate(value: DateInput): Date {
  return value instanceof Date ? value : new Date(value)
}

/** Counts and other numbers with the locale's grouping (1.234 or 1,234). */
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return value.toLocaleString(intlLocale(), options)
}

/**
 * A statistic with a fixed number of fraction digits (2,50 or 2.50).
 * Non-finite or missing input renders as a dash placeholder.
 */
export function formatDecimal(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString(intlLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** A ratio as percentage (0.425 gives 42,5 % or 42.5%). */
export function formatPercent(value: number, digits = 1): string {
  return value.toLocaleString(intlLocale(), {
    style: 'percent',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatDate(value: DateInput, options?: Intl.DateTimeFormatOptions): string {
  return toDate(value).toLocaleDateString(intlLocale(), options)
}

export function formatTime(value: DateInput, options?: Intl.DateTimeFormatOptions): string {
  return toDate(value).toLocaleTimeString(intlLocale(), options)
}

export function formatDateTime(value: DateInput, options?: Intl.DateTimeFormatOptions): string {
  return toDate(value).toLocaleString(intlLocale(), options)
}

/**
 * A confidence interval as "0,5 bis 2,1" or "0.5 to 2.1". A bracket with a
 * comma between the bounds reads as four numbers in German, where the comma
 * is the decimal separator ("[0,5, 2,1]").
 */
export function formatInterval(low: number | null | undefined, high: number | null | undefined, digits = 2): string {
  return t('common.format.interval', { low: formatDecimal(low, digits), high: formatDecimal(high, digits) })
}

/** Decimal and group separator of the active locale, for D3 and CSV helpers. */
export function numberSeparators(): { decimal: string; group: string } {
  const parts = new Intl.NumberFormat(intlLocale()).formatToParts(12345.6)
  return {
    decimal: parts.find((part) => part.type === 'decimal')?.value ?? '.',
    group: parts.find((part) => part.type === 'group')?.value ?? ',',
  }
}

export { currentLocale, intlLocale }
