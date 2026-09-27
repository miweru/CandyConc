// Barrel für den framework-freien CQL-Builder-AST.
// Re-exportiert exakt die Symbolmenge, die vorher aus
// src/components/search/cqlBuilder.ts exportiert wurde (Etappe F3, AST-Heimholung).
// Bewusst KEIN `export *`: die ast/*-Module exportieren zusätzlich ein paar
// modulinterne Helfer (z. B. normalizeTokenFlags, TOKEN_OPERATORS), die im
// Ur-Modul privat waren und nur wegen der Aufteilung sichtbar werden müssen.
export type {
  CqlBuilderMode,
  CqlBuilderLiteralKind,
  CqlBuilderTokenOperator,
  CqlBuilderMetaOperator,
  CqlBuilderMetaKind,
  CqlBuilderNodeType,
  CqlWithinScope,
  CqlBuilderLiteral,
  CqlBuilderLiteralTarget,
  CqlBuilderLiteralOverride,
  CqlBuilderTokenCondition,
  CqlBuilderTokNode,
  CqlBuilderSeqNode,
  CqlBuilderAltNode,
  CqlBuilderQuantNode,
  CqlBuilderWithinNode,
  CqlBuilderWhereNode,
  CqlBuilderNode,
  CqlBuilderMetaCond,
  CqlBuilderMetaGroup,
  CqlBuilderMetaExpr,
  CqlBuilderHydrationResult,
  CqlBuilderSelectionKind,
  CqlBuilderOutlineItem,
  CqlBuilderNodeParentContext,
  CqlBuilderMetaParentContext,
} from './types'

export {
  createBuilderId,
  createLiteral,
  createTokenCondition,
  createMetaCond,
  createMetaGroup,
  createMetaExpr,
  createBuilderNode,
  createBuilderRoot,
  cloneLiteral,
  cloneTokenCondition,
  cloneMetaExpr,
  cloneNode,
  cloneMetaExprFresh,
  cloneNodeFresh,
  getNodeTypeOptions,
  getTokenOperatorOptions,
  getMetaOperatorOptions,
  getTokenAttributeSuggestions,
  nodeTypeLabel,
  literalKindLabel,
  nodeExplanation,
  literalExplanation,
  tokenOperatorSupportsValueFlags,
} from './nodes'

export {
  collectNodeLiteralTargets,
  collectMetaLiteralTargets,
  applyNodeLiteralOverrides,
  applyMetaLiteralOverrides,
  tokenConditionExplanation,
  metaExprExplanation,
  quantifierExplanation,
  collectMetaFields,
  findNodeById,
  findMetaExprById,
  collectBuilderOutline,
  findNodeParentContext,
  findMetaParentContext,
  findMetaParentContextInTree,
} from './traverse'

export type { CqlBuilderNodeWrapperType } from './operations'
export {
  wrapNode,
  wrapMetaExpr,
  transformNodeInTree,
  transformMetaExprInTree,
  groupSelectedNodeSiblings,
  wrapSelectedNodeSiblings,
  ungroupNodeSibling,
  moveSelectedNodeSiblings,
  groupSelectedMetaSiblings,
  ungroupMetaSibling,
  moveSelectedMetaSiblings,
  duplicateNodeSibling,
  duplicateMetaSibling,
  extractNodeSibling,
  insertNodeSibling,
  extractMetaSibling,
  insertMetaSibling,
  normalizeSelectedNode,
  normalizeSelectedMetaExpr,
} from './operations'

export { generateMetaExprPreview, generateBuilderQuery } from './serialize'

export { hydrateBuilderState } from './hydrate'
