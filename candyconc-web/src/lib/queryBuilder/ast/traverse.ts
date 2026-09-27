import { t } from '@/i18n'
import { formatNumber } from '@/i18n/format'
import { fallbackQuerySamples, type QuerySamples } from '@/lib/queryBuilder/samples'
import { generateBuilderQuery, generateMetaExprPreview } from './serialize'
import { cloneMetaExpr, cloneNode, nodeTypeLabel, tokenOperatorSupportsValueFlags } from './nodes'
import type {
  CqlBuilderLiteral,
  CqlBuilderLiteralOverride,
  CqlBuilderLiteralTarget,
  CqlBuilderMetaExpr,
  CqlBuilderMetaParentContext,
  CqlBuilderNode,
  CqlBuilderNodeParentContext,
  CqlBuilderOutlineItem,
  CqlBuilderTokenCondition,
} from './types'

function visitMetaLiterals(
  expr: CqlBuilderMetaExpr,
  visitor: (literal: CqlBuilderLiteral, expr: CqlBuilderMetaExpr, index: number) => void,
) {
  if (expr.kind === 'cond') {
    visitor(expr.value, expr, 0)
    return
  }
  expr.parts.forEach((part) => visitMetaLiterals(part, visitor))
}

function visitNodeLiterals(
  node: CqlBuilderNode,
  visitor: (literal: CqlBuilderLiteral, context: { scope: 'token' | 'meta'; label: string; detail: string }) => void,
) {
  switch (node.type) {
    case 'tok':
      node.conditions.forEach((condition) => {
        const attr = condition.attr.trim() || 'attr'
        if (condition.op === 'in') {
          condition.setValues.forEach((literal, index) => {
            visitor(literal, {
              scope: 'token',
              label: `${attr}[${index + 1}]`,
              detail: `${attr} in {...}` ,
            })
          })
          return
        }
        visitor(condition.scalar, {
          scope: 'token',
          label: attr,
          detail: `${attr} ${condition.op}`,
        })
      })
      return
    case 'seq':
      node.parts.forEach((part) => visitNodeLiterals(part, visitor))
      return
    case 'alt':
      node.options.forEach((option) => visitNodeLiterals(option, visitor))
      return
    case 'quant':
    case 'within':
      visitNodeLiterals(node.node, visitor)
      return
    case 'where':
      visitMetaLiterals(node.expr, (literal, expr) => {
        const field = expr.kind === 'cond' ? expr.field.trim() || 'field' : 'field'
        const detail = expr.kind === 'cond' ? `${field} ${expr.op}` : t('querybuilder.meta.metaConditionShort')
        visitor(literal, {
          scope: 'meta',
          label: field,
          detail,
        })
      })
      visitNodeLiterals(node.node, visitor)
  }
}

export function collectNodeLiteralTargets(node: CqlBuilderNode): CqlBuilderLiteralTarget[] {
  const targets: CqlBuilderLiteralTarget[] = []
  visitNodeLiterals(node, (literal, context) => {
    targets.push({
      literalId: literal.id,
      kind: literal.kind,
      scope: context.scope,
      label: context.label,
      detail: context.detail,
      currentValue: literal.value,
    })
  })
  return targets
}

export function collectMetaLiteralTargets(expr: CqlBuilderMetaExpr): CqlBuilderLiteralTarget[] {
  const targets: CqlBuilderLiteralTarget[] = []
  visitMetaLiterals(expr, (literal, current) => {
    const field = current.kind === 'cond' ? current.field.trim() || 'field' : 'field'
    const detail = current.kind === 'cond' ? `${field} ${current.op}` : t('querybuilder.meta.metaConditionShort')
    targets.push({
      literalId: literal.id,
      kind: literal.kind,
      scope: 'meta',
      label: field,
      detail,
      currentValue: literal.value,
    })
  })
  return targets
}

function applyLiteralOverride(literal: CqlBuilderLiteral, overrides: Record<string, CqlBuilderLiteralOverride>) {
  const override = overrides[literal.id]
  if (!override) return
  literal.kind = override.kind ?? literal.kind
  literal.value = override.value
}

export function applyNodeLiteralOverrides(
  node: CqlBuilderNode,
  overrides: Record<string, CqlBuilderLiteralOverride>,
): CqlBuilderNode {
  const snapshot = cloneNode(node)
  visitNodeLiterals(snapshot, (literal) => applyLiteralOverride(literal, overrides))
  return snapshot
}

export function applyMetaLiteralOverrides(
  expr: CqlBuilderMetaExpr,
  overrides: Record<string, CqlBuilderLiteralOverride>,
): CqlBuilderMetaExpr {
  const snapshot = cloneMetaExpr(expr)
  visitMetaLiterals(snapshot, (literal) => applyLiteralOverride(literal, overrides))
  return snapshot
}

// Syntax patterns and examples are query syntax. They go into the messages
// between backticks, which the editors render as code (CodeSpanText).
export function tokenConditionExplanation(
  condition: CqlBuilderTokenCondition,
  samples: QuerySamples = fallbackQuerySamples(),
): string {
  const attr = condition.attr.trim() || 'attr'
  const flagNote = condition.flags === 'c' && tokenOperatorSupportsValueFlags(condition.op)
    ? ` ${t('querybuilder.ast.caseNote', { flag: '`%c`' })}`
    : ''
  if (condition.op === 'in') {
    return t('querybuilder.ast.condSet', {
      syntax: `\`${attr} in {...}\``,
      example: `\`${attr} in {"${samples.posNoun}", "${samples.posAdj}"}\``,
    }) + flagNote
  }
  if (condition.op === '~') {
    return t('querybuilder.ast.condRegex', {
      syntax: `\`${attr}~pattern\``,
      example: `\`${attr}~"^un.*"\``,
    }) + flagNote
  }
  if (condition.op === '!=') {
    return t('querybuilder.ast.condNotEqual', {
      syntax: `\`${attr}!=value\``,
      example: `\`${attr}!="${samples.nounC}"\``,
      flag: '`%c`',
    })
  }
  return t('querybuilder.ast.condEqual', {
    syntax: `\`${attr}=value\``,
    example: `\`${attr}="${samples.noun}"\``,
  }) + flagNote
}

export function metaExprExplanation(expr: CqlBuilderMetaExpr, samples: QuerySamples = fallbackQuerySamples()): string {
  if (expr.kind === 'cond') {
    return t('querybuilder.ast.metaCond', {
      syntax: '`field op value`',
      exampleA: `\`genre="${samples.metaValue}"\``,
      exampleB: '`year>=2000`',
    })
  }
  return expr.kind === 'and'
    ? t('querybuilder.ast.metaAnd', { syntax: '`a & b & c`' })
    : t('querybuilder.ast.metaOr', { syntax: '`a | b | c`' })
}

export function quantifierExplanation(min: number, max: number | null): string {
  if (min === 0 && max === 1) return t('querybuilder.ast.quantOptional', { syntax: '?' })
  if (min === 0 && max === null) return t('querybuilder.ast.quantAny', { syntax: '*' })
  if (min === 1 && max === null) return t('querybuilder.ast.quantAtLeastOnce', { syntax: '+' })
  if (max === null) return t('querybuilder.ast.quantOpen', { syntax: `{${min},}` })
  if (min === max) return t('querybuilder.ast.quantExact', { count: String(min), syntax: `{${min}}` }, min)
  return t('querybuilder.ast.quantRange', { syntax: `{${min},${max}}` })
}

export function collectMetaFields(node: CqlBuilderNode): string[] {
  const fields = new Set<string>()

  const walkMeta = (expr: CqlBuilderMetaExpr) => {
    if (expr.kind === 'cond') {
      const field = expr.field.trim()
      if (field) fields.add(field)
      return
    }
    expr.parts.forEach(walkMeta)
  }

  const walkNode = (current: CqlBuilderNode) => {
    switch (current.type) {
      case 'tok':
        return
      case 'seq':
        current.parts.forEach(walkNode)
        return
      case 'alt':
        current.options.forEach(walkNode)
        return
      case 'quant':
      case 'within':
        walkNode(current.node)
        return
      case 'where':
        walkMeta(current.expr)
        walkNode(current.node)
    }
  }

  walkNode(node)
  return Array.from(fields).sort((left, right) => left.localeCompare(right, 'de'))
}

export function findNodeById(node: CqlBuilderNode, id: string): CqlBuilderNode | null {
  if (node.id === id) return node
  switch (node.type) {
    case 'tok':
      return null
    case 'seq':
      for (const part of node.parts) {
        const found = findNodeById(part, id)
        if (found) return found
      }
      return null
    case 'alt':
      for (const option of node.options) {
        const found = findNodeById(option, id)
        if (found) return found
      }
      return null
    case 'quant':
    case 'within':
      return findNodeById(node.node, id)
    case 'where':
      return findNodeById(node.node, id)
  }
}

export function findMetaExprById(expr: CqlBuilderMetaExpr, id: string): CqlBuilderMetaExpr | null {
  if (expr.id === id) return expr
  if (expr.kind === 'cond') return null
  for (const part of expr.parts) {
    const found = findMetaExprById(part, id)
    if (found) return found
  }
  return null
}

export function findMetaExprInTree(root: CqlBuilderNode, id: string): CqlBuilderMetaExpr | null {
  switch (root.type) {
    case 'tok':
      return null
    case 'seq':
      for (const part of root.parts) {
        const found = findMetaExprInTree(part, id)
        if (found) return found
      }
      return null
    case 'alt':
      for (const option of root.options) {
        const found = findMetaExprInTree(option, id)
        if (found) return found
      }
      return null
    case 'quant':
    case 'within':
      return findMetaExprInTree(root.node, id)
    case 'where': {
      const inExpr = findMetaExprById(root.expr, id)
      if (inExpr) return inExpr
      return findMetaExprInTree(root.node, id)
    }
  }
}

function nodeDetail(node: CqlBuilderNode): string {
  switch (node.type) {
    case 'tok':
      return t('querybuilder.ast.detailConditions', { count: formatNumber(node.conditions.length) }, node.conditions.length)
    case 'seq':
      return t('querybuilder.ast.detailParts', { count: formatNumber(node.parts.length) }, node.parts.length)
    case 'alt':
      return t('querybuilder.ast.detailOptions', { count: formatNumber(node.options.length) }, node.options.length)
    case 'quant':
      return quantifierExplanation(node.min, node.max)
    case 'within':
      return node.scope === 's' ? t('querybuilder.ast.detailSentence') : t('querybuilder.ast.detailDocument')
    case 'where': {
      const fields = collectMetaFields(node)
      return fields.length
        ? t('querybuilder.ast.detailMetaFields', { fields: fields.join(', ') })
        : t('querybuilder.ast.metaPlusQuery')
    }
  }
}

function metaDetail(expr: CqlBuilderMetaExpr): string {
  if (expr.kind === 'cond') {
    return expr.field.trim() ? `${expr.field.trim()} ${expr.op}` : 'field op value'
  }
  return expr.kind === 'and'
    ? t('querybuilder.items.partsBadge', { count: formatNumber(expr.parts.length) }, expr.parts.length)
    : t('querybuilder.items.optionsBadge', { count: formatNumber(expr.parts.length) }, expr.parts.length)
}

export function collectBuilderOutline(node: CqlBuilderNode): CqlBuilderOutlineItem[] {
  const items: CqlBuilderOutlineItem[] = []

  const walkMeta = (expr: CqlBuilderMetaExpr, depth: number) => {
    items.push({
      id: expr.id,
      kind: 'meta',
      depth,
      label: expr.kind === 'cond'
        ? t('querybuilder.meta.metaCondition')
        : expr.kind === 'and' ? t('querybuilder.meta.andGroup') : t('querybuilder.meta.orGroup'),
      detail: metaDetail(expr),
      preview: generateMetaExprPreview(expr) || t('querybuilder.common.empty'),
    })
    if (expr.kind === 'cond') return
    expr.parts.forEach((part) => walkMeta(part, depth + 1))
  }

  const walkNode = (current: CqlBuilderNode, depth: number) => {
    items.push({
      id: current.id,
      kind: 'node',
      depth,
      label: nodeTypeLabel(current.type),
      detail: nodeDetail(current),
      preview: generateBuilderQuery(current) || t('querybuilder.common.empty'),
    })

    switch (current.type) {
      case 'tok':
        return
      case 'seq':
        current.parts.forEach((part) => walkNode(part, depth + 1))
        return
      case 'alt':
        current.options.forEach((option) => walkNode(option, depth + 1))
        return
      case 'quant':
      case 'within':
        walkNode(current.node, depth + 1)
        return
      case 'where':
        walkMeta(current.expr, depth + 1)
        walkNode(current.node, depth + 1)
    }
  }

  walkNode(node, 0)
  return items
}

export function findNodeParentContext(
  root: CqlBuilderNode,
  targetId: string
): CqlBuilderNodeParentContext {
  if (root.type === 'seq') {
    const index = root.parts.findIndex((part) => part.id === targetId)
    if (index >= 0) return { parent: root, collection: 'parts', index }
    for (const part of root.parts) {
      const found = findNodeParentContext(part, targetId)
      if (found.parent) return found
    }
  }

  if (root.type === 'alt') {
    const index = root.options.findIndex((option) => option.id === targetId)
    if (index >= 0) return { parent: root, collection: 'options', index }
    for (const option of root.options) {
      const found = findNodeParentContext(option, targetId)
      if (found.parent) return found
    }
  }

  if (root.type === 'quant' || root.type === 'within' || root.type === 'where') {
    return findNodeParentContext(root.node, targetId)
  }

  return { parent: null, collection: null, index: -1 }
}

export function findMetaParentContext(
  expr: CqlBuilderMetaExpr,
  targetId: string
): CqlBuilderMetaParentContext {
  if (expr.kind === 'cond') {
    return { parent: null, index: -1 }
  }

  const index = expr.parts.findIndex((part) => part.id === targetId)
  if (index >= 0) return { parent: expr, index }

  for (const part of expr.parts) {
    const found = findMetaParentContext(part, targetId)
    if (found.parent) return found
  }
  return { parent: null, index: -1 }
}

export function findMetaParentContextInTree(
  root: CqlBuilderNode,
  targetId: string
): CqlBuilderMetaParentContext {
  if (root.type === 'where') {
    const own = findMetaParentContext(root.expr, targetId)
    if (own.parent) return own
    return findMetaParentContextInTree(root.node, targetId)
  }
  if (root.type === 'seq') {
    for (const part of root.parts) {
      const found = findMetaParentContextInTree(part, targetId)
      if (found.parent) return found
    }
  }
  if (root.type === 'alt') {
    for (const option of root.options) {
      const found = findMetaParentContextInTree(option, targetId)
      if (found.parent) return found
    }
  }
  if (root.type === 'quant' || root.type === 'within') {
    return findMetaParentContextInTree(root.node, targetId)
  }
  return { parent: null, index: -1 }
}

