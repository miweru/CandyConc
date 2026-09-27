/**
 * Tool Renderer Components
 *
 * Maps REGISTERED backend tool names to Vue components that render their
 * results. Every key MUST be a tool that actually exists in the backend
 * registry (candyconc.tooling.registry.REGISTRY); the guard test
 * `toolRendererRegistry.test.ts` enforces this. `null` means: real tool,
 * no bespoke renderer (GenericEvidenceRenderer fallback).
 */

import type { Component } from 'vue'
import FrequencyRenderer from './FrequencyRenderer.vue'
import CollocationsRenderer from './CollocationsRenderer.vue'
import QueryResultsRenderer from './QueryResultsRenderer.vue'
import SemanticResultsRenderer from './SemanticResultsRenderer.vue'
import WordSketchRenderer from './WordSketchRenderer.vue'
import KeynessRenderer from './KeynessRenderer.vue'
import DocumentSearchRenderer from './DocumentSearchRenderer.vue'
import ClusterRenderer from './ClusterRenderer.vue'
import GenericEvidenceRenderer from './GenericEvidenceRenderer.vue'

export const toolRenderers: Record<string, Component | null> = {
  // Query
  'run_cqlf_query': QueryResultsRenderer,

  // Analysis
  'frequency_list': FrequencyRenderer,
  'collocate_stats': CollocationsRenderer,
  'dispersion_offsets': null,
  'keyness': KeynessRenderer,
  'word_sketch': WordSketchRenderer,
  'semantic_search': SemanticResultsRenderer,
  'similar_words': SemanticResultsRenderer,
  'semantic_cluster': ClusterRenderer,
  'semantic_cluster_words': ClusterRenderer,
  'semantic_recluster': ClusterRenderer,
  'refine_cluster_label': ClusterRenderer,

  // Documents
  'document_search': DocumentSearchRenderer,
  'documentation_search': DocumentSearchRenderer,

  // Clusters
  'cluster_save': ClusterRenderer,
  'cluster_export_md': ClusterRenderer,
}

export {
  FrequencyRenderer,
  CollocationsRenderer,
  QueryResultsRenderer,
  SemanticResultsRenderer,
  WordSketchRenderer,
  KeynessRenderer,
  DocumentSearchRenderer,
  ClusterRenderer,
  GenericEvidenceRenderer
}
