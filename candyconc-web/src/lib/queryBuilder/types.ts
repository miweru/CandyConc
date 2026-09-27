import type { Component } from 'vue'
import type { CqlBuilderNode } from '@/lib/queryBuilder/ast'

export interface BuilderTemplate {
  id: string
  title: string
  text: string
  example: string
  icon: Component
  requiresTokenAttributes?: string[]
  create: () => CqlBuilderNode
}

export interface BuilderHistoryEntry {
  id: string
  label: string
  node: CqlBuilderNode
  cql: string
  signature: string
  createdAt: number
}
