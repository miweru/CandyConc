/**
 * useVimNavigation - Vim-like keyboard navigation for lists
 */

import { ref, onMounted, onUnmounted } from 'vue'
import { useUiStore } from '@/stores/ui'

export interface VimNavigationOptions {
  onNavigate?: (index: number) => void
  onSelect?: (index: number) => void
  onEscape?: () => void
  totalItems: () => number
  enabled?: () => boolean
}

export function useVimNavigation(options: VimNavigationOptions) {
  const uiStore = useUiStore()
  const currentIndex = ref(0)
  const lastKeyTime = ref(0)
  const lastKey = ref('')

  function isInputFocused(): boolean {
    const active = document.activeElement
    if (!active) return false
    const tag = active.tagName.toLowerCase()
    return tag === 'input' || tag === 'textarea' || (active as HTMLElement).isContentEditable
  }

  function navigate(direction: 'up' | 'down' | 'first' | 'last') {
    const total = options.totalItems()
    if (total === 0) return

    switch (direction) {
      case 'up':
        currentIndex.value = Math.max(0, currentIndex.value - 1)
        break
      case 'down':
        currentIndex.value = Math.min(total - 1, currentIndex.value + 1)
        break
      case 'first':
        currentIndex.value = 0
        break
      case 'last':
        currentIndex.value = total - 1
        break
    }

    options.onNavigate?.(currentIndex.value)
  }

  function handleKeydown(e: KeyboardEvent) {
    // Check if navigation is enabled
    if (options.enabled && !options.enabled()) return
    if (!uiStore.shortcutsEnabled) return
    if (isInputFocused()) return

    const now = Date.now()
    const key = e.key

    // Handle 'gg' for first item (double tap within 300ms)
    if (key === 'g') {
      if (lastKey.value === 'g' && now - lastKeyTime.value < 300) {
        e.preventDefault()
        navigate('first')
        lastKey.value = ''
        return
      }
      lastKey.value = 'g'
      lastKeyTime.value = now
      return
    }

    // Reset last key for non-g keys
    lastKey.value = ''

    switch (key) {
      case 'j':
        e.preventDefault()
        navigate('down')
        break

      case 'k':
        e.preventDefault()
        navigate('up')
        break

      case 'G':
        e.preventDefault()
        navigate('last')
        break

      case 'Enter':
      case ' ':
        e.preventDefault()
        options.onSelect?.(currentIndex.value)
        break

      case 'Escape':
        e.preventDefault()
        options.onEscape?.()
        break
    }
  }

  function setIndex(index: number) {
    const total = options.totalItems()
    currentIndex.value = Math.max(0, Math.min(total - 1, index))
  }

  function reset() {
    currentIndex.value = 0
  }

  onMounted(() => {
    document.addEventListener('keydown', handleKeydown)
  })

  onUnmounted(() => {
    document.removeEventListener('keydown', handleKeydown)
  })

  return {
    currentIndex,
    navigate,
    setIndex,
    reset
  }
}
