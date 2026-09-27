import type { Component } from 'vue'
import type { ActiveTab } from '@/stores/ui'
import {
  CollocationNetworkTab,
  CollocationsTab,
  ContrastTab,
  DispersionTab,
  FrequencyTab,
  KeynessTab,
  NgramsTab,
  ReaderTab,
  SemanticTab,
  TrendTab,
  WordSketchTab,
} from '@/components/analysis/lazy'

export type ComponentBackedAnalysisTab = Exclude<ActiveTab, 'kwic'>

export const analysisTabComponents = {
  reader: ReaderTab,
  frequency: FrequencyTab,
  collocations: CollocationsTab,
  collocation_network: CollocationNetworkTab,
  dispersion: DispersionTab,
  semantic: SemanticTab,
  ngrams: NgramsTab,
  contrast: ContrastTab,
  keyness: KeynessTab,
  wordsketch: WordSketchTab,
  trend: TrendTab,
} satisfies Record<ComponentBackedAnalysisTab, Component>

export const componentBackedAnalysisTabs = Object.keys(
  analysisTabComponents,
) as ComponentBackedAnalysisTab[]

export function analysisComponentForTab(tab: ActiveTab | null): Component | null {
  if (!tab || tab === 'kwic') return null
  return analysisTabComponents[tab]
}

export function analysisComponentPropsForTab(tab: ActiveTab | null): Record<string, unknown> {
  return tab === 'keyness' ? { mode: 'keyness' } : {}
}
