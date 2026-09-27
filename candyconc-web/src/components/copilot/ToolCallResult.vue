<script setup lang="ts">
/**
 * ToolCallResult - Displays a tool call and its result
 */
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, type ToolCall } from '@/stores'
import { useMcpToolsStore } from '@/stores/mcpTools'
import { Loader2, CheckCircle, XCircle, Wrench, Flag } from 'lucide-vue-next'
import { GenericEvidenceRenderer, toolRenderers } from './tools'
import { copilotControlTool, copilotToolContractStatus, copilotToolMetadata } from '@/lib/copilotTools'
import {
  mcpToolRuntimeBlockReason,
  mcpToolRuntimeLabel,
  toolResultIntegrityReason,
} from '@/lib/copilotToolRuntime'
import { type SemanticScoreKind, deriveSemanticScoreKind } from '@/lib/semanticScore'
import { collocationRowsForDisplay } from '@/lib/collocationMeasure'

interface Props {
  toolCall: ToolCall
}

const props = defineProps<Props>()
const { t } = useI18n()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const mcpTools = useMcpToolsStore()
const toolMetadata = computed(() => copilotToolMetadata(props.toolCall.name))
const toolContractStatus = computed(() =>
  copilotToolContractStatus(props.toolCall.name, productCapabilities.contract)
)
const mcpToolStatus = computed(() =>
  mcpTools.toolStatusesByName.get(props.toolCall.name)
)
const mcpRuntimeLabel = computed(() =>
  controlTool.value ? null : mcpToolRuntimeLabel(mcpToolStatus.value)
)
const resultIntegrityReason = computed(() =>
  toolResultIntegrityReason(props.toolCall.result)
)
// A turn-control tool (from the backend contract) ends the investigation. It
// carries no corpus evidence and is never shown as blocked.
const controlTool = computed(() =>
  copilotControlTool(props.toolCall.name, productCapabilities.contract)
)

const contractBlockReason = computed(() => {
  const contract = productCapabilities.contract
  if (!contract) {
    return t('copilot.toolCall.blockLoading')
  }
  const status = toolContractStatus.value
  if (status.status === 'unknown') {
    return t('copilot.toolCall.blockUnknownTool')
  }
  const capabilityIds = status.status === 'product'
    ? status.capabilityIds
    : status.canonicalCapabilityIds
  if (!capabilityIds.length) return null
  const blockedIds = capabilityIds.filter((id) => !productCapabilities.isVisible(id))
  if (blockedIds.length) {
    return t('copilot.toolCall.blockCapabilityHidden')
  }
  const operationIds = status.operationIds ?? []
  if (!operationIds.length) {
    return t('copilot.toolCall.blockNoOperation')
  }
  const operationRecords = operationIds
    .map((operationId) => ({
      operationId,
      record: productCapabilities.operationUiRecordFor(operationId, corpusCapabilities.activeSummary),
    }))
  const missingOperationIds = operationRecords
    .filter((record) => !record.record)
    .map((record) => record.operationId)
  if (missingOperationIds.length) {
    return t('copilot.toolCall.blockOperationMissing')
  }
  const blockedOperations = operationRecords
    .filter((record) => record.record && !record.record.availability.enabled)
  if (blockedOperations.length) {
    return t('copilot.toolCall.blockOperationDisabled')
  }
  const renderableOperations = operationRecords.filter((record) => {
    const responseShape = record.record?.responseShape?.trim()
    return Boolean(responseShape)
      && responseShape !== 'void'
      && responseShape !== 'unknown'
  })
  if (renderableOperations.length !== operationRecords.length) {
    return t('copilot.toolCall.blockNoShape')
  }
  return null
})

const mcpGroundingBlockReason = computed(() =>
  mcpToolRuntimeBlockReason(
    props.toolCall.name,
    toolContractStatus.value,
    mcpToolStatus.value,
  )
)

const evidenceBlockReason = computed(() =>
  props.toolCall.status === 'success' && !controlTool.value
    ? resultIntegrityReason.value ?? contractBlockReason.value ?? mcpGroundingBlockReason.value
    : null
)

const effectiveStatus = computed(() =>
  evidenceBlockReason.value ? 'error' : props.toolCall.status
)

const statusIcon = computed(() => {
  if (controlTool.value && effectiveStatus.value !== 'running') return Flag
  switch (effectiveStatus.value) {
    case 'running': return Loader2
    case 'success': return CheckCircle
    case 'error': return XCircle
    default: return Wrench
  }
})

const statusColor = computed(() => {
  if (controlTool.value) return 'text-neutral-500'
  switch (effectiveStatus.value) {
    case 'running': return 'text-copilot-thinking'
    case 'success': return 'text-success-500'
    case 'error': return 'text-error-500'
    default: return 'text-neutral-500'
  }
})

const displayName = computed(() => controlTool.value?.label ?? toolMetadata.value.label)

const resultContractLabel = computed(() => {
  if (controlTool.value) return t('copilot.toolCall.contractControl')
  if (toolMetadata.value.sideEffect && toolMetadata.value.interpretative) {
    return t('copilot.toolCall.contractSideEffectInterpretive')
  }
  if (toolMetadata.value.sideEffect) {
    return t('copilot.toolCall.contractSideEffect')
  }
  if (toolMetadata.value.interpretative) {
    return t('copilot.toolCall.contractInterpretive')
  }
  if (evidenceBlockReason.value) {
    return t('copilot.toolCall.contractBlocked')
  }
  if (props.toolCall.status === 'success' || props.toolCall.status === 'running') {
    return t('copilot.toolCall.contractComputed')
  }
  return t('copilot.toolCall.contractToolCall')
})

const resultContractTitle = computed(() => {
  if (controlTool.value) return controlTool.value.description
  if (toolMetadata.value.sideEffect && toolMetadata.value.interpretative) {
    return t('copilot.toolCall.titleSideEffectInterpretive')
  }
  if (toolMetadata.value.sideEffect) {
    return t('copilot.toolCall.titleSideEffect')
  }
  if (toolMetadata.value.interpretative) {
    return t('copilot.toolCall.titleInterpretive')
  }
  if (evidenceBlockReason.value) {
    return evidenceBlockReason.value
  }
  return toolMetadata.value.methodNote ?? t('copilot.toolCall.titleComputed')
})

const rendererComponent = computed(() => {
  const renderer = toolRenderers[props.toolCall.name]
  return renderer || null
})

function extractRows(result: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(result)) {
    return result as Array<Record<string, unknown>>
  }
  if (result && typeof result === 'object') {
    const maybeRows = (result as { rows?: unknown }).rows
    if (Array.isArray(maybeRows)) {
      return maybeRows as Array<Record<string, unknown>>
    }
  }
  return []
}

const collocationFallbackNote = computed(() => {
  if (props.toolCall.name !== 'collocate_stats') return null
  const result = props.toolCall.result
  if (!result || typeof result !== 'object') return null
  const record = result as Record<string, unknown>
  if (record.term_mode !== 'lemma_fallback') return null
  const requested = typeof record.requested_term === 'string'
    ? record.requested_term
    : t('copilot.toolCall.requestedFormFallback')
  const effective = typeof record.effective_term === 'string'
    ? record.effective_term
    : t('copilot.toolCall.lemmaQueryFallback')
  return t('copilot.toolCall.collocationFallback', { requested, effective })
})

function semanticRows(rows: Array<Record<string, unknown>>) {
  return rows.map((row, index) => {
    const text = String(row.kw ?? row.text ?? row.match ?? '')
    const score = Number(row.score ?? row.similarity ?? 0)
    const docId = String(row.doc_id ?? row.doc ?? `result-${index + 1}`)
    const chunkId = String(row.chunk_id ?? index + 1)
    const metadata = (row.meta as Record<string, string> | undefined) ?? (row.metadata as Record<string, string> | undefined)
    return {
      doc_id: docId,
      chunk_id: chunkId,
      text,
      score,
      metadata
    }
  })
}

function similarWordRows(result: Record<string, unknown>) {
  const neighbours = Array.isArray(result.neighbours) ? result.neighbours : []
  return semanticRows(neighbours.filter((row): row is Record<string, unknown> =>
    Boolean(row) && typeof row === 'object'
  ).map((row) => ({
    text: row.word ?? row.term ?? '',
    score: row.score,
    doc_id: result.term ? t('copilot.toolCall.similarTo', { term: String(result.term) }) : 'similar_words',
    chunk_id: row.word ?? row.term ?? '',
    metadata: {
      Frequenz: String(row.corpusFrequency ?? row.corpus_frequency ?? row.frequency ?? 'n/a'),
      Backend: String(result.backend ?? 'n/a'),
    },
  })))
}

function normalizeToolResult(toolName: string, result: unknown): unknown {
  if (!result || typeof result !== 'object') {
    return result
  }

  const rows = extractRows(result)

  switch (toolName) {
    case 'run_cqlf_query':
    case 'query_count': {
      const queryResult = result as { total?: unknown; truncated?: unknown; queryTime?: unknown; query_time_ms?: unknown }
      const kwicRows = rows.length > 0 ? rows : extractRows((result as { rows?: unknown }).rows)
      const total = typeof queryResult.total === 'number' ? queryResult.total : null
      const truncated = typeof queryResult.truncated === 'boolean' ? queryResult.truncated : total == null
      return {
        total,
        sampleCount: kwicRows.length,
        truncated,
        queryTime: typeof queryResult.queryTime === 'number'
          ? queryResult.queryTime
          : typeof queryResult.query_time_ms === 'number'
            ? queryResult.query_time_ms
            : undefined,
      }
    }
    case 'collocate_stats': {
      // Das WIRKSAME Mass steht in der ANTWORT, nicht im Aufruf. Ohne
      // sort_by rechnet das Werkzeug nach logDice und meldet genau das in
      // result.sort_by zurueck. Die Argumente sind dann leer, und die
      // Anzeige fiel auf die Rueckfallkette, die bei MI begann.
      const argumente = props.toolCall.arguments as
        { sort_by?: unknown; measure?: unknown } | undefined
      return collocationRowsForDisplay(rows, {
        wirksamesMass: (result as { sort_by?: unknown }).sort_by,
        angefordertesMass: argumente?.sort_by ?? argumente?.measure,
      })
    }
    case 'semantic_search':
      return semanticRows(rows)
    case 'similar_words':
      return similarWordRows(result as Record<string, unknown>)
    case 'word_sketch':
      return (result as { tables?: unknown }).tables ?? result
    case 'document_search':
    case 'documentation_search':
      return rows
    default:
      return result
  }
}

const normalizedResult = computed(() =>
  normalizeToolResult(props.toolCall.name, props.toolCall.result)
)

// SEM-01: the score KIND the SemanticResultsRenderer needs. similar_words scores
// are true cosines; passage search defaults to a rerank score unless the result
// meta proves a cosine path. One shared decision with the analysis SemanticTab.
const semanticScoreKind = computed<SemanticScoreKind>(() => {
  if (props.toolCall.name === 'similar_words') return 'cosine'
  const result = props.toolCall.result
  const meta = result && typeof result === 'object'
    ? (result as { meta?: unknown }).meta
    : undefined
  return deriveSemanticScoreKind(meta as Parameters<typeof deriveSemanticScoreKind>[0])
})

const isSemanticRenderer = computed(() =>
  props.toolCall.name === 'semantic_search' || props.toolCall.name === 'similar_words'
)

const noLocalActionReason = computed(() => {
  const result = props.toolCall.result
  if (!result || typeof result !== 'object') return null
  const record = result as { status?: unknown; reason?: unknown }
  return record.status === 'no-action'
    ? String(record.reason ?? t('copilot.toolCall.noLocalAction'))
    : null
})

const hasCustomRenderer = computed(() => 
  rendererComponent.value !== null && 
  props.toolCall.status === 'success' && 
  normalizedResult.value &&
  !evidenceBlockReason.value &&
  !noLocalActionReason.value
)

const semanticInterpretationNote = computed(() =>
  props.toolCall.name === 'similar_words'
    ? t('copilot.toolCall.semanticNote')
    : null
)

onMounted(() => {
  void mcpTools.load()
})
</script>

<template>
  <div class="tool-call-result">
    <div class="tool-header">
      <component 
        :is="statusIcon" 
        :class="[
          'w-4 h-4',
          statusColor,
          { 'animate-spin': effectiveStatus === 'running' }
        ]"
      />
      <span class="tool-name">{{ displayName }}</span>
      <span class="tool-contract-pill" :title="resultContractTitle">
        {{ resultContractLabel }}
      </span>
      <span
        v-if="mcpRuntimeLabel"
        class="tool-contract-pill"
        :class="{ 'tool-contract-pill--blocked': mcpToolStatus && !mcpToolStatus.dispatchable }"
      >
        {{ mcpRuntimeLabel }}
      </span>
    </div>

    <!-- Arguments (collapsed by default) -->
    <details v-if="Object.keys(toolCall.arguments).length > 0" class="tool-details">
      <summary class="text-xs text-neutral-500 cursor-pointer">
        {{ t('copilot.toolCall.showParameters') }}
      </summary>
      <pre class="tool-args">{{ JSON.stringify(toolCall.arguments, null, 2) }}</pre>
    </details>

    <!-- Turn control: the end of the investigation, not evidence -->
    <div v-if="controlTool" class="tool-control" data-testid="tool-control">
      {{ controlTool.description }}
    </div>

    <!-- Result Preview -->
    <div v-else-if="evidenceBlockReason" class="tool-error">
      {{ evidenceBlockReason }}
    </div>

    <div v-else-if="toolCall.status === 'success' && toolCall.result" class="tool-result">
      <p v-if="collocationFallbackNote" class="collocation-fallback-note" role="status">
        {{ collocationFallbackNote }}
      </p>
      <template v-if="noLocalActionReason">
        <span class="text-xs text-neutral-500">{{ noLocalActionReason }}</span>
      </template>
      <!-- Custom Renderer -->
      <component
        v-else-if="hasCustomRenderer"
        :is="rendererComponent"
        :data="normalizedResult"
        :score-kind="isSemanticRenderer ? semanticScoreKind : undefined"
      />
      <p v-if="semanticInterpretationNote" class="semantic-note">
        {{ semanticInterpretationNote }}
      </p>
      <!-- Contract-aware fallback for product tools without bespoke renderer -->
      <GenericEvidenceRenderer
        v-else-if="typeof normalizedResult === 'object'"
        :tool-name="toolCall.name"
        :data="normalizedResult"
        :args="toolCall.arguments"
      />
      <template v-else>
        {{ toolCall.result }}
      </template>
    </div>

    <!-- Error -->
    <div v-if="toolCall.status === 'error'" class="tool-error">
      {{ toolCall.error || t('copilot.toolCall.unknownError') }}
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.tool-call-result {
  @apply p-2 rounded-lg;
  @apply bg-copilot-tool-bg;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.tool-header {
  @apply flex flex-wrap items-center gap-2;
}

.tool-name {
  @apply text-sm font-medium text-neutral-700 dark:text-neutral-300;
}

.tool-contract-pill {
  @apply rounded-full bg-neutral-100 px-2 py-0.5;
  @apply text-[0.65rem] font-semibold uppercase tracking-wide;
  @apply text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400;
}

.tool-contract-pill--blocked {
  @apply bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-200;
}

.tool-details {
  @apply mt-2;
}

.tool-args {
  @apply mt-1 p-2 text-xs rounded;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply overflow-x-auto;
}

.tool-result {
  @apply mt-2 text-sm text-neutral-600 dark:text-neutral-400;
}

.semantic-note {
  @apply mt-2 text-xs leading-relaxed text-neutral-600 dark:text-neutral-300;
}

.collocation-fallback-note {
  @apply mb-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs leading-relaxed text-amber-900;
  @apply dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100;
}

.tool-error {
  @apply mt-2 text-sm text-error-500;
}

.tool-control {
  @apply mt-2 text-sm text-neutral-600 dark:text-neutral-400;
}
</style>
