/**
 * D3 number formats that match the tables of the active locale.
 * Kept apart from `./format` so modules without charts do not load D3.
 */
import * as d3 from 'd3'
import { numberSeparators } from './format'

/** A D3 format locale built from the active Intl separators. */
export function d3FormatLocale(): d3.FormatLocaleObject {
  const { decimal, group } = numberSeparators()
  return d3.formatLocale({
    decimal,
    thousands: group,
    grouping: [3],
    currency: ['', ''],
  })
}

/** Like `d3.format(specifier)`, with the separators of the active locale. */
export function localeD3Format(specifier: string): (value: number | { valueOf(): number }) => string {
  return d3FormatLocale().format(specifier)
}
