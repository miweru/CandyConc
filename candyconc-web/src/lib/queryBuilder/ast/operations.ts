import { createBuilderId, createBuilderNode, createMetaCond, createMetaGroup, cloneNodeFresh, cloneMetaExprFresh } from './nodes'
import {
  findMetaExprInTree,
  findMetaParentContextInTree,
  findNodeById,
  findNodeParentContext,
} from './traverse'
import type {
  CqlBuilderAltNode,
  CqlBuilderMetaExpr,
  CqlBuilderMetaGroup,
  CqlBuilderNode,
  CqlBuilderSeqNode,
} from './types'

export type CqlBuilderNodeWrapperType = 'seq' | 'alt' | 'quant' | 'within' | 'where'

export function wrapNode(node: CqlBuilderNode, wrapper: CqlBuilderNodeWrapperType): CqlBuilderNode {
  switch (wrapper) {
    case 'seq':
      return {
        id: createBuilderId(),
        type: 'seq',
        parts: [node, createBuilderNode('tok')],
      }
    case 'alt':
      return {
        id: createBuilderId(),
        type: 'alt',
        options: [node, createBuilderNode('tok')],
      }
    case 'quant':
      return {
        id: createBuilderId(),
        type: 'quant',
        node,
        min: 0,
        max: 1,
      }
    case 'within':
      return {
        id: createBuilderId(),
        type: 'within',
        scope: 's',
        node,
      }
    case 'where':
      return {
        id: createBuilderId(),
        type: 'where',
        expr: createMetaGroup('and'),
        node,
      }
  }
}

export function wrapMetaExpr(expr: CqlBuilderMetaExpr, kind: 'and' | 'or'): CqlBuilderMetaExpr {
  return {
    id: createBuilderId(),
    kind,
    parts: [expr, createMetaCond()],
  }
}

export function transformNodeInTree(
  root: CqlBuilderNode,
  targetId: string,
  transform: (node: CqlBuilderNode) => CqlBuilderNode
): CqlBuilderNode {
  if (root.id === targetId) {
    return transform(root)
  }

  switch (root.type) {
    case 'tok':
      return root
    case 'seq':
      root.parts = root.parts.map((part) => transformNodeInTree(part, targetId, transform))
      return root
    case 'alt':
      root.options = root.options.map((option) => transformNodeInTree(option, targetId, transform))
      return root
    case 'quant':
    case 'within':
      root.node = transformNodeInTree(root.node, targetId, transform)
      return root
    case 'where':
      root.node = transformNodeInTree(root.node, targetId, transform)
      return root
  }
}

function transformMetaExpr(
  expr: CqlBuilderMetaExpr,
  targetId: string,
  transform: (expr: CqlBuilderMetaExpr) => CqlBuilderMetaExpr
): CqlBuilderMetaExpr {
  if (expr.id === targetId) {
    return transform(expr)
  }
  if (expr.kind === 'cond') return expr
  expr.parts = expr.parts.map((part) => transformMetaExpr(part, targetId, transform))
  return expr
}

export function transformMetaExprInTree(
  root: CqlBuilderNode,
  targetId: string,
  transform: (expr: CqlBuilderMetaExpr) => CqlBuilderMetaExpr
): CqlBuilderNode {
  switch (root.type) {
    case 'tok':
      return root
    case 'seq':
      root.parts = root.parts.map((part) => transformMetaExprInTree(part, targetId, transform))
      return root
    case 'alt':
      root.options = root.options.map((option) => transformMetaExprInTree(option, targetId, transform))
      return root
    case 'quant':
    case 'within':
      root.node = transformMetaExprInTree(root.node, targetId, transform)
      return root
    case 'where':
      root.expr = transformMetaExpr(root.expr, targetId, transform)
      root.node = transformMetaExprInTree(root.node, targetId, transform)
      return root
  }
}

function spliceGroupedItems<T extends { id: string }>(
  items: T[],
  selectedIds: string[],
  replacement: T
): boolean {
  const indices = selectedIds
    .map((id) => items.findIndex((item) => item.id === id))
    .filter((index) => index >= 0)
    .sort((left, right) => left - right)

  if (!indices.length) return false
  const first = indices[0]!
  const last = indices[indices.length - 1]!
  const contiguous = indices.every((value, idx) => value === first + idx)
  if (!contiguous) return false
  const selected = items.slice(first, last + 1)
  if (selected.length !== selectedIds.length) return false
  items.splice(first, selected.length, replacement)
  return true
}

function moveContiguousItems<T extends { id: string }>(
  items: T[],
  selectedIds: string[],
  targetIndex: number
): T[] | null {
  const indices = selectedIds
    .map((id) => items.findIndex((item) => item.id === id))
    .filter((index) => index >= 0)
    .sort((left, right) => left - right)

  if (!indices.length) return null
  const first = indices[0]!
  const last = indices[indices.length - 1]!
  const contiguous = indices.every((value, idx) => value === first + idx)
  if (!contiguous) return null

  const selected = items.slice(first, last + 1)
  if (selected.length !== selectedIds.length) return null
  if (targetIndex < 0 || targetIndex > items.length) return null
  if (targetIndex >= first && targetIndex <= last + 1) return null

  items.splice(first, selected.length)
  const adjustedIndex = targetIndex > first ? targetIndex - selected.length : targetIndex
  items.splice(adjustedIndex, 0, ...selected)
  return selected
}

function nodeSiblingArray(
  parent: CqlBuilderSeqNode | CqlBuilderAltNode,
  collection: 'parts' | 'options'
): CqlBuilderNode[] {
  if (collection === 'parts') {
    return (parent as CqlBuilderSeqNode).parts
  }
  return (parent as CqlBuilderAltNode).options
}

export function groupSelectedNodeSiblings(
  root: CqlBuilderNode,
  selectedIds: string[],
  kind: 'seq' | 'alt'
): CqlBuilderNode | null {
  if (selectedIds.length < 2) return null
  const firstId = selectedIds[0]
  if (!firstId) return null
  const first = findNodeParentContext(root, firstId)
  if (!first.parent || !first.collection) return null
  const sameParent = selectedIds.every((id) => {
    const ctx = findNodeParentContext(root, id)
    return ctx.parent?.id === first.parent?.id && ctx.collection === first.collection
  })
  if (!sameParent) return null

  const items = nodeSiblingArray(first.parent, first.collection)
  const ordered = items.filter((item: CqlBuilderNode) => selectedIds.includes(item.id))
  if (ordered.length !== selectedIds.length) return null
  const replacement = kind === 'seq'
    ? { id: createBuilderId(), type: 'seq' as const, parts: ordered }
    : { id: createBuilderId(), type: 'alt' as const, options: ordered }
  const changed = spliceGroupedItems(items, selectedIds, replacement)
  return changed ? replacement : null
}

export function wrapSelectedNodeSiblings(
  root: CqlBuilderNode,
  selectedIds: string[],
  wrapper: 'quant' | 'within' | 'where'
): CqlBuilderNode | null {
  if (!selectedIds.length) return null
  const firstId = selectedIds[0]
  if (!firstId) return null
  const first = findNodeParentContext(root, firstId)
  if (!first.parent || !first.collection) return null
  const sameParent = selectedIds.every((id) => {
    const ctx = findNodeParentContext(root, id)
    return ctx.parent?.id === first.parent?.id && ctx.collection === first.collection
  })
  if (!sameParent) return null

  const items = nodeSiblingArray(first.parent, first.collection)
  const indices = selectedIds
    .map((id) => items.findIndex((item) => item.id === id))
    .filter((index) => index >= 0)
    .sort((left, right) => left - right)

  if (!indices.length) return null
  const start = indices[0]!
  const end = indices[indices.length - 1]!
  const contiguous = indices.every((value, idx) => value === start + idx)
  if (!contiguous) return null

  const selected = items.slice(start, end + 1)
  if (selected.length !== selectedIds.length) return null

  const fragment = selected.length === 1
    ? selected[0]!
    : first.collection === 'parts'
      ? {
          id: createBuilderId(),
          type: 'seq' as const,
          parts: selected,
        }
      : {
          id: createBuilderId(),
          type: 'alt' as const,
          options: selected,
        }

  const wrapped = wrapNode(fragment, wrapper)
  items.splice(start, selected.length, wrapped)
  return wrapped
}

export function ungroupNodeSibling(root: CqlBuilderNode, targetId: string): CqlBuilderNode[] | null {
  const ctx = findNodeParentContext(root, targetId)
  if (!ctx.parent || !ctx.collection) return null
  const items = nodeSiblingArray(ctx.parent, ctx.collection)
  const target = items[ctx.index]
  if (!target || (target.type !== 'seq' && target.type !== 'alt')) return null
  const sameKind = (ctx.collection === 'parts' && target.type === 'seq') || (ctx.collection === 'options' && target.type === 'alt')
  if (!sameKind) return null
  const children = target.type === 'seq' ? target.parts : target.options
  items.splice(ctx.index, 1, ...children)
  return children
}

export function moveSelectedNodeSiblings(
  root: CqlBuilderNode,
  selectedIds: string[],
  targetIndex: number
): CqlBuilderNode[] | null {
  if (!selectedIds.length) return null
  const firstId = selectedIds[0]
  if (!firstId) return null
  const first = findNodeParentContext(root, firstId)
  if (!first.parent || !first.collection) return null
  const sameParent = selectedIds.every((id) => {
    const ctx = findNodeParentContext(root, id)
    return ctx.parent?.id === first.parent?.id && ctx.collection === first.collection
  })
  if (!sameParent) return null
  return moveContiguousItems(nodeSiblingArray(first.parent, first.collection), selectedIds, targetIndex)
}

export function groupSelectedMetaSiblings(
  root: CqlBuilderNode,
  selectedIds: string[],
  kind: 'and' | 'or'
): CqlBuilderMetaExpr | null {
  if (selectedIds.length < 2) return null
  const firstId = selectedIds[0]
  if (!firstId) return null
  const first = findMetaParentContextInTree(root, firstId)
  if (!first.parent) return null
  const sameParent = selectedIds.every((id) => findMetaParentContextInTree(root, id).parent?.id === first.parent?.id)
  if (!sameParent) return null
  const ordered = first.parent.parts.filter((part) => selectedIds.includes(part.id))
  if (ordered.length !== selectedIds.length) return null
  const replacement: CqlBuilderMetaGroup = {
    id: createBuilderId(),
    kind,
    parts: ordered,
  }
  const changed = spliceGroupedItems(first.parent.parts, selectedIds, replacement)
  return changed ? replacement : null
}

export function ungroupMetaSibling(root: CqlBuilderNode, targetId: string): CqlBuilderMetaExpr[] | null {
  const ctx = findMetaParentContextInTree(root, targetId)
  if (!ctx.parent) return null
  const target = ctx.parent.parts[ctx.index]
  if (!target || target.kind === 'cond' || target.kind !== ctx.parent.kind) return null
  ctx.parent.parts.splice(ctx.index, 1, ...target.parts)
  return target.parts
}

export function moveSelectedMetaSiblings(
  root: CqlBuilderNode,
  selectedIds: string[],
  targetIndex: number
): CqlBuilderMetaExpr[] | null {
  if (!selectedIds.length) return null
  const firstId = selectedIds[0]
  if (!firstId) return null
  const first = findMetaParentContextInTree(root, firstId)
  if (!first.parent) return null
  const sameParent = selectedIds.every((id) => findMetaParentContextInTree(root, id).parent?.id === first.parent?.id)
  if (!sameParent) return null
  return moveContiguousItems(first.parent.parts, selectedIds, targetIndex)
}

function normalizeMetaExprNode(expr: CqlBuilderMetaExpr): CqlBuilderMetaExpr {
  if (expr.kind === 'cond') return expr

  const normalizedParts = expr.parts
    .map(normalizeMetaExprNode)
    .flatMap((part) => (part.kind === expr.kind ? part.parts : [part]))

  if (normalizedParts.length === 1) {
    return normalizedParts[0]!
  }

  expr.parts = normalizedParts
  return expr
}

function normalizeNodeTree(node: CqlBuilderNode): CqlBuilderNode {
  switch (node.type) {
    case 'tok':
      return node
    case 'seq': {
      const normalizedParts = node.parts
        .map(normalizeNodeTree)
        .flatMap((part) => (part.type === 'seq' ? part.parts : [part]))
      if (normalizedParts.length === 1) {
        return normalizedParts[0]!
      }
      node.parts = normalizedParts
      return node
    }
    case 'alt': {
      const normalizedOptions = node.options
        .map(normalizeNodeTree)
        .flatMap((option) => (option.type === 'alt' ? option.options : [option]))
      if (normalizedOptions.length === 1) {
        return normalizedOptions[0]!
      }
      node.options = normalizedOptions
      return node
    }
    case 'quant':
      node.node = normalizeNodeTree(node.node)
      if ((node.node.type === 'seq' && node.node.parts.length === 1) || (node.node.type === 'alt' && node.node.options.length === 1)) {
        node.node = normalizeNodeTree(node.node)
      }
      return node
    case 'within':
      node.node = normalizeNodeTree(node.node)
      return node
    case 'where':
      node.expr = normalizeMetaExprNode(node.expr)
      node.node = normalizeNodeTree(node.node)
      return node
  }
}

export function duplicateNodeSibling(root: CqlBuilderNode, targetId: string): CqlBuilderNode | null {
  const ctx = findNodeParentContext(root, targetId)
  if (!ctx.parent || !ctx.collection) return null
  const items = nodeSiblingArray(ctx.parent, ctx.collection)
  const target = items[ctx.index]
  if (!target) return null
  const duplicate = cloneNodeFresh(target)
  items.splice(ctx.index + 1, 0, duplicate)
  return duplicate
}

export function duplicateMetaSibling(root: CqlBuilderNode, targetId: string): CqlBuilderMetaExpr | null {
  const ctx = findMetaParentContextInTree(root, targetId)
  if (!ctx.parent) return null
  const target = ctx.parent.parts[ctx.index]
  if (!target) return null
  const duplicate = cloneMetaExprFresh(target)
  ctx.parent.parts.splice(ctx.index + 1, 0, duplicate)
  return duplicate
}

export function extractNodeSibling(root: CqlBuilderNode, targetId: string): CqlBuilderNode | null {
  const ctx = findNodeParentContext(root, targetId)
  if (!ctx.parent || !ctx.collection) return null
  const items = nodeSiblingArray(ctx.parent, ctx.collection)
  const [extracted] = items.splice(ctx.index, 1)
  if (!items.length) {
    items.push(createBuilderNode('tok'))
  }
  return extracted ?? null
}

export function insertNodeSibling(
  root: CqlBuilderNode,
  targetId: string,
  node: CqlBuilderNode,
  position: 'before' | 'after' = 'after',
): CqlBuilderNode | null {
  const ctx = findNodeParentContext(root, targetId)
  if (!ctx.parent || !ctx.collection) return null
  const items = nodeSiblingArray(ctx.parent, ctx.collection)
  const inserted = cloneNodeFresh(node)
  const offset = position === 'before' ? 0 : 1
  items.splice(ctx.index + offset, 0, inserted)
  return inserted
}

export function extractMetaSibling(root: CqlBuilderNode, targetId: string): CqlBuilderMetaExpr | null {
  const ctx = findMetaParentContextInTree(root, targetId)
  if (!ctx.parent) return null
  const [extracted] = ctx.parent.parts.splice(ctx.index, 1)
  if (!ctx.parent.parts.length) {
    ctx.parent.parts.push(createMetaCond())
  }
  return extracted ?? null
}

export function insertMetaSibling(
  root: CqlBuilderNode,
  targetId: string,
  expr: CqlBuilderMetaExpr,
  position: 'before' | 'after' = 'after',
): CqlBuilderMetaExpr | null {
  const ctx = findMetaParentContextInTree(root, targetId)
  if (!ctx.parent) return null
  const inserted = cloneMetaExprFresh(expr)
  const offset = position === 'before' ? 0 : 1
  ctx.parent.parts.splice(ctx.index + offset, 0, inserted)
  return inserted
}

export function normalizeSelectedNode(root: CqlBuilderNode, targetId: string): CqlBuilderNode | null {
  const target = findNodeById(root, targetId)
  if (!target) return null
  const normalized = normalizeNodeTree(target)
  if (root.id === targetId) {
    return normalized
  }
  transformNodeInTree(root, targetId, () => normalized)
  return normalized
}

export function normalizeSelectedMetaExpr(root: CqlBuilderNode, targetId: string): CqlBuilderMetaExpr | null {
  const target = findMetaExprInTree(root, targetId)
  if (!target) return null
  const normalized = normalizeMetaExprNode(target)
  transformMetaExprInTree(root, targetId, () => normalized)
  return normalized
}
