import type { FilterSpec, FilterSpecValue } from '@/api/client'
import { t } from '@/i18n'

export interface LegacyFilterBuckets {
  prompting_method: string[]
  model: string[]
  register: string[]
  source: string[]
}

export interface FilterSpecChip {
  field: string
  label: string
  valueLabel: string
  title: string
  kind: 'equals' | 'in' | 'range' | 'comparison' | 'unknown'
}

const LEGACY_FILTER_LABEL_KEYS: Record<keyof LegacyFilterBuckets, string> = {
  prompting_method: 'subcorpus.filterSpec.promptingMethod',
  model: 'subcorpus.filterSpec.model',
  register: 'subcorpus.filterSpec.register',
  source: 'subcorpus.filterSpec.source',
}

export const LEGACY_FILTER_FIELDS = Object.keys(LEGACY_FILTER_LABEL_KEYS) as Array<keyof LegacyFilterBuckets>

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

export function filterFieldLabel(field: string): string {
  const key = LEGACY_FILTER_LABEL_KEYS[field as keyof LegacyFilterBuckets]
  return key ? t(key) : field
}

export function filterSpecValueLabel(value: FilterSpecValue): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ')
  if (isRecord(value)) {
    if (value.op === 'between') return t('subcorpus.filterSpec.range', { lo: String(value.lo), hi: String(value.hi) })
    if (typeof value.op === 'string' && 'value' in value) {
      return `${value.op} ${String(value.value)}`
    }
  }
  return String(value)
}

export function filterSpecValueKind(value: FilterSpecValue): FilterSpecChip['kind'] {
  if (Array.isArray(value)) return 'in'
  if (isRecord(value)) {
    if (value.op === 'between') return 'range'
    if (typeof value.op === 'string' && 'value' in value) return 'comparison'
    return 'unknown'
  }
  return 'equals'
}

export function filterSpecChips(spec: FilterSpec | null | undefined): FilterSpecChip[] {
  if (!spec) return []
  return Object.entries(spec)
    .filter(([field]) => field.trim().length > 0)
    .map(([field, value]) => {
      const label = filterFieldLabel(field)
      const valueLabel = filterSpecValueLabel(value)
      return {
        field,
        label,
        valueLabel,
        title: `${label}: ${valueLabel}`,
        kind: filterSpecValueKind(value),
      }
    })
}

export function filterSpecSummaryParts(spec: FilterSpec | null | undefined): string[] {
  return filterSpecChips(spec).map((chip) => chip.title)
}

export function deriveFilterSpecFromLegacy(
  filters: LegacyFilterBuckets,
  explicit?: FilterSpec | null,
): FilterSpec {
  if (explicit && Object.keys(explicit).length) return { ...explicit }
  const spec: FilterSpec = {}
  for (const field of LEGACY_FILTER_FIELDS) {
    if (filters[field].length) spec[field] = [...filters[field]]
  }
  return spec
}

export function legacyFiltersFromSpec(spec: FilterSpec | null | undefined): LegacyFilterBuckets {
  const out: LegacyFilterBuckets = { prompting_method: [], model: [], register: [], source: [] }
  if (!spec) return out
  for (const field of LEGACY_FILTER_FIELDS) {
    const value = spec[field]
    if (Array.isArray(value)) {
      out[field] = value.map((item) => String(item))
    } else if (typeof value === 'string' || typeof value === 'number') {
      out[field] = [String(value)]
    }
  }
  return out
}

export function searchableFilterSpecText(spec: FilterSpec | null | undefined): string {
  return filterSpecChips(spec)
    .flatMap((chip) => [chip.field, chip.label, chip.valueLabel])
    .join(' ')
}
