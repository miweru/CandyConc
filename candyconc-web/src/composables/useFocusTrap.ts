/**
 * useFocusTrap - Trap focus within a container element
 * Essential for accessible modals, dialogs, and overlays
 */

import { ref, type Ref, onUnmounted } from 'vue'

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]'
].join(', ')

export interface FocusTrapOptions {
  /** Initial element to focus (selector or element) */
  initialFocus?: string | HTMLElement | null
  /** Element to return focus to on deactivate */
  returnFocusTo?: HTMLElement | null
  /** Allow escape key to deactivate */
  escapeDeactivates?: boolean
  /** Callback when escape is pressed */
  onEscape?: () => void
}

export function useFocusTrap(
  containerRef: Ref<HTMLElement | null>,
  options: FocusTrapOptions = {}
) {
  const {
    escapeDeactivates = true,
    onEscape
  } = options

  const isActive = ref(false)
  const previousActiveElement = ref<HTMLElement | null>(null)

  function getFocusableElements(): HTMLElement[] {
    if (!containerRef.value) return []
    return Array.from(
      containerRef.value.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
    ).filter(el => {
      // Filter out hidden elements
      return el.offsetParent !== null && !el.hasAttribute('inert')
    })
  }

  function getFirstFocusable(): HTMLElement | null {
    const elements = getFocusableElements()
    return elements[0] ?? null
  }

  function getLastFocusable(): HTMLElement | null {
    const elements = getFocusableElements()
    return elements[elements.length - 1] ?? null
  }

  function handleKeydown(e: KeyboardEvent) {
    if (typeof document === 'undefined') return
    if (!isActive.value || !containerRef.value) return

    // Handle Escape
    if (e.key === 'Escape') {
      if (escapeDeactivates) {
        e.preventDefault()
        onEscape?.()
      }
      return
    }

    // Handle Tab
    if (e.key !== 'Tab') return

    const focusable = getFocusableElements()
    if (focusable.length === 0) {
      e.preventDefault()
      return
    }

    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement

    // Shift+Tab on first element -> go to last
    if (e.shiftKey && active === first) {
      e.preventDefault()
      last?.focus()
      return
    }

    // Tab on last element -> go to first
    if (!e.shiftKey && active === last) {
      e.preventDefault()
      first?.focus()
      return
    }

    // If focus is outside container, bring it back
    if (!containerRef.value.contains(active)) {
      e.preventDefault()
      first?.focus()
    }
  }

  function activate(initialFocusOverride?: string | HTMLElement | null) {
    if (typeof document === 'undefined') return
    if (isActive.value) return

    // Store current focus to restore later
    previousActiveElement.value = document.activeElement as HTMLElement | null

    isActive.value = true
    document.addEventListener('keydown', handleKeydown)

    // Determine initial focus
    const initialFocus = initialFocusOverride ?? options.initialFocus

    // Use requestAnimationFrame to ensure DOM is ready
    const runAfterPaint = typeof requestAnimationFrame === 'function'
      ? requestAnimationFrame
      : (callback: FrameRequestCallback) => window.setTimeout(callback, 0)
    runAfterPaint(() => {
      if (!containerRef.value) return

      let elementToFocus: HTMLElement | null = null

      if (typeof initialFocus === 'string') {
        elementToFocus = containerRef.value.querySelector(initialFocus)
      } else if (initialFocus instanceof HTMLElement) {
        elementToFocus = initialFocus
      }

      // Fall back to first focusable element
      if (!elementToFocus) {
        elementToFocus = getFirstFocusable()
      }

      // Fall back to container itself
      if (!elementToFocus) {
        containerRef.value.setAttribute('tabindex', '-1')
        elementToFocus = containerRef.value
      }

      elementToFocus?.focus()
    })
  }

  function deactivate() {
    if (typeof document === 'undefined') return
    if (!isActive.value) return

    isActive.value = false
    document.removeEventListener('keydown', handleKeydown)

    // Restore focus
    const returnTo = options.returnFocusTo ?? previousActiveElement.value
    if (returnTo && typeof returnTo.focus === 'function') {
      // Use requestAnimationFrame to ensure smooth transition
      const runAfterPaint = typeof requestAnimationFrame === 'function'
        ? requestAnimationFrame
        : (callback: FrameRequestCallback) => window.setTimeout(callback, 0)
      runAfterPaint(() => {
        returnTo.focus()
      })
    }

    previousActiveElement.value = null
  }

  // Cleanup on unmount
  onUnmounted(() => {
    if (isActive.value && typeof document !== 'undefined') {
      document.removeEventListener('keydown', handleKeydown)
    }
  })

  return {
    isActive,
    activate,
    deactivate,
    getFirstFocusable,
    getLastFocusable,
    getFocusableElements
  }
}
