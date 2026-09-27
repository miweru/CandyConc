import type {
  CorpusSummary,
  ProductCapability,
  ProductCapabilityBackendRouteDescriptor,
} from '@/api/client'
import {
  hasParallelGroups,
  hasParallelKwic,
  hasPassageSearch,
  hasWordSimilarity,
  isCorpusPaired,
  supportsFrequencyGroup,
  supportsTokenAttribute,
  type CorpusFrequencyGroup,
} from '@/lib/corpusFeatureOptions'
import { t } from '@/i18n'

export type CorpusFeatureDecisionStatus = 'pass' | 'blocked' | 'unknown'

export interface ProductBackendRouteFeaturePredicate {
  (route: ProductCapabilityBackendRouteDescriptor): boolean
}

export interface CorpusFeatureAlternative {
  routePath?: string
  methods: string[]
  requirements: string[]
  missing: string[]
}

export interface CorpusFeatureDecision {
  status: CorpusFeatureDecisionStatus
  requirements: string[]
  missing: string[]
  alternatives: CorpusFeatureAlternative[]
}

function unique(values: Iterable<string | null | undefined>): string[] {
  return [...new Set([...values].filter((value): value is string => Boolean(value)))]
}

function routeRequirements(route: ProductCapabilityBackendRouteDescriptor): string[] {
  return unique(route.requires_corpus_features ?? [])
}

function routeMethods(route: ProductCapabilityBackendRouteDescriptor): string[] {
  return (route.methods ?? []).map((method) => method.toUpperCase())
}

export function corpusFeatureLabel(feature: string): string {
  if (feature.startsWith('token_attributes.')) {
    return t('capabilities.corpusFeatures.tokenAttribute', { name: feature.slice('token_attributes.'.length) })
  }
  if (feature.startsWith('frequency_groups.')) {
    return t('capabilities.corpusFeatures.frequencyGroup', { name: feature.slice('frequency_groups.'.length) })
  }
  if (feature === 'semantic.passage_search') return t('capabilities.corpusFeatures.passageIndex')
  if (feature === 'semantic.word_similarity') return t('capabilities.corpusFeatures.wordIndex')
  if (feature === 'semantic.sentence_alignment') return t('capabilities.corpusFeatures.sentenceAlignment')
  if (feature === 'alignment.parallel_groups') return t('capabilities.corpusFeatures.parallelGroups')
  if (feature === 'alignment.parallel_kwic') return t('capabilities.corpusFeatures.parallelKwic')
  if (feature === 'alignment.paired') return t('capabilities.corpusFeatures.paired')
  if (feature.startsWith('capabilities.')) return feature.slice('capabilities.'.length)
  return feature
}

export function isCorpusFeatureAvailable(summary: CorpusSummary | null, feature: string): boolean {
  if (!summary) return false
  if (feature.startsWith('token_attributes.')) {
    return supportsTokenAttribute(summary, feature.slice('token_attributes.'.length))
  }
  if (feature.startsWith('frequency_groups.')) {
    return supportsFrequencyGroup(summary, feature.slice('frequency_groups.'.length) as CorpusFrequencyGroup)
  }
  if (feature === 'semantic.passage_search') return hasPassageSearch(summary)
  if (feature === 'semantic.word_similarity') return hasWordSimilarity(summary)
  if (feature === 'semantic.sentence_alignment') return Boolean(summary.features?.semantic?.sentence_alignment)
  if (feature === 'alignment.parallel_groups') return hasParallelGroups(summary)
  if (feature === 'alignment.parallel_kwic') return hasParallelKwic(summary)
  if (feature === 'alignment.paired') return isCorpusPaired(summary)
  if (feature.startsWith('capabilities.')) {
    return summary.capabilities[feature.slice('capabilities.'.length)] === true
  }
  return summary.capabilities[feature] === true
}

export function productCapabilityFeatureAlternatives(
  capability: ProductCapability | undefined,
  predicate?: ProductBackendRouteFeaturePredicate,
): CorpusFeatureAlternative[] {
  if (!capability) return []
  const descriptors = capability.backend_route_descriptors ?? []
  const matchingRoutes = predicate ? descriptors.filter(predicate) : descriptors
  if (descriptors.length > 0) {
    return matchingRoutes.map((route) => ({
      routePath: route.path,
      methods: routeMethods(route),
      requirements: routeRequirements(route),
      missing: [],
    }))
  }

  const capabilityRequirements = unique(capability.requires_corpus_features ?? [])
  return capabilityRequirements.length
    ? [{ methods: [], requirements: capabilityRequirements, missing: [] }]
    : []
}

export function evaluateCapabilityCorpusFeatures(
  capability: ProductCapability | undefined,
  summary: CorpusSummary | null,
  predicate?: ProductBackendRouteFeaturePredicate,
): CorpusFeatureDecision {
  const alternatives = productCapabilityFeatureAlternatives(capability, predicate)
  const requirements = unique(alternatives.flatMap((alternative) => alternative.requirements))
  if (requirements.length === 0) {
    return { status: 'pass', requirements: [], missing: [], alternatives }
  }
  if (!summary) {
    return {
      status: 'unknown',
      requirements,
      missing: requirements,
      alternatives: alternatives.map((alternative) => ({
        ...alternative,
        missing: alternative.requirements,
      })),
    }
  }

  const checkedAlternatives = alternatives.map((alternative) => ({
    ...alternative,
    missing: alternative.requirements.filter((feature) => !isCorpusFeatureAvailable(summary, feature)),
  }))
  if (checkedAlternatives.some((alternative) => alternative.missing.length === 0)) {
    return {
      status: 'pass',
      requirements,
      missing: [],
      alternatives: checkedAlternatives,
    }
  }
  return {
    status: 'blocked',
    requirements,
    missing: unique(checkedAlternatives.flatMap((alternative) => alternative.missing)),
    alternatives: checkedAlternatives,
  }
}

export function corpusFeatureDecisionReason(
  label: string,
  decision: CorpusFeatureDecision,
): string | null {
  if (decision.status === 'pass') return null
  const requirements = decision.missing.map(corpusFeatureLabel).join(', ')
  if (decision.status === 'unknown') {
    return t('capabilities.corpusFeatures.waiting', { label, requirements })
  }
  return t('capabilities.corpusFeatures.missing', { label, requirements })
}

export function corpusFeatureDecisionPartialReason(
  label: string,
  decision: CorpusFeatureDecision,
): string | null {
  if (decision.status !== 'pass') return null
  const missing = unique(decision.alternatives.flatMap((alternative) => alternative.missing))
  if (!missing.length) return null
  return t('capabilities.corpusFeatures.partial', { label, missing: missing.map(corpusFeatureLabel).join(', ') })
}
