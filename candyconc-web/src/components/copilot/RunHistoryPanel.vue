<script setup lang="ts">
/**
 * RunHistoryPanel - View and export analysis run history
 *
 * Shows run records with filtering (including per-project), annotations,
 * and export options.
 */
import { ref, computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  History, FileJson, FileSpreadsheet, Trash2,
  Filter, Search, StickyNote, FolderOpen, Plus, X,
  ChevronDown, ChevronRight, Beaker, Database
} from 'lucide-vue-next'
import {
  filterRuns,
  downloadRunsJson,
  downloadRunsCsv,
  downloadProject,
  deleteRunRecord,
  addRunNote,
  getAllProjects,
  createProject,
  addRunToProject,
  type RunFilter,
} from '@/services/runRecordService'
import type { RunRecordV1 } from '@/types/copilot-protocol'
import { formatDateTime, formatNumber } from '@/i18n/format'

const { t } = useI18n()
const kindFilterId = useId()
const notesFilterId = useId()

const filter = ref<RunFilter>({})
const searchQuery = ref('')
const selectedRuns = ref<Set<string>>(new Set())
const expandedRuns = ref<Set<string>>(new Set())
const showFilters = ref(false)
const showProjects = ref(false)
const newProjectName = ref('')
const newNoteText = ref('')
const editingNoteRunId = ref<string | null>(null)

const filteredRuns = computed(() => {
  return filterRuns({
    ...filter.value,
    search: searchQuery.value || undefined,
  })
})

const projects = computed(() => getAllProjects())

const hasSelection = computed(() => selectedRuns.value.size > 0)

const selectedRunsList = computed(() =>
  filteredRuns.value.filter(r => selectedRuns.value.has(r.runId))
)

function formatTimestamp(ts: number): string {
  const date = new Date(ts)
  return formatDateTime(date, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getKindIcon(kind: string) {
  return kind === 'query' ? Database : Beaker
}

function formatScopeLabel(run: RunRecordV1): string {
  const scope = run.evidence.researchScope
  if (scope?.label) return scope.label
  if (scope?.subcorpusName) return scope.subcorpusName
  if (scope?.docsetId) return t('copilot.runHistory.scopeSubcorpusId', { id: scope.docsetId })
  if (scope?.scopeStatus === 'corpus' || !run.corpus.subcorpusHash) return t('copilot.runHistory.scopeWholeCorpus')
  return t('copilot.runHistory.scopeSubcorpus')
}

function toggleSelection(runId: string) {
  if (selectedRuns.value.has(runId)) {
    selectedRuns.value.delete(runId)
  } else {
    selectedRuns.value.add(runId)
  }
  // Trigger reactivity
  selectedRuns.value = new Set(selectedRuns.value)
}

function selectAll() {
  selectedRuns.value = new Set(filteredRuns.value.map(r => r.runId))
}

function clearSelection() {
  selectedRuns.value = new Set()
}

function toggleExpanded(runId: string) {
  if (expandedRuns.value.has(runId)) {
    expandedRuns.value.delete(runId)
  } else {
    expandedRuns.value.add(runId)
  }
  expandedRuns.value = new Set(expandedRuns.value)
}

function handleExportJson() {
  if (hasSelection.value) {
    downloadRunsJson(selectedRunsList.value)
  } else {
    downloadRunsJson()
  }
}

function handleExportCsv() {
  if (hasSelection.value) {
    downloadRunsCsv(selectedRunsList.value)
  } else {
    downloadRunsCsv()
  }
}

function handleDelete(runId: string) {
  deleteRunRecord(runId)
  selectedRuns.value.delete(runId)
  selectedRuns.value = new Set(selectedRuns.value)
}

function handleDeleteSelected() {
  for (const runId of selectedRuns.value) {
    deleteRunRecord(runId)
  }
  clearSelection()
}

function handleAddNote(runId: string) {
  if (newNoteText.value.trim()) {
    addRunNote(runId, newNoteText.value.trim())
    newNoteText.value = ''
    editingNoteRunId.value = null
  }
}

function startAddNote(runId: string) {
  editingNoteRunId.value = runId
  newNoteText.value = ''
}

function cancelAddNote() {
  editingNoteRunId.value = null
  newNoteText.value = ''
}

function handleCreateProject() {
  if (newProjectName.value.trim()) {
    createProject(newProjectName.value.trim())
    newProjectName.value = ''
  }
}

function handleAddToProject(projectId: string) {
  for (const runId of selectedRuns.value) {
    addRunToProject(projectId, runId)
  }
}

function handleExportProject() {
  if (filter.value.projectId) {
    downloadProject(filter.value.projectId)
  }
}

function clearFilters() {
  filter.value = {}
  searchQuery.value = ''
}

</script>

<template>
  <div class="run-history-panel">
    <!-- Header -->
    <header class="panel-header">
      <div class="flex items-center gap-2">
        <History class="w-5 h-5 text-copilot-primary" />
        <h2 class="font-semibold">{{ t('copilot.runHistory.title') }}</h2>
      </div>
    </header>

    <!-- Toolbar -->
    <div class="toolbar">
      <!-- Search -->
      <div class="search-wrapper">
        <Search class="w-4 h-4 text-neutral-400" />
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('copilot.runHistory.searchPlaceholder')"
          class="search-input"
        />
      </div>

      <!-- Filter and project toggles. The groups wrap below the search in a narrow panel. -->
      <div class="toolbar-group">
        <button class="toolbar-btn" @click="showFilters = !showFilters">
          <Filter class="w-4 h-4" />
          {{ t('copilot.runHistory.filter') }}
        </button>
        <button class="toolbar-btn" @click="showProjects = !showProjects">
          <FolderOpen class="w-4 h-4" />
          {{ t('copilot.runHistory.projects') }}
        </button>
      </div>

      <!-- Export Buttons -->
      <div class="toolbar-group toolbar-exports">
        <button class="toolbar-btn" @click="handleExportJson" :title="hasSelection ? t('copilot.runHistory.exportSelection') : t('copilot.runHistory.exportAll')">
          <FileJson class="w-4 h-4" />
          JSON
        </button>
        <button class="toolbar-btn" @click="handleExportCsv" :title="hasSelection ? t('copilot.runHistory.exportSelection') : t('copilot.runHistory.exportAll')">
          <FileSpreadsheet class="w-4 h-4" />
          CSV
        </button>
      </div>
    </div>

    <!-- Filter Panel -->
    <div v-if="showFilters" class="filter-panel">
      <div class="filter-row">
        <label class="filter-label" :for="kindFilterId">{{ t('copilot.runHistory.kind') }}</label>
        <select :id="kindFilterId" v-model="filter.kind" class="filter-select">
          <option :value="undefined">{{ t('copilot.runHistory.all') }}</option>
          <option value="query">{{ t('copilot.runHistory.kindQuery') }}</option>
          <option value="analysis">{{ t('copilot.runHistory.kindAnalysis') }}</option>
        </select>
      </div>
      <div class="filter-row">
        <label class="filter-label" :for="notesFilterId">{{ t('copilot.runHistory.withNotes') }}</label>
        <select :id="notesFilterId" v-model="filter.hasNotes" class="filter-select">
          <option :value="undefined">{{ t('copilot.runHistory.any') }}</option>
          <option :value="true">{{ t('copilot.runHistory.yes') }}</option>
          <option :value="false">{{ t('copilot.runHistory.no') }}</option>
        </select>
      </div>
      <div class="filter-row">
        <label class="filter-label" for="run-project-filter">{{ t('copilot.runHistory.project') }}</label>
        <select id="run-project-filter" v-model="filter.projectId" class="filter-select project-filter-select">
          <option :value="undefined">{{ t('copilot.runHistory.all') }}</option>
          <option v-for="project in projects" :key="project.id" :value="project.id">
            {{ project.name }} ({{ project.runIds.length }})
          </option>
        </select>
        <button
          v-if="filter.projectId"
          class="project-export-btn"
          @click="handleExportProject"
        >
          <FileJson class="w-3 h-3" />
          {{ t('copilot.runHistory.exportProject') }}
        </button>
      </div>
      <button class="filter-clear" @click="clearFilters">
        <X class="w-3 h-3" />
        {{ t('copilot.runHistory.resetFilters') }}
      </button>
    </div>

    <!-- Projects Panel -->
    <div v-if="showProjects" class="projects-panel">
      <div class="projects-header">
        <span class="text-xs font-medium uppercase text-neutral-500">{{ t('copilot.runHistory.projects') }}</span>
        <div class="new-project-form">
          <input
            v-model="newProjectName"
            type="text"
            :placeholder="t('copilot.runHistory.newProject')"
            class="new-project-input"
            @keyup.enter="handleCreateProject"
          />
          <button class="new-project-btn" @click="handleCreateProject" :disabled="!newProjectName.trim()">
            <Plus class="w-3 h-3" />
          </button>
        </div>
      </div>
      <div v-if="projects.length === 0" class="text-xs text-neutral-400 py-2">
        {{ t('copilot.runHistory.noProjects') }}
      </div>
      <div v-else class="projects-list">
        <button
          v-for="project in projects"
          :key="project.id"
          class="project-item"
          @click="handleAddToProject(project.id)"
          :disabled="!hasSelection"
        >
          <FolderOpen class="w-4 h-4" />
          <span>{{ project.name }}</span>
          <span class="project-count">{{ project.runIds.length }}</span>
        </button>
      </div>
    </div>

    <!-- Selection Actions -->
    <div v-if="hasSelection" class="selection-bar">
      <span class="selection-count">{{ t('copilot.runHistory.selected', { count: selectedRuns.size }) }}</span>
      <button class="selection-btn" @click="selectAll">{{ t('copilot.runHistory.all') }}</button>
      <button class="selection-btn" @click="clearSelection">{{ t('copilot.runHistory.none') }}</button>
      <div class="flex-1" />
      <button class="selection-btn danger" @click="handleDeleteSelected">
        <Trash2 class="w-3 h-3" />
        {{ t('copilot.runHistory.delete') }}
      </button>
    </div>

    <!-- Run List -->
    <div class="run-list">
      <div v-if="filteredRuns.length === 0" class="empty-state">
        <History class="w-8 h-8 text-neutral-300" />
        <p>{{ t('copilot.runHistory.empty') }}</p>
      </div>

      <div
        v-for="run in filteredRuns"
        :key="run.runId"
        class="run-item"
        :class="{ selected: selectedRuns.has(run.runId), expanded: expandedRuns.has(run.runId) }"
      >
        <!-- Run Header -->
        <div class="run-header" @click="toggleExpanded(run.runId)">
          <input
            type="checkbox"
            :checked="selectedRuns.has(run.runId)"
            @click.stop="toggleSelection(run.runId)"
            class="run-checkbox"
          />

          <button class="expand-btn" @click.stop="toggleExpanded(run.runId)">
            <ChevronRight v-if="!expandedRuns.has(run.runId)" class="w-4 h-4" />
            <ChevronDown v-else class="w-4 h-4" />
          </button>

          <component :is="getKindIcon(run.kind)" class="w-4 h-4 text-neutral-400" />

          <div class="run-info">
            <span class="run-summary">{{ run.summary }}</span>
          </div>

          <span class="run-time">{{ formatTimestamp(run.ts) }}</span>

          <span v-if="run.notes?.length" class="run-notes-badge" :title="t('copilot.runHistory.notesCount', { count: run.notes.length }, run.notes.length)">
            <StickyNote class="w-3 h-3" />
            {{ run.notes.length }}
          </span>
        </div>

        <!-- Run Details (expanded) -->
        <div v-if="expandedRuns.has(run.runId)" class="run-details">
          <div class="detail-grid">
            <div class="detail-item">
              <span class="detail-label">{{ t('copilot.runHistory.corpus') }}</span>
              <code class="detail-value">{{ run.corpus.corpusId }}</code>
            </div>
            <div class="detail-item">
              <span class="detail-label">{{ t('copilot.runHistory.scope') }}</span>
              <span class="detail-value">{{ formatScopeLabel(run) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">{{ t('copilot.runHistory.result') }}</span>
              <code class="detail-value">
                <span v-if="run.resultRef.rows">{{ t('copilot.runHistory.rows', { count: formatNumber(run.resultRef.rows) }, run.resultRef.rows) }}</span>
                <span v-else>{{ t('copilot.runHistory.saved') }}</span>
              </code>
            </div>
          </div>

          <!-- Notes -->
          <div class="detail-section">
            <span class="detail-label">{{ t('copilot.runHistory.notes') }}</span>
            <ul v-if="run.notes?.length" class="notes-list">
              <li v-for="(note, idx) in run.notes" :key="idx">{{ note }}</li>
            </ul>
            <p v-else class="text-xs text-neutral-400 italic">{{ t('copilot.runHistory.noNotes') }}</p>

            <!-- Add Note -->
            <div v-if="editingNoteRunId === run.runId" class="add-note-form">
              <input
                v-model="newNoteText"
                type="text"
                :placeholder="t('copilot.runHistory.addNotePlaceholder')"
                class="note-input"
                @keyup.enter="handleAddNote(run.runId)"
                @keyup.escape="cancelAddNote"
              />
              <button class="note-btn" @click="handleAddNote(run.runId)">
                <Plus class="w-3 h-3" />
              </button>
              <button class="note-btn cancel" @click="cancelAddNote">
                <X class="w-3 h-3" />
              </button>
            </div>
            <button v-else class="add-note-btn" @click="startAddNote(run.runId)">
              <Plus class="w-3 h-3" />
              {{ t('copilot.runHistory.addNote') }}
            </button>
          </div>

          <!-- Actions -->
          <div class="detail-actions">
            <button class="action-btn danger" @click="handleDelete(run.runId)">
              <Trash2 class="w-3 h-3" />
              {{ t('copilot.runHistory.delete') }}
            </button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
@reference "../../style.css";

.run-history-panel {
  @apply flex flex-col h-full;
  @apply bg-white dark:bg-neutral-900;
}

.panel-header {
  @apply flex items-center justify-between px-4 py-3;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.toolbar {
  @apply flex flex-wrap items-center gap-2 px-4 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
}

.toolbar-group {
  @apply flex items-center gap-2;
}

.toolbar-exports {
  @apply ml-auto;
}

.search-wrapper {
  @apply flex items-center gap-2 px-3 py-1.5 min-w-0;
  @apply bg-white dark:bg-neutral-800 rounded-lg;
  @apply border border-neutral-200 dark:border-neutral-700;
  flex: 1 1 9rem;
}

.search-input {
  @apply bg-transparent border-none outline-none text-sm min-w-0 w-full;
  @apply text-neutral-800 dark:text-neutral-200;
  @apply placeholder:text-neutral-400;
}

.toolbar-btn {
  @apply flex items-center gap-1.5 px-2.5 py-1.5;
  @apply text-xs font-medium rounded-md;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.filter-panel, .projects-panel {
  @apply px-4 py-3;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.filter-row {
  @apply flex items-center gap-2 mb-2;
}

.filter-label {
  @apply text-xs text-neutral-500 w-20;
}

.filter-select {
  @apply text-xs px-2 py-1 rounded;
  @apply bg-white dark:bg-neutral-700;
  @apply border border-neutral-200 dark:border-neutral-600;
}

.project-filter-select {
  max-width: 180px;
}

.project-export-btn {
  @apply flex items-center gap-1 px-2 py-1;
  @apply text-xs rounded;
  @apply text-copilot-primary hover:bg-copilot-primary/10;
}

.filter-clear {
  @apply flex items-center gap-1 text-xs text-neutral-500;
  @apply hover:text-neutral-700 dark:hover:text-neutral-300;
}

.projects-header {
  @apply flex items-center justify-between mb-2;
}

.new-project-form {
  @apply flex items-center gap-1;
}

.new-project-input {
  @apply text-xs px-2 py-1 rounded;
  @apply bg-white dark:bg-neutral-700;
  @apply border border-neutral-200 dark:border-neutral-600;
  width: 120px;
}

.new-project-btn {
  @apply p-1 rounded text-copilot-primary;
  @apply hover:bg-copilot-primary/10;
  @apply disabled:opacity-50;
}

.projects-list {
  @apply space-y-1;
}

.project-item {
  @apply flex items-center gap-2 w-full px-2 py-1.5;
  @apply text-xs text-left rounded;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50;
}

.project-count {
  @apply ml-auto text-neutral-400;
}

.selection-bar {
  @apply flex items-center gap-2 px-4 py-2;
  @apply bg-copilot-primary/10;
  @apply border-b border-copilot-primary/20;
}

.selection-count {
  @apply text-xs font-medium text-copilot-primary;
}

.selection-btn {
  @apply flex items-center gap-1 px-2 py-1;
  @apply text-xs rounded;
  @apply text-copilot-primary hover:bg-copilot-primary/20;
}

.selection-btn.danger {
  @apply text-red-600 hover:bg-red-100 dark:hover:bg-red-900/30;
}

.run-list {
  @apply flex-1 overflow-y-auto;
}

.empty-state {
  @apply flex flex-col items-center justify-center h-full;
  @apply text-neutral-400 text-sm;
  gap: 8px;
}

.run-item {
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.run-item.selected {
  @apply bg-copilot-primary/5;
}

.run-header {
  @apply flex items-center gap-2 px-4 py-3;
  @apply cursor-pointer;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-800/50;
}

.run-checkbox {
  @apply w-4 h-4 rounded;
  @apply accent-copilot-primary;
}

.expand-btn {
  @apply p-0.5 rounded text-neutral-400;
  @apply hover:text-neutral-600 dark:hover:text-neutral-300;
}

.run-info {
  @apply flex-1 min-w-0;
}

.run-summary {
  @apply block text-sm font-medium text-neutral-800 dark:text-neutral-200;
  @apply truncate;
}

.run-time {
  @apply text-xs text-neutral-400 whitespace-nowrap;
}

.run-notes-badge {
  @apply flex items-center gap-1 px-1.5 py-0.5;
  @apply text-xs rounded-full;
  @apply bg-amber-100 dark:bg-amber-900/30;
  @apply text-amber-600 dark:text-amber-400;
}

.run-details {
  @apply px-4 pb-4 pt-2;
  @apply bg-neutral-50 dark:bg-neutral-800/30;
}

.detail-grid {
  @apply grid grid-cols-2 gap-2 mb-3;
}

.detail-item {
  @apply flex flex-col;
}

.detail-label {
  @apply text-xs font-medium text-neutral-500 uppercase tracking-wide;
}

.detail-value {
  @apply text-xs text-neutral-700 dark:text-neutral-300;
  @apply bg-neutral-200/50 dark:bg-neutral-700/50 px-1.5 py-0.5 rounded;
}

.detail-section {
  @apply mb-3;
}

.notes-list {
  @apply text-xs text-neutral-700 dark:text-neutral-300;
  @apply list-disc list-inside pl-1 space-y-1;
}

.add-note-form {
  @apply flex items-center gap-1 mt-2;
}

.note-input {
  @apply flex-1 text-xs px-2 py-1 rounded;
  @apply bg-white dark:bg-neutral-700;
  @apply border border-neutral-200 dark:border-neutral-600;
}

.note-btn {
  @apply p-1 rounded text-copilot-primary;
  @apply hover:bg-copilot-primary/10;
}

.note-btn.cancel {
  @apply text-neutral-500;
}

.add-note-btn {
  @apply flex items-center gap-1 mt-2;
  @apply text-xs text-copilot-primary;
  @apply hover:underline;
}

.detail-actions {
  @apply flex gap-2 pt-2 border-t border-neutral-200 dark:border-neutral-700;
}

.action-btn {
  @apply flex items-center gap-1 px-2 py-1;
  @apply text-xs rounded;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
}

.action-btn.danger {
  @apply text-red-600 hover:bg-red-100 dark:hover:bg-red-900/30;
}

</style>
