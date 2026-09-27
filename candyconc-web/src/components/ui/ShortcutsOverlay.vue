<script setup lang="ts">
/**
 * ShortcutsOverlay - Keyboard shortcuts reference (press ? to open)
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { Keyboard } from 'lucide-vue-next'
import Modal from './Modal.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useUiStore } from '@/stores/ui'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  modelValue: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

interface ShortcutGroup {
  title: string
  shortcuts: ShortcutItem[]
}

interface ShortcutItem {
  keys: string[]
  description: string
  statusNote?: string | null
  disabled?: boolean
}

const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const uiStore = useUiStore()

const settingsShortcutSurfaceIds = [
  'settings.preferences',
  'settings.embedding_management',
  'admin.system_operations',
  'corpus.catalogue',
  'corpus.import',
]

function shortcutKeys(shortcut: string): string[] {
  return shortcut.split('+').map((key) => key.trim()).filter(Boolean)
}

function compact<T>(items: Array<T | null>): T[] {
  return items.filter((item): item is T => Boolean(item))
}

function surfaceShortcut(
  capabilityId: string,
  keys: string[],
  description: string,
): ShortcutItem | null {
  const availability = productCapabilities.surfaceAvailability(
    capabilityId,
    corpusCapabilities.activeSummary,
  )
  if (!availability.visible) return null
  return {
    keys,
    description,
    disabled: !availability.enabled,
    statusNote: availability.disabledReason ?? availability.partialReason,
  }
}

function anySurfaceShortcut(
  capabilityIds: string[],
  keys: string[],
  description: string,
): ShortcutItem | null {
  const decisions = capabilityIds
    .map((capabilityId) => productCapabilities.surfaceAvailability(capabilityId))
    .filter((availability) => availability.visible)
  if (!decisions.length) return null
  const enabled = decisions.some((availability) => availability.enabled)
  return {
    keys,
    description,
    disabled: !enabled,
    statusNote: enabled
      ? decisions.find((availability) => availability.partialReason)?.partialReason ?? null
      : decisions.find((availability) => availability.disabledReason)?.disabledReason ?? null,
  }
}

const shortcutGroups = computed<ShortcutGroup[]>(() => {
  const groups: ShortcutGroup[] = [
    {
      title: t('layout.shortcuts.groupNavigation'),
      shortcuts: [
        ...productCapabilities.discoverableAnalysisTabs.map((surface) => {
          const availability = productCapabilities.surfaceAvailability(
            surface.capabilityId,
            corpusCapabilities.activeSummary,
          )
          return {
            keys: shortcutKeys(surface.shortcut),
            description: surface.primary
              ? t('layout.shortcuts.tab', { label: surface.label })
              : t('layout.shortcuts.tabInMore', { label: surface.label }),
            disabled: !availability.enabled,
            statusNote: availability.disabledReason ?? availability.partialReason,
          }
        }),
        { keys: ['j'], description: t('layout.shortcuts.nextLine') },
        { keys: ['k'], description: t('layout.shortcuts.previousLine') },
        { keys: ['↓'], description: t('layout.shortcuts.nextLineKwic') },
        { keys: ['↑'], description: t('layout.shortcuts.previousLineKwic') },
        { keys: ['Home'], description: t('layout.shortcuts.firstLineKwic') },
        { keys: ['End'], description: t('layout.shortcuts.lastLineKwic') },
        { keys: ['PageUp'], description: t('layout.shortcuts.pageUp') },
        { keys: ['PageDown'], description: t('layout.shortcuts.pageDown') },
        { keys: ['g', 'g'], description: t('layout.shortcuts.firstLine') },
        { keys: ['G'], description: t('layout.shortcuts.lastLine') },
      ],
    },
    {
      title: t('layout.shortcuts.groupActions'),
      shortcuts: compact([
        { keys: ['/'], description: t('layout.shortcuts.focusSearch') },
        { keys: ['Enter'], description: t('layout.shortcuts.runSearch') },
        surfaceShortcut('query.cqlf', ['Cmd', 'B'], t('layout.shortcuts.openQueryBuilder')),
        { keys: ['Space'], description: t('layout.shortcuts.selectLine') },
        { keys: ['Esc'], description: t('layout.shortcuts.closeOverlays') },
        { keys: ['Cmd', 'Z'], description: t('layout.shortcuts.undo') },
        { keys: ['Cmd', 'Shift', 'Z'], description: t('layout.shortcuts.redo') },
      ]),
    },
    {
      title: t('layout.shortcuts.groupCopilot'),
      shortcuts: compact([
        { keys: ['Cmd', 'K'], description: t('layout.shortcuts.openPalette') },
        surfaceShortcut('research.copilot_grounding', ['Cmd', 'Shift', 'K'], t('layout.shortcuts.toggleCopilot')),
      ]),
    },
    {
      title: t('layout.shortcuts.groupTools'),
      shortcuts: compact([
        anySurfaceShortcut(settingsShortcutSurfaceIds, ['Cmd', ','], t('layout.shortcuts.openSettings')),
        surfaceShortcut('research.replay_export', ['Cmd', 'E'], t('layout.shortcuts.openExport')),
        { keys: ['?'], description: t('layout.shortcuts.showHelp') },
      ]),
    },
  ]
  return groups.filter((group) => group.shortcuts.length > 0)
})

// Global keyboard listener for ? key
function handleGlobalKey(e: KeyboardEvent) {
  // The "Enable keyboard shortcuts" preference switches this key as well.
  if (!uiStore.shortcutsEnabled) return
  if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey) {
    const target = e.target as HTMLElement
    if (target.tagName !== 'INPUT' && target.tagName !== 'TEXTAREA') {
      e.preventDefault()
      emit('update:modelValue', true)
    }
  }
}

onMounted(() => {
  void productCapabilities.load()
  document.addEventListener('keydown', handleGlobalKey)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleGlobalKey)
})
</script>

<template>
  <Modal
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="t('layout.shortcuts.title')"
    size="lg"
  >
    <template #header>
      <div class="flex items-center gap-3">
        <Keyboard class="w-5 h-5 text-primary-500" />
        <h2 class="text-lg font-semibold">{{ t('layout.shortcuts.title') }}</h2>
      </div>
    </template>

    <div class="shortcuts-grid">
      <div v-for="group in shortcutGroups" :key="group.title" class="shortcut-group">
        <h3 class="group-title">{{ group.title }}</h3>
        <div class="shortcuts-list">
          <div v-for="shortcut in group.shortcuts" :key="shortcut.description" class="shortcut-row">
            <span class="shortcut-desc" :class="{ disabled: shortcut.disabled }">
              {{ shortcut.description }}
              <small v-if="shortcut.statusNote" class="shortcut-status">{{ shortcut.statusNote }}</small>
            </span>
            <span class="shortcut-keys">
              <kbd v-for="(key, idx) in shortcut.keys" :key="key">
                {{ key }}
                <span v-if="idx < shortcut.keys.length - 1" class="key-separator">+</span>
              </kbd>
            </span>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <p class="footer-hint">
        <i18n-t keypath="layout.shortcuts.footerHint" scope="global"><template #key><kbd>?</kbd></template></i18n-t>
      </p>
    </template>
  </Modal>
</template>

<style scoped>
@reference "../../style.css";

.shortcuts-grid {
  @apply grid grid-cols-2 gap-6;
}

@media (max-width: 640px) {
  .shortcuts-grid {
    @apply grid-cols-1;
  }
}

.shortcut-group {
  @apply space-y-3;
}

.group-title {
  @apply text-sm font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply pb-2 border-b border-neutral-200 dark:border-neutral-700;
}

.shortcuts-list {
  @apply space-y-2;
}

.shortcut-row {
  @apply flex items-center justify-between gap-4;
  @apply py-1;
}

.shortcut-desc {
  @apply text-sm text-neutral-700 dark:text-neutral-300;
}

.shortcut-desc.disabled {
  @apply text-neutral-500 dark:text-neutral-500;
}

.shortcut-status {
  @apply mt-0.5 block text-xs text-warning-600 dark:text-warning-400;
}

.shortcut-keys {
  @apply flex items-center gap-1;
}

.shortcut-keys kbd {
  @apply inline-flex items-center;
  @apply px-2 py-1 rounded;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-xs font-mono;
  @apply text-neutral-600 dark:text-neutral-400;
}

.key-separator {
  @apply text-neutral-400 mx-0.5;
}

.footer-hint {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.footer-hint kbd {
  @apply inline-flex items-center;
  @apply px-1.5 py-0.5 mx-1 rounded;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-xs font-mono;
}
</style>
