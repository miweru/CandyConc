import { computed, ref, type Ref } from 'vue'
import type { CqlBuilderNode } from '@/lib/queryBuilder/ast'
import { cloneBuilderNode, createHistoryEntry } from '@/lib/queryBuilder/fragments'
import { HISTORY_LIMIT } from '@/lib/queryBuilder/constants'
import type { BuilderHistoryEntry } from '@/lib/queryBuilder/types'
import { t } from '@/i18n'
import { formatNumber } from '@/i18n/format'

/**
 * Internal marker for the debounced "direct edit" commit. It is compared in
 * the commit logic and replaced by the translated label when an entry is
 * written, so the comparison does not depend on the interface language.
 */
const DIRECT_EDIT = '__direct_edit__'

function historyLabelText(label: string): string {
  return label === DIRECT_EDIT ? t('querybuilder.history.directEdit') : label
}

/**
 * Undo/Redo timeline for the CQL builder AST.
 *
 * Extracted verbatim from QueryBuilderStudio.vue (Phase 2 split). Owns the
 * history entries, the debounced direct-edit commit snapshot and
 * the pending-label/suppress flags that the deep rootNode watcher consumes.
 *
 * Restoring an entry (writing rootNode/advancedCql, re-triggering suggest and
 * meta loads) intentionally stays in the component — it touches state owned
 * by other concerns.
 */
export function useBuilderHistory(rootNode: Ref<CqlBuilderNode>) {
  const historyEntries = ref<BuilderHistoryEntry[]>([])
  const historyIndex = ref(-1)

  let pendingHistoryLabel: string | null = null
  let suppressNextHistoryCommit = false
  let historyCommitTimer: ReturnType<typeof setTimeout> | null = null
  let pendingHistorySnapshot: { label: string; node: CqlBuilderNode } | null = null

  function queueHistoryLabel(label: string) {
    pendingHistoryLabel = label
  }

  function flushPendingHistory() {
    if (historyCommitTimer) {
      clearTimeout(historyCommitTimer)
      historyCommitTimer = null
    }
    if (!pendingHistorySnapshot) return
    rememberHistory(pendingHistorySnapshot.label, pendingHistorySnapshot.node)
    pendingHistorySnapshot = null
  }

  function rememberHistory(label: string, node: CqlBuilderNode = rootNode.value) {
    const text = historyLabelText(label)
    const entry = createHistoryEntry(node, text)
    const active = historyEntries.value[historyIndex.value]
    if (active?.signature === entry.signature) {
      if (active.label !== text && label !== DIRECT_EDIT) {
        active.label = text
      }
      return
    }

    const nextEntries = historyEntries.value.slice(0, historyIndex.value + 1)
    nextEntries.push(entry)
    if (nextEntries.length > HISTORY_LIMIT) {
      nextEntries.splice(0, nextEntries.length - HISTORY_LIMIT)
    }
    historyEntries.value = nextEntries
    historyIndex.value = nextEntries.length - 1
  }

  function scheduleHistoryCommit(label: string, node: CqlBuilderNode = rootNode.value) {
    if (label !== DIRECT_EDIT) {
      flushPendingHistory()
      rememberHistory(label, node)
      return
    }

    pendingHistorySnapshot = {
      label,
      node: cloneBuilderNode(node),
    }
    if (historyCommitTimer) {
      clearTimeout(historyCommitTimer)
    }
    historyCommitTimer = setTimeout(() => {
      if (!pendingHistorySnapshot) return
      rememberHistory(pendingHistorySnapshot.label, pendingHistorySnapshot.node)
      pendingHistorySnapshot = null
      historyCommitTimer = null
    }, 320)
  }

  function resetHistory(label: string) {
    flushPendingHistory()
    historyEntries.value = [createHistoryEntry(rootNode.value, label)]
    historyIndex.value = 0
    pendingHistoryLabel = null
    suppressNextHistoryCommit = false
  }

  /** Suppress the history commit triggered by the next rootNode mutation (used when restoring an entry). */
  function markNextHistoryCommitSuppressed() {
    suppressNextHistoryCommit = true
  }

  /**
   * Atomically read-and-clear the pending label / suppress flag.
   * Called exactly once per deep rootNode watcher invocation.
   */
  function consumeHistoryCommitFlags(): { label: string; suppress: boolean } {
    const label = pendingHistoryLabel ?? DIRECT_EDIT
    const suppress = suppressNextHistoryCommit
    pendingHistoryLabel = null
    suppressNextHistoryCommit = false
    return { label, suppress }
  }

  const canUndo = computed(() => historyIndex.value > 0)
  const canRedo = computed(() => historyIndex.value >= 0 && historyIndex.value < historyEntries.value.length - 1)
  const currentHistoryEntry = computed(() => historyEntries.value[historyIndex.value] ?? null)
  const visibleHistoryEntries = computed(() => {
    const total = historyEntries.value.length
    if (!total) return []
    const start = Math.max(0, historyIndex.value - 2)
    const end = Math.min(total, start + 6)
    return historyEntries.value.slice(start, end).map((entry, offset) => ({
      ...entry,
      index: start + offset,
      active: start + offset === historyIndex.value,
    }))
  })

  const historySummary = computed(() => {
    const entry = currentHistoryEntry.value
    if (!entry) {
      return {
        title: t('querybuilder.history.startsTitle'),
        detail: t('querybuilder.history.startsDetail'),
      }
    }
    return {
      title: t('querybuilder.history.position', {
        index: formatNumber(historyIndex.value + 1),
        total: formatNumber(historyEntries.value.length),
      }),
      detail: t('querybuilder.history.activeDetail', { label: entry.label }),
    }
  })

  return {
    historyEntries,
    historyIndex,
    queueHistoryLabel,
    flushPendingHistory,
    rememberHistory,
    scheduleHistoryCommit,
    resetHistory,
    markNextHistoryCommitSuppressed,
    consumeHistoryCommitFlags,
    canUndo,
    canRedo,
    currentHistoryEntry,
    visibleHistoryEntries,
    historySummary,
  }
}
