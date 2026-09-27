import { t } from '@/i18n'
import { createBuilderId, createBuilderNode, createLiteral, createMetaCond, createMetaGroup, createTokenCondition, normalizeTokenFlags, tokenOperatorSupportsValueFlags } from './nodes'
import { META_OPERATORS, NODE_TYPES, TOKEN_OPERATORS } from './types'
import type {
  CqlBuilderHydrationResult,
  CqlBuilderLiteral,
  CqlBuilderMetaExpr,
  CqlBuilderMetaOperator,
  CqlBuilderNode,
  CqlBuilderNodeType,
  CqlBuilderTokenCondition,
  CqlBuilderTokenOperator,
} from './types'

interface BuilderJsonCond {
  attr?: unknown
  op?: unknown
  value?: unknown
  flags?: unknown
}

interface BuilderJsonNode {
  type?: unknown
  conds?: unknown
  parts?: unknown
  options?: unknown
  node?: unknown
  expr?: unknown
  scope?: unknown
  m?: unknown
  n?: unknown
}

interface BuilderJsonMetaExpr {
  kind?: unknown
  field?: unknown
  op?: unknown
  value?: unknown
  parts?: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function builderNodeType(node: unknown): CqlBuilderNodeType | null {
  if (!isRecord(node) || typeof node.type !== 'string') return null
  return NODE_TYPES.includes(node.type as CqlBuilderNodeType) ? (node.type as CqlBuilderNodeType) : null
}

function literalFromUnknown(value: unknown): CqlBuilderLiteral | null {
  if (typeof value === 'string') {
    return createLiteral({ kind: 'string', value })
  }
  if (typeof value === 'number') {
    return createLiteral({ kind: 'number', value: String(value) })
  }
  return null
}

function parseTokenCondition(rawCond: unknown): { condition: CqlBuilderTokenCondition | null; unsupportedReason?: string } {
  if (!isRecord(rawCond)) {
    return { condition: null, unsupportedReason: t('querybuilder.validator.invalidTokenCondition') }
  }

  const cond = rawCond as BuilderJsonCond
  const attr = typeof cond.attr === 'string' ? cond.attr : ''
  const op = typeof cond.op === 'string' ? cond.op : ''

  if (!attr || !TOKEN_OPERATORS.includes(op as CqlBuilderTokenOperator)) {
    return { condition: null, unsupportedReason: t('querybuilder.validator.unknownAttrOrOperator') }
  }
  const flags = tokenOperatorSupportsValueFlags(op as CqlBuilderTokenOperator)
    ? normalizeTokenFlags(cond.flags)
    : ''

  if (op === 'in') {
    if (!Array.isArray(cond.value)) {
      return { condition: null, unsupportedReason: t('querybuilder.validator.setNeedsValues') }
    }
    const values = cond.value.map(literalFromUnknown).filter((value): value is CqlBuilderLiteral => Boolean(value))
    if (!values.length) {
      return { condition: null, unsupportedReason: t('querybuilder.validator.emptySet') }
    }
    return {
      condition: createTokenCondition({
        attr,
        op: 'in',
        setValues: values,
        flags,
      }),
    }
  }

  const scalar = literalFromUnknown(cond.value)
  if (!scalar) {
    return { condition: null, unsupportedReason: t('querybuilder.validator.invalidLiteral') }
  }

  return {
    condition: createTokenCondition({
      attr,
      op: op as CqlBuilderTokenOperator,
      scalar,
      flags,
    }),
  }
}

function parseBuilderNode(rawNode: unknown): { node: CqlBuilderNode | null; unsupportedReason?: string } {
  if (!isRecord(rawNode)) {
    return { node: null, unsupportedReason: t('querybuilder.validator.missingNode') }
  }

  const node = rawNode as BuilderJsonNode
  const type = builderNodeType(node)
  if (!type) {
    return { node: null, unsupportedReason: t('querybuilder.validator.unknownNodeType') }
  }

  if (type === 'tok') {
    const conds = Array.isArray(node.conds) ? node.conds : []
    const conditions: CqlBuilderTokenCondition[] = []
    for (const rawCond of conds) {
      const parsed = parseTokenCondition(rawCond)
      if (!parsed.condition) return { node: null, unsupportedReason: parsed.unsupportedReason }
      conditions.push(parsed.condition)
    }
    return {
      node: {
        id: typeof (rawNode as Record<string, unknown>).id === 'string' ? String((rawNode as Record<string, unknown>).id) : createBuilderId(),
        type: 'tok',
        conditions,
      },
    }
  }

  if (type === 'seq') {
    const parts = Array.isArray(node.parts) ? node.parts : []
    const renderedParts: CqlBuilderNode[] = []
    for (const part of parts) {
      const parsed = parseBuilderNode(part)
      if (!parsed.node) return parsed
      renderedParts.push(parsed.node)
    }
    return {
      node: {
        id: typeof (rawNode as Record<string, unknown>).id === 'string' ? String((rawNode as Record<string, unknown>).id) : createBuilderId(),
        type: 'seq',
        parts: renderedParts.length ? renderedParts : [createBuilderNode('tok')],
      },
    }
  }

  if (type === 'alt') {
    const options = Array.isArray(node.options) ? node.options : []
    const renderedOptions: CqlBuilderNode[] = []
    for (const option of options) {
      const parsed = parseBuilderNode(option)
      if (!parsed.node) return parsed
      renderedOptions.push(parsed.node)
    }
    return {
      node: {
        id: typeof (rawNode as Record<string, unknown>).id === 'string' ? String((rawNode as Record<string, unknown>).id) : createBuilderId(),
        type: 'alt',
        options: renderedOptions.length ? renderedOptions : [createBuilderNode('tok'), createBuilderNode('tok')],
      },
    }
  }

  if (type === 'quant') {
    const parsedChild = parseBuilderNode(node.node)
    if (!parsedChild.node) return parsedChild
    const min = typeof node.m === 'number' ? node.m : Number(node.m)
    const max = node.n === null || node.n === undefined ? null : typeof node.n === 'number' ? node.n : Number(node.n)
    if (!Number.isFinite(min) || min < 0) {
      return { node: null, unsupportedReason: t('querybuilder.validator.invalidLowerBound') }
    }
    if (max !== null && (!Number.isFinite(max) || max < min)) {
      return { node: null, unsupportedReason: t('querybuilder.validator.invalidUpperBound') }
    }
    return {
      node: {
        id: typeof (rawNode as Record<string, unknown>).id === 'string' ? String((rawNode as Record<string, unknown>).id) : createBuilderId(),
        type: 'quant',
        node: parsedChild.node,
        min: Math.round(min),
        max: max === null ? null : Math.round(max),
      },
    }
  }

  if (type === 'within') {
    const parsedChild = parseBuilderNode(node.node)
    if (!parsedChild.node) return parsedChild
    const scope = node.scope === 'doc' ? 'doc' : node.scope === 's' ? 's' : null
    if (!scope) {
      return { node: null, unsupportedReason: t('querybuilder.validator.withinScope', { sentence: '<s>', document: '<doc>' }) }
    }
    return {
      node: {
        id: typeof (rawNode as Record<string, unknown>).id === 'string' ? String((rawNode as Record<string, unknown>).id) : createBuilderId(),
        type: 'within',
        scope,
        node: parsedChild.node,
      },
    }
  }

  const parsedExpr = parseMetaExpr(node.expr)
  if (!parsedExpr.expr) return { node: null, unsupportedReason: parsedExpr.unsupportedReason }
  const parsedChild = parseBuilderNode(node.node)
  if (!parsedChild.node) return parsedChild
  return {
    node: {
      id: typeof (rawNode as Record<string, unknown>).id === 'string' ? String((rawNode as Record<string, unknown>).id) : createBuilderId(),
      type: 'where',
      expr: parsedExpr.expr,
      node: parsedChild.node,
    },
  }
}

function parseMetaExpr(rawExpr: unknown): { expr: CqlBuilderMetaExpr | null; unsupportedReason?: string } {
  if (!isRecord(rawExpr)) {
    return { expr: null, unsupportedReason: t('querybuilder.validator.invalidMetaExpr') }
  }

  const expr = rawExpr as BuilderJsonMetaExpr
  const kind = typeof expr.kind === 'string' ? expr.kind : null
  if (kind === 'cond') {
    const field = typeof expr.field === 'string' ? expr.field : ''
    const op = typeof expr.op === 'string' ? expr.op : ''
    const value = literalFromUnknown(expr.value)
    if (!field || !META_OPERATORS.includes(op as CqlBuilderMetaOperator) || !value) {
      return { expr: null, unsupportedReason: t('querybuilder.validator.incompleteMetaCond') }
    }
    return {
      expr: createMetaCond({
        field,
        op: op as CqlBuilderMetaOperator,
        value,
      }),
    }
  }

  if (kind !== 'and' && kind !== 'or') {
    return { expr: null, unsupportedReason: t('querybuilder.validator.unknownMetaExpr') }
  }

  const parts = Array.isArray(expr.parts) ? expr.parts : []
  const parsedParts: CqlBuilderMetaExpr[] = []
  for (const part of parts) {
    const parsed = parseMetaExpr(part)
    if (!parsed.expr) return parsed
    parsedParts.push(parsed.expr)
  }
  return {
    expr: createMetaGroup(kind, { parts: parsedParts.length ? parsedParts : [createMetaCond(), createMetaCond()] }),
  }
}

export function hydrateBuilderState(builder: unknown): CqlBuilderHydrationResult {
  if (!builder) {
    return { node: null, unsupportedReason: t('querybuilder.validator.noStructure') }
  }

  const parsed = parseBuilderNode(builder)
  if (!parsed.node) {
    return { node: null, unsupportedReason: parsed.unsupportedReason ?? t('querybuilder.validator.invalidStructure') }
  }
  return { node: parsed.node }
}
