import { parseCoKwicQuery } from './coKwic'
import { canHydrateSimpleSearchQuery, hydrateSimpleSearchQuery } from '@/lib/queryBuilder/simple'
import { t } from '@/i18n'

const CQL_PREFIX_RE = /^cql:\s*/i
const CQL_SHAPE_RE = /^(?:\[|\(|within\s*\(|where\s*\()/i

export function stripCoQueryTerm(raw: string): string {
  const trimmed = (raw ?? '').trim()
  if (!trimmed) return ''
  const parsed = parseCoKwicQuery(trimmed)
  if (parsed?.term) return parsed.term.trim()
  return trimmed
}

export function extractSimpleCqlToken(raw: string): string | null {
  const trimmed = (raw ?? '').trim()
  if (!trimmed) return null
  const query = normalizeBuilderSeedTerm(trimmed)
  const hydrated = hydrateSimpleSearchQuery(query)
  const token = hydrated?.term?.trim()
  return token ? token : null
}

export function normalizeBuilderSeedTerm(raw: string): string {
  const trimmed = (raw ?? '').trim()
  if (!trimmed) return ''
  return trimmed.replace(CQL_PREFIX_RE, '').trim()
}

export function shouldOpenQueryBuilderInAdvancedMode(raw: string): boolean {
  const trimmed = (raw ?? '').trim()
  if (!trimmed) return false
  if (CQL_PREFIX_RE.test(trimmed)) return true
  const query = normalizeBuilderSeedTerm(trimmed)
  if (canHydrateSimpleSearchQuery(query)) return false
  return CQL_SHAPE_RE.test(query)
}

export function resolveWordSketchTerm(raw: string): { term: string | null; reason?: string } {
  const base = stripCoQueryTerm(raw)
  if (!base) return { term: null, reason: t('search.queryTerm.enterWordOrQuery') }
  if (base.toLowerCase().startsWith('cql:') && !base.slice(4).trim()) {
    return { term: null, reason: t('search.queryTerm.queryMissing') }
  }
  return { term: base }
}
