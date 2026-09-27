<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ImportReportEntry, ImportReportRole } from '@/lib/importReportDiagnostics'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  title: string
  entries: readonly ImportReportEntry[]
  ariaLabel: string
}>()

const showExpertReports = ref(false)
const normalEntries = computed(() => props.entries.filter((entry) => !entry.expertOnly))
const expertEntries = computed(() => props.entries.filter((entry) => entry.expertOnly))
const visibleEntries = computed(() =>
  showExpertReports.value ? [...normalEntries.value, ...expertEntries.value] : normalEntries.value
)

const roleLabelKeys: Record<ImportReportRole, string> = {
  build: 'corpus.reportList.roleBuild',
  quality: 'corpus.reportList.roleQuality',
  manifest: 'corpus.reportList.roleManifest',
  metadata: 'corpus.reportList.roleMetadata',
  debug: 'corpus.reportList.roleDebug',
  unknown: 'corpus.reportList.roleUnknown',
}

function roleLabel(role: ImportReportRole): string {
  const key = roleLabelKeys[role]
  return key ? t(key) : role
}
</script>

<template>
  <div v-if="entries.length" class="report-list" :aria-label="ariaLabel">
    <h5>{{ title }}</h5>
    <p v-if="!normalEntries.length" class="report-empty">
      {{ t('corpus.reportList.noNormalized') }}
    </p>
    <article
      v-for="report in visibleEntries"
      :key="report.key"
      class="report-card"
      :class="{
        'report-card--expert': report.expertOnly,
        'report-card--unknown': !report.known,
      }"
    >
      <div class="report-heading">
        <strong>{{ report.label }}</strong>
        <span class="report-role" :class="`report-role--${report.role}`">{{ roleLabel(report.role) }}</span>
        <span v-if="report.expertOnly" class="report-role report-role--expert">{{ t('corpus.reportList.expert') }}</span>
      </div>
      <span>{{ report.summary }}</span>
      <p v-if="report.expertOnly" class="report-note">
        {{ t('corpus.reportList.expertNote') }}
      </p>
      <div v-if="report.diagnostics.length" class="report-diagnostics" :aria-label="t('corpus.reportList.diagnosticsAria')">
        <div
          v-for="diagnostic in report.diagnostics"
          :key="diagnostic.key"
          class="report-diagnostic"
          :class="`report-diagnostic--${diagnostic.severity}`"
        >
          <strong>{{ diagnostic.label }}</strong>
          <span v-if="diagnostic.value">{{ diagnostic.value }}</span>
          <small v-if="diagnostic.note">{{ diagnostic.note }}</small>
        </div>
      </div>
      <details v-if="report.snippet" class="report-snippet">
        <summary>{{ report.expertOnly ? t('corpus.reportList.showDebugExcerpt') : t('corpus.reportList.showReportExcerpt') }}</summary>
        <pre>{{ report.snippet }}</pre>
      </details>
      <details v-if="report.fullText" class="report-full">
        <summary>{{ t('corpus.reportList.showFullReport') }}</summary>
        <p>{{ t('corpus.reportList.fullReportNote') }}</p>
        <pre>{{ report.fullText }}</pre>
      </details>
    </article>
    <button
      v-if="expertEntries.length"
      type="button"
      class="debug-toggle"
      @click="showExpertReports = !showExpertReports"
    >
      {{ showExpertReports ? t('corpus.reportList.hideDebugReports') : t('corpus.reportList.showDebugReports', { count: expertEntries.length }) }}
    </button>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.report-list { @apply mt-4 space-y-2 rounded-lg border border-neutral-200 bg-white p-3 dark:border-neutral-700 dark:bg-neutral-900/60; }
.report-list h5 { @apply text-xs font-semibold uppercase tracking-wider text-neutral-500 dark:text-neutral-400; }
.report-empty { @apply text-xs text-neutral-500 dark:text-neutral-400; }
.report-card { @apply rounded-lg border border-neutral-100 bg-neutral-50 p-3 text-xs dark:border-neutral-800 dark:bg-neutral-950/40; }
.report-card--expert { @apply border-warning-200 bg-warning-50/70 dark:border-warning-900/50 dark:bg-warning-900/10; }
.report-card--unknown { @apply border-dashed; }
.report-heading { @apply flex flex-wrap items-center gap-1.5; }
.report-card strong { @apply block text-neutral-800 dark:text-neutral-100; }
.report-card span { @apply mt-1 block text-neutral-500 dark:text-neutral-400; }
.report-role { @apply mt-0 rounded-full border border-neutral-200 bg-white px-1.5 py-0.5 text-[0.58rem] font-semibold uppercase tracking-wide text-neutral-600 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-300; }
.report-role--quality,
.report-role--expert { @apply border-warning-200 bg-warning-100 text-warning-800 dark:border-warning-900/50 dark:bg-warning-900/30 dark:text-warning-200; }
.report-role--debug,
.report-role--unknown { @apply border-neutral-300 bg-neutral-100 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-200; }
.report-role--manifest,
.report-role--metadata { @apply border-primary-100 bg-primary-50 text-primary-800 dark:border-primary-900/40 dark:bg-primary-900/20 dark:text-primary-200; }
.report-note { @apply mt-2 text-[0.68rem] leading-relaxed text-warning-800 dark:text-warning-200; }
.report-diagnostics { @apply mt-3 grid grid-cols-1 gap-2 md:grid-cols-2; }
.report-diagnostic { @apply rounded-md border px-2 py-1.5; }
.report-diagnostic strong { @apply text-[0.68rem] font-semibold; }
.report-diagnostic span { @apply mt-0.5 text-[0.72rem]; }
.report-diagnostic small { @apply mt-1 block text-[0.65rem] leading-relaxed; }
.report-diagnostic--success { @apply border-success-100 bg-success-50 text-success-800 dark:border-success-900/40 dark:bg-success-900/20 dark:text-success-200; }
.report-diagnostic--info { @apply border-neutral-200 bg-white text-neutral-700 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200; }
.report-diagnostic--warning { @apply border-warning-100 bg-warning-50 text-warning-800 dark:border-warning-900/40 dark:bg-warning-900/20 dark:text-warning-200; }
.report-diagnostic--error { @apply border-error-100 bg-error-50 text-error-800 dark:border-error-900/40 dark:bg-error-900/20 dark:text-error-200; }
/* The closed disclosure has the surface of the card, only the report text
   itself is set as a dark code block. A closed dark details element showed
   up as a black bar in the light theme. */
.report-snippet,
.report-full { @apply mt-2 rounded border border-neutral-200 bg-white px-2 py-1.5 text-[0.7rem] leading-relaxed text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200; }
.report-snippet summary,
.report-full summary { @apply cursor-pointer text-neutral-700 dark:text-neutral-200; }
.report-full p { @apply mt-2 text-[0.66rem] leading-relaxed text-neutral-500 dark:text-neutral-400; }
.report-snippet pre,
.report-full pre { @apply mt-2 overflow-auto whitespace-pre-wrap rounded bg-neutral-950 p-2 text-neutral-100; }
.report-snippet pre { @apply max-h-44; }
.report-full pre { @apply max-h-96; }
.debug-toggle { @apply rounded-lg border border-warning-200 px-2 py-1 text-[0.68rem] font-medium text-warning-800 hover:bg-warning-50 dark:border-warning-900/50 dark:text-warning-200 dark:hover:bg-warning-900/20; }
</style>
