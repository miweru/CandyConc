<script setup lang="ts">
/**
 * CommandPalette - Universal command palette (Cmd+K)
 * Fuzzy search over all features with keyboard navigation
 * With focus trap for accessibility
 */
import { ref, computed, watch, onUnmounted, type Component } from 'vue'
import {
  Search,
  FileText,
  FileSpreadsheet,
  Moon,
  Sun,
  HelpCircle,
} from 'lucide-vue-next'
import { asSwitchTabId, useUiStore } from '@/stores/ui'
import { useExportStore, type ExportFormat } from '@/stores/export'
import {
  type ProductOperationUiRecord,
  useProductCapabilitiesStore,
} from '@/stores/productCapabilities'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { actionBus } from '@/actions'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useAnnounce } from '@/composables/useAnnounce'
import { iconComponentForSurfaceIconName } from '@/lib/productSurfaceIcons'
import {
  iconNameForCapability,
  iconNameForAnalysisTab,
  iconNameForSurface,
  openTargetForSurface,
} from '@/lib/productSurfaceRegistry'
import {
  productCapabilitySurfaces,
  type ProductCapabilitySurface,
} from '@/lib/productCapabilities'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Command {
  id: string
  category: 'nav' | 'analysis' | 'export' | 'corpus' | 'settings' | 'copilot'
  label: string
  shortcut?: string
  icon: Component
  disabledReason?: string | null
  statusNote?: string | null
  searchText?: string
  action: () => void | Promise<void>
}

interface Props {
  modelValue: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const uiStore = useUiStore()
const exportStore = useExportStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()

const searchQuery = ref('')
const selectedIndex = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)
const paletteRef = ref<HTMLElement | null>(null)

// Focus trap for accessibility
const { activate: activateTrap, deactivate: deactivateTrap } = useFocusTrap(paletteRef, {
  escapeDeactivates: true,
  onEscape: close,
  initialFocus: 'input'
})

// Screen reader announcements
const { announce } = useAnnounce()

const tabCommands = computed<Command[]>(() =>
  productCapabilities.discoverableAnalysisTabs.map((surface) => {
    const availability = productCapabilities.surfaceAvailability(
      surface.capabilityId,
      corpusCapabilities.activeSummary,
    )
    return {
      id: surface.commandId ?? `nav-${surface.tab}`,
      category: surface.primary ? 'nav' : 'analysis',
      label: surface.label,
      shortcut: surface.shortcut,
      icon: iconComponentForSurfaceIconName(iconNameForAnalysisTab(surface.tab)),
      disabledReason: availability.disabledReason,
      statusNote: availability.partialReason,
      action: async () => { await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: asSwitchTabId(surface.tab) } }) },
    }
  })
)

function categoryForSurface(record: ProductCapabilitySurface): Command['category'] {
  if (record.kind === 'search_workbench') return 'nav'
  if (record.kind === 'corpus_manager') return 'corpus'
  if (record.kind === 'settings_panel') return 'settings'
  if (record.kind === 'export_dialog') return 'export'
  if (record.kind === 'copilot_panel') return 'copilot'
  if (record.kind === 'workspace_panel' || record.kind === 'job_lifecycle') return 'analysis'
  if (record.kind === 'kwic_layer') return 'nav'
  return 'nav'
}

function categoryForOperation(record: ProductOperationUiRecord): Command['category'] {
  if (record.openTarget?.kind === 'export_dialog') return 'export'
  if (record.openTarget?.kind === 'corpus_manager') return 'corpus'
  if (record.openTarget?.kind === 'settings') return 'settings'
  if (record.openTarget?.kind === 'copilot') return 'copilot'
  if (record.openTarget?.kind === 'analysis_tab' || record.capabilityId.startsWith('analysis.')) return 'analysis'
  return 'nav'
}

function operationCommandId(operationId: string): string {
  return `operation-${operationId.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase()}`
}

function operationDisabledReason(record: ProductOperationUiRecord): string | null {
  return record.availability.disabledReason
}

function operationPrimaryActionLabel(record: ProductOperationUiRecord): string {
  const hasContextSurface = Boolean(
    record.openTarget &&
    record.adapterStatus === 'ready' &&
    record.availability.enabled,
  )
  if (record.openTarget?.kind === 'annotation_settings' && record.availability.enabled) {
    return t('layout.palette.openAnnotationSettings')
  }
  if (
    record.surfaceOpenAllowed &&
    record.genericAction === 'open_surface' &&
    hasContextSurface
  ) {
    return record.openLabel ?? t('layout.palette.openSurface')
  }
  if (hasContextSurface) return t('layout.palette.openContextSurface')
  if (!record.availability.enabled) return t('layout.palette.inspectBlock')
  return t('layout.palette.expertApi')
}

async function runOperationCommand(record: ProductOperationUiRecord): Promise<void> {
  const opened = await productCapabilities.openOperation(
    record.operationId,
    corpusCapabilities.activeSummary,
  )
  if (!opened) throw new Error(t('layout.palette.openFailed'))
}

const surfaceUtilityCommands = computed<Command[]>(() =>
  productCapabilitySurfaces
    .filter((record) => record.kind !== 'analysis_tab' && openTargetForSurface(record))
    .map((record) => {
      const availability = productCapabilities.surfaceAvailability(
        record.capabilityId,
        corpusCapabilities.activeSummary,
      )
      return {
        id: record.commandId ?? `surface-${record.capabilityId}`,
        category: categoryForSurface(record),
        label: record.commandLabel ?? t('layout.palette.openNamed', { label: record.label }),
        shortcut: record.shortcut,
        icon: iconComponentForSurfaceIconName(iconNameForSurface(record)),
        disabledReason: availability.disabledReason,
        statusNote: availability.partialReason,
        action: async () => {
          await productCapabilities.openSurface(
            record.capabilityId,
            corpusCapabilities.activeSummary,
          )
        },
        visible: availability.visible,
      }
    })
    .filter((command) => command.visible)
    .map(({ visible: _visible, ...command }) => command)
)

const operationCommands = computed<Command[]>(() =>
  productCapabilities.firstClassOperationUiRecords
    .map((record) =>
      productCapabilities.operationUiRecordFor(
        record.operationId,
        corpusCapabilities.activeSummary,
      ) ?? record
    )
    .filter((record) => record.openTarget && record.adapterStatus === 'ready')
    .map((activeRecord) => {
      const disabledReason = operationDisabledReason(activeRecord)
      return {
        id: operationCommandId(activeRecord.operationId),
        category: categoryForOperation(activeRecord),
        label: t('layout.palette.operationLabel', { action: operationPrimaryActionLabel(activeRecord), label: activeRecord.label }),
        icon: iconComponentForSurfaceIconName(iconNameForCapability(activeRecord.capabilityId)),
        disabledReason,
        statusNote: null,
        searchText: [
          activeRecord.label,
          activeRecord.description,
          activeRecord.operationId,
          activeRecord.routeLabel,
          activeRecord.effects.join(' '),
          activeRecord.adapterStatus,
          activeRecord.genericAction,
          activeRecord.executionPolicy,
          activeRecord.surfaceSlot,
          activeRecord.copilotTools.join(' '),
        ].join(' '),
        action: async () => runOperationCommand(activeRecord),
      }
    })
)

const utilityCommands = computed<Command[]>(() => {
  const commands: Command[] = [...surfaceUtilityCommands.value]

  if (productCapabilities.isVisible('research.replay_export')) {
    commands.push(
      exportFormatCommand('pdf', t('layout.palette.exportPdf'), FileText, 'Cmd+E'),
      exportFormatCommand('docx', t('layout.palette.exportWord'), FileText),
      exportFormatCommand('csv', t('layout.palette.exportCsv'), FileSpreadsheet),
    )
  }

  commands.push(
    { id: 'settings-theme-toggle', category: 'settings', label: t('layout.palette.toggleTheme'), icon: uiStore.isDarkMode ? Sun : Moon, action: () => uiStore.toggleTheme() },
    { id: 'settings-help', category: 'settings', label: t('layout.palette.helpShortcuts'), shortcut: '?', icon: HelpCircle, action: () => uiStore.openShortcuts() },
  )

  return commands
})

const baseCommands = computed<Command[]>(() => [
  ...tabCommands.value,
  ...utilityCommands.value,
  ...operationCommands.value,
])

const categoryLabels = computed<Record<string, string>>(() => ({
  nav: t('layout.palette.categoryNav'),
  analysis: t('layout.palette.categoryAnalysis'),
  export: t('layout.palette.categoryExport'),
  corpus: t('layout.palette.categoryCorpus'),
  settings: t('layout.palette.categorySettings'),
  copilot: t('layout.palette.categoryCopilot'),
}))

// Simple fuzzy search
function fuzzyMatch(query: string, text: string): boolean {
  const lowerQuery = query.toLowerCase()
  const lowerText = text.toLowerCase()

  // Direct substring match
  if (lowerText.includes(lowerQuery)) return true

  // Character-by-character fuzzy match
  let queryIndex = 0
  for (const char of lowerText) {
    if (char === lowerQuery[queryIndex]) {
      queryIndex++
      if (queryIndex === lowerQuery.length) return true
    }
  }
  return false
}

// Filtered and grouped commands
const filteredCommands = computed(() => {
  if (!searchQuery.value.trim()) {
    return baseCommands.value
  }
  return baseCommands.value.filter(cmd =>
    fuzzyMatch(searchQuery.value, `${cmd.label} ${cmd.searchText ?? ''}`)
  )
})

const groupedCommands = computed(() => {
  const groups: Record<string, Command[]> = {}

  for (const cmd of filteredCommands.value) {
    const category = cmd.category
    if (!groups[category]) {
      groups[category] = []
    }
    groups[category]!.push(cmd)
  }

  return groups
})

const flatFilteredCommands = computed(() => filteredCommands.value)

// Reset selection when search changes
watch(searchQuery, () => {
  selectedIndex.value = 0
})

function exportFormatCommand(
  format: Extract<ExportFormat, 'pdf' | 'docx' | 'csv'>,
  label: string,
  icon: Component,
  shortcut?: string,
): Command {
  const availability = exportStore.exportFormatAvailability(
    format,
    format === 'csv' ? 'all-server' : 'loaded',
  )
  return {
    id: `export-${format}`,
    category: 'export',
    label,
    shortcut,
    icon,
    disabledReason: availability.disabledReason,
    statusNote: null,
    action: () => openExport(format),
  }
}

function openExport(format: 'pdf' | 'docx' | 'csv') {
  exportStore.setPreselectedFormat(format)
  uiStore.openExport()
}

function close() {
  emit('update:modelValue', false)
  searchQuery.value = ''
  selectedIndex.value = 0
}

async function executeCommand(cmd: Command) {
  if (cmd.disabledReason) {
    uiStore.showToast(cmd.disabledReason, 'warning')
    announce(cmd.disabledReason)
    return
  }
  try {
    await cmd.action()
    close()
  } catch (error) {
    const message = error instanceof Error ? error.message : t('layout.palette.runFailed')
    uiStore.showToast(message, 'error')
    announce(message)
  }
}

function handleKeydown(e: KeyboardEvent) {
  // Note: Escape is handled by focus trap, other keys handled here
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      selectedIndex.value = Math.min(selectedIndex.value + 1, flatFilteredCommands.value.length - 1)
      break
    case 'ArrowUp':
      e.preventDefault()
      selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
      break
    case 'Enter': {
      e.preventDefault()
      const cmd = flatFilteredCommands.value[selectedIndex.value]
      if (cmd) executeCommand(cmd)
      break
    }
  }
}

// Focus input and activate trap when opened
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) {
    document.body.style.overflow = 'hidden'
    // Activate focus trap and focus input
    setTimeout(() => {
      activateTrap()
      inputRef.value?.focus()
    }, 50)
    // Announce to screen readers
    announce(t('layout.palette.announceOpen'))
  } else {
    document.body.style.overflow = ''
    deactivateTrap()
  }
})

// Announce filtered results count
watch(filteredCommands, (commands) => {
  if (props.modelValue && searchQuery.value) {
    announce(t('layout.palette.announceCount', { count: commands.length }, commands.length))
  }
}, { flush: 'post' })

onUnmounted(() => {
  deactivateTrap()
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="palette">
      <div v-if="modelValue" class="command-palette-container" @click="close">
        <div
          ref="paletteRef"
          class="command-palette"
          role="dialog"
          aria-modal="true"
          :aria-label="t('layout.palette.title')"
          @click.stop
          @keydown="handleKeydown"
        >
          <!-- Search Input -->
          <div class="search-section">
            <Search class="search-icon" aria-hidden="true" />
            <input
              ref="inputRef"
              v-model="searchQuery"
              type="text"
              class="search-input"
              :placeholder="t('layout.palette.placeholder')"
              autocomplete="off"
              spellcheck="false"
              role="combobox"
              aria-autocomplete="list"
              aria-controls="command-results"
              :aria-expanded="filteredCommands.length > 0"
              :aria-activedescendant="flatFilteredCommands[selectedIndex]?.id"
            />
            <kbd class="escape-hint">ESC</kbd>
          </div>

          <!-- Results -->
          <div id="command-results" class="results-section" role="listbox" :aria-label="t('layout.palette.results')">
            <template v-if="Object.keys(groupedCommands).length > 0">
              <div
                v-for="(commands, category) in groupedCommands"
                :key="category"
                class="command-group"
                role="group"
                :aria-label="categoryLabels[category]"
              >
                <div class="group-label" aria-hidden="true">{{ categoryLabels[category] }}</div>
                <button
                  v-for="cmd in commands"
                  :key="cmd.id"
                  :id="cmd.id"
                  type="button"
                  role="option"
                  class="command-item"
                  :class="{
                    selected: flatFilteredCommands.indexOf(cmd) === selectedIndex,
                    disabled: cmd.disabledReason,
                    partial: cmd.statusNote,
                  }"
                  :aria-selected="flatFilteredCommands.indexOf(cmd) === selectedIndex"
                  :aria-disabled="Boolean(cmd.disabledReason)"
                  :title="cmd.disabledReason ?? cmd.statusNote ?? cmd.label"
                  @click="executeCommand(cmd)"
                  @mouseenter="selectedIndex = flatFilteredCommands.indexOf(cmd)"
                >
                  <component :is="cmd.icon" class="command-icon" aria-hidden="true" />
                  <span class="command-text">
                    <span class="command-label">{{ cmd.label }}</span>
                    <span v-if="cmd.disabledReason" class="command-reason">{{ cmd.disabledReason }}</span>
                    <span v-else-if="cmd.statusNote" class="command-note">{{ cmd.statusNote }}</span>
                  </span>
                  <kbd v-if="cmd.shortcut" class="command-shortcut" :aria-label="t('layout.palette.shortcut')">{{ cmd.shortcut }}</kbd>
                </button>
              </div>
            </template>
            <div v-else class="no-results" role="status" aria-live="polite">
              {{ t('layout.palette.noResults') }}
            </div>
          </div>

          <!-- Footer -->
          <div class="palette-footer">
            <span class="hint">
              <kbd>↑↓</kbd> {{ t('layout.palette.hintNavigate') }}
            </span>
            <span class="hint">
              <kbd>↵</kbd> {{ t('layout.palette.hintRun') }}
            </span>
            <span class="hint">
              <kbd>ESC</kbd> {{ t('layout.palette.hintClose') }}
            </span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
@reference "../../style.css";

.command-palette-container {
  @apply fixed inset-0;
  @apply flex items-start justify-center;
  @apply bg-black/50;
  @apply pt-[15vh];
  @apply px-4;
  z-index: var(--z-modal);
}

.command-palette {
  @apply w-full max-w-xl;
  @apply bg-white dark:bg-neutral-900;
  @apply rounded-2xl shadow-2xl;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply overflow-hidden;
}

/* Search Section */
.search-section {
  @apply flex items-center gap-3;
  @apply px-4 py-3;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.search-icon {
  @apply w-5 h-5 text-neutral-400;
}

.search-input {
  @apply flex-1 bg-transparent;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply placeholder-neutral-400 dark:placeholder-neutral-500;
  @apply outline-none;
  @apply text-base;
}

.escape-hint {
  @apply px-2 py-1 rounded;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply text-xs font-mono;
}

/* Results Section */
.results-section {
  @apply max-h-[50vh] overflow-y-auto;
  @apply py-2;
}

.command-group {
  @apply px-2;
}

.command-group + .command-group {
  @apply mt-2 pt-2;
  @apply border-t border-neutral-100 dark:border-neutral-800;
}

.group-label {
  @apply px-2 py-1;
  @apply text-xs font-semibold uppercase tracking-wider;
  @apply text-neutral-400 dark:text-neutral-500;
}

.command-item {
  @apply w-full flex items-center gap-3;
  @apply px-3 py-2.5 rounded-lg;
  @apply text-left;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply transition-colors duration-100;
}

.command-item:hover,
.command-item.selected {
  @apply bg-primary-50 dark:bg-primary-900/30;
  @apply text-primary-700 dark:text-primary-300;
}

.command-item.disabled {
  @apply opacity-60;
}

.command-item.partial:not(.disabled) {
  @apply ring-1 ring-warning-100 dark:ring-warning-900/40;
}

.command-icon {
  @apply w-5 h-5 flex-shrink-0;
}

.command-text {
  @apply flex-1;
}

.command-label {
  @apply block;
}

.command-reason {
  @apply block mt-0.5 text-xs text-warning-600 dark:text-warning-400;
}

.command-note {
  @apply block mt-0.5 text-xs text-warning-600 dark:text-warning-400;
}

.command-shortcut {
  @apply px-2 py-0.5 rounded;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply text-xs font-mono;
}

.no-results {
  @apply px-4 py-8;
  @apply text-center text-neutral-500 dark:text-neutral-400;
}

/* Footer */
.palette-footer {
  @apply flex items-center justify-center gap-6;
  @apply px-4 py-3;
  @apply border-t border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
}

.hint {
  @apply flex items-center gap-1.5;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.hint kbd {
  @apply px-1.5 py-0.5 rounded;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply font-mono;
}

/* Transitions */
.palette-enter-active {
  @apply transition-all duration-200 ease-out;
}

.palette-leave-active {
  @apply transition-all duration-150 ease-in;
}

.palette-enter-from,
.palette-leave-to {
  @apply opacity-0;
}

.palette-enter-from .command-palette,
.palette-leave-to .command-palette {
  @apply scale-95 -translate-y-4;
}
</style>
