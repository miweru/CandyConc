/**
 * Part-of-speech tagsets the interface can describe.
 *
 * The `pos` attribute holds whatever the import wrote: Universal POS from a
 * spaCy import, the source tagset from a VRT import. The manifest does not
 * name the tagset of a spaCy import, so the tagset is recognised from the
 * values the corpus actually contains. Help texts (tag descriptions, groups,
 * examples) are only shown for a recognised tagset.
 */

export type PosTagset = 'upos' | 'stts'

/** Universal Dependencies POS tags, plus SPACE which spaCy emits for whitespace. */
export const UPOS_TAGS: ReadonlySet<string> = new Set([
  'ADJ', 'ADP', 'ADV', 'AUX', 'CCONJ', 'DET', 'INTJ', 'NOUN', 'NUM', 'PART',
  'PRON', 'PROPN', 'PUNCT', 'SCONJ', 'SYM', 'VERB', 'X', 'SPACE',
])

/** STTS (Stuttgart-Tübingen tagset), including its punctuation tags. */
export const STTS_TAGS: ReadonlySet<string> = new Set([
  'ADJA', 'ADJD', 'ADV', 'APPR', 'APPRART', 'APPO', 'APZR', 'ART', 'CARD', 'FM',
  'ITJ', 'KOUI', 'KOUS', 'KON', 'KOKOM', 'NN', 'NE', 'PDS', 'PDAT', 'PIS', 'PIAT',
  'PIDAT', 'PPER', 'PPOSS', 'PPOSAT', 'PRELS', 'PRELAT', 'PRF', 'PWS', 'PWAT',
  'PWAV', 'PROAV', 'PTKA', 'PTKANT', 'PTKNEG', 'PTKVZ', 'PTKZU', 'TRUNC', 'VVFIN',
  'VVIMP', 'VVINF', 'VVIZU', 'VVPP', 'VAFIN', 'VAIMP', 'VAINF', 'VAPP', 'VMFIN',
  'VMINF', 'VMPP', 'XY', '$.', '$,', '$(',
])

/** STTS tags without punctuation, the ones with a description in the catalog. */
export const STTS_DESCRIBED_TAGS: ReadonlySet<string> = new Set(
  [...STTS_TAGS].filter((tag) => !tag.startsWith('$')),
)

/** Group ids in display order. Titles come from `search.searchBar.posGroups`. */
export const POS_GROUP_ORDER = ['nominal', 'verbal', 'adjAdv', 'pronArt', 'conj', 'particle', 'prep', 'other'] as const
export type PosGroup = (typeof POS_GROUP_ORDER)[number]

const UPOS_GROUPS: Record<string, PosGroup> = {
  NOUN: 'nominal',
  PROPN: 'nominal',
  VERB: 'verbal',
  AUX: 'verbal',
  ADJ: 'adjAdv',
  ADV: 'adjAdv',
  PRON: 'pronArt',
  DET: 'pronArt',
  CCONJ: 'conj',
  SCONJ: 'conj',
  PART: 'particle',
  ADP: 'prep',
}

const STTS_GROUPS: Record<string, PosGroup> = {
  NN: 'nominal',
  NE: 'nominal',
  VVFIN: 'verbal',
  VVIMP: 'verbal',
  VVINF: 'verbal',
  VVIZU: 'verbal',
  VVPP: 'verbal',
  VAFIN: 'verbal',
  VAIMP: 'verbal',
  VAINF: 'verbal',
  VAPP: 'verbal',
  VMFIN: 'verbal',
  VMINF: 'verbal',
  VMPP: 'verbal',
  PTKVZ: 'verbal',
  ADJA: 'adjAdv',
  ADJD: 'adjAdv',
  ADV: 'adjAdv',
  ART: 'pronArt',
  PPER: 'pronArt',
  PDS: 'pronArt',
  PDAT: 'pronArt',
  PIS: 'pronArt',
  PIAT: 'pronArt',
  PIDAT: 'pronArt',
  PPOSS: 'pronArt',
  PPOSAT: 'pronArt',
  PRELS: 'pronArt',
  PRELAT: 'pronArt',
  PRF: 'pronArt',
  PWS: 'pronArt',
  PWAT: 'pronArt',
  PWAV: 'pronArt',
  PROAV: 'pronArt',
  KOUI: 'conj',
  KOUS: 'conj',
  KON: 'conj',
  KOKOM: 'conj',
  PTKA: 'particle',
  PTKANT: 'particle',
  PTKNEG: 'particle',
  PTKZU: 'particle',
  APPR: 'prep',
  APPRART: 'prep',
  APPO: 'prep',
  APZR: 'prep',
}

/**
 * The tagset all non-empty values belong to, or null. A single value that is
 * neither UPOS nor STTS (another source tagset) means no recognised tagset.
 */
export function detectPosTagset(values: readonly string[]): PosTagset | null {
  const tags = values.map((value) => value.trim()).filter(Boolean)
  if (!tags.length) return null
  if (tags.every((tag) => UPOS_TAGS.has(tag))) return 'upos'
  if (tags.every((tag) => STTS_TAGS.has(tag))) return 'stts'
  return null
}

/** True when the catalog has a description for this tag in this tagset. */
export function isDescribedPosTag(tag: string, tagset: PosTagset | null): boolean {
  if (tagset === 'upos') return UPOS_TAGS.has(tag)
  if (tagset === 'stts') return STTS_DESCRIBED_TAGS.has(tag)
  return false
}

export function posTagGroup(tag: string, tagset: PosTagset | null): PosGroup {
  if (tagset === 'upos') return UPOS_GROUPS[tag] ?? 'other'
  if (tagset === 'stts') return STTS_GROUPS[tag] ?? 'other'
  return 'other'
}

const EXAMPLE_PREFERENCE: Record<PosTagset, readonly string[]> = {
  upos: ['NOUN', 'VERB', 'ADJ'],
  stts: ['NN', 'VVFIN', 'ADJA'],
}

/**
 * A tag of the corpus to use in examples: a noun or verb tag of the recognised
 * tagset when the corpus has it, else its most frequent non-punctuation tag.
 * `values` are ordered by frequency (lexicon suggestions with empty prefix).
 */
export function examplePosTag(values: readonly string[], tagset: PosTagset | null): string | null {
  const tags = values.map((value) => value.trim()).filter(Boolean)
  if (!tags.length) return null
  if (tagset) {
    const preferred = EXAMPLE_PREFERENCE[tagset].find((tag) => tags.includes(tag))
    if (preferred) return preferred
  }
  return tags.find((tag) => /[A-Za-z]/.test(tag) && tag !== 'PUNCT' && tag !== 'SPACE') ?? tags[0] ?? null
}
