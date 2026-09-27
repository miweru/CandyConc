import type { ProductSurfaceOpenTarget } from '@/lib/productSurfaceRegistry'

interface ProductOperationOpenTargetRule {
  prefixes: readonly string[]
  target: ProductSurfaceOpenTarget
}

const productOperationOpenTargetRules: readonly ProductOperationOpenTargetRule[] = [
  { prefixes: ['kwic.workspace.parallel'], target: { kind: 'workspace', tab: 'subcorpora' } },
  { prefixes: ['research.subcorpora.docset_intersection'], target: { kind: 'analysis_tab', tab: 'keyness' } },
  {
    prefixes: [
      'kwic.annotations.scheme',
      'kwic.annotations.settings',
      'kwic.annotations.agreement',
    ],
    target: { kind: 'annotation_settings' },
  },
] as const

function normalizedSlot(value: string): string {
  return value.trim().replace(/\.+$/g, '')
}

export function operationSlotMatches(surfaceSlot: string, prefix: string): boolean {
  const slot = normalizedSlot(surfaceSlot)
  const needle = normalizedSlot(prefix)
  if (!slot || !needle) return false
  return slot === needle || slot.startsWith(`${needle}.`)
}

export function productOpenTargetForOperationSlot(
  surfaceSlot: string,
  fallback: ProductSurfaceOpenTarget | null,
): ProductSurfaceOpenTarget | null {
  const slot = normalizedSlot(surfaceSlot)
  if (!slot) return null
  if (!fallback) return null
  if (slot === 'corpus_manager') {
    return { kind: 'corpus_manager' }
  }

  for (const rule of productOperationOpenTargetRules) {
    if (rule.prefixes.some((prefix) => operationSlotMatches(surfaceSlot, prefix))) {
      return rule.target
    }
  }

  return fallback
}
