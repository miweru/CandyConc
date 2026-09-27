<script setup lang="ts">
import { computed } from 'vue'
import type { CorpusImportPreflightResponse } from '@/api/client'
import {
  formatEvidenceBytes,
  preflightMappingSuggestions,
  preflightOfflineValidationFacts,
  preflightPlaintextFacts,
  preflightTargetFacts,
  resolvedPreflightColumns,
} from '@/lib/corpusImportEvidence'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  result: CorpusImportPreflightResponse
}>()

const evidence = computed(() => props.result.evidence ?? {})
const methodContract = computed(() => evidence.value.method_contract)
const inputContract = computed(() => methodContract.value?.input ?? null)
const outputContract = computed(() => methodContract.value?.output ?? null)
const expectedColumns = computed(() => methodContract.value?.expected_columns ?? [])
const reports = computed(() => methodContract.value?.reports ?? [])
const targetFacts = computed(() => preflightTargetFacts(props.result))
const resolvedColumns = computed(() => resolvedPreflightColumns(props.result))
const mappingSuggestions = computed(() => preflightMappingSuggestions(props.result))
const plaintextFacts = computed(() => preflightPlaintextFacts(props.result))
const offlineValidationFacts = computed(() => preflightOfflineValidationFacts(props.result))
const sourceFacts = computed(() => {
  const items: Array<{ key: string; label: string; value: string }> = []
  const yesNo = (value: boolean) => (value ? t('corpus.shared.yes') : t('corpus.shared.no'))
  if (evidence.value.path) items.push({ key: 'path', label: t('corpus.preflightEvidence.path'), value: String(evidence.value.path) })
  if (typeof evidence.value.exists === 'boolean') {
    items.push({ key: 'exists', label: t('corpus.preflightEvidence.exists'), value: yesNo(evidence.value.exists) })
  }
  if (typeof evidence.value.is_file === 'boolean') {
    items.push({ key: 'is_file', label: t('corpus.preflightEvidence.file'), value: yesNo(evidence.value.is_file) })
  }
  if (typeof evidence.value.is_dir === 'boolean') {
    items.push({ key: 'is_dir', label: t('corpus.preflightEvidence.directory'), value: yesNo(evidence.value.is_dir) })
  }
  if (evidence.value.suffix) items.push({ key: 'suffix', label: t('corpus.preflightEvidence.suffix'), value: String(evidence.value.suffix) })
  if (evidence.value.size_bytes !== undefined && evidence.value.size_bytes !== null) {
    items.push({ key: 'size_bytes', label: t('corpus.preflightEvidence.size'), value: formatEvidenceBytes(Number(evidence.value.size_bytes)) })
  }
  return items
})
const columns = computed(() => evidence.value.columns ?? [])
const outputContractLabel = computed(() => {
  if (!outputContract.value) return ''
  const pairingLabel = outputContract.value.paired
    ? t('corpus.shared.paired')
    : outputContract.value.paired_data_dependent
      ? t('corpus.shared.dataDependentPairs')
      : t('corpus.preflightEvidence.notPaired')
  return `${pairingLabel}${outputContract.value.pairing_kind ? ` · ${outputContract.value.pairing_kind}` : ''}`
})

</script>

<template>
  <div class="preflight-evidence-panel">
    <div class="evidence-grid">
      <section class="evidence-section">
        <h5>{{ t('corpus.preflightEvidence.source') }}</h5>
        <div class="fact-grid">
          <span v-for="item in sourceFacts" :key="item.key" class="fact-chip">
            <strong>{{ item.label }}</strong>
            {{ item.value }}
          </span>
          <span
            v-for="item in offlineValidationFacts"
            :key="`offline-${item.key}`"
            class="fact-chip"
            :class="{ offline: item.key === 'hf_offline_preflight' }"
          >
            <strong>{{ item.label }}</strong>
            {{ item.value }}
          </span>
          <span v-if="!sourceFacts.length && !offlineValidationFacts.length" class="fact-chip muted">{{ t('corpus.preflightEvidence.noSourceEvidence') }}</span>
        </div>
        <div v-if="plaintextFacts.length" class="column-list" :aria-label="t('corpus.preflightEvidence.plaintextAria')">
          <strong>{{ t('corpus.preflightEvidence.plaintextTitle') }}</strong>
          <div class="fact-grid">
            <span v-for="item in plaintextFacts" :key="`plaintext-${item.key}`" class="fact-chip">
              <strong>{{ item.label }}</strong>
              {{ item.value }}
            </span>
          </div>
        </div>
        <div v-if="columns.length" class="column-list">
          <strong>{{ t('corpus.preflightEvidence.columns', { count: columns.length }) }}</strong>
          <div class="chip-row">
            <span v-for="column in columns" :key="column" class="fact-chip code">{{ column }}</span>
          </div>
        </div>
        <div v-if="mappingSuggestions.length" class="contract-list" :aria-label="t('corpus.preflightEvidence.mappingSuggestions')">
          <strong>{{ t('corpus.preflightEvidence.mappingSuggestions') }}</strong>
          <ul>
            <li v-for="suggestion in mappingSuggestions" :key="`mapping-${suggestion.missingColumn}`" class="warn">
              <code>{{ suggestion.missingColumn }}</code>
              <span>{{ t('corpus.preflightEvidence.notFoundInSource') }}</span>
              <span v-if="suggestion.candidateColumns.length">
                {{ t('corpus.preflightEvidence.candidates', { list: suggestion.candidateColumns.join(', ') }) }}
              </span>
              <small v-if="suggestion.safeMapping">{{ suggestion.safeMapping }}</small>
              <small v-if="suggestion.fallbackBehavior">{{ suggestion.fallbackBehavior }}</small>
            </li>
          </ul>
        </div>
      </section>

      <section v-if="targetFacts.length" class="evidence-section">
        <h5>{{ t('corpus.preflightEvidence.target') }}</h5>
        <div class="fact-grid">
          <span v-for="item in targetFacts" :key="item.key" class="fact-chip">
            <strong>{{ item.label }}</strong>
            {{ item.value }}
          </span>
        </div>
        <p class="muted-text">
          {{ t('corpus.preflightEvidence.targetNote') }}
        </p>
      </section>

      <section class="evidence-section">
        <h5>{{ t('corpus.preflightEvidence.inputRequirements') }}</h5>
        <div v-if="inputContract" class="fact-grid">
          <span class="fact-chip">
            <strong>{{ t('corpus.preflightEvidence.kind') }}</strong>
            {{ inputContract.kind }}
          </span>
          <span class="fact-chip">
            <strong>{{ t('corpus.preflightEvidence.directories') }}</strong>
            {{ inputContract.accepts_directories ? t('corpus.shared.accepted') : t('corpus.shared.notAccepted') }}
          </span>
          <span v-if="inputContract.extensions.length" class="fact-chip">
            <strong>{{ t('corpus.preflightEvidence.extensions') }}</strong>
            {{ inputContract.extensions.join(', ') }}
          </span>
          <span v-if="inputContract.path_hint" class="fact-chip">
            <strong>{{ t('corpus.preflightEvidence.pathHint') }}</strong>
            {{ inputContract.path_hint }}
          </span>
        </div>
        <p v-else class="muted-text">{{ t('corpus.preflightEvidence.noMethodDescription') }}</p>
      </section>
    </div>

    <section v-if="methodContract" class="evidence-section">
      <h5>{{ t('corpus.preflightEvidence.importMethod') }}</h5>
      <p v-if="methodContract.description" class="muted-text">{{ methodContract.description }}</p>
      <div class="contract-row">
        <span class="fact-chip"><strong>{{ t('corpus.preflightEvidence.method') }}</strong>{{ methodContract.method }}</span>
        <span v-if="methodContract.label" class="fact-chip"><strong>{{ t('corpus.preflightEvidence.label') }}</strong>{{ methodContract.label }}</span>
        <span v-if="outputContract" class="fact-chip">
          <strong>{{ t('corpus.preflightEvidence.output') }}</strong>
          {{ outputContractLabel }}
        </span>
      </div>
      <div v-if="expectedColumns.length" class="contract-list">
        <strong>{{ t('corpus.preflightEvidence.expectedColumns') }}</strong>
        <ul>
          <li v-for="column in expectedColumns" :key="column.key">
            <code>{{ column.key }}</code>
            <span>{{ column.label || column.key }}</span>
            <em v-if="column.required">{{ t('corpus.shared.required') }}</em>
            <small v-if="column.configured_by">{{ t('corpus.preflightEvidence.configuredVia', { field: column.configured_by }) }}</small>
          </li>
        </ul>
      </div>
      <div v-if="resolvedColumns.length" class="contract-list">
        <strong>{{ t('corpus.preflightEvidence.resolvedMapping') }}</strong>
        <ul>
          <li v-for="column in resolvedColumns" :key="`resolved-${column.key}`">
            <code>{{ column.key }}</code>
            <span>{{ column.label }}</span>
            <em v-if="column.required">{{ t('corpus.shared.required') }}</em>
            <small v-if="column.configuredBy">
              <template v-if="column.resolvedBy === 'mapping'">
                {{ t('corpus.preflightEvidence.userMapping', { option: column.configuredBy, name: column.resolvedName ?? '' }) }}
              </template>
              <template v-else-if="column.resolvedBy === 'default'">
                {{ t('corpus.preflightEvidence.defaultMapping', { option: column.configuredBy, name: column.resolvedName ?? '' }) }}
              </template>
              <template v-else>
                {{ t('corpus.preflightEvidence.unsetMapping', { option: column.configuredBy }) }}
              </template>
            </small>
            <small v-else>
              {{ t('corpus.preflightEvidence.standardField', { name: column.resolvedName ?? column.key }) }}
            </small>
          </li>
        </ul>
      </div>
      <div v-if="outputContract?.emitted_features?.length" class="contract-list">
        <strong>{{ t('corpus.preflightEvidence.plannedArtifacts') }}</strong>
        <p class="muted-text">{{ t('corpus.preflightEvidence.plannedArtifactsNote') }}</p>
        <div class="chip-row">
          <span v-for="feature in outputContract.emitted_features" :key="feature" class="fact-chip code">{{ feature }}</span>
        </div>
      </div>
      <div v-if="outputContract?.guarantees?.length || outputContract?.limitations?.length" class="contract-list">
        <strong>{{ t('corpus.preflightEvidence.guaranteesLimits') }}</strong>
        <ul>
          <li v-for="item in outputContract.guarantees" :key="`guarantee-${item}`" class="ok">{{ item }}</li>
          <li v-for="item in outputContract.limitations" :key="`limit-${item}`" class="warn">{{ item }}</li>
        </ul>
      </div>
      <div v-if="reports.length" class="contract-list">
        <strong>{{ t('corpus.shared.expectedReports') }}</strong>
        <div class="chip-row">
          <span v-for="report in reports" :key="report.key" class="fact-chip">{{ report.label || report.key }}</span>
        </div>
      </div>
    </section>

  </div>
</template>

<style scoped>
@reference "../../style.css";

.preflight-evidence-panel {
  @apply mt-3 space-y-3 rounded-lg border border-neutral-200 bg-neutral-50 p-3;
  @apply dark:border-neutral-700 dark:bg-neutral-950/40;
}

.evidence-grid {
  /* Columns follow the width of the corpus manager panel, not the window. */
  @apply grid gap-3;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
}

.evidence-section {
  @apply rounded-lg border border-neutral-100 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-900/70;
}

.evidence-section h5 {
  @apply mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.fact-grid,
.contract-row,
.chip-row {
  @apply flex flex-wrap gap-1.5;
}

.fact-chip {
  /* Paths break at any character instead of running out of the chip. */
  @apply min-w-0 max-w-full rounded-lg border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-[0.68rem] text-neutral-700;
  overflow-wrap: anywhere;
  @apply dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-300;
}

.fact-chip strong {
  @apply mr-1 font-semibold text-neutral-500 dark:text-neutral-400;
}

.fact-chip.code,
.contract-list code {
  @apply font-mono;
}

.fact-chip.muted,
.muted-text {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.fact-chip.offline {
  @apply border-warning-100 bg-warning-50 text-warning-800;
  @apply dark:border-warning-900/40 dark:bg-warning-900/20 dark:text-warning-200;
}

.column-list,
.contract-list {
  @apply mt-3 space-y-1.5;
}

.column-list > strong,
.contract-list > strong {
  @apply block text-[0.68rem] uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.contract-list ul {
  @apply space-y-1;
}

.contract-list li {
  @apply flex flex-wrap items-center gap-1.5 rounded-md border border-neutral-100 bg-neutral-50 px-2 py-1 text-[0.68rem] text-neutral-700;
  @apply dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-300;
}

.contract-list em {
  @apply rounded-full bg-warning-100 px-1.5 py-0.5 text-[0.6rem] not-italic text-warning-800;
  @apply dark:bg-warning-900/40 dark:text-warning-200;
}

.contract-list small {
  @apply text-neutral-500 dark:text-neutral-400;
}

.contract-list li.ok {
  @apply border-success-100 bg-success-50 text-success-800 dark:border-success-900/40 dark:bg-success-900/20 dark:text-success-200;
}

.contract-list li.warn {
  @apply border-warning-100 bg-warning-50 text-warning-800 dark:border-warning-900/40 dark:bg-warning-900/20 dark:text-warning-200;
}

</style>
