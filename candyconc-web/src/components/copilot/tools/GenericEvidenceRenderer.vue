<script setup lang="ts">
/**
 * GenericEvidenceRenderer - method-aware fallback for Copilot tool evidence.
 *
 * It is intentionally small: every Product-Contract tool gets at least a
 * readable evidence card before bespoke renderers are worth adding.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { copilotToolMetadata } from '@/lib/copilotTools'
import { formatNumber } from '@/i18n/format'

interface Props {
  toolName: string
  data: unknown
  args?: Record<string, unknown>
}

const props = withDefaults(defineProps<Props>(), {
  args: () => ({}),
})
const { t } = useI18n()

const metadata = computed(() => copilotToolMetadata(props.toolName))

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—'
    return formatNumber(value, { maximumFractionDigits: Math.abs(value) >= 1000 ? 3 : 4 })
  }
  if (typeof value === 'boolean') return value ? t('copilot.renderers.yes') : t('copilot.renderers.no')
  if (Array.isArray(value)) {
    return value.length <= 4
      ? value.map(formatValue).join(', ')
      : t('copilot.renderers.values', { count: formatNumber(value.length) }, value.length)
  }
  if (typeof value === 'object') return JSON.stringify(value)
  const text = String(value)
  return text.length > 140 ? `${text.slice(0, 137)}…` : text
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
}

function valuesObjectRows(value: Record<string, unknown>): Array<Record<string, unknown>> {
  const rawValues = value.values
  if (!isRecord(rawValues)) return []
  const rows: Array<Record<string, unknown>> = []
  for (const [field, values] of Object.entries(rawValues)) {
    if (Array.isArray(values)) {
      for (const entry of values.slice(0, 20)) {
        rows.push({ field, value: entry })
      }
    } else {
      rows.push({ field, value: values })
    }
  }
  return rows
}

function rowsFrom(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) return value.filter(isRecord)
  if (!isRecord(value)) return []

  const metadataRows = valuesObjectRows(value)
  if (metadataRows.length) return metadataRows

  const candidates = [
    value.rows,
    value.hits,
    value.results,
    value.items,
    value.documents,
    value.docs,
    value.neighbours,
    value.neighbors,
    value.groups,
    value.variants,
    value.subcorpora,
    value.clusters,
    value.annotations,
    value.offsets,
  ]

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) continue
    if (candidate.every(isRecord)) return candidate as Array<Record<string, unknown>>
    if (candidate.every((item) => typeof item === 'number' || typeof item === 'string')) {
      return candidate.slice(0, 20).map((item, index) => ({ index: index + 1, value: item }))
    }
  }

  return []
}

const rows = computed(() => rowsFrom(props.data))
const rowPreview = computed(() => rows.value.slice(0, 6))

const methodBlock = computed(() => {
  if (!isRecord(props.data)) return null
  const method = props.data.method ?? props.data.provenance
  return isRecord(method) ? method : null
})

const metrics = computed(() => {
  const source = isRecord(props.data) ? props.data : {}
  const keys = [
    'total',
    'total_rows',
    'row_count',
    'sampleCount',
    'count',
    'reason',
    'feature',
    'detail',
    'code',
    'backend',
    'label',
    'source',
    'docset_id',
    'doc_count',
    'docCount',
    'token_count',
    'tokenCount',
    'hitDocCount',
    'refDocCount',
    'char_count',
    'n_tokens',
    'n_types',
    'ttr',
    'sttr',
    'guiraud',
    'mattr',
    'sttr_window',
    'sttr_n_windows',
    'analyst_tokens_only',
    'partitions',
    'dp',
    'dpnorm',
    'min_n',
    'max_n',
    'ref_doc',
    'base_doc_id',
    'doc_id',
    'pos',
    'queryTime',
    'query_time_ms',
    'truncated',
    'corpus',
    'docsetId',
    'job_id',
    'status',
  ]
  const seen = new Set<string>()
  const result: Array<{ label: string; value: string }> = []

  for (const key of keys) {
    if (!(key in source)) continue
    const raw = source[key]
    if (raw === undefined || raw === null) continue
    const label = humanizeKey(key)
    result.push({ label, value: formatValue(raw) })
    seen.add(key)
  }

  if (rows.value.length && !seen.has('sampleCount')) {
    result.unshift({ label: t('copilot.renderers.shownEvidenceLines'), value: formatNumber(rows.value.length) })
  }

  const query = props.args.query ?? props.args.term ?? source.query
  if (query !== undefined) result.unshift({ label: t('copilot.renderers.queryTerm'), value: formatValue(query) })
  const docset = props.args.docset_id ?? source.docset_id ?? source.docsetId
  if (docset !== undefined) result.push({ label: t('copilot.renderers.docset'), value: formatValue(docset) })

  return result.slice(0, 10)
})

function columnsForRows(inputRows: Array<Record<string, unknown>>): string[] {
  const preferredByKind: Record<string, string[]> = {
    query: ['position', 'left', 'match', 'right', 'docId', 'doc_id', 'total'],
    frequency: ['word', 'item', 'term', 'lemma', 'pos', 'frequency', 'f', 'relative'],
    collocation: ['word', 'term', 'frequency', 'f', 'score', 'measure', 'mi', 'lmi', 'npmi', 'z', 't'],
    network: ['source', 'target', 'word', 'score', 'weight', 'frequency'],
    dispersion: ['index', 'value', 'offset', 'partition', 'count'],
    ngram: ['ngram', 'n', 'freq', 'frequency', 'f', 'freq_target', 'freq_reference', 'per_million_target', 'per_million_reference', 'diff_per_million'],
    // Backend ngram_contrast uses snake_case; keep both to avoid hiding the
    // normalization basis.
    ngram_contrast: ['ngram', 'n', 'freq_target', 'freq_reference', 'per_million_target', 'per_million_reference', 'diff_per_million'],
    keyness: ['word', 'target_freq', 'reference_freq', 'll', 'll_signed', 'log_ratio', 'p_value', 'q_value'],
    contrast: ['word', 'term', 'targetFreq', 'referenceFreq', 'freq_target', 'freq_reference', 'diffPerMillion', 'diff_per_million', 'score', 'measure'],
    wordsketch: ['relation', 'word', 'collocate', 'frequency', 'score'],
    semantic: ['word', 'term', 'score', 'frequency', 'corpus_frequency', 'text', 'doc_id', 'chunk_id'],
    document: ['doc_id', 'docId', 'pos', 'left', 'kw', 'right', 'title', 'text', 'snippet', 'score'],
    parallel: ['ref_doc', 'doc_id', 'model', 'prompting_method', 'text_type', 'left', 'kw', 'right', 'matched', 'similarity'],
    docset: ['name', 'id', 'docset_id', 'field', 'value', 'doc_count', 'docCount', 'token_count', 'tokenCount', 'status', 'source'],
    annotation: ['category', 'label', 'count', 'agreement', 'status'],
    export: ['format', 'path', 'url', 'rows', 'status'],
    navigation: ['target', 'tab', 'index', 'indices', 'status'],
    policy: ['level', 'reason', 'status'],
    generic: [],
  }

  const allKeys = Array.from(new Set(inputRows.flatMap((row) => Object.keys(row))))
  const preferred = (props.toolName === 'ngram_contrast'
    ? preferredByKind.ngram_contrast
    : preferredByKind[metadata.value.evidenceKind]) ?? []
  const ordered = [
    ...preferred.filter((key) => allKeys.includes(key)),
    ...allKeys.filter((key) => !preferred.includes(key)),
  ]
  return ordered.slice(0, 5)
}

const columns = computed(() => columnsForRows(rowPreview.value))

const compactObjectEntries = computed(() => {
  if (!isRecord(props.data) || rows.value.length) return []
  return Object.entries(props.data)
    .filter(([, value]) => value !== undefined && value !== null && typeof value !== 'object')
    .slice(0, 12)
    .map(([key, value]) => ({ key: humanizeKey(key), value: formatValue(value) }))
})

const textEvidence = computed(() => {
  if (!isRecord(props.data)) return null
  const text = typeof props.data.text === 'string' ? props.data.text : ''
  if (text) {
    return {
      label: t('copilot.renderers.text'),
      text,
      truncated: props.data.truncated === true,
    }
  }
  const left = typeof props.data.left === 'string' ? props.data.left : ''
  const kw = typeof props.data.kw === 'string' ? props.data.kw : ''
  const right = typeof props.data.right === 'string' ? props.data.right : ''
  if (left || kw || right) {
    return {
      label: t('copilot.renderers.kwicContext'),
      text: `${left} ${kw} ${right}`.trim(),
      truncated: false,
    }
  }
  return null
})

const diagnostics = computed(() => {
  if (!isRecord(props.data) || !isRecord(props.data.diagnostics)) return []
  return Object.entries(props.data.diagnostics)
    .filter(([, value]) => value !== undefined && value !== null)
    .slice(0, 6)
    .map(([key, value]) => ({ key: humanizeKey(key), value: formatValue(value) }))
})
</script>

<template>
  <div class="generic-evidence-card">
    <div class="evidence-heading">
      <strong>{{ metadata.label }}</strong>
      <span>{{ metadata.evidenceKind }}</span>
    </div>
    <p class="evidence-summary">{{ metadata.summary }}</p>
    <p v-if="metadata.methodNote" class="method-note">{{ metadata.methodNote }}</p>

    <div v-if="metrics.length" class="metric-grid">
      <div v-for="metric in metrics" :key="`${metric.label}-${metric.value}`" class="metric-chip">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
      </div>
    </div>

    <figure v-if="textEvidence" class="text-evidence">
      <figcaption>
        {{ textEvidence.label }}
        <span v-if="textEvidence.truncated">{{ t('copilot.renderers.truncated') }}</span>
      </figcaption>
      <blockquote>{{ textEvidence.text }}</blockquote>
    </figure>

    <div v-if="rowPreview.length && columns.length" class="preview-table-wrap">
      <table class="preview-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in rowPreview" :key="rowIndex">
            <td v-for="column in columns" :key="`${rowIndex}-${column}`">
              {{ formatValue(row[column]) }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="rows.length > rowPreview.length" class="table-note">
        {{ t('copilot.renderers.evidenceLinesShown', { shown: formatNumber(rowPreview.length), total: formatNumber(rows.length) }) }}
      </p>
    </div>

    <dl v-else-if="compactObjectEntries.length" class="object-summary">
      <div v-for="entry in compactObjectEntries" :key="entry.key">
        <dt>{{ entry.key }}</dt>
        <dd>{{ entry.value }}</dd>
      </div>
    </dl>

    <dl v-if="diagnostics.length" class="object-summary diagnostics-summary">
      <div v-for="entry in diagnostics" :key="entry.key">
        <dt>{{ entry.key }}</dt>
        <dd>{{ entry.value }}</dd>
      </div>
    </dl>

    <p v-if="methodBlock" class="method-source">
      {{ t('copilot.renderers.methodProvenance', { fields: Object.keys(methodBlock).slice(0, 6).join(', ') }) }}
    </p>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.generic-evidence-card {
  @apply rounded-lg border border-neutral-200 bg-white p-3 text-xs dark:border-neutral-700 dark:bg-neutral-900/70;
}

.evidence-heading {
  @apply flex items-start justify-between gap-2 text-sm text-neutral-900 dark:text-neutral-100;
}

.evidence-heading span {
  @apply rounded-full bg-neutral-100 px-2 py-0.5 text-[0.65rem] uppercase tracking-wide text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400;
}

.evidence-summary {
  @apply mt-1 text-neutral-600 dark:text-neutral-300;
}

.method-note,
.method-source,
.table-note {
  @apply mt-2 rounded-md bg-warning-50 px-2 py-1 text-[0.68rem] leading-relaxed text-warning-800 dark:bg-warning-900/30 dark:text-warning-200;
}

.metric-grid {
  @apply mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2;
}

.metric-chip {
  @apply rounded-md bg-neutral-50 px-2 py-1 dark:bg-neutral-950/40;
}

.metric-chip span {
  @apply block text-[0.65rem] uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.metric-chip strong {
  @apply block truncate text-neutral-800 dark:text-neutral-100;
}

.preview-table-wrap {
  @apply mt-3 overflow-x-auto;
}

.text-evidence {
  @apply mt-3 rounded-lg border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-700 dark:bg-neutral-950/40;
}

.text-evidence figcaption {
  @apply mb-1 flex items-center justify-between text-[0.65rem] uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.text-evidence figcaption span {
  @apply rounded-full bg-warning-100 px-2 py-0.5 text-warning-800 dark:bg-warning-900/30 dark:text-warning-200;
}

.text-evidence blockquote {
  @apply max-h-40 overflow-auto whitespace-pre-wrap text-sm leading-relaxed text-neutral-800 dark:text-neutral-100;
}

.preview-table {
  @apply w-full border-collapse text-left text-[0.72rem];
}

.preview-table th {
  @apply border-b border-neutral-200 px-2 py-1 font-semibold text-neutral-500 dark:border-neutral-700 dark:text-neutral-400;
}

.preview-table td {
  @apply max-w-56 truncate border-b border-neutral-100 px-2 py-1 text-neutral-700 dark:border-neutral-800 dark:text-neutral-300;
}

.object-summary {
  @apply mt-3 space-y-1;
}

.object-summary div {
  @apply flex justify-between gap-3 rounded-md bg-neutral-50 px-2 py-1 dark:bg-neutral-950/40;
}

.object-summary dt {
  @apply text-neutral-500 dark:text-neutral-400;
}

.object-summary dd {
  @apply truncate text-right text-neutral-800 dark:text-neutral-100;
}

.diagnostics-summary {
  @apply border-t border-neutral-100 pt-2 dark:border-neutral-800;
}
</style>
