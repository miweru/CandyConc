import { normalizeTokenFlags, tokenOperatorSupportsValueFlags } from './nodes'
import type {
  CqlBuilderLiteral,
  CqlBuilderMetaExpr,
  CqlBuilderNode,
  CqlBuilderTokenCondition,
} from './types'

function escapeCqlString(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

function serializeLiteral(literal: CqlBuilderLiteral): string {
  if (literal.kind === 'number') {
    const trimmed = literal.value.trim()
    return trimmed || '0'
  }
  return `"${escapeCqlString(literal.value)}"`
}

function renderTokenFlags(condition: CqlBuilderTokenCondition): string {
  return tokenOperatorSupportsValueFlags(condition.op) && normalizeTokenFlags(condition.flags) ? ' %c' : ''
}

function renderTokenCondition(condition: CqlBuilderTokenCondition): string | null {
  const attr = condition.attr.trim()
  if (!attr) return null

  if (condition.op === 'in') {
    const values = condition.setValues.filter((literal) => literal.value.trim().length > 0)
    if (!values.length) return null
    return `${attr} in {${values.map(serializeLiteral).join(', ')}}${renderTokenFlags(condition)}`
  }

  const scalarValue = condition.scalar.value.trim()
  if (!scalarValue) return null
  return `${attr}${condition.op}${serializeLiteral({ ...condition.scalar, value: scalarValue })}${renderTokenFlags(condition)}`
}

function needsParensForQuantifiedNode(node: CqlBuilderNode): boolean {
  return node.type === 'seq' || node.type === 'alt'
}

function renderMetaExpr(expr: CqlBuilderMetaExpr, parentKind: 'and' | 'or' | null = null): string {
  if (expr.kind === 'cond') {
    const field = expr.field.trim()
    if (!field || !expr.value.value.trim()) return ''
    return `${field}${expr.op}${serializeLiteral(expr.value)}`
  }

  const renderedParts = expr.parts
    .map((part) => renderMetaExpr(part))
    .filter(Boolean)
    .map((part, index) => {
      const child = expr.parts[index]
      const needsWrap = child?.kind !== 'cond' && child?.kind !== expr.kind
      return needsWrap ? `(${part})` : part
    })

  const joined = renderedParts.join(expr.kind === 'and' ? ' & ' : ' | ')
  if (!joined) return ''
  return parentKind && parentKind !== expr.kind ? `(${joined})` : joined
}

export function generateMetaExprPreview(expr: CqlBuilderMetaExpr): string {
  return renderMetaExpr(expr).trim()
}

function renderNode(node: CqlBuilderNode, context: 'root' | 'seq' | 'quant' = 'root'): string {
  switch (node.type) {
    case 'tok': {
      if (!node.conditions.length) return '[]'
      const conditions = node.conditions
        .map(renderTokenCondition)
        .filter((condition): condition is string => Boolean(condition))
      return conditions.length ? `[${conditions.join(' & ')}]` : ''
    }
    case 'seq': {
      const rendered = node.parts
        .map((part) => renderNode(part, 'seq'))
        .filter(Boolean)
        .join(' ')
      if (context === 'quant' && rendered) return `(${rendered})`
      return rendered
    }
    case 'alt': {
      const rendered = node.options.map((option) => renderNode(option, 'root')).filter(Boolean).join(' | ')
      return `(${rendered})`
    }
    case 'quant': {
      const inner = renderNode(node.node, 'quant')
      const renderedInner = needsParensForQuantifiedNode(node.node) ? inner : renderNode(node.node, 'root')
      return `${renderedInner}${renderQuantifier(node.min, node.max)}`
    }
    case 'within':
      return `within(<${node.scope}>, ${renderNode(node.node, 'root')})`
    case 'where': {
      const expr = renderMetaExpr(node.expr)
      return `where(${expr}, ${renderNode(node.node, 'root')})`
    }
  }
}

function renderQuantifier(min: number, max: number | null): string {
  if (min === 0 && max === 1) return '?'
  if (min === 0 && max === null) return '*'
  if (min === 1 && max === null) return '+'
  if (max === null) return `{${min},}`
  if (min === max) return `{${min}}`
  return `{${min},${max}}`
}

export function generateBuilderQuery(node: CqlBuilderNode): string {
  return renderNode(node, 'root').trim()
}
