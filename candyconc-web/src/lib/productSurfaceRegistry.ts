import type { ActiveTab } from '@/stores/ui'
import {
  surfaceForCapability,
  type AnalysisTabSurface,
  type ProductCapabilityOpenTarget,
  type ProductCapabilitySurface,
  type ProductCapabilitySurfaceKind,
} from '@/lib/productCapabilities'
import { t } from '@/i18n'

export type ProductSurfaceIconName =
  | 'bar-chart-2'
  | 'book-open'
  | 'brain'
  | 'database'
  | 'file-text'
  | 'hash'
  | 'list'
  | 'network'
  | 'settings'
  | 'share-2'
  | 'sparkles'
  | 'trending-up'
  | 'wand-2'
  | 'bookmark'
  | 'scale'
  | 'shield'

export type ProductSurfaceOpenTarget = ProductCapabilityOpenTarget

const analysisTabIconNames: Record<ActiveTab, ProductSurfaceIconName> = {
  kwic: 'list',
  reader: 'book-open',
  frequency: 'bar-chart-2',
  collocations: 'network',
  collocation_network: 'share-2',
  dispersion: 'trending-up',
  semantic: 'brain',
  ngrams: 'hash',
  contrast: 'scale',
  keyness: 'scale',
  wordsketch: 'book-open',
  trend: 'trending-up',
}

const surfaceKindDefaultIconNames: Record<ProductCapabilitySurfaceKind, ProductSurfaceIconName> = {
  analysis_tab: 'bar-chart-2',
  search_workbench: 'wand-2',
  corpus_manager: 'database',
  workspace_panel: 'bookmark',
  job_lifecycle: 'trending-up',
  kwic_layer: 'list',
  copilot_panel: 'sparkles',
  export_dialog: 'file-text',
  settings_panel: 'settings',
  session_panel: 'shield',
}

const capabilityIconNames: Record<string, ProductSurfaceIconName> = {
  'query.kwic': 'list',
  'query.cqlf': 'wand-2',
  'query.document_access': 'file-text',
  'analysis.frequency': 'bar-chart-2',
  'analysis.async_jobs': 'trending-up',
  'analysis.collocations': 'network',
  'analysis.collocation_network': 'share-2',
  'analysis.dispersion': 'trending-up',
  'analysis.ngrams': 'hash',
  'analysis.keyness': 'scale',
  'analysis.contrast': 'scale',
  'analysis.wordsketch': 'book-open',
  'analysis.semantic_similarity': 'brain',
  'admin.system_operations': 'settings',
  'settings.embedding_management': 'database',
  'settings.model_route': 'settings',
  'settings.preferences': 'settings',
  'corpus.catalogue': 'database',
  'corpus.import': 'database',
  'corpus.alignment_parallel': 'share-2',
  'research.subcorpora_docsets': 'bookmark',
  'research.annotations': 'list',
  'research.bookmarks': 'bookmark',
  'research.analysis_presets': 'bookmark',
  'research.copilot_grounding': 'sparkles',
  'research.replay_export': 'file-text',
  'platform.session': 'shield',
}

export function iconNameForAnalysisTab(tab: ActiveTab): ProductSurfaceIconName {
  return analysisTabIconNames[tab]
}

export function iconNameForSurface(surface: ProductCapabilitySurface): ProductSurfaceIconName {
  if (surface.kind === 'analysis_tab' && surface.tab) {
    return iconNameForAnalysisTab(surface.tab)
  }
  return capabilityIconNames[surface.capabilityId] ?? surfaceKindDefaultIconNames[surface.kind]
}

export function iconNameForCapability(id: string): ProductSurfaceIconName {
  const surface = surfaceForCapability(id)
  return surface ? iconNameForSurface(surface) : 'file-text'
}

export function isFallbackAnalysisTab(tab: string): tab is ActiveTab {
  return tab === 'kwic'
}

export function isFallbackAnalysisSurface(surface: AnalysisTabSurface): boolean {
  return isFallbackAnalysisTab(surface.tab)
}

export function openTargetForSurface(
  surface: ProductCapabilitySurface | undefined,
): ProductSurfaceOpenTarget | null {
  if (!surface) return null
  if (surface.openTarget) return surface.openTarget

  if (surface.kind === 'analysis_tab' && surface.tab) {
    return { kind: 'analysis_tab', tab: surface.tab }
  }

  return null
}

export function openLabelForSurface(surface: ProductCapabilitySurface | undefined): string | null {
  if (!surface) return null
  if (surface.openTarget?.kind === 'subcorpus_drawer') return t('capabilities.open.subcorpusFilter')
  if (surface.kind === 'analysis_tab') return t('capabilities.open.analysis')
  if (surface.kind === 'search_workbench') return t('capabilities.open.workbench')
  if (surface.kind === 'corpus_manager') return t('capabilities.open.corpusManager')
  if (surface.kind === 'workspace_panel') return t('capabilities.open.workspace')
  if (surface.kind === 'job_lifecycle') return t('capabilities.open.analysisJobs')
  if (surface.kind === 'kwic_layer') {
    return surface.capabilityId === 'research.bookmarks' ? t('capabilities.open.bookmarks') : t('capabilities.open.kwic')
  }
  if (surface.kind === 'copilot_panel') return t('capabilities.open.copilot')
  if (surface.kind === 'export_dialog') return t('capabilities.open.export')
  if (surface.kind === 'settings_panel') return t('capabilities.open.settings')
  if (surface.kind === 'session_panel') return t('capabilities.open.session')
  return t('capabilities.open.surface')
}
