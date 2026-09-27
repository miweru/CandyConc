import {
  Braces,
  GitBranch,
  Repeat,
  ScanSearch,
} from 'lucide-vue-next'
import { t } from '@/i18n'
import { fallbackQuerySamples, type QuerySamples } from '@/lib/queryBuilder/samples'

export const HISTORY_LIMIT = 40

// Field names offered when the corpus metadata schema is not known.
export const commonMetaFields = [
  'author',
  'date',
  'genre',
  'source',
  'title',
  'year',
]

// Titles and texts follow the active interface language. The examples are
// query syntax built from the query samples of the active corpus.
export function builderGuide(samples: QuerySamples = fallbackQuerySamples()) {
  return [
    {
      title: t('querybuilder.guide.tokenTitle'),
      text: t('querybuilder.guide.tokenText'),
      example: `[word="${samples.noun}" & pos="${samples.posNoun}"]`,
      icon: Braces,
    },
    {
      title: t('querybuilder.guide.structureTitle'),
      text: t('querybuilder.guide.structureText'),
      example: '[word="A"] ([word="B"] | [word="C"])+',
      icon: Repeat,
    },
    {
      title: t('querybuilder.guide.wrapperTitle'),
      text: t('querybuilder.guide.wrapperText'),
      example: `within(<s>, [lemma="${samples.verb}"])`,
      icon: ScanSearch,
    },
    {
      title: t('querybuilder.guide.metaTitle'),
      text: t('querybuilder.guide.metaText'),
      example: `genre="${samples.metaValue}" & (year<1950 | year>=2000)`,
      icon: GitBranch,
    },
  ]
}
