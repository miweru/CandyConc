/**
 * Starter questions for the empty copilot chat.
 *
 * They are examples, not a workflow: general corpus questions that fit the
 * active corpus. Metadata fields come from the corpus metadata schema, so a
 * question names a field the corpus really has. No field, tag or word of a
 * particular research project is built in.
 */
import { t } from '@/i18n'

export interface StarterMetaField {
  name: string
  kind?: string
  hasString?: boolean
  hasNumber?: boolean
  stringValueCount?: number | null
}

export interface StarterContext {
  /** The corpus has a part-of-speech attribute. */
  hasPos: boolean
  /** Fields of the corpus metadata schema, empty when unknown. */
  fields: readonly StarterMetaField[]
}

export interface StarterPrompt {
  id: 'topWords' | 'typicalByField' | 'trendOverField' | 'collocations' | 'queryLanguage'
  text: string
}

/** A category is worth comparing when it has at least two and not too many values. */
const MAX_CATEGORY_VALUES = 30
const TIME_FIELD = /(^|_)(year|date|decade|period|jahr|datum|jahrzehnt|zeit)(_|$)/i
const IDENTITY_FIELD = /(^|_)(id|hash|uuid|guid|path|url|ref_doc|paired_with)$/i

function isIdentity(name: string): boolean {
  return IDENTITY_FIELD.test(name)
}

/**
 * The metadata field with the fewest distinct text values (two or more), a
 * natural target for "which words are typical of each value".
 */
export function pickCategoryField(fields: readonly StarterMetaField[]): string | null {
  const candidates = fields
    .filter((field) => !isIdentity(field.name) && !TIME_FIELD.test(field.name))
    .filter((field) => field.hasString !== false)
    .filter((field) => typeof field.stringValueCount === 'number'
      && field.stringValueCount >= 2
      && field.stringValueCount <= MAX_CATEGORY_VALUES)
    .sort((a, b) => (a.stringValueCount ?? 0) - (b.stringValueCount ?? 0) || a.name.localeCompare(b.name))
  return candidates[0]?.name ?? null
}

/** A year or date field for a question about change over time. `year` wins over coarser fields. */
export function pickTimeField(fields: readonly StarterMetaField[]): string | null {
  const candidates = fields.filter((field) => !isIdentity(field.name) && TIME_FIELD.test(field.name))
  const rank = (name: string) => {
    const lower = name.toLowerCase()
    if (/(^|_)(year|jahr)(_|$)/.test(lower)) return 0
    if (/(^|_)(date|datum)(_|$)/.test(lower)) return 1
    return 2
  }
  return [...candidates].sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))[0]?.name ?? null
}

/** Up to four starter questions in the active interface language. */
export function buildStarterPrompts(context: StarterContext): StarterPrompt[] {
  const prompts: StarterPrompt[] = [{ id: 'topWords', text: t('copilot.starters.topWords') }]
  const collocations: StarterPrompt = {
    id: 'collocations',
    text: context.hasPos ? t('copilot.starters.collocationsNoun') : t('copilot.starters.collocationsWord'),
  }
  const category = pickCategoryField(context.fields)
  const time = pickTimeField(context.fields)
  prompts.push(category
    ? { id: 'typicalByField', text: t('copilot.starters.typicalByField', { field: category }) }
    : collocations)
  if (time) {
    prompts.push({ id: 'trendOverField', text: t('copilot.starters.trendOverField', { field: time }) })
  } else if (category) {
    prompts.push(collocations)
  }
  prompts.push({ id: 'queryLanguage', text: t('copilot.starters.queryLanguage') })
  return prompts
}
