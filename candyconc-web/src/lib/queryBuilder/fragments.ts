import {
  Braces,
  Filter,
  GitBranch,
  Layers3,
  Repeat,
  ScanSearch,
} from 'lucide-vue-next'
import {
  createLiteral,
  createMetaCond,
  createMetaGroup,
  createTokenCondition,
  generateBuilderQuery,
  type CqlBuilderNode,
} from '@/lib/queryBuilder/ast'
import type { BuilderHistoryEntry, BuilderTemplate } from '@/lib/queryBuilder/types'
import { t } from '@/i18n'
import { fallbackQuerySamples, type QuerySamples } from '@/lib/queryBuilder/samples'

function createTokNode(...conditions: ReturnType<typeof createTokenCondition>[]): CqlBuilderNode {
  return {
    id: crypto.randomUUID(),
    type: 'tok',
    conditions,
  }
}

export function cloneBuilderNode(node: CqlBuilderNode): CqlBuilderNode {
  return JSON.parse(JSON.stringify(node)) as CqlBuilderNode
}

export function createHistoryEntry(node: CqlBuilderNode, label: string): BuilderHistoryEntry {
  const snapshot = cloneBuilderNode(node)
  return {
    id: crypto.randomUUID(),
    label,
    node: snapshot,
    cql: generateBuilderQuery(snapshot),
    signature: JSON.stringify(snapshot),
    createdAt: Date.now(),
  }
}

function wordNode(value: string): CqlBuilderNode {
  return createTokNode(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value }) }))
}

// Titles and texts follow the interface language. Examples and the literal
// values of the created nodes are query syntax built from the query samples
// (words of the active corpus, else catalog words).
export function starterTemplates(samples: QuerySamples = fallbackQuerySamples()): BuilderTemplate[] {
  const { noun, nounB, nounC, adjective, metaValue } = samples
  return [
    {
      id: 'token-clause',
      title: t('querybuilder.templates.tokenTitle'),
      text: t('querybuilder.templates.tokenText'),
      example: `[word="${noun}"]`,
      icon: Braces,
      create: () => wordNode(noun),
    },
    {
      id: 'sequence',
      title: t('querybuilder.templates.sequenceTitle'),
      text: t('querybuilder.templates.sequenceText'),
      example: `[word="${adjective}"] [word="${noun}"]`,
      icon: Layers3,
      create: () => ({
        id: crypto.randomUUID(),
        type: 'seq',
        parts: [wordNode(adjective), wordNode(noun)],
      }),
    },
    {
      id: 'alternative',
      title: t('querybuilder.templates.alternativeTitle'),
      text: t('querybuilder.templates.alternativeText'),
      example: `([word="${nounB}"] | [word="${nounC}"])`,
      icon: GitBranch,
      create: () => ({
        id: crypto.randomUUID(),
        type: 'alt',
        options: [wordNode(nounB), wordNode(nounC)],
      }),
    },
    {
      id: 'within-sentence',
      title: 'within(<s>, ...)',
      text: t('querybuilder.templates.withinText'),
      example: `within(<s>, [word="${noun}"])`,
      icon: ScanSearch,
      create: () => ({
        id: crypto.randomUUID(),
        type: 'within',
        scope: 's',
        node: wordNode(noun),
      }),
    },
    {
      id: 'where-filter',
      title: 'where(..., ...)',
      text: t('querybuilder.templates.whereText'),
      example: `where(genre="${metaValue}", within(<s>, [word="${noun}"]))`,
      icon: Filter,
      create: () => ({
        id: crypto.randomUUID(),
        type: 'where',
        expr: createMetaGroup('and', {
          parts: [
            createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: metaValue }) }),
            createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2000' }) }),
          ],
        }),
        node: {
          id: crypto.randomUUID(),
          type: 'within',
          scope: 's',
          node: wordNode(noun),
        },
      }),
    },
    {
      id: 'semantic-macro',
      title: t('querybuilder.templates.simTitle'),
      text: t('querybuilder.templates.simText'),
      example: `[sim="${noun}" & k=20]`,
      icon: Repeat,
      requiresTokenAttributes: ['sim'],
      create: () =>
        createTokNode(
          createTokenCondition({ attr: 'sim', op: '=', scalar: createLiteral({ value: noun }) }),
          createTokenCondition({ attr: 'k', op: '=', scalar: createLiteral({ kind: 'number', value: '20' }) }),
        ),
    },
  ]
}
