import type { CorpusSummary, SuggestionItem } from '@/api/client'
import type { SimpleSearchIntent } from '@/lib/queryBuilder/simple'
import { t } from '@/i18n'

export type CorpusTokenAttribute = string
export type CorpusFrequencyGroup = 'word' | 'lemma' | 'pos'

export interface CorpusQueryAttributeOption {
  attr: CorpusTokenAttribute
  cqlAttribute: string
  label: string
  requires: string[]
}

export interface CorpusFrequencyGroupOption {
  value: CorpusFrequencyGroup
  label: string
  requires: string[]
}

export interface CorpusSimpleIntentOption {
  intent: SimpleSearchIntent
  label: string
  requires: string[]
}

type CapabilityMap = Record<string, boolean>

const CQL_PARAMETER_ATTRIBUTES = new Set(['k'])
const KNOWN_OPTIONAL_TOKEN_ATTRIBUTES = new Set(['lemma', 'pos', 'ner', 'morph', 'rel', 'sim'])
const WORD_KEYS = ['word', 'word_lex', 'token_word', 'tokens_word']
const LEMMA_KEYS = ['lemma', 'lemma_lex', 'token_lemma', 'tokens_lemma']
const POS_KEYS = ['pos', 'pos_lex', 'tag_pos', 'token_pos', 'tokens_pos']
const NER_KEYS = ['ner', 'ent', 'entity', 'entities', 'ent_lex', 'token_ent', 'token_ner', 'tokens_ner']
const MORPH_KEYS = ['morph', 'morph_lex', 'token_morph', 'tokens_morph']
const REL_KEYS = ['rel', 'rel_lex', 'token_rel', 'tokens_rel']
const LEGACY_WORD_SIMILARITY_KEYS = ['word_similarity', 'faiss_word']

const QUERY_ATTRIBUTES: CorpusQueryAttributeOption[] = [
  { attr: 'word', cqlAttribute: 'word', get label() { return t('corpus.featureOptions.attrWord') }, requires: WORD_KEYS },
  { attr: 'lemma', cqlAttribute: 'lemma', get label() { return t('corpus.featureOptions.attrLemma') }, requires: LEMMA_KEYS },
  { attr: 'pos', cqlAttribute: 'pos', get label() { return t('corpus.featureOptions.attrPos') }, requires: POS_KEYS },
  { attr: 'ner', cqlAttribute: 'ner', get label() { return t('corpus.featureOptions.attrNer') }, requires: NER_KEYS },
  { attr: 'morph', cqlAttribute: 'morph', get label() { return t('corpus.featureOptions.attrMorph') }, requires: MORPH_KEYS },
  { attr: 'rel', cqlAttribute: 'rel', get label() { return t('corpus.featureOptions.attrRel') }, requires: REL_KEYS },
  { attr: 'sim', cqlAttribute: 'sim', get label() { return t('corpus.featureOptions.attrSim') }, requires: LEGACY_WORD_SIMILARITY_KEYS },
]

const FREQUENCY_GROUPS: CorpusFrequencyGroupOption[] = [
  { value: 'word', get label() { return t('corpus.featureOptions.groupWord') }, requires: WORD_KEYS },
  { value: 'lemma', get label() { return t('corpus.featureOptions.groupLemma') }, requires: LEMMA_KEYS },
  { value: 'pos', get label() { return t('corpus.featureOptions.groupPos') }, requires: POS_KEYS },
]

const SIMPLE_INTENTS: CorpusSimpleIntentOption[] = [
  { intent: 'exact', get label() { return t('corpus.featureOptions.intentExact') }, requires: WORD_KEYS },
  { intent: 'lemma', get label() { return t('corpus.featureOptions.intentLemma') }, requires: LEMMA_KEYS },
  { intent: 'similar', get label() { return t('corpus.featureOptions.intentSimilar') }, requires: LEGACY_WORD_SIMILARITY_KEYS },
]

function caps(summary: CorpusSummary | null): CapabilityMap {
  return summary?.capabilities ?? {}
}

function hasAny(summary: CorpusSummary | null, keys: string[]): boolean {
  if (keys.includes('word')) return true
  const capabilityMap = caps(summary)
  return keys.some((key) => capabilityMap[key] === true)
}

function descriptorTokenAttributes(summary: CorpusSummary | null): CorpusQueryAttributeOption[] | null {
  const attrs = summary?.features?.token_attributes
  if (!attrs?.length) return null
  return attrs.map((attr) => ({
    attr: attr.id,
    cqlAttribute: attr.cql_attribute,
    label: attr.label,
    requires: attr.artifacts ?? [],
  }))
}

function descriptorFrequencyGroups(summary: CorpusSummary | null): CorpusFrequencyGroupOption[] | null {
  const groups = summary?.features?.frequency_groups
  if (!groups?.length) return null
  return groups
    .filter((group) => group.id === 'word' || group.id === 'lemma' || group.id === 'pos')
    .map((group) => ({
      value: group.id as CorpusFrequencyGroup,
      label: group.label,
      requires: group.artifacts ?? [],
    }))
}

export function supportsTokenAttribute(
  summary: CorpusSummary | null,
  attr: CorpusTokenAttribute,
): boolean {
  const normalized = normalizeCqlAttribute(attr) ?? attr
  const descriptorOptions = descriptorTokenAttributes(summary)
  if (descriptorOptions) {
    return descriptorOptions.some((entry) => entry.attr === normalized || entry.cqlAttribute === normalized)
  }
  const option = QUERY_ATTRIBUTES.find((entry) => entry.attr === normalized)
  return option ? hasAny(summary, option.requires) : false
}

export function supportsFrequencyGroup(
  summary: CorpusSummary | null,
  group: CorpusFrequencyGroup,
): boolean {
  const descriptorOptions = descriptorFrequencyGroups(summary)
  if (descriptorOptions) {
    return descriptorOptions.some((entry) => entry.value === group)
  }
  const option = FREQUENCY_GROUPS.find((entry) => entry.value === group)
  return option ? hasAny(summary, option.requires) : false
}

export function supportsSimpleIntent(
  summary: CorpusSummary | null,
  intent: SimpleSearchIntent,
): boolean {
  if (intent === 'exact') return supportsTokenAttribute(summary, 'word')
  if (intent === 'lemma') return supportsTokenAttribute(summary, 'lemma')
  if (intent === 'similar') return hasWordSimilarity(summary)
  const option = SIMPLE_INTENTS.find((entry) => entry.intent === intent)
  return option ? hasAny(summary, option.requires) : false
}

export function queryAttributeOptions(summary: CorpusSummary | null): CorpusQueryAttributeOption[] {
  const descriptorOptions = descriptorTokenAttributes(summary)
  if (descriptorOptions) return descriptorOptions
  return QUERY_ATTRIBUTES.filter((option) => hasAny(summary, option.requires))
}

export function frequencyGroupOptions(summary: CorpusSummary | null): CorpusFrequencyGroupOption[] {
  const descriptorOptions = descriptorFrequencyGroups(summary)
  if (descriptorOptions?.length) return descriptorOptions
  return FREQUENCY_GROUPS.filter((option) => hasAny(summary, option.requires))
}

export function simpleIntentOptions(summary: CorpusSummary | null): CorpusSimpleIntentOption[] {
  return SIMPLE_INTENTS.filter((option) => supportsSimpleIntent(summary, option.intent))
}

export function hasSemanticSearch(summary: CorpusSummary | null): boolean {
  return hasPassageSearch(summary) || hasWordSimilarity(summary)
}

export function hasPassageSearch(summary: CorpusSummary | null): boolean {
  return summary?.features?.semantic?.passage_search === true
}

export function hasWordSimilarity(summary: CorpusSummary | null): boolean {
  if (summary?.features?.semantic) return Boolean(summary.features.semantic.word_similarity)
  return hasAny(summary, LEGACY_WORD_SIMILARITY_KEYS)
}

export function isCorpusPaired(summary: CorpusSummary | null): boolean {
  if (summary?.features?.alignment) return Boolean(summary.features.alignment.paired)
  return Boolean(summary?.capabilities.parallel || summary?.paired)
}

export function alignmentPairAxes(summary: CorpusSummary | null): string[] {
  if (summary?.features?.alignment?.pair_axes) return summary.features.alignment.pair_axes
  return summary?.pair_axes ?? []
}

export function alignmentPairingSchema(summary: CorpusSummary | null) {
  return summary?.features?.alignment?.pairing_schema ?? null
}

export function alignmentGenericAxisFiltersSupported(summary: CorpusSummary | null): boolean {
  return Boolean(alignmentPairingSchema(summary)?.generic_axis_filters)
}

function humanizePairAxis(axis: string): string {
  const trimmed = axis.trim()
  if (!trimmed) return ''
  return trimmed.replace(/[_-]+/g, ' ')
}

export function alignmentPairAxesLabel(summary: CorpusSummary | null): string {
  const axes = alignmentPairAxes(summary).map(humanizePairAxis).filter(Boolean)
  return axes.length ? axes.join(', ') : t('corpus.featureOptions.notDeclared')
}

export function alignmentVariantControlLabel(summary: CorpusSummary | null): string {
  const axes = alignmentPairAxes(summary).map(humanizePairAxis).filter(Boolean)
  return axes.length
    ? t('corpus.featureOptions.variantsWithAxes', { axes: axes.join(', ') })
    : t('corpus.featureOptions.variants')
}

export function alignmentExecutionContractLabel(summary: CorpusSummary | null): string {
  const schema = alignmentPairingSchema(summary)
  if (!schema) return t('corpus.featureOptions.noPairingSchema')
  if (schema.generic_axis_filters) {
    return t('corpus.featureOptions.pairingGeneric', { schema: schema.schema_id })
  }
  const legacy = schema.legacy_variant_filter_field
    ? t('corpus.featureOptions.pairingLegacy', { field: schema.legacy_variant_filter_field })
    : ''
  return t('corpus.featureOptions.pairingGroup', { schema: schema.schema_id, field: schema.group_key_field, legacy })
}

export function hasParallelGroups(summary: CorpusSummary | null): boolean {
  if (summary?.features?.alignment) return Boolean(summary.features.alignment.parallel_groups)
  return isCorpusPaired(summary)
}

export function hasParallelKwic(summary: CorpusSummary | null): boolean {
  if (summary?.features?.alignment) return Boolean(summary.features.alignment.parallel_kwic)
  return isCorpusPaired(summary)
}

export function normalizeCqlAttribute(attr: string): CorpusTokenAttribute | null {
  const normalized = attr.trim().toLowerCase()
  if (normalized === 'ent' || normalized === 'entity') return 'ner'
  if (
    normalized === 'word' ||
    normalized === 'lemma' ||
    normalized === 'pos' ||
    normalized === 'ner' ||
    normalized === 'morph' ||
    normalized === 'rel' ||
    normalized === 'sim'
  ) {
    return normalized
  }
  return null
}

export function cqlTokenAttributesInText(text: string): CorpusTokenAttribute[] {
  const attrs = new Set<CorpusTokenAttribute>()
  const patterns = [/\[\s*([a-z_][\w-]*)\s*=/gi, /[&|]\s*([a-z_][\w-]*)\s*=/gi]
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      const attr = String(match[1] ?? '').trim().toLowerCase()
      if (!attr || CQL_PARAMETER_ATTRIBUTES.has(attr)) continue
      attrs.add(normalizeCqlAttribute(attr) ?? attr)
    }
  }
  return [...attrs]
}

export function unsupportedCqlAttributes(
  summary: CorpusSummary | null,
  text: string,
): CorpusTokenAttribute[] {
  const descriptorBacked = Boolean(summary?.features?.token_attributes?.length)
  return cqlTokenAttributesInText(text).filter((attr) => {
    if (supportsTokenAttribute(summary, attr)) return false
    return descriptorBacked || KNOWN_OPTIONAL_TOKEN_ATTRIBUTES.has(attr)
  })
}

export function isCqlSuggestionSupported(summary: CorpusSummary | null, item: SuggestionItem): boolean {
  const hint = item.hint?.toLowerCase() ?? ''
  const text = item.text.toLowerCase()
  if (unsupportedCqlAttributes(summary, `${item.text}\n${item.hint ?? ''}`).length > 0) {
    return false
  }
  const checks: Array<[CorpusTokenAttribute, RegExp]> = [
    ['lemma', /\blemm(?:a|ata)\b|\[\s*lemma\s*=|\b&\s*lemma\s*=/i],
    ['pos', /\bpos\b|\[\s*pos\s*=|\b&\s*pos\s*=/i],
    ['ner', /\bner\b|\bentit[aä]t|\[\s*(?:ner|ent)\s*=|\b&\s*(?:ner|ent)\s*=/i],
    ['morph', /\bmorph(?:ologie)?\b|\[\s*morph\s*=|\b&\s*morph\s*=/i],
    ['rel', /\brelation\b|\bdependency\b|\[\s*rel\s*=|\b&\s*rel\s*=/i],
    ['sim', /\bsemantik|\bembedding|\bsim(?:\b|=)|\[\s*sim\s*=|\b&\s*sim\s*=/i],
  ]
  return checks.every(([attr, pattern]) => {
    if (supportsTokenAttribute(summary, attr)) return true
    return !(pattern.test(hint) || pattern.test(text))
  })
}
