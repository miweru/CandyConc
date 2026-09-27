export type CqlBuilderMode = 'simple' | 'advanced'
export type CqlBuilderLiteralKind = 'string' | 'number'
export type CqlBuilderTokenOperator = '=' | '!=' | '~' | 'in'
export type CqlBuilderMetaOperator = '=' | '!=' | '>=' | '<=' | '>' | '<'
export type CqlBuilderMetaKind = 'cond' | 'and' | 'or'
export type CqlBuilderNodeType = 'tok' | 'seq' | 'alt' | 'quant' | 'within' | 'where'
export type CqlWithinScope = 's' | 'doc'

export interface CqlBuilderLiteral {
  id: string
  kind: CqlBuilderLiteralKind
  value: string
}

export interface CqlBuilderLiteralTarget {
  literalId: string
  kind: CqlBuilderLiteralKind
  scope: 'token' | 'meta'
  label: string
  detail: string
  currentValue: string
}

export interface CqlBuilderLiteralOverride {
  kind?: CqlBuilderLiteralKind
  value: string
}

export interface CqlBuilderTokenCondition {
  id: string
  attr: string
  op: CqlBuilderTokenOperator
  scalar: CqlBuilderLiteral
  setValues: CqlBuilderLiteral[]
  flags: string
}

interface CqlBuilderNodeBase {
  id: string
  type: CqlBuilderNodeType
}

export interface CqlBuilderTokNode extends CqlBuilderNodeBase {
  type: 'tok'
  conditions: CqlBuilderTokenCondition[]
}

export interface CqlBuilderSeqNode extends CqlBuilderNodeBase {
  type: 'seq'
  parts: CqlBuilderNode[]
}

export interface CqlBuilderAltNode extends CqlBuilderNodeBase {
  type: 'alt'
  options: CqlBuilderNode[]
}

export interface CqlBuilderQuantNode extends CqlBuilderNodeBase {
  type: 'quant'
  node: CqlBuilderNode
  min: number
  max: number | null
}

export interface CqlBuilderWithinNode extends CqlBuilderNodeBase {
  type: 'within'
  scope: CqlWithinScope
  node: CqlBuilderNode
}

export interface CqlBuilderWhereNode extends CqlBuilderNodeBase {
  type: 'where'
  expr: CqlBuilderMetaExpr
  node: CqlBuilderNode
}

export type CqlBuilderNode =
  | CqlBuilderTokNode
  | CqlBuilderSeqNode
  | CqlBuilderAltNode
  | CqlBuilderQuantNode
  | CqlBuilderWithinNode
  | CqlBuilderWhereNode

interface CqlBuilderMetaBase {
  id: string
  kind: CqlBuilderMetaKind
}

export interface CqlBuilderMetaCond extends CqlBuilderMetaBase {
  kind: 'cond'
  field: string
  op: CqlBuilderMetaOperator
  value: CqlBuilderLiteral
}

export interface CqlBuilderMetaGroup extends CqlBuilderMetaBase {
  kind: 'and' | 'or'
  parts: CqlBuilderMetaExpr[]
}

export type CqlBuilderMetaExpr = CqlBuilderMetaCond | CqlBuilderMetaGroup

export interface CqlBuilderHydrationResult {
  node: CqlBuilderNode | null
  unsupportedReason?: string
}

export type CqlBuilderSelectionKind = 'node' | 'meta'

export interface CqlBuilderOutlineItem {
  id: string
  kind: CqlBuilderSelectionKind
  depth: number
  label: string
  detail: string
  preview: string
}

export interface CqlBuilderNodeParentContext {
  parent: CqlBuilderSeqNode | CqlBuilderAltNode | null
  collection: 'parts' | 'options' | null
  index: number
}

export interface CqlBuilderMetaParentContext {
  parent: CqlBuilderMetaGroup | null
  index: number
}

export const TOKEN_OPERATORS: CqlBuilderTokenOperator[] = ['=', '!=', '~', 'in']
export const META_OPERATORS: CqlBuilderMetaOperator[] = ['=', '!=', '>=', '<=', '>', '<']
export const TOKEN_ATTRIBUTES = ['word', 'lemma', 'pos', 'ent', 'ner', 'sim', 'k']
export const NODE_TYPES: CqlBuilderNodeType[] = ['tok', 'seq', 'alt', 'quant', 'within', 'where']
