/**
 * Lazy-loaded analysis components for code splitting
 * Import from here instead of index.ts for dynamic loading
 */
import { defineAsyncComponent, h } from 'vue'
import { t } from '@/i18n'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'

const loadingComponent = LoadingSpinner

const errorComponent = {
  render: () => h('div', { class: 'p-4 text-center text-error-500' }, t('analysis.lazy.loadFailed')),
}

export const ReaderTab = defineAsyncComponent({
  loader: () => import('./ReaderTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const FrequencyTab = defineAsyncComponent({
  loader: () => import('./FrequencyTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const CollocationsTab = defineAsyncComponent({
  loader: () => import('./CollocationsTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const CollocationNetworkTab = defineAsyncComponent({
  loader: () => import('./CollocationNetworkTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const DispersionTab = defineAsyncComponent({
  loader: () => import('./DispersionTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const SemanticTab = defineAsyncComponent({
  loader: () => import('./SemanticTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const NgramsTab = defineAsyncComponent({
  loader: () => import('./NgramsTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const ContrastTab = defineAsyncComponent({
  loader: () => import('./ContrastTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const KeynessTab = defineAsyncComponent({
  loader: () => import('./KeynessTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const WordSketchTab = defineAsyncComponent({
  loader: () => import('./WordSketchTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

export const TrendTab = defineAsyncComponent({
  loader: () => import('./TrendTab.vue'),
  loadingComponent,
  errorComponent,
  delay: 100,
  timeout: 10000
})

// Charts are also heavy (D3)
export const BarChart = defineAsyncComponent({
  loader: () => import('./charts/BarChart.vue'),
  loadingComponent,
  delay: 50
})

export const ForceGraph = defineAsyncComponent({
  loader: () => import('./charts/ForceGraph.vue'),
  loadingComponent,
  delay: 50
})

export const Heatmap = defineAsyncComponent({
  loader: () => import('./charts/Heatmap.vue'),
  loadingComponent,
  delay: 50
})

export const LineChart = defineAsyncComponent({
  loader: () => import('./charts/LineChart.vue'),
  loadingComponent,
  delay: 50
})
