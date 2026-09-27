import type { FilterSpec } from '@/api/client'
import type { RunRecordResearchScopeEvidence } from '@/types/copilot-protocol'
import { csvMeta } from '@/utils/csv'
import { describeScopeEvidence, formatScopeResolvedAt } from '@/lib/scopeEvidence'
import { quickHash } from '@/utils/hashing'
import { t } from '@/i18n'

export type ResearchScopeStatus = 'corpus' | 'fresh' | 'dirty' | 'stale' | 'warning'

export interface ResearchScopeSource {
  activeCorpus?: string | null
  hasActiveDocset: boolean
  activeDocsetId?: string | null
  isDirty: boolean
  activeScopeStale?: boolean | null
  activeScopeWarning?: string | null
  activeScopeResolvedAt?: number | null
  activeSubcorpusName?: string | null
  lastQuery?: string | null
  metaSchemaHash?: string | null
  activeFilterSpec?: FilterSpec | null
  stats?: {
    docCount?: number
    tokenCount?: number
    refDocCount?: number
  }
  filters?: {
    prompting_method: string[]
    model: string[]
    register: string[]
    source: string[]
  }
  includeAi?: boolean
  includeHuman?: boolean
}

export interface ResearchScopeEvidence {
  status: ResearchScopeStatus
  corpus: string
  docsetId?: string
  label: string
  warning?: string
  resolvedAt?: number
  resolvedAtLabel?: string
  metadataSchemaHash?: string
  filterSpec?: FilterSpec
  scopeHash: string
  stats: {
    docCount?: number
    tokenCount?: number
    refDocCount?: number
  }
}

export interface ResearchScopePolicyResult {
  ok: boolean
  docsetId?: string
  message?: string
  evidence: ResearchScopeEvidence
}

export interface ResearchScopePolicyOptions {
  operation: string
  useDocsetScope?: boolean
  blockDirty?: boolean
  allowStale?: boolean
}

function scopeStatus(source: ResearchScopeSource): ResearchScopeStatus {
  if (!source.hasActiveDocset) return 'corpus'
  if (source.isDirty) return 'dirty'
  if (source.activeScopeStale) return 'stale'
  if (source.activeScopeWarning) return 'warning'
  return 'fresh'
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(',')}}`
  }
  return JSON.stringify(value)
}

function hashString(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

function buildScopeHash(source: ResearchScopeSource): string {
  return hashString(stableJson({
    corpus: source.activeCorpus || 'default',
    query: source.lastQuery || null,
    filters: source.filters ?? null,
    filterSpec: source.activeFilterSpec ?? null,
    includeAi: source.includeAi ?? null,
    includeHuman: source.includeHuman ?? null,
    metadataSchemaHash: source.metaSchemaHash ?? null,
    subcorpusName: source.activeSubcorpusName ?? null,
  }))
}

export function buildResearchScopeEvidence(source: ResearchScopeSource): ResearchScopeEvidence {
  const status = scopeStatus(source)
  const description = describeScopeEvidence({
    hasActiveDocset: source.hasActiveDocset,
    isDirty: source.isDirty,
    activeScopeStale: Boolean(source.activeScopeStale),
    activeScopeWarning: source.activeScopeWarning ?? null,
    activeScopeResolvedAt: source.activeScopeResolvedAt ?? null,
  })
  const resolvedAt = source.activeScopeResolvedAt ?? undefined
  return {
    status,
    corpus: source.activeCorpus || 'default',
    docsetId: source.hasActiveDocset && source.activeDocsetId ? source.activeDocsetId : undefined,
    label: source.hasActiveDocset ? description.label : t('search.researchScope.wholeCorpus'),
    warning: description.warning ?? undefined,
    resolvedAt,
    resolvedAtLabel: formatScopeResolvedAt(resolvedAt) ?? undefined,
    metadataSchemaHash: source.metaSchemaHash ?? undefined,
    filterSpec: source.activeFilterSpec ? { ...source.activeFilterSpec } : undefined,
    scopeHash: buildScopeHash(source),
    stats: {
      docCount: source.stats?.docCount,
      tokenCount: source.stats?.tokenCount,
      refDocCount: source.stats?.refDocCount,
    },
  }
}

export function researchScopeToRunEvidence(
  evidence: ResearchScopeEvidence,
  subcorpusName?: string | null
): Partial<RunRecordResearchScopeEvidence> {
  return {
    corpusId: evidence.corpus,
    scopeHash: evidence.scopeHash,
    scopeStatus: evidence.status,
    label: evidence.label,
    docsetId: evidence.docsetId,
    subcorpusName: subcorpusName ?? undefined,
    metadataSchemaHash: evidence.metadataSchemaHash,
  }
}

export function executionScopeForApi(
  source: ResearchScopeSource,
  corpus: string,
  docsetId?: string
): Partial<RunRecordResearchScopeEvidence> {
  if (docsetId && source.activeDocsetId === docsetId) {
    return researchScopeToRunEvidence(
      buildResearchScopeEvidence(source),
      source.activeSubcorpusName
    )
  }
  if (docsetId) {
    return {
      corpusId: corpus,
      scopeHash: quickHash({ corpus, docsetId }),
      scopeStatus: 'unknown',
      label: `Docset ${docsetId}`,
      docsetId,
      metadataSchemaHash: source.metaSchemaHash ?? undefined,
    }
  }
  return researchScopeToRunEvidence(buildResearchScopeEvidence({
    activeCorpus: corpus,
    hasActiveDocset: false,
    activeDocsetId: null,
    isDirty: false,
    activeScopeStale: false,
    activeScopeWarning: null,
    activeScopeResolvedAt: null,
    metaSchemaHash: source.metaSchemaHash,
  }))
}

export function ensureUsableResearchScope(
  source: ResearchScopeSource,
  options: ResearchScopePolicyOptions
): ResearchScopePolicyResult {
  const evidence = buildResearchScopeEvidence(source)
  const useDocsetScope = options.useDocsetScope ?? true
  const blockDirty = options.blockDirty ?? true
  const allowStale = options.allowStale ?? true

  if (!useDocsetScope || !source.hasActiveDocset) {
    return { ok: true, evidence: { ...evidence, docsetId: undefined }, docsetId: undefined }
  }

  if (blockDirty && source.isDirty) {
    return {
      ok: false,
      evidence,
      message: t('search.researchScope.needsApplied', { operation: options.operation }),
    }
  }

  if (!allowStale && source.activeScopeStale) {
    return {
      ok: false,
      evidence,
      message: t('search.researchScope.needsFresh', { operation: options.operation }),
    }
  }

  return { ok: true, evidence, docsetId: evidence.docsetId }
}

export function researchScopeMetaPairs(source: ResearchScopeSource): Array<[string, string]> {
  const evidence = buildResearchScopeEvidence(source)
  const pairs: Array<[string, string]> = [
    ['ScopeStatus', evidence.status],
    ['ScopeLabel', evidence.label],
    ['ScopeCorpus', evidence.corpus],
    ['ScopeDocset', evidence.docsetId ?? 'all'],
    ['ScopeHash', evidence.scopeHash],
    ['ScopeDirty', String(source.isDirty)],
    ['ScopeStale', String(Boolean(source.activeScopeStale))],
  ]
  if (evidence.warning) pairs.push(['ScopeWarning', evidence.warning])
  if (evidence.resolvedAt) pairs.push(['ScopeResolvedAt', new Date(evidence.resolvedAt).toISOString()])
  if (evidence.metadataSchemaHash) pairs.push(['ScopeMetadataSchemaHash', evidence.metadataSchemaHash])
  if (evidence.filterSpec) pairs.push(['ScopeFilterSpec', JSON.stringify(evidence.filterSpec)])
  if (typeof evidence.stats.docCount === 'number') pairs.push(['ScopeDocCount', String(evidence.stats.docCount)])
  if (typeof evidence.stats.tokenCount === 'number') pairs.push(['ScopeTokenCount', String(evidence.stats.tokenCount)])
  if (typeof evidence.stats.refDocCount === 'number') pairs.push(['ScopeRefDocCount', String(evidence.stats.refDocCount)])
  return pairs
}

export function researchScopeCsvMeta(source: ResearchScopeSource): string[] {
  return researchScopeMetaPairs(source).map(([label, value]) => csvMeta(label, value))
}

export function researchScopeMarkdownMeta(source: ResearchScopeSource): string[] {
  return researchScopeMetaPairs(source).map(([label, value]) => `- ${label}: ${value}`)
}

export function researchScopeLatexMeta(source: ResearchScopeSource, escapeLatex: (value: string) => string): string[] {
  return researchScopeMetaPairs(source).map(([label, value]) => `${escapeLatex(label)}: ${escapeLatex(value)}\\`)
}
