<script setup lang="ts">
/**
 * ResearchToolsPanel - Forschungswerkzeuge
 *
 * Zwei Bereiche:
 * - Analyse-Templates (eingebaute Pipelines) ausführen und exportieren
 * - Reproduzierbarkeit: Live-Replay einzelner Runs, Replay-Report,
 *   lokaler Run-Export (JSON mit Payload-Redaktion, BibTeX)
 */
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FlaskConical, Play, RefreshCw,
  Check, X, ChevronRight, Loader2, AlertTriangle,
  BookTemplate, Download, FileText, Quote, FileJson
} from 'lucide-vue-next'
import type { RunRecordV1 } from '@/types/copilot-protocol'
import type { AnalysisTemplate } from '@/services/analysisTemplateService'
import {
  reproduceRun,
  generateReproducibilityReport,
  getReproductionState,
  exportReportAsMarkdown,
  type ReproducibilityResult,
  type ReproducibilityReport,
} from '@/services/reproducibilityService'
import {
  getAllTemplates,
  executeTemplate,
  validateParameters,
  exportTemplateAsJson,
} from '@/services/analysisTemplateService'
import {
  createRunPackage,
  createRunsPackage,
  downloadPackageAsJson,
  exportRunAsBibTeX,
} from '@/services/runExportService'
import { getRecentRuns } from '@/services/runRecordService'
import { downloadText } from '@/utils/download'
import CodeSpanText from '@/components/ui/CodeSpanText.vue'
import { formatDateTime } from '@/i18n/format'
import { formatDurationMs, formatSuccessRate } from '@/lib/copilotNumbers'

const { t } = useI18n()

// ============================================================================
// State
// ============================================================================

const activeTab = ref<'reproduce' | 'templates'>('templates')

// Reproducibility
const selectedRunId = ref<string | null>(null)
const reproResult = ref<ReproducibilityResult | null>(null)
const reproReport = ref<ReproducibilityReport | null>(null)
const reproError = ref<string | null>(null)

// Templates
const selectedTemplate = ref<AnalysisTemplate | null>(null)
const templateParams = ref<Record<string, unknown>>({})
const templateValidation = ref<{ valid: boolean; errors: string[] }>({ valid: true, errors: [] })
const templateRunning = ref(false)
const templateCurrentStep = ref<string | null>(null)

// Export
const exportRunIds = ref<Set<string>>(new Set())

// ============================================================================
// Computed
// ============================================================================

const recentRuns = computed(() => getRecentRuns(10))
const templates = computed(() => getAllTemplates())
const reproState = computed(() => getReproductionState())

const templatesByCategory = computed(() => {
  const grouped = new Map<string, AnalysisTemplate[]>()
  for (const template of templates.value) {
    const cat = template.category ?? 'weitere' // i18n-ignore: internal category id
    if (!grouped.has(cat)) grouped.set(cat, [])
    grouped.get(cat)!.push(template)
  }
  return grouped
})

function categoryLabel(category: string): string {
  if (category === 'corpus') return t('copilot.researchTools.categoryCorpus')
  if (category === 'frequency') return t('copilot.researchTools.categoryFrequency')
  if (category === 'collocation') return t('copilot.researchTools.categoryCollocation')
  if (category === 'comparison') return t('copilot.researchTools.categoryComparison')
  if (category === 'weitere') return t('copilot.researchTools.categoryOther') // i18n-ignore: internal category id
  return category
}

function reportReproducibilityRate(report: ReproducibilityReport): string {
  if (report.summary.totalAttempts === 0) return t('copilot.researchTools.rateNotComputed')
  return formatSuccessRate(report.summary.successfulMatches, report.summary.totalAttempts)
}

function differenceLabel(field: string): string {
  if (field === 'scopeHash') return t('copilot.researchTools.diffScopeHash')
  if (field === 'corpusId') return t('copilot.researchTools.diffCorpus')
  if (field === 'resultHash') return t('copilot.researchTools.diffResultHash')
  if (field === 'rowCount') return t('copilot.researchTools.diffRowCount')
  return field
}

function formatDifferenceValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return t('copilot.researchTools.unknownValue')
  return String(value)
}

// ============================================================================
// Reproducibility Actions
// ============================================================================

async function handleExecuteReproduce() {
  if (!selectedRunId.value) return
  reproResult.value = null
  reproReport.value = null
  reproError.value = null

  try {
    reproResult.value = await reproduceRun(selectedRunId.value)
  } catch (e) {
    reproError.value = e instanceof Error ? e.message : t('copilot.researchTools.error')
  }
}

async function handleFullReport() {
  if (!selectedRunId.value) return

  reproResult.value = null
  reproReport.value = null
  reproError.value = null

  try {
    reproReport.value = await generateReproducibilityReport(selectedRunId.value, 3)
  } catch (e) {
    reproError.value = e instanceof Error ? e.message : t('copilot.researchTools.error')
  }
}

function handleExportReport() {
  if (!reproReport.value) return
  const md = exportReportAsMarkdown(reproReport.value)
  downloadText(md, `repro_report_${reproReport.value.id}.md`, 'text/markdown')
}

// ============================================================================
// Template Actions
// ============================================================================

function selectTemplate(template: AnalysisTemplate) {
  selectedTemplate.value = template
  templateParams.value = {}

  // Set defaults
  for (const param of template.parameters) {
    if (param.defaultValue !== undefined) {
      templateParams.value[param.name] = param.defaultValue
    }
  }

  validateTemplateParams()
}

function validateTemplateParams() {
  if (!selectedTemplate.value) return
  templateValidation.value = validateParameters(selectedTemplate.value, templateParams.value)
}

async function handleRunTemplate() {
  if (!selectedTemplate.value || !templateValidation.value.valid) return

  templateRunning.value = true
  templateCurrentStep.value = null

  try {
    await executeTemplate(selectedTemplate.value.id, templateParams.value, {
      onStepStart: (stepId) => {
        templateCurrentStep.value = stepId
      },
      onStepComplete: () => {
        // Could show progress
      },
    })
  } catch (e) {
    console.error('Template execution failed:', e)
  } finally {
    templateRunning.value = false
    templateCurrentStep.value = null
  }
}

function handleExportTemplate() {
  if (!selectedTemplate.value) return
  const json = exportTemplateAsJson(selectedTemplate.value.id)
  if (json) {
    downloadText(json, `template_${selectedTemplate.value.id}.json`, 'application/json')
  }
}

// ============================================================================
// Run Export Actions
// ============================================================================

function toggleExportRun(runId: string) {
  if (exportRunIds.value.has(runId)) {
    exportRunIds.value.delete(runId)
  } else {
    exportRunIds.value.add(runId)
  }
  exportRunIds.value = new Set(exportRunIds.value)
}

function handleDownloadRunJson() {
  const ids = Array.from(exportRunIds.value)

  let pkg
  if (ids.length === 1) {
    pkg = createRunPackage(ids[0]!)
  } else if (ids.length > 1) {
    pkg = createRunsPackage(ids)
  }

  if (pkg) {
    downloadPackageAsJson(pkg)
  }
}

function handleExportBibTeX() {
  const runs = Array.from(exportRunIds.value)
    .map(id => recentRuns.value.find(r => r.runId === id))
    .filter((r): r is RunRecordV1 => r !== undefined)

  if (runs.length > 0) {
    const bibtex = runs.map(r => exportRunAsBibTeX(r)).join('\n\n')
    downloadText(bibtex, 'candyconc_references.bib', 'text/plain')
  }
}

// ============================================================================
// Helpers
// ============================================================================

function formatTimestamp(ts: number): string {
  return formatDateTime(ts, {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <div class="research-tools-panel">
    <!-- Tab Navigation -->
    <div class="tab-nav">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'templates' }"
        @click="activeTab = 'templates'"
      >
        <BookTemplate class="w-4 h-4" />
        {{ t('copilot.researchTools.tabTemplates') }}
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'reproduce' }"
        @click="activeTab = 'reproduce'"
      >
        <RefreshCw class="w-4 h-4" />
        {{ t('copilot.researchTools.tabReproduce') }}
      </button>
    </div>

    <!-- Templates Tab -->
    <div v-if="activeTab === 'templates'" class="tab-content">
      <div class="templates-grid">
        <!-- Template List -->
        <div class="template-list">
          <div
            v-for="[category, categoryTemplates] in templatesByCategory"
            :key="category"
            class="template-category"
          >
            <h4 class="category-title">{{ categoryLabel(category) }}</h4>
            <button
              v-for="template in categoryTemplates"
              :key="template.id"
              class="template-item"
              :class="{ selected: selectedTemplate?.id === template.id }"
              @click="selectTemplate(template)"
            >
              <span class="template-name">{{ template.name }}</span>
            </button>
          </div>
        </div>

        <!-- Template Details -->
        <div class="template-details">
          <template v-if="selectedTemplate">
            <h3 class="details-title">{{ selectedTemplate.name }}</h3>
            <p v-if="selectedTemplate.description" class="details-description">
              {{ selectedTemplate.description }}
            </p>

            <!-- Parameters -->
            <div v-if="selectedTemplate.parameters.length > 0" class="params-section">
              <h4 class="params-title">{{ t('copilot.researchTools.parameters') }}</h4>
              <div
                v-for="param in selectedTemplate.parameters"
                :key="param.name"
                class="param-field"
              >
                <label :for="param.name" class="param-label">
                  {{ param.label }}
                  <span v-if="param.required" class="required">*</span>
                </label>

                <input
                  v-if="param.type === 'string'"
                  :id="param.name"
                  v-model="templateParams[param.name]"
                  type="text"
                  class="param-input"
                  @input="validateTemplateParams"
                />

                <input
                  v-else-if="param.type === 'number'"
                  :id="param.name"
                  v-model.number="templateParams[param.name]"
                  type="number"
                  class="param-input"
                  :min="param.validation?.min"
                  :max="param.validation?.max"
                  @input="validateTemplateParams"
                />

                <select
                  v-else-if="param.type === 'select'"
                  :id="param.name"
                  v-model="templateParams[param.name]"
                  class="param-select"
                  @change="validateTemplateParams"
                >
                  <option
                    v-for="opt in param.options"
                    :key="String(opt.value)"
                    :value="opt.value"
                  >
                    {{ opt.label }}
                  </option>
                </select>

                <p v-if="param.description" class="param-hint">
                  {{ param.description }}
                </p>
              </div>
            </div>

            <!-- Validation Errors -->
            <div v-if="templateValidation.errors.length > 0" class="validation-errors">
              <AlertTriangle class="w-4 h-4" />
              <ul>
                <li v-for="err in templateValidation.errors" :key="err">{{ err }}</li>
              </ul>
            </div>

            <!-- Steps Preview -->
            <div class="steps-section">
              <h4 class="steps-title">{{ t('copilot.researchTools.steps') }}</h4>
              <ol class="steps-list">
                <li
                  v-for="step in selectedTemplate.steps"
                  :key="step.id"
                  class="step-item"
                  :class="{ active: templateCurrentStep === step.id }"
                >
                  <Loader2 v-if="templateCurrentStep === step.id" class="w-3 h-3 animate-spin" />
                  <ChevronRight v-else class="w-3 h-3" />
                  <span>{{ step.description || step.actionType }}</span>
                </li>
              </ol>
            </div>

            <!-- Actions -->
            <div class="details-actions">
              <button
                class="btn-primary"
                :disabled="!templateValidation.valid || templateRunning"
                @click="handleRunTemplate"
              >
                <Loader2 v-if="templateRunning" class="w-4 h-4 animate-spin" />
                <Play v-else class="w-4 h-4" />
                {{ t('copilot.researchTools.run') }}
              </button>
              <button class="btn-secondary" @click="handleExportTemplate">
                <Download class="w-4 h-4" />
                {{ t('copilot.researchTools.export') }}
              </button>
            </div>
          </template>

          <div v-else class="empty-details">
            <BookTemplate class="w-8 h-8 text-neutral-300" />
            <p>{{ t('copilot.researchTools.selectTemplate') }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Reproduce Tab -->
    <div v-if="activeTab === 'reproduce'" class="tab-content">
      <div class="reproduce-section">
        <h4 class="section-title">
          <FlaskConical class="w-4 h-4" />
          {{ t('copilot.researchTools.selectRun') }}
        </h4>

        <div class="run-select-list">
          <button
            v-for="run in recentRuns"
            :key="run.runId"
            class="run-select-item"
            :class="{ selected: selectedRunId === run.runId }"
            @click="selectedRunId = run.runId"
          >
            <span class="run-summary">{{ run.summary }}</span>
            <span class="run-time">{{ formatTimestamp(run.ts) }}</span>
          </button>
        </div>

        <div v-if="selectedRunId" class="reproduce-actions">
          <button
            class="btn-secondary"
            :disabled="reproState.isRunning"
            @click="handleExecuteReproduce"
          >
            <Play class="w-4 h-4" />
            {{ t('copilot.researchTools.liveReplay') }}
          </button>
          <button
            class="btn-primary"
            :disabled="reproState.isRunning"
            @click="handleFullReport"
          >
            <Loader2 v-if="reproState.isRunning" class="w-4 h-4 animate-spin" />
            <FileText v-else class="w-4 h-4" />
            {{ t('copilot.researchTools.replayReport') }}
          </button>
        </div>
        <p v-if="selectedRunId" class="replay-mode-note">
          {{ t('copilot.researchTools.replayNote') }}
        </p>

        <!-- Progress -->
        <div v-if="reproState.progress" class="repro-progress">
          <Loader2 class="w-4 h-4 animate-spin" />
          <span>{{ t('copilot.researchTools.attempt', { current: reproState.progress.current, total: reproState.progress.total }) }}</span>
        </div>

        <!-- Quick Result -->
        <div v-if="reproResult" class="repro-result" :class="{ success: reproResult.matched, failed: !reproResult.matched }">
          <Check v-if="reproResult.matched" class="w-5 h-5" />
          <X v-else class="w-5 h-5" />
          <div class="result-content">
            <span class="result-status">
              {{ reproResult.matched
                ? t('copilot.researchTools.match')
                : reproResult.error ? t('copilot.researchTools.error') : t('copilot.researchTools.mismatch') }}
            </span>
            <span v-if="reproResult.error" class="result-detail">
              <CodeSpanText :text="reproResult.error" />
            </span>
            <span v-else-if="reproResult.differences?.length" class="result-detail">
              {{ t('copilot.researchTools.differences', { count: reproResult.differences.length }, reproResult.differences.length) }}
            </span>
            <span class="result-duration">{{ formatDurationMs(reproResult.durationMs) }}</span>
            <ul v-if="reproResult.differences?.length" class="difference-list">
              <li
                v-for="diff in reproResult.differences"
                :key="`${diff.field}-${formatDifferenceValue(diff.original)}-${formatDifferenceValue(diff.new)}`"
              >
                <strong>{{ differenceLabel(diff.field) }}:</strong>
                <code>{{ formatDifferenceValue(diff.original) }}</code>
                <span>→</span>
                <code>{{ formatDifferenceValue(diff.new) }}</code>
              </li>
            </ul>
          </div>
        </div>

        <!-- Full Report -->
        <div v-if="reproReport" class="repro-report">
          <div class="report-header">
            <h4>{{ t('copilot.researchTools.reportTitle') }}</h4>
            <button class="btn-icon" @click="handleExportReport">
              <Download class="w-4 h-4" />
            </button>
          </div>
          <div class="report-summary">
            <div class="summary-stat">
              <span class="stat-value">{{ reportReproducibilityRate(reproReport) }}</span>
              <span class="stat-label">{{ t('copilot.researchTools.identical') }}</span>
            </div>
            <div class="summary-stat">
              <span class="stat-value">{{ reproReport.summary.totalAttempts }}</span>
              <span class="stat-label">{{ t('copilot.researchTools.attempts') }}</span>
            </div>
            <div class="summary-stat">
              <span class="stat-value">{{ reproReport.summary.failedMatches }}</span>
              <span class="stat-label">{{ t('copilot.researchTools.mismatched') }}</span>
            </div>
            <div class="summary-stat">
              <span class="stat-value">{{ reproReport.summary.errors }}</span>
              <span class="stat-label">{{ t('copilot.researchTools.failed') }}</span>
            </div>
          </div>
        </div>

        <!-- Error -->
        <div v-if="reproError" class="repro-error">
          <AlertTriangle class="w-4 h-4" />
          {{ reproError }}
        </div>

        <!-- Run Export -->
        <div class="export-section">
          <h4 class="section-title">
            <Download class="w-4 h-4" />
            {{ t('copilot.researchTools.runExport') }}
          </h4>
          <p class="export-hint">
            {{ t('copilot.researchTools.exportHint') }}
          </p>

          <div class="run-select-list">
            <label
              v-for="run in recentRuns"
              :key="run.runId"
              class="run-checkbox-item"
            >
              <input
                type="checkbox"
                :checked="exportRunIds.has(run.runId)"
                @change="toggleExportRun(run.runId)"
              />
              <span class="run-summary">{{ run.summary }}</span>
              <span class="run-time">{{ formatTimestamp(run.ts) }}</span>
            </label>
          </div>

          <div v-if="exportRunIds.size > 0" class="export-actions">
            <button class="btn-secondary" @click="handleDownloadRunJson">
              <FileJson class="w-4 h-4" />
              {{ t('copilot.researchTools.exportJson') }}
            </button>
            <button class="btn-secondary" @click="handleExportBibTeX">
              <Quote class="w-4 h-4" />
              {{ t('copilot.researchTools.exportBibtex') }}
            </button>
          </div>
          <p v-else class="export-hint">
            {{ t('copilot.researchTools.exportNone') }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.research-tools-panel {
  @apply flex flex-col h-full;
  @apply bg-white dark:bg-neutral-900;
}

.tab-nav {
  @apply flex border-b border-neutral-200 dark:border-neutral-700;
}

.tab-btn {
  @apply flex items-center gap-2 px-4 py-3;
  @apply text-sm font-medium;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply border-b-2 border-transparent;
  @apply hover:text-neutral-800 dark:hover:text-neutral-200;
  @apply transition-colors;
}

.tab-btn.active {
  @apply text-copilot-primary border-copilot-primary;
}

.tab-content {
  @apply flex-1 overflow-y-auto p-4;
}

/* Templates */
.templates-grid {
  @apply grid grid-cols-2 gap-4 h-full;
}

.template-list {
  @apply space-y-4 overflow-y-auto pr-2;
}

.template-category {
  @apply space-y-1;
}

.category-title {
  @apply text-xs font-semibold text-neutral-500 uppercase tracking-wide mb-2;
}

.template-item {
  @apply flex items-center justify-between w-full;
  @apply px-3 py-2 rounded-lg text-left;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.template-item.selected {
  @apply bg-copilot-primary/10 ring-1 ring-copilot-primary/30;
}

.template-name {
  @apply text-sm text-neutral-800 dark:text-neutral-200;
}

.template-details {
  @apply bg-neutral-50 dark:bg-neutral-800 rounded-lg p-4;
  @apply overflow-y-auto;
}

.details-title {
  @apply text-lg font-semibold text-neutral-800 dark:text-neutral-200 mb-2;
}

.details-description {
  @apply text-sm text-neutral-600 dark:text-neutral-400 mb-4;
}

.params-section, .steps-section {
  @apply mb-4;
}

.params-title, .steps-title {
  @apply text-xs font-semibold text-neutral-500 uppercase tracking-wide mb-2;
}

.param-field {
  @apply mb-3;
}

.param-label {
  @apply block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1;
}

.required {
  @apply text-red-500;
}

.param-input, .param-select {
  @apply w-full px-3 py-2 rounded-lg;
  @apply bg-white dark:bg-neutral-700;
  @apply border border-neutral-200 dark:border-neutral-600;
  @apply text-sm text-neutral-800 dark:text-neutral-200;
  @apply focus:outline-none focus:ring-2 focus:ring-copilot-primary/30;
}

.param-hint {
  @apply text-xs text-neutral-500 mt-1;
}

.validation-errors {
  @apply flex items-start gap-2 p-3 rounded-lg mb-4;
  @apply bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400;
  @apply text-sm;
}

.validation-errors ul {
  @apply list-disc list-inside;
}

.steps-list {
  @apply space-y-1;
}

.step-item {
  @apply flex items-center gap-2 text-sm;
  @apply text-neutral-600 dark:text-neutral-400;
}

.step-item.active {
  @apply text-copilot-primary font-medium;
}

.details-actions {
  @apply flex gap-2 pt-4 border-t border-neutral-200 dark:border-neutral-700;
}

.empty-details {
  @apply flex flex-col items-center justify-center h-full;
  @apply text-neutral-400 text-sm;
  gap: 8px;
}

/* Reproduce */
.reproduce-section {
  @apply space-y-4;
}

.section-title {
  @apply flex items-center gap-2;
  @apply text-sm font-semibold text-neutral-700 dark:text-neutral-300;
}

.run-select-list {
  @apply space-y-1 max-h-48 overflow-y-auto;
}

.run-select-item {
  @apply flex items-center justify-between w-full;
  @apply px-3 py-2 rounded-lg text-left;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.run-select-item.selected {
  @apply bg-copilot-primary/10 ring-1 ring-copilot-primary/30;
}

.run-checkbox-item {
  @apply flex items-center gap-3 w-full;
  @apply px-3 py-2 rounded-lg cursor-pointer;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
}

.run-summary {
  @apply flex-1 text-sm text-neutral-800 dark:text-neutral-200 truncate;
}

.run-time {
  @apply text-xs text-neutral-400;
}

.reproduce-actions, .export-actions {
  @apply flex flex-wrap gap-2;
}

.replay-mode-note {
  @apply rounded-lg bg-neutral-50 px-3 py-2 text-xs leading-relaxed text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300;
}

.repro-progress {
  @apply flex items-center gap-2 text-sm text-copilot-primary;
}

.repro-result {
  @apply flex items-center gap-3 p-4 rounded-lg;
}

.repro-result.success {
  @apply bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400;
}

.repro-result.failed {
  @apply bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400;
}

.result-content {
  @apply flex-1;
}

.result-status {
  @apply block text-sm font-medium;
}

.result-detail {
  @apply block text-xs opacity-85;
}

.difference-list {
  @apply mt-2 space-y-1 text-xs;
}

.difference-list li {
  @apply flex flex-wrap items-center gap-1;
}

.difference-list code {
  @apply rounded bg-white/60 px-1 py-0.5 font-mono text-[11px] dark:bg-neutral-950/40;
}

.result-duration {
  @apply text-xs opacity-75;
}

.repro-report {
  @apply p-4 rounded-lg bg-neutral-50 dark:bg-neutral-800;
}

.report-header {
  @apply flex items-center justify-between mb-3;
}

.report-header h4 {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-200;
}

.report-summary {
  @apply grid grid-cols-2 gap-4 md:grid-cols-4;
}

.summary-stat {
  @apply text-center;
}

.stat-value {
  @apply block text-2xl font-bold text-copilot-primary;
}

.stat-label {
  @apply text-xs text-neutral-500;
}

.repro-error {
  @apply flex items-center gap-2 p-3 rounded-lg;
  @apply bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400;
  @apply text-sm;
}

/* Export */
.export-section {
  @apply space-y-3 pt-4 border-t border-neutral-200 dark:border-neutral-700;
}

.export-hint {
  @apply text-xs text-neutral-500;
}

/* Buttons */
.btn-primary {
  @apply flex items-center gap-2 px-4 py-2 rounded-lg;
  @apply bg-copilot-primary text-white;
  @apply hover:bg-copilot-primary/90;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors text-sm font-medium;
}

.btn-secondary {
  @apply flex items-center gap-2 px-4 py-2 rounded-lg;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply hover:bg-neutral-300 dark:hover:bg-neutral-600;
  @apply transition-colors text-sm font-medium;
}

.btn-icon {
  @apply p-1.5 rounded-md;
  @apply text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
}
</style>
