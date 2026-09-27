/**
 * The two sides of a paired corpus as the index records them in text_type.
 *
 * Paired imports from builder revision 2 on write `anchor` for the version
 * the others are compared with and `version` for every other one. Older
 * paired imports and the human/AI research layout write `human` and `ai`.
 * The server reads both pairs (candyconc.core.pairing), and so does the
 * interface. The human/AI wording belongs only to corpora that carry these
 * values.
 */
import type { CorpusSummary } from '@/api/client'
import { alignmentPairingSchema } from '@/lib/corpusFeatureOptions'
import { t } from '@/i18n'

export interface PairSideValues {
  anchor: string
  version: string
}

const ANCHOR_VALUES = new Set(['anchor', 'human'])
const VERSION_VALUES = new Set(['version', 'ai'])

const HUMAN_AI: PairSideValues = { anchor: 'human', version: 'ai' }
const ANCHOR_VERSION: PairSideValues = { anchor: 'anchor', version: 'version' }

function normalize(value: unknown): string {
  return String(value ?? '').trim().toLowerCase()
}

export function isAnchorSide(textType: unknown): boolean {
  return ANCHOR_VALUES.has(normalize(textType))
}

export function isVersionSide(textType: unknown): boolean {
  return VERSION_VALUES.has(normalize(textType))
}

/**
 * The text_type values of the two sides in a corpus. The pairing schema names
 * the anchor value (`default_anchor_role`). Without one the corpus follows
 * the older human/AI values.
 */
export function pairSideValues(summary: CorpusSummary | null | undefined): PairSideValues {
  const anchor = normalize(alignmentPairingSchema(summary ?? null)?.default_anchor_role)
  return anchor === 'anchor' ? ANCHOR_VERSION : HUMAN_AI
}

/** The pair side values of a corpus judged by the text_type values it has. */
export function pairSideValuesFromTextTypes(values: readonly string[]): PairSideValues {
  const present = new Set(values.map(normalize))
  if ((present.has('anchor') || present.has('version')) && !present.has('human') && !present.has('ai')) {
    return ANCHOR_VERSION
  }
  return HUMAN_AI
}

/** Display label of a text_type value. Other values stay as the data has them. */
export function textTypeLabel(value: string): string {
  switch (normalize(value)) {
    case 'anchor':
      return t('common.pairSides.anchor')
    case 'version':
      return t('common.pairSides.version')
    case 'human':
      return t('common.pairSides.human')
    case 'ai':
      return t('common.pairSides.ai')
    case 'mixed':
      return t('common.pairSides.mixed')
    default:
      return value
  }
}
