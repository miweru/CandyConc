/**
 * useUndoRedo - Keyboard shortcuts for undo/redo
 */

import { onMounted, onUnmounted } from 'vue'
import { useHistoryStore } from '@/stores/history'
import { useUiStore } from '@/stores/ui'
import { t } from '@/i18n'

export interface UndoRedoOptions {
  onUndo?: () => void
  onRedo?: () => void
  showToast?: boolean
}

export function useUndoRedo(options: UndoRedoOptions = {}) {
  const historyStore = useHistoryStore()
  const uiStore = useUiStore()
  const { showToast = true } = options

  function handleKeydown(e: KeyboardEvent) {
    // The "Enable keyboard shortcuts" preference switches undo and redo too.
    if (!uiStore.shortcutsEnabled) return
    // Check for Cmd/Ctrl + Z
    if ((e.metaKey || e.ctrlKey) && e.key === 'z') {
      e.preventDefault()

      if (e.shiftKey) {
        // Redo: Cmd+Shift+Z
        if (historyStore.canRedo) {
          const success = historyStore.redo()
          if (success) {
            options.onRedo?.()
            if (showToast) {
              uiStore.showToast(t('layout.undo.redone'), 'info', 2000)
            }
          }
        }
      } else {
        // Undo: Cmd+Z
        if (historyStore.canUndo) {
          const success = historyStore.undo()
          if (success) {
            options.onUndo?.()
            if (showToast) {
              uiStore.showToast(t('layout.undo.undone'), 'info', 2000)
            }
          }
        }
      }
    }

    // Also support Cmd+Y for redo (Windows style)
    if ((e.metaKey || e.ctrlKey) && e.key === 'y') {
      e.preventDefault()
      if (historyStore.canRedo) {
        const success = historyStore.redo()
        if (success) {
          options.onRedo?.()
          if (showToast) {
            uiStore.showToast(t('layout.undo.redone'), 'info', 2000)
          }
        }
      }
    }
  }

  onMounted(() => {
    document.addEventListener('keydown', handleKeydown)
  })

  onUnmounted(() => {
    document.removeEventListener('keydown', handleKeydown)
  })

  return {
    undo: () => historyStore.undo(),
    redo: () => historyStore.redo(),
    canUndo: historyStore.canUndo,
    canRedo: historyStore.canRedo,
    pushState: () => historyStore.pushState(),
    clear: () => historyStore.clear(),
  }
}
