<script setup lang="ts">
/**
 * ExportDialog - Modal for configuring and triggering exports
 */
import { ref, computed, watch, type Component } from 'vue'
import { FileJson, FileText, FileSpreadsheet, FileCode2 } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import { useExportStore, type ExportFormat, type ExportOptions, type ExportScope } from '@/stores/export'
import { useQueryStore } from '@/stores/query'
import { useUiStore, type ProductOperationFocus } from '@/stores/ui'
import { useAnnotationsStore } from '@/stores/annotations'
import { useProductOperationFocus } from '@/composables/useProductOperationFocus'
import { formatNumber } from '@/i18n/format'
import { formatSampleProvenance } from '@/lib/kwicCitation'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  modelValue: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const exportStore = useExportStore()
const queryStore = useQueryStore()
const uiStore = useUiStore()
const annotationsStore = useAnnotationsStore()
const { consumeFocusFor, focusIs, modeIs } = useProductOperationFocus()

// Form state
const format = ref<ExportFormat>('csv')
const includeResults = ref(true)
const includeFrequency = ref(false)
const includeCollocations = ref(false)
const includeStatistics = ref(false)
const includeContext = ref(true)
const includeMetadata = ref(true)
const includeReproMeta = ref(false)
const includeAnnotations = ref(false)
const rowRange = ref<'all' | 'selected' | 'range' | 'annotated' | 'category'>('all')
const rangeStart = ref(1)
const rangeEnd = ref(100)
const rangeCategoryId = ref<string | null>(null)
const scope = ref<ExportScope>('loaded')
// Server-CSV im Excel-kompatiblen Dialekt (Semikolon, UTF-8-BOM). Nur für
// Server-CSV wirksam; das Standard-CSV bleibt byte-identisch.
const excelDe = ref(false)

const hasAnnotations = computed(() => annotationsStore.annotatedCount > 0)

// Annotations are local data that we splice into a CSV section. The loaded-rows
// CSV and the server-scope CSV both carry it; tsv/json/jsonl/xlsx server
// streams and EvidencePackage reports cannot, so we never let the box claim a
// section the download then silently drops (ANNOTATION-02 honesty fix). The
// excel-de dialect uses ';' — the comma-built annotation section would break
// that file, so it is not carryable there either.
const annotationsCarryable = computed(
  () => format.value === 'csv' && !usesEvidencePackageReport.value && !excelDe.value
)
const annotationNoteText = computed(() => {
  if (usesEvidencePackageReport.value) return t('export.dialog.notRenderedInReport')
  if (format.value === 'csv' && excelDe.value) return t('export.dialog.annotationNotInExcel')
  if (!hasAnnotations.value) return t('export.dialog.annotationNone')
  if (!annotationsCarryable.value) return t('export.dialog.annotationCsvOnly')
  const count = annotationsStore.annotatedCount
  if (scope.value === 'all-server') {
    return t('export.dialog.annotationServerScope', { count: formatNumber(count) }, count)
  }
  return t('export.dialog.annotatedLines', { count: formatNumber(count) }, count)
})

// Server-side concordance uses exact counts and bounded row streams; the
// EvidencePackage is always server-built.
function formatUsesEvidencePackage(value: ExportFormat): boolean {
  return ['pdf', 'docx', 'latex', 'evidence-json'].includes(value)
}

const isEvidencePackage = computed(() => format.value === 'evidence-json')
const usesEvidencePackageReport = computed(() =>
  formatUsesEvidencePackage(format.value)
)
const serverConcordanceFormats = new Set<ExportFormat>(['csv', 'tsv', 'json', 'jsonl', 'xlsx'])
const isServerOnlyConcordanceFormat = computed(() => serverConcordanceFormats.has(format.value) && format.value !== 'csv')
const serverScopeAvailable = computed(() => serverConcordanceFormats.has(format.value) || usesEvidencePackageReport.value)
const isServerScope = computed(() =>
  usesEvidencePackageReport.value || isServerOnlyConcordanceFormat.value || (scope.value === 'all-server' && serverScopeAvailable.value)
)

// Streaming the full match set replaces the client report sections, so force
// CSV + results-only semantics when the server scope is active.
watch(format, (value) => {
  if (formatUsesEvidencePackage(value)) {
    scope.value = 'all-server'
    includeFrequency.value = false
    includeCollocations.value = false
    includeStatistics.value = false
    includeAnnotations.value = false
    if (value === 'evidence-json') includeReproMeta.value = true
    return
  }
  if (serverConcordanceFormats.has(value) && value !== 'csv') {
    scope.value = 'all-server'
    // tsv/json/jsonl streams cannot carry the appended annotation CSV section,
    // so uncheck the box rather than promise a section we then drop.
    includeAnnotations.value = false
    return
  }
  if (scope.value === 'all-server' && value !== 'csv') {
    scope.value = 'loaded'
  }
})

// The Excel dialect only exists for the server-CSV stream; leaving that
// combination clears the switch so it cannot silently ride along.
watch([format, isServerScope], () => {
  if (format.value !== 'csv' || !isServerScope.value) excelDe.value = false
})

const isExporting = computed(() => exportStore.isExporting)
const progress = computed(() => exportStore.exportProgress)
const loadedResultCount = computed(() => queryStore.results.length)
const resultSectionLabel = computed(() =>
  usesEvidencePackageReport.value
    ? t('export.dialog.resultsFromPackage')
    : t('export.dialog.resultsLoaded')
)
const totalResultLabel = computed(() => {
  const sample = queryStore.sampleProvenance
  const total = sample?.population ?? queryStore.totalHits
  if (sample ? sample.populationPartial : queryStore.countIsLowerBound) {
    return t('export.dialog.totalPartial', { count: formatNumber(total) }, total)
  }
  if (sample || queryStore.totalKnown) {
    return t('export.dialog.totalKnown', { count: formatNumber(total) }, total)
  }
  return t('export.dialog.totalUnknown')
})

interface FormatOption {
  key: string
  value: ExportFormat
  scope?: ExportScope
  label: string
  icon: Component
  description: string
  provenance: string
  fillLevel: string
}

// Labels resolve inside the computed so a language switch relabels the cards.
const formatGroups = computed<Array<{ key: string; title: string; note: string; options: FormatOption[] }>>(() => {
  const serverOption = (key: string, value: ExportFormat, label: string, icon: Component): FormatOption => ({
    key,
    value,
    scope: 'all-server',
    label,
    icon,
    description: t('export.dialog.serverConcordance'),
    provenance: t('export.dialog.provenanceServer'),
    fillLevel: t('export.dialog.fillServer'),
  })
  const evidenceOption = (
    key: string,
    value: ExportFormat,
    label: string,
    icon: Component,
    description: string,
    fillLevel: string,
  ): FormatOption => ({
    key,
    value,
    scope: 'all-server',
    label,
    icon,
    description,
    provenance: t('export.dialog.provenanceEvidence'),
    fillLevel,
  })
  return [
    {
      key: 'server-concordance',
      title: t('export.dialog.groupServerTitle'),
      note: t('export.dialog.groupServerNote'),
      options: [
        serverOption('csv-server', 'csv', 'CSV', FileSpreadsheet),
        serverOption('tsv-server', 'tsv', 'TSV', FileSpreadsheet),
        serverOption('json-server', 'json', 'JSON', FileJson),
        serverOption('jsonl-server', 'jsonl', 'JSONL', FileJson),
        serverOption('xlsx-server', 'xlsx', 'XLSX', FileSpreadsheet),
      ],
    },
    {
      key: 'evidence-package',
      title: t('export.dialog.groupEvidenceTitle'),
      note: t('export.dialog.groupEvidenceNote'),
      options: [
        evidenceOption('pdf-evidence', 'pdf', 'PDF', FileText, t('export.dialog.evidenceReport'), t('export.dialog.fillRebuilt')),
        evidenceOption('docx-evidence', 'docx', 'Word', FileText, t('export.dialog.evidenceReport'), t('export.dialog.fillRebuilt')),
        evidenceOption('evidence-json', 'evidence-json', 'Evidence JSON', FileJson, t('export.dialog.provenancePackage'), t('export.dialog.fillEvidenceRows')),
        evidenceOption('latex-evidence', 'latex', 'LaTeX', FileCode2, t('export.dialog.evidenceSource'), t('export.dialog.fillRebuilt')),
      ],
    },
    {
      key: 'loaded-excerpt',
      title: t('export.dialog.groupLoadedTitle'),
      note: t('export.dialog.groupLoadedNote'),
      options: [
        {
          key: 'csv-loaded',
          value: 'csv',
          scope: 'loaded',
          label: 'CSV',
          icon: FileSpreadsheet,
          description: t('export.dialog.loadedExcerpt'),
          provenance: t('export.dialog.provenanceBrowser'),
          fillLevel: t('export.dialog.fillLoaded'),
        },
      ],
    },
  ]
})

function replayFormatForFocus(focus: ProductOperationFocus): ExportFormat | null {
  if (focus.operationId === 'research.replay_export.pdf' || focus.preferredMode === 'pdf') return 'pdf'
  if (focus.operationId === 'research.replay_export.docx' || focus.preferredMode === 'docx') return 'docx'
  if (
    focus.operationId === 'research.replay_export.evidence_package' ||
    focus.preferredMode === 'evidence_package'
  ) {
    return 'evidence-json'
  }
  if (focus.operationId === 'research.replay_export.concordance' || focus.preferredMode === 'concordance') return 'csv'
  return null
}

function applyFocusedReplayExport(focus: ProductOperationFocus): void {
  const nextFormat = replayFormatForFocus(focus)
  if (!nextFormat) return
  format.value = nextFormat
  exportStore.setPreselectedFormat(nextFormat)
  if (focus.operationId === 'research.replay_export.concordance' || focus.preferredMode === 'concordance') {
    scope.value = 'all-server'
  }
}

function isFocusedFormat(value: ExportFormat): boolean {
  if (value === 'pdf') return focusIs('research.replay_export.pdf') || modeIs('pdf')
  if (value === 'docx') return focusIs('research.replay_export.docx') || modeIs('docx')
  if (value === 'evidence-json') {
    return focusIs('research.replay_export.evidence_package') || modeIs('evidence_package')
  }
  if (value === 'csv') return focusIs('research.replay_export.concordance') || modeIs('concordance')
  return false
}

function buildOptions(): ExportOptions {
  return {
    format: format.value,
    includeResults: includeResults.value,
    includeFrequency: includeFrequency.value,
    includeCollocations: includeCollocations.value,
    includeStatistics: includeStatistics.value,
    includeContext: includeContext.value,
    includeMetadata: includeMetadata.value,
    includeReproMeta: includeReproMeta.value,
    includeAnnotations: includeAnnotations.value,
    rowRange: rowRange.value,
    rangeStart: rangeStart.value,
    rangeEnd: rangeEnd.value,
    rangeCategoryId: rangeCategoryId.value,
    scope: isServerScope.value ? 'all-server' : 'loaded',
    excelDe: excelDe.value,
  }
}

function availabilityScopeForFormat(value: ExportFormat): ExportScope {
  if (formatUsesEvidencePackage(value)) return 'all-server'
  if (serverConcordanceFormats.has(value) && (scope.value === 'all-server' || value !== 'csv')) return 'all-server'
  return 'loaded'
}

function availabilityScopeForOption(option: FormatOption): ExportScope {
  return option.scope ?? availabilityScopeForFormat(option.value)
}

function formatAvailability(value: ExportFormat, optionScope = availabilityScopeForFormat(value)) {
  return exportStore.exportFormatAvailability(value, optionScope)
}

function formatBlockReason(option: FormatOption): string | null {
  return formatAvailability(option.value, availabilityScopeForOption(option)).disabledReason
}

function canSelectFormat(option: FormatOption): boolean {
  return formatAvailability(option.value, availabilityScopeForOption(option)).enabled
}

function selectedScope(): ExportScope {
  return usesEvidencePackageReport.value || isServerOnlyConcordanceFormat.value ? 'all-server' : scope.value
}

function formatOptionIsActive(option: FormatOption): boolean {
  return format.value === option.value && availabilityScopeForOption(option) === selectedScope()
}

function formatOptionIsFocused(option: FormatOption): boolean {
  if (option.value === 'csv' && option.scope === 'loaded') return false
  return isFocusedFormat(option.value)
}

function selectFormatOption(option: FormatOption): void {
  if (!canSelectFormat(option)) return
  format.value = option.value
  if (option.scope) scope.value = option.scope
}

const pendingOptions = computed(() => buildOptions())
const operationAvailability = computed(() =>
  exportStore.exportOptionsAvailability(pendingOptions.value)
)
const currentExportJob = computed(() => exportStore.currentJob)
const recentExportJobs = computed(() => exportStore.exportHistory.slice(0, 3))

function exportStatusLabel(status: string): string {
  if (status === 'pending') return t('export.dialog.statusPending')
  if (status === 'processing') return t('export.dialog.statusProcessing')
  if (status === 'completed') return t('export.dialog.statusCompleted')
  if (status === 'error') return t('export.dialog.statusError')
  return status
}

function exportCoverageLabel(job: {
  total?: number | null
  exportedRows?: number | null
  exportCap?: number | null
  truncated?: boolean
}): string | null {
  if (job.total === null || job.total === undefined) return null
  if (job.exportedRows === null || job.exportedRows === undefined) {
    return t('export.dialog.coverageCounted', { count: formatNumber(job.total) }, job.total)
  }
  const values = {
    rows: formatNumber(job.exportedRows),
    total: formatNumber(job.total),
    cap: job.exportCap !== null && job.exportCap !== undefined ? formatNumber(job.exportCap) : '',
  }
  if (values.cap) {
    return job.truncated
      ? t('export.dialog.coverageRowsCapTruncated', values)
      : t('export.dialog.coverageRowsCap', values)
  }
  return job.truncated
    ? t('export.dialog.coverageRowsTruncated', values)
    : t('export.dialog.coverageRows', values)
}

const activeQueryBlockReason = computed(() =>
  (isServerScope.value || usesEvidencePackageReport.value || includeFrequency.value) && !queryStore.term.trim()
    ? t('export.dialog.needsSearch')
    : null
)
const exportBlockReason = computed(() =>
  activeQueryBlockReason.value ?? operationAvailability.value.disabledReason
)

/**
 * The annotation CSV export rides on a loaded-scope CSV. While "Aktuell geladene
 * Treffer" stays checked, the loaded KWIC rows themselves are an unreleased
 * browser export and block the whole CSV. Unchecking results unblocks the
 * annotation-only export (ANNOTATION-02). Surface that as an actionable hint.
 */
const annotationExportBlockedByLoadedRows = computed(
  () =>
    format.value === 'csv' &&
    !isServerScope.value &&
    includeResults.value &&
    includeAnnotations.value &&
    !operationAvailability.value.enabled,
)

const canExport = computed(() => {
  if (activeQueryBlockReason.value) return false
  if (!operationAvailability.value.enabled) return false
  if (isServerScope.value) {
    // Server full export re-runs the active query; it just needs a search.
    return queryStore.term.trim().length > 0
  }
  return includeResults.value || includeFrequency.value || includeAnnotations.value
})

watch(includeCollocations, (value) => {
  if (value) includeCollocations.value = false
})

consumeFocusFor(['research.replay_export'], applyFocusedReplayExport)

// Apply preselected export format when dialog opens
watch(
  () => props.modelValue,
  (isOpen) => {
    if (isOpen) {
      if (exportStore.preselectedFormat) {
        format.value = exportStore.preselectedFormat
        if (exportStore.preselectedFormat === 'csv') {
          scope.value = 'all-server'
        }
      }
      return
    }
    exportStore.setPreselectedFormat(null)
  },
  { immediate: true },
)

async function handleExport() {
  try {
    await exportStore.exportData(pendingOptions.value)
    uiStore.showToast(t('export.dialog.exportDone'), 'success')
    exportStore.setPreselectedFormat(null)
    emit('update:modelValue', false)
  } catch (error) {
    const message = error instanceof Error ? error.message : t('export.dialog.exportFailed')
    uiStore.showToast(message, 'error')
  }
}

function close() {
  exportStore.setPreselectedFormat(null)
  emit('update:modelValue', false)
}
</script>

<template>
  <Modal
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="t('export.dialog.title')"
    :description="t('export.dialog.description')"
    size="lg"
  >
    <div class="export-form">
      <div v-if="queryStore.sampleProvenance" class="scope-summary">
        <strong>{{ formatSampleProvenance(queryStore.sampleProvenance) }}</strong>
        <span v-if="isServerScope">{{ t('export.dialog.sampleServerReplay') }}</span>
      </div>

      <!-- Format Selection -->
      <div class="form-section">
        <label class="section-label">{{ t('export.dialog.sectionFormat') }}</label>
        <div class="format-groups">
          <section
            v-for="group in formatGroups"
            :key="group.key"
            class="format-group"
          >
            <div class="format-group-head">
              <strong>{{ group.title }}</strong>
              <span>{{ group.note }}</span>
            </div>
            <div class="format-grid">
              <button
                v-for="opt in group.options"
                :key="opt.key"
                type="button"
                class="format-btn"
                :class="{ active: formatOptionIsActive(opt), 'operation-focused': formatOptionIsFocused(opt) }"
                :disabled="!canSelectFormat(opt)"
                :title="formatBlockReason(opt) ?? opt.description"
                @click="selectFormatOption(opt)"
              >
                <component :is="opt.icon" class="w-6 h-6" />
                <span class="format-label">{{ opt.label }}</span>
                <span class="format-desc">{{ opt.description }}</span>
                <span class="format-provenance">{{ opt.provenance }}</span>
                <span class="format-fill">{{ opt.fillLevel }}</span>
                <span v-if="formatBlockReason(opt)" class="format-block">
                  {{ formatBlockReason(opt) }}
                </span>
              </button>
            </div>
          </section>
        </div>
      </div>

      <!-- Content Selection -->
      <div class="form-section">
        <label class="section-label">{{ t('export.dialog.sectionContent') }}</label>
        <div class="checkbox-group">
          <label class="checkbox-item">
            <input v-model="includeResults" type="checkbox" />
            <span>{{ resultSectionLabel }}</span>
            <span class="item-count">
              {{ usesEvidencePackageReport
                ? t('export.dialog.rebuiltFromQuery')
                : t('export.dialog.loadedLinesWithTotal', { count: formatNumber(loadedResultCount), total: totalResultLabel }, loadedResultCount) }}
            </span>
          </label>
          <label class="checkbox-item">
            <input v-model="includeFrequency" type="checkbox" :disabled="usesEvidencePackageReport" />
            <span>{{ t('export.dialog.frequencyList') }}</span>
            <span v-if="usesEvidencePackageReport" class="item-count">{{ t('export.dialog.notRenderedInReport') }}</span>
          </label>
          <label class="checkbox-item">
            <input v-model="includeCollocations" type="checkbox" disabled />
            <span>{{ t('export.dialog.collocations') }}</span>
            <span class="item-count">{{ t('export.dialog.collocationBlocked') }}</span>
          </label>
          <label class="checkbox-item">
            <input v-model="includeStatistics" type="checkbox" :disabled="usesEvidencePackageReport" />
            <span>{{ t('export.dialog.statistics') }}</span>
            <span v-if="usesEvidencePackageReport" class="item-count">{{ t('export.dialog.setByPackage') }}</span>
          </label>
          <label class="checkbox-item">
            <input v-model="includeAnnotations" type="checkbox" :disabled="!hasAnnotations || !annotationsCarryable" />
            <span>{{ t('export.dialog.includeAnnotations') }}</span>
            <span class="item-count">{{ annotationNoteText }}</span>
          </label>
        </div>
        <p v-if="includeAnnotations && annotationsCarryable" class="advanced-note">
          {{ t('export.dialog.annotationSectionNote') }}
        </p>
        <p
          v-if="annotationExportBlockedByLoadedRows"
          class="advanced-note advanced-note--warning"
          data-testid="annotation-export-unblock-hint"
        >
          <i18n-t keypath="export.dialog.annotationUnblockHint" scope="global">
            <template #label>{{ resultSectionLabel }}</template>
            <template #action>
              <button type="button" class="inline-action" @click="includeResults = false">
                {{ t('export.dialog.annotationUnblockAction') }}
              </button>
            </template>
          </i18n-t>
        </p>
        <p v-if="usesEvidencePackageReport" class="advanced-note">
          {{ t('export.dialog.evidenceReportNote') }}
        </p>
        <p v-if="exportBlockReason" class="advanced-note advanced-note--warning">
          {{ exportBlockReason }}
        </p>
      </div>

      <!-- Options -->
      <div class="form-section">
        <label class="section-label">{{ t('export.dialog.sectionOptions') }}</label>
        <div class="checkbox-group">
          <label class="checkbox-item">
            <input v-model="includeContext" type="checkbox" :disabled="usesEvidencePackageReport" />
            <span>{{ t('export.dialog.includeContext') }}</span>
            <span v-if="usesEvidencePackageReport" class="item-count">{{ t('export.dialog.setByServerPackage') }}</span>
          </label>
          <label class="checkbox-item">
            <input v-model="includeMetadata" type="checkbox" :disabled="usesEvidencePackageReport" />
            <span>{{ t('export.dialog.includeMetadata') }}</span>
            <span v-if="usesEvidencePackageReport" class="item-count">{{ t('export.dialog.setByServerPackage') }}</span>
          </label>
          <label
            v-if="format === 'csv' && isServerScope"
            class="checkbox-item"
            data-testid="excel-csv-dialect"
          >
            <input v-model="excelDe" type="checkbox" />
            <span>{{ t('export.dialog.excelDialect') }}</span>
            <span class="item-count">{{ t('export.dialog.excelDialectNote') }}</span>
          </label>
        </div>
      </div>

      <!-- Advanced -->
      <details class="advanced">
        <summary class="advanced-summary">
          <span>{{ t('export.dialog.advancedOptions') }}</span>
          <span class="advanced-hint">{{ t('export.dialog.advancedHint') }}</span>
        </summary>
        <div class="advanced-body">
          <div class="form-section">
            <label class="section-label">{{ t('export.dialog.sectionReplication') }}</label>
            <div class="checkbox-group">
              <label class="checkbox-item">
                <input v-model="includeReproMeta" type="checkbox" />
                <span>{{ t('export.dialog.appendReproMeta') }}</span>
              </label>
            </div>
          </div>
          <p class="advanced-note">
            {{ t('export.dialog.latexHint') }}
          </p>
        </div>
      </details>

      <!-- Treffer-Scope (server full export vs loaded window) -->
      <div class="form-section">
        <label class="section-label">{{ t('export.dialog.sectionHitScope') }}</label>
        <div v-if="usesEvidencePackageReport" class="scope-summary scope-summary--server">
          <strong>{{ t('export.dialog.evidenceWorkflowTitle') }}</strong>
          <span>{{ t('export.dialog.evidenceWorkflowText') }}</span>
        </div>
        <div v-else class="range-options">
          <label class="radio-item">
            <input v-model="scope" type="radio" value="loaded" />
            <span>{{ t('export.dialog.scopeLoaded', { count: formatNumber(loadedResultCount) }) }}</span>
          </label>
          <label
            class="radio-item"
            :class="{ 'is-disabled': !serverScopeAvailable }"
          >
            <input
              v-model="scope"
              type="radio"
              value="all-server"
              :disabled="!serverScopeAvailable"
            />
            <span>{{ t('export.dialog.scopeServer') }}</span>
          </label>
        </div>
        <p class="advanced-note">
          <template v-if="isEvidencePackage">
            <i18n-t keypath="export.dialog.noteEvidenceJson" scope="global">
              <template #package><strong>{{ t('export.dialog.evidencePackageName') }}</strong></template>
            </i18n-t>
          </template>
          <template v-else-if="usesEvidencePackageReport">
            {{ t('export.dialog.noteReport') }}
            <template v-if="format === 'latex'">
              {{ t('export.dialog.noteLatex') }}
            </template>
          </template>
          <template v-else-if="isServerScope">
            {{ t('export.dialog.noteServerScope', { format: format.toUpperCase() }) }}
          </template>
          <template v-else-if="!serverScopeAvailable">
            {{ t('export.dialog.noteServerUnavailable') }}
          </template>
          <template v-else>
            {{ t('export.dialog.noteLoaded') }}
          </template>
        </p>
      </div>

      <!-- Row Range -->
      <div v-if="!isServerScope && !usesEvidencePackageReport" class="form-section">
        <label class="section-label">{{ t('export.dialog.sectionLines') }}</label>
        <div class="range-options">
          <label class="radio-item">
            <input v-model="rowRange" type="radio" value="all" />
            <span>{{ t('export.dialog.rowsAll') }}</span>
          </label>
          <label class="radio-item">
            <input v-model="rowRange" type="radio" value="selected" />
            <span>{{ t('export.dialog.rowsSelected', { count: formatNumber(queryStore.selectedCount) }) }}</span>
          </label>
          <label class="radio-item" :class="{ 'is-disabled': !hasAnnotations }">
            <input v-model="rowRange" type="radio" value="annotated" :disabled="!hasAnnotations" />
            <span>{{ t('export.dialog.rowsAnnotated', { count: formatNumber(annotationsStore.annotatedCount) }) }}</span>
          </label>
          <label
            v-if="annotationsStore.categories.length"
            class="radio-item"
            :class="{ 'is-disabled': !hasAnnotations }"
          >
            <input v-model="rowRange" type="radio" value="category" :disabled="!hasAnnotations" />
            <span>{{ t('export.dialog.rowsByCategory') }}</span>
            <select
              v-model="rangeCategoryId"
              class="template-select"
              :disabled="rowRange !== 'category'"
            >
              <option :value="''">{{ t('export.dialog.uncategorizedNoteOnly') }}</option>
              <option
                v-for="cat in annotationsStore.categories"
                :key="cat.id"
                :value="cat.id"
              >
                {{ cat.label }} ({{ annotationsStore.categoryCounts.byCategory[cat.id] ?? 0 }})
              </option>
            </select>
          </label>
          <label class="radio-item">
            <input v-model="rowRange" type="radio" value="range" />
            <span>{{ t('export.dialog.rowsRange') }}</span>
            <input
              v-model.number="rangeStart"
              type="number"
              min="1"
              class="range-input"
              :disabled="rowRange !== 'range'"
            />
            <span>{{ t('export.dialog.rowsRangeTo') }}</span>
            <input
              v-model.number="rangeEnd"
              type="number"
              min="1"
              class="range-input"
              :disabled="rowRange !== 'range'"
            />
          </label>
        </div>
        <p class="advanced-note">
          {{ t('export.dialog.rowsNote') }}
        </p>
      </div>

      <!-- Progress -->
      <div v-if="isExporting" class="progress-section">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${progress}%` }" />
        </div>
        <span class="progress-label">{{ progress }}%</span>
      </div>

      <div
        v-if="currentExportJob || recentExportJobs.length"
        class="export-runtime-evidence"
        :aria-label="t('export.dialog.runtimeAria')"
      >
        <div class="runtime-copy">
          <span class="runtime-kicker">{{ t('export.dialog.runtimeKicker') }}</span>
          <strong>{{ t('export.dialog.runtimeTitle') }}</strong>
          <p>{{ t('export.dialog.runtimeText') }}</p>
        </div>
        <div v-if="currentExportJob" class="runtime-card runtime-card--active">
          <span class="runtime-card-label">{{ t('export.dialog.currentExport') }}</span>
          <strong>{{ exportStatusLabel(currentExportJob.status) }} · {{ currentExportJob.progress }}%</strong>
          <span v-if="currentExportJob.filename" class="runtime-card-meta">
            {{ currentExportJob.filename }}
          </span>
          <span v-if="exportCoverageLabel(currentExportJob)" class="runtime-card-meta">
            {{ exportCoverageLabel(currentExportJob) }}
          </span>
          <span v-if="currentExportJob.warning" class="runtime-card-meta">
            {{ currentExportJob.warning }}
          </span>
        </div>
        <div v-if="recentExportJobs.length" class="runtime-card">
          <span class="runtime-card-label">{{ t('export.dialog.recentExports') }}</span>
          <ul class="runtime-history">
            <li
              v-for="job in recentExportJobs"
              :key="job.id"
            >
              <span>{{ job.filename ?? t('export.dialog.formatExport', { format: job.format.toUpperCase() }) }}</span>
              <strong>{{ exportStatusLabel(job.status) }}</strong>
              <small v-if="exportCoverageLabel(job)">{{ exportCoverageLabel(job) }}</small>
              <small v-if="job.warning">{{ job.warning }}</small>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <template #footer>
      <Button variant="ghost" @click="close">
        {{ t('export.dialog.cancel') }}
      </Button>
      <Button
        variant="primary"
        :loading="isExporting"
        :disabled="!canExport"
        :title="exportBlockReason ?? undefined"
        @click="handleExport"
      >
        {{ t('export.dialog.submit') }}
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
@reference "../../style.css";

.export-form {
  @apply space-y-6;
}

.form-section {
  @apply space-y-3;
}

.section-label {
  @apply block text-sm font-medium;
  @apply text-neutral-700 dark:text-neutral-300;
}

/* Format Grid */
.format-groups {
  @apply space-y-3;
}

.format-group {
  @apply rounded-2xl border border-neutral-200 bg-white/60 p-3;
  @apply dark:border-neutral-700 dark:bg-neutral-900/40;
}

.format-group-head {
  @apply mb-3 flex flex-col gap-1;
}

.format-group-head strong {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.format-group-head span {
  @apply text-xs leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.format-grid {
  @apply grid grid-cols-3 gap-3;
}

.format-btn {
  @apply flex flex-col items-center gap-1;
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border-2 border-transparent;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply transition-all;
}

.format-btn:disabled {
  @apply cursor-not-allowed opacity-50 hover:bg-neutral-50 dark:hover:bg-neutral-800;
}

.format-btn:hover {
  @apply bg-neutral-100 dark:bg-neutral-700;
}

.format-btn.active {
  @apply bg-primary-50 dark:bg-primary-900/30;
  @apply border-primary-500;
  @apply text-primary-600 dark:text-primary-400;
}

.format-btn.operation-focused {
  @apply ring-2 ring-amber-300 ring-offset-2 ring-offset-white;
  @apply dark:ring-amber-500/80 dark:ring-offset-neutral-950;
}

.format-label {
  @apply font-medium text-sm;
}

.format-desc {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.format-provenance,
.format-fill {
  @apply text-center text-[0.65rem] leading-tight text-neutral-500 dark:text-neutral-400;
}

.format-block {
  @apply max-w-full text-center text-[0.65rem] leading-tight;
  @apply text-warning-700 dark:text-warning-300;
}

/* Checkboxes */
.checkbox-group {
  @apply space-y-2;
}

.checkbox-item {
  @apply flex items-center gap-3 cursor-pointer;
  @apply text-sm text-neutral-700 dark:text-neutral-300;
}

.checkbox-item input[type="checkbox"] {
  @apply w-4 h-4 rounded;
  @apply border-neutral-300 dark:border-neutral-600;
  @apply text-primary-600;
  @apply focus:ring-primary-500;
}

.item-count {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  @apply ml-auto;
}

/* Radio Options */
.range-options {
  @apply space-y-2;
}

.radio-item {
  @apply flex items-center gap-3 cursor-pointer;
  @apply text-sm text-neutral-700 dark:text-neutral-300;
}

.radio-item input[type="radio"] {
  @apply w-4 h-4;
  @apply border-neutral-300 dark:border-neutral-600;
  @apply text-primary-600;
  @apply focus:ring-primary-500;
}

.radio-item.is-disabled {
  @apply opacity-50 cursor-not-allowed;
}

.scope-summary {
  @apply rounded-xl border px-3 py-2 text-sm;
  @apply flex flex-col gap-1;
}

.scope-summary strong {
  @apply text-neutral-800 dark:text-neutral-100;
}

.scope-summary span {
  @apply text-xs leading-relaxed text-neutral-600 dark:text-neutral-300;
}

.scope-summary--server {
  @apply border-primary-200 bg-primary-50 dark:border-primary-900/40 dark:bg-primary-900/20;
}

.advanced-note--warning {
  @apply text-warning-700 dark:text-warning-300;
}

.inline-action {
  @apply underline font-medium;
  @apply text-primary-600 dark:text-primary-400;
  @apply hover:text-primary-700 dark:hover:text-primary-300;
}

.range-input {
  @apply w-20 px-2 py-1 rounded;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-300 dark:border-neutral-600;
  @apply text-sm text-center;
}

.range-input:disabled {
  @apply opacity-50;
}

.template-select {
  @apply px-2.5 py-1.5 rounded-lg text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.advanced {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50/60 dark:bg-neutral-900/60;
  @apply px-3 py-2;
}

.advanced-summary {
  @apply flex items-center justify-between gap-2;
  @apply text-sm font-medium text-neutral-700 dark:text-neutral-300;
  @apply cursor-pointer select-none;
}

.advanced-summary::-webkit-details-marker {
  display: none;
}

.advanced-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.advanced-body {
  @apply mt-3 space-y-4;
}

.advanced-note {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

/* Progress */
.progress-section {
  @apply flex items-center gap-3;
}

.progress-bar {
  @apply flex-1 h-2 rounded-full overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.progress-fill {
  @apply h-full rounded-full;
  @apply bg-primary-500;
  transition: width 0.3s ease;
}

.progress-label {
  @apply text-sm font-medium text-neutral-600 dark:text-neutral-400;
  @apply min-w-[3rem] text-right;
}

.export-runtime-evidence {
  @apply rounded-2xl border border-neutral-200 bg-neutral-50/80 p-3;
  @apply grid gap-3 text-sm;
  @apply dark:border-neutral-700 dark:bg-neutral-900/70;
}

.runtime-copy {
  @apply space-y-1;
}

.runtime-kicker,
.runtime-card-label {
  @apply block text-xs font-semibold uppercase tracking-wide;
  @apply text-neutral-500 dark:text-neutral-400;
}

.runtime-copy strong {
  @apply block text-neutral-900 dark:text-neutral-50;
}

.runtime-copy p {
  @apply text-xs leading-relaxed text-neutral-600 dark:text-neutral-300;
}

.runtime-card {
  @apply rounded-xl border border-neutral-200 bg-white p-3;
  @apply dark:border-neutral-700 dark:bg-neutral-950;
}

.runtime-card--active {
  @apply border-primary-200 bg-primary-50/70;
  @apply dark:border-primary-900/50 dark:bg-primary-950/30;
}

.runtime-card strong {
  @apply block text-neutral-800 dark:text-neutral-100;
}

.runtime-card-meta {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.runtime-history {
  @apply mt-2 space-y-1;
}

.runtime-history li {
  @apply flex items-center justify-between gap-3 text-xs;
  @apply text-neutral-600 dark:text-neutral-300;
}
</style>
