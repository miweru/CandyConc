<script setup lang="ts">
/**
 * HeaderActions - Header action buttons (Export, Bookmarks, Settings, Theme)
 */
import { computed, onMounted, watch, defineAsyncComponent } from 'vue'
import { Download, Bookmark, Settings, Sun, Moon, HelpCircle, Layers, Save, Database, BookOpen, Keyboard } from 'lucide-vue-next'
import { getHelpStatus } from '@/api/client'
import { useUiStore } from '@/stores/ui'
import { useBookmarksStore } from '@/stores/bookmarks'
import { useExportStore, type ExportFormat } from '@/stores/export'
import { useCorpusImportsStore } from '@/stores/corpusImports'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import Dropdown from '@/components/ui/Dropdown.vue'
import DropdownItem from '@/components/ui/DropdownItem.vue'
import AuthSessionPanel from '@/components/auth/AuthSessionPanel.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// Lazy load panels (only shown on demand)
const SettingsPanel = defineAsyncComponent({
  loader: () => import('@/components/settings/SettingsPanel.vue'),
  delay: 100
})

const ExportDialog = defineAsyncComponent({
  loader: () => import('@/components/export/ExportDialog.vue'),
  delay: 100
})

const BookmarksPanel = defineAsyncComponent({
  loader: () => import('@/components/bookmarks/BookmarksPanel.vue'),
  delay: 100
})

const WorkspaceManager = defineAsyncComponent({
  loader: () => import('@/components/workspace/WorkspaceManager.vue'),
  delay: 100
})

const uiStore = useUiStore()
const bookmarksStore = useBookmarksStore()
const exportStore = useExportStore()
const corpusImports = useCorpusImportsStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()

const exportAvailability = computed(() => productCapabilities.surfaceAvailability('research.replay_export', corpusCapabilities.activeSummary))
const bookmarksAvailability = computed(() => productCapabilities.surfaceAvailability('research.bookmarks', corpusCapabilities.activeSummary))
const subcorporaAvailability = computed(() => productCapabilities.surfaceAvailability('research.subcorpora_docsets', corpusCapabilities.activeSummary))
const analysisLibraryAvailability = computed(() => {
  const presets = productCapabilities.surfaceAvailability('research.analysis_presets', corpusCapabilities.activeSummary)
  const jobs = productCapabilities.surfaceAvailability('analysis.async_jobs', corpusCapabilities.activeSummary)
  if (presets.enabled) return presets
  if (jobs.enabled) return jobs
  return presets.visible ? presets : jobs
})
const exportFormatAvailabilities = computed(() => ({
  pdf: exportStore.exportFormatAvailability('pdf'),
  docx: exportStore.exportFormatAvailability('docx'),
  csv: exportStore.exportFormatAvailability('csv', 'all-server'),
}))
const corpusManagerAvailabilities = computed(() => [
  productCapabilities.surfaceAvailability('corpus.import', corpusCapabilities.activeSummary),
  productCapabilities.surfaceAvailability('corpus.catalogue', corpusCapabilities.activeSummary),
])
const corpusManagerEnabled = computed(() =>
  corpusManagerAvailabilities.value.some((availability) => availability.enabled)
)
const importMonitorItems = computed(() => corpusImports.recentJobs)
const runningImportJobs = computed(() =>
  importMonitorItems.value.filter((item) => ['queued', 'running'].includes(String(item.status).toLowerCase()))
)
const failedImportJobs = computed(() =>
  importMonitorItems.value.filter((item) => ['failed', 'error'].includes(String(item.status).toLowerCase()))
)
const staleImportJobs = computed(() =>
  importMonitorItems.value.filter((item) => String(item.status).toLowerCase() === 'stale')
)
const importJobBadgeText = computed(() => {
  if (runningImportJobs.value.length) return t('layout.headerActions.jobsRunning', { count: runningImportJobs.value.length })
  if (failedImportJobs.value.length) return t('layout.headerActions.jobsFailed', { count: failedImportJobs.value.length }, failedImportJobs.value.length)
  if (staleImportJobs.value.length) return t('layout.headerActions.jobsStale', { count: staleImportJobs.value.length })
  return null
})
const corpusManagerTitle = computed(() => {
  if (!corpusManagerEnabled.value) {
    return corpusManagerAvailabilities.value.find((availability) => availability.disabledReason)?.disabledReason ?? t('layout.headerActions.manageCorpora')
  }
  if (importJobBadgeText.value) return t('layout.headerActions.manageCorporaJobs', { status: importJobBadgeText.value })
  return t('layout.headerActions.manageCorpora')
})
const canExport = computed(() => exportAvailability.value.visible)
const canUseSubcorpora = computed(() => subcorporaAvailability.value.visible)
const canUseAnalysisPresets = computed(() => analysisLibraryAvailability.value.visible)
const canUseBookmarks = computed(() => bookmarksAvailability.value.visible)
const canOpenCorpusManager = computed(() =>
  corpusManagerAvailabilities.value.some((availability) => availability.visible)
)
const canOpenWorkspace = computed(() => canUseSubcorpora.value || canUseAnalysisPresets.value)
const canOpenProductSettings = computed(() =>
  productCapabilities.hasContract ||
  productCapabilities.status === 'loading' ||
  productCapabilities.status === 'error' ||
  productCapabilities.isVisible('settings.embedding_management') ||
  productCapabilities.isVisible('settings.preferences')
)
function warnDisabled(reason: string | null | undefined) {
  if (reason) uiStore.showToast(reason, 'warning')
}

function openSurfaceOrWarn(id: string) {
  const availability = productCapabilities.surfaceAvailability(id, corpusCapabilities.activeSummary)
  if (!availability.enabled) {
    warnDisabled(availability.disabledReason)
    return
  }
  void productCapabilities.openSurface(id, corpusCapabilities.activeSummary)
}

// The header button lists the saved subcorpora. The filter that builds a
// scope has its own button next to the search bar, so the saved subcorpora
// do not have to be reached via "Analyses".
function openSavedSubcorpora() {
  if (!subcorporaAvailability.value.enabled) {
    warnDisabled(subcorporaAvailability.value.disabledReason)
    return
  }
  uiStore.openWorkspace('subcorpora')
}

/**
 * Help menu: the bundled manual (/docs/, served by the backend when the
 * package holds it) and the keyboard shortcuts. Nothing is fetched from the
 * network.
 */
async function openDocumentation() {
  let url: string | null = null
  try {
    const status = await getHelpStatus()
    url = status.docsAvailable ? status.docsUrl : null
  } catch {
    url = null
  }
  if (!url) {
    uiStore.showToast(t('layout.headerActions.docsMissing'), 'info', 8000)
    return
  }
  window.open(url, '_blank', 'noopener')
}

function openFirstSurfaceOrWarn(ids: string[]) {
  const decisions = ids
    .map((id) => ({
      id,
      availability: productCapabilities.surfaceAvailability(id, corpusCapabilities.activeSummary),
    }))
    .filter((item) => item.availability.visible)
  const enabled = decisions.find((item) => item.availability.enabled)
  if (enabled) {
    void productCapabilities.openSurface(enabled.id, corpusCapabilities.activeSummary)
    return
  }
  warnDisabled(decisions[0]?.availability.disabledReason)
}

function handleExport(format: ExportFormat) {
  if (!exportAvailability.value.enabled) {
    warnDisabled(exportAvailability.value.disabledReason ?? t('layout.headerActions.exportNotEnabled'))
    return
  }
  const formatAvailability =
    format === 'pdf' || format === 'docx' || format === 'csv'
      ? exportFormatAvailabilities.value[format]
      : exportStore.exportFormatAvailability(format)
  if (!formatAvailability.enabled) {
    warnDisabled(formatAvailability.disabledReason ?? t('layout.headerActions.formatNotEnabled'))
    return
  }
  exportStore.setPreselectedFormat(format)
  uiStore.openExport()
}

onMounted(() => {
  if (canUseBookmarks.value) bookmarksStore.init()
  void productCapabilities.ensureAccessContext().then(() => {
    if (corpusImports.canListJobs) {
      void corpusImports.loadJobs()
    }
  })
})

watch(canUseBookmarks, (visible) => {
  if (visible) bookmarksStore.init()
})

watch(
  () => corpusImports.canListJobs,
  (visible) => {
    if (visible) void corpusImports.loadJobs()
  },
)
</script>

<template>
  <div class="header-actions">
    <!-- Export Dropdown -->
    <Dropdown v-if="canExport && exportAvailability.enabled" align="right">
      <template #trigger="{ triggerProps }">
        <button
          type="button"
          class="action-btn"
          :title="t('layout.headerActions.export')"
          :aria-label="t('layout.headerActions.export')"
          data-onboarding="export"
          v-bind="triggerProps"
        >
          <Download class="w-5 h-5" />
        </button>
      </template>
      <DropdownItem
        :disabled="!exportFormatAvailabilities.pdf.enabled"
        :title="exportFormatAvailabilities.pdf.disabledReason ?? t('layout.headerActions.exportPdf')"
        @click="handleExport('pdf')"
      >
        {{ t('layout.headerActions.exportPdf') }}
      </DropdownItem>
      <DropdownItem
        :disabled="!exportFormatAvailabilities.docx.enabled"
        :title="exportFormatAvailabilities.docx.disabledReason ?? t('layout.headerActions.exportWord')"
        @click="handleExport('docx')"
      >
        {{ t('layout.headerActions.exportWord') }}
      </DropdownItem>
      <DropdownItem
        :disabled="!exportFormatAvailabilities.csv.enabled"
        :title="exportFormatAvailabilities.csv.disabledReason ?? t('layout.headerActions.exportCsv')"
        @click="handleExport('csv')"
      >
        {{ t('layout.headerActions.exportCsv') }}
      </DropdownItem>
    </Dropdown>
    <button
      v-else-if="canExport"
      type="button"
      class="action-btn is-disabled"
      :title="exportAvailability.disabledReason ?? t('layout.headerActions.exportUnavailable')"
      :aria-label="exportAvailability.disabledReason ?? t('layout.headerActions.exportUnavailable')"
      aria-disabled="true"
      data-onboarding="export"
      @click="warnDisabled(exportAvailability.disabledReason)"
    >
      <Download class="w-5 h-5" />
    </button>

    <!-- Bookmarks -->
    <button
      v-if="canUseBookmarks"
      type="button"
      class="action-btn"
      :class="{ 'has-items': bookmarksStore.hasBookmarks, 'is-disabled': !bookmarksAvailability.enabled }"
      :title="bookmarksAvailability.disabledReason ?? t('layout.headerActions.bookmarks')"
      :aria-label="bookmarksAvailability.disabledReason ?? t('layout.headerActions.bookmarks')"
      :aria-disabled="!bookmarksAvailability.enabled"
      @click="openSurfaceOrWarn('research.bookmarks')"
    >
      <Bookmark class="w-5 h-5" />
    </button>

    <!-- Subcorpus Manager -->
    <button
      v-if="canUseSubcorpora"
      type="button"
      class="action-btn"
      :class="{ 'is-disabled': !subcorporaAvailability.enabled }"
      :title="subcorporaAvailability.disabledReason ?? t('layout.headerActions.subcorpora')"
      :aria-label="subcorporaAvailability.disabledReason ?? t('layout.headerActions.subcorpora')"
      :aria-disabled="!subcorporaAvailability.enabled"
      @click="openSavedSubcorpora"
    >
      <Layers class="w-5 h-5" />
    </button>

    <!-- Analysis Library -->
    <button
      v-if="canUseAnalysisPresets"
      type="button"
      class="action-btn"
      :class="{ 'is-disabled': !analysisLibraryAvailability.enabled }"
      :title="analysisLibraryAvailability.disabledReason ?? t('layout.headerActions.analyses')"
      :aria-label="analysisLibraryAvailability.disabledReason ?? t('layout.headerActions.analyses')"
      :aria-disabled="!analysisLibraryAvailability.enabled"
      @click="openFirstSurfaceOrWarn(['research.analysis_presets', 'analysis.async_jobs'])"
    >
      <Save class="w-5 h-5" />
    </button>

    <!-- Corpus Manager -->
    <button
      v-if="canOpenCorpusManager"
      type="button"
      class="action-btn"
      :class="{ 'has-items': importJobBadgeText, 'has-error': failedImportJobs.length, 'is-disabled': !corpusManagerEnabled }"
      :title="corpusManagerTitle"
      :aria-label="corpusManagerTitle"
      :aria-disabled="!corpusManagerEnabled"
      @click="openFirstSurfaceOrWarn(['corpus.import', 'corpus.catalogue'])"
    >
      <Database class="w-5 h-5" />
      <span v-if="importJobBadgeText" class="job-badge">{{ importJobBadgeText }}</span>
    </button>

    <!-- Settings -->
    <button
      v-if="canOpenProductSettings"
      type="button"
      class="action-btn"
      :title="t('layout.headerActions.settings')"
      :aria-label="t('layout.headerActions.settings')"
      @click="uiStore.openSettings()"
    >
      <Settings class="w-5 h-5" />
    </button>

    <!-- Session / Auth -->
    <AuthSessionPanel />

    <!-- Theme Toggle -->
    <button
      type="button"
      class="action-btn"
      :title="uiStore.isDarkMode ? t('layout.headerActions.lightTheme') : t('layout.headerActions.darkTheme')"
      :aria-label="uiStore.isDarkMode ? t('layout.headerActions.lightTheme') : t('layout.headerActions.darkTheme')"
      @click="uiStore.toggleTheme()"
    >
      <Sun v-if="uiStore.isDarkMode" class="w-5 h-5" />
      <Moon v-else class="w-5 h-5" />
    </button>

    <!-- Help -->
    <Dropdown align="right">
      <template #trigger="{ triggerProps }">
        <button
          type="button"
          class="action-btn"
          :title="t('layout.headerActions.helpTitle')"
          :aria-label="t('layout.headerActions.help')"
          data-testid="help-menu"
          v-bind="triggerProps"
        >
          <HelpCircle class="w-5 h-5" />
        </button>
      </template>
      <DropdownItem :icon="BookOpen" data-testid="help-documentation" @click="openDocumentation">
        {{ t('layout.headerActions.documentation') }}
      </DropdownItem>
      <DropdownItem :icon="Keyboard" data-testid="help-shortcuts" @click="uiStore.openShortcuts()">
        {{ t('layout.headerActions.shortcuts') }}
      </DropdownItem>
    </Dropdown>

    <!-- Panels -->
    <SettingsPanel v-if="(canOpenProductSettings || canOpenCorpusManager) && uiStore.settingsOpen" v-model="uiStore.settingsOpen" />
    <ExportDialog v-if="canExport && uiStore.exportOpen" v-model="uiStore.exportOpen" />
    <BookmarksPanel v-if="canUseBookmarks && uiStore.bookmarksOpen" v-model="uiStore.bookmarksOpen" />
    <WorkspaceManager v-if="canOpenWorkspace && uiStore.workspaceOpen" />
  </div>
</template>

<style scoped>
@reference "../../style.css";

.header-actions {
  /* Wrap + shrink so the icon row never forces a page-level horizontal scroll
     at 375px (DESIGN-A11Y-01 / KWIC-PLAIN-03). */
  @apply flex flex-wrap items-center justify-end gap-1 min-w-0;
}

.action-btn {
  @apply relative p-2 rounded-lg;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply hover:text-neutral-900 dark:hover:text-neutral-100;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors duration-150;
}

.action-btn.has-items {
  @apply text-primary-600 dark:text-primary-400;
}

.action-btn.has-error {
  @apply text-error-600 dark:text-error-400;
}

.action-btn.is-disabled {
  @apply opacity-50 cursor-not-allowed;
}

.job-badge {
  @apply absolute -right-2 -top-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold leading-none;
  @apply bg-primary-600 text-white shadow-sm;
}

.has-error .job-badge {
  @apply bg-error-600;
}
</style>
