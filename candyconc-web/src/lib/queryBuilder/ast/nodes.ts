import { t } from '@/i18n'
import { fallbackQuerySamples, type QuerySamples } from '@/lib/queryBuilder/samples'
import {
  META_OPERATORS,
  TOKEN_ATTRIBUTES,
  TOKEN_OPERATORS,
} from './types'
import type {
  CqlBuilderLiteral,
  CqlBuilderLiteralKind,
  CqlBuilderMetaCond,
  CqlBuilderMetaExpr,
  CqlBuilderMetaGroup,
  CqlBuilderMetaKind,
  CqlBuilderMetaOperator,
  CqlBuilderNode,
  CqlBuilderNodeType,
  CqlBuilderTokenCondition,
  CqlBuilderTokenOperator,
} from './types'

export function createBuilderId(): string {
  return crypto.randomUUID()
}

export function createLiteral(
  overrides: Partial<CqlBuilderLiteral> = {}
): CqlBuilderLiteral {
  return {
    id: overrides.id ?? createBuilderId(),
    kind: overrides.kind ?? 'string',
    value: overrides.value ?? '',
  }
}

export function createTokenCondition(
  overrides: Partial<CqlBuilderTokenCondition> = {}
): CqlBuilderTokenCondition {
  const op = overrides.op ?? '='
  return {
    id: overrides.id ?? createBuilderId(),
    attr: overrides.attr ?? 'word',
    op,
    scalar: overrides.scalar ? createLiteral(overrides.scalar) : createLiteral(),
    setValues: overrides.setValues?.map((literal) => createLiteral(literal)) ?? [createLiteral()],
    flags: tokenOperatorSupportsValueFlags(op) ? normalizeTokenFlags(overrides.flags) : '',
  }
}

export function createMetaCond(
  overrides: Partial<CqlBuilderMetaCond> = {}
): CqlBuilderMetaCond {
  return {
    id: overrides.id ?? createBuilderId(),
    kind: 'cond',
    field: overrides.field ?? 'source',
    op: overrides.op ?? '=',
    value: overrides.value ? createLiteral(overrides.value) : createLiteral(),
  }
}

export function createMetaGroup(
  kind: 'and' | 'or' = 'and',
  overrides: Partial<CqlBuilderMetaGroup> = {}
): CqlBuilderMetaGroup {
  return {
    id: overrides.id ?? createBuilderId(),
    kind,
    parts: overrides.parts?.map((part) => cloneMetaExpr(part)) ?? [createMetaCond(), createMetaCond()],
  }
}

export function createMetaExpr(kind: CqlBuilderMetaKind = 'cond'): CqlBuilderMetaExpr {
  if (kind === 'cond') return createMetaCond()
  return createMetaGroup(kind)
}

export function createBuilderNode(type: CqlBuilderNodeType = 'tok'): CqlBuilderNode {
  switch (type) {
    case 'tok':
      return {
        id: createBuilderId(),
        type: 'tok',
        conditions: [createTokenCondition()],
      }
    case 'seq':
      return {
        id: createBuilderId(),
        type: 'seq',
        parts: [createBuilderNode('tok'), createBuilderNode('tok')],
      }
    case 'alt':
      return {
        id: createBuilderId(),
        type: 'alt',
        options: [createBuilderNode('tok'), createBuilderNode('tok')],
      }
    case 'quant':
      return {
        id: createBuilderId(),
        type: 'quant',
        node: createBuilderNode('tok'),
        min: 0,
        max: 1,
      }
    case 'within':
      return {
        id: createBuilderId(),
        type: 'within',
        scope: 's',
        node: createBuilderNode('tok'),
      }
    case 'where':
      return {
        id: createBuilderId(),
        type: 'where',
        expr: createMetaGroup('and'),
        node: createBuilderNode('tok'),
      }
  }
}

export function createBuilderRoot(): CqlBuilderNode {
  return createBuilderNode('tok')
}

export function cloneLiteral(literal: CqlBuilderLiteral): CqlBuilderLiteral {
  return createLiteral(literal)
}

export function cloneTokenCondition(condition: CqlBuilderTokenCondition): CqlBuilderTokenCondition {
  return createTokenCondition({
    ...condition,
    scalar: cloneLiteral(condition.scalar),
    setValues: condition.setValues.map(cloneLiteral),
  })
}

export function cloneMetaExpr(expr: CqlBuilderMetaExpr): CqlBuilderMetaExpr {
  if (expr.kind === 'cond') {
    return createMetaCond({
      ...expr,
      value: cloneLiteral(expr.value),
    })
  }
  return createMetaGroup(expr.kind, {
    ...expr,
    parts: expr.parts.map(cloneMetaExpr),
  })
}

export function cloneNode(node: CqlBuilderNode): CqlBuilderNode {
  switch (node.type) {
    case 'tok':
      return {
        id: node.id,
        type: 'tok',
        conditions: node.conditions.map(cloneTokenCondition),
      }
    case 'seq':
      return {
        id: node.id,
        type: 'seq',
        parts: node.parts.map(cloneNode),
      }
    case 'alt':
      return {
        id: node.id,
        type: 'alt',
        options: node.options.map(cloneNode),
      }
    case 'quant':
      return {
        id: node.id,
        type: 'quant',
        node: cloneNode(node.node),
        min: node.min,
        max: node.max,
      }
    case 'within':
      return {
        id: node.id,
        type: 'within',
        scope: node.scope,
        node: cloneNode(node.node),
      }
    case 'where':
      return {
        id: node.id,
        type: 'where',
        expr: cloneMetaExpr(node.expr),
        node: cloneNode(node.node),
      }
  }
}

export function cloneMetaExprFresh(expr: CqlBuilderMetaExpr): CqlBuilderMetaExpr {
  if (expr.kind === 'cond') {
    return createMetaCond({
      field: expr.field,
      op: expr.op,
      value: createLiteral({
        kind: expr.value.kind,
        value: expr.value.value,
      }),
    })
  }
  return createMetaGroup(expr.kind, {
    parts: expr.parts.map(cloneMetaExprFresh),
  })
}

export function cloneNodeFresh(node: CqlBuilderNode): CqlBuilderNode {
  switch (node.type) {
    case 'tok':
      return {
        id: createBuilderId(),
        type: 'tok',
        conditions: node.conditions.map((condition) =>
          createTokenCondition({
            attr: condition.attr,
            op: condition.op,
            scalar: createLiteral({
              kind: condition.scalar.kind,
              value: condition.scalar.value,
            }),
            setValues: condition.setValues.map((literal) =>
              createLiteral({
                kind: literal.kind,
                value: literal.value,
              })
            ),
            flags: condition.flags,
          })
        ),
      }
    case 'seq':
      return {
        id: createBuilderId(),
        type: 'seq',
        parts: node.parts.map(cloneNodeFresh),
      }
    case 'alt':
      return {
        id: createBuilderId(),
        type: 'alt',
        options: node.options.map(cloneNodeFresh),
      }
    case 'quant':
      return {
        id: createBuilderId(),
        type: 'quant',
        node: cloneNodeFresh(node.node),
        min: node.min,
        max: node.max,
      }
    case 'within':
      return {
        id: createBuilderId(),
        type: 'within',
        scope: node.scope,
        node: cloneNodeFresh(node.node),
      }
    case 'where':
      return {
        id: createBuilderId(),
        type: 'where',
        expr: cloneMetaExprFresh(node.expr),
        node: cloneNodeFresh(node.node),
      }
  }
}

export function getNodeTypeOptions(): Array<{ value: CqlBuilderNodeType; label: string }> {
  return [
    { value: 'tok', label: t('querybuilder.ast.typeTok') },
    { value: 'seq', label: t('querybuilder.ast.typeSeq') },
    { value: 'alt', label: t('querybuilder.ast.typeAlt') },
    { value: 'quant', label: t('querybuilder.ast.typeQuant') },
    { value: 'within', label: 'within(...)' },
    { value: 'where', label: 'where(...)' },
  ]
}

export function getTokenOperatorOptions(): Array<{ value: CqlBuilderTokenOperator; label: string }> {
  return TOKEN_OPERATORS.map((value) => ({ value, label: value }))
}

export function getMetaOperatorOptions(): CqlBuilderMetaOperator[] {
  return META_OPERATORS
}

export function getTokenAttributeSuggestions(): string[] {
  return TOKEN_ATTRIBUTES
}

export function nodeTypeLabel(type: CqlBuilderNodeType): string {
  return getNodeTypeOptions().find((option) => option.value === type)?.label ?? type
}

export function literalKindLabel(kind: CqlBuilderLiteralKind): string {
  return kind === 'number' ? t('querybuilder.ast.kindNumber') : t('querybuilder.ast.kindString')
}

// The examples are query syntax built from the query samples: words and tags
// of the active corpus when the studio provides them, else catalog words.
export function nodeExplanation(node: CqlBuilderNode, samples: QuerySamples = fallbackQuerySamples()): string {
  switch (node.type) {
    case 'tok':
      return t('querybuilder.ast.explainTok', { example: `\`[word="${samples.noun}" & pos="${samples.posNoun}"]\`` })
    case 'seq':
      return t('querybuilder.ast.explainSeq', { example: `\`[word="${samples.adjective}"] [pos="${samples.posNoun}"]\`` })
    case 'alt':
      return t('querybuilder.ast.explainAlt', { example: `\`([word="${samples.nounB}"] | [word="${samples.nounC}"])\`` })
    case 'quant':
      return t('querybuilder.ast.explainQuant', { operators: '`?`, `*`, `+`, `{m}`, `{m,n}`', last: '`{m,}`' })
    case 'within':
      return t('querybuilder.ast.explainWithin', {
        syntax: '`within(...)`',
        example: `\`within(<s>, [lemma="${samples.verb}"])\``,
      })
    case 'where':
      return t('querybuilder.ast.explainWhere', { syntax: '`where(meta_expr, query)`' }) // i18n-ignore: query syntax
  }
}

export function literalExplanation(literal: CqlBuilderLiteral): string {
  return literal.kind === 'number'
    ? t('querybuilder.ast.explainNumber', { example: '`2024`' })
    : t('querybuilder.ast.explainString', { example: '`"news"`' })
}

export function normalizeTokenFlags(flags: unknown): string {
  if (typeof flags !== 'string') return ''
  return /[cd]/i.test(flags) ? 'c' : ''
}

export function tokenOperatorSupportsValueFlags(op: CqlBuilderTokenOperator): boolean {
  return op === '=' || op === 'in' || op === '~'
}
