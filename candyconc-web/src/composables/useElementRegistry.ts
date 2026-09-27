/**
 * useElementRegistry Composable - Registry for UI elements the Copilot can target
 *
 * Handles both static DOM elements and virtual elements (e.g., virtualized list rows)
 * that may not be in the DOM but still need to be addressable by the ghost cursor.
 */

import { ref, shallowRef, nextTick } from 'vue'
import type { Action } from '@/actions/types'

export type ElementType = 'static' | 'virtual'
export type ElementActivationIntent = 'primary' | 'secondary'

export interface ElementPosition {
  x: number
  y: number
  width?: number
  height?: number
}

export interface RegisteredElement {
  id: string
  type: ElementType
  /** CSS selector for static elements */
  selector?: string
  /** Function to get current position (for virtual elements or dynamic positioning) */
  getPosition?: () => ElementPosition | null
  /** Function to scroll element into view (for virtual elements) */
  scrollIntoView?: () => Promise<void>
  /** Explicit action allowed when a virtual cursor activates this target. */
  getActivationAction?: (intent: ElementActivationIntent) => Action | null
  /** Optional metadata about the element */
  metadata?: Record<string, unknown>
}

// Singleton registry (shared across all usages)
const elementRegistry = shallowRef<Map<string, RegisteredElement>>(new Map())
const registrationCallbacks = ref<Set<(id: string, element: RegisteredElement) => void>>(new Set())
const unregistrationCallbacks = ref<Set<(id: string) => void>>(new Set())

export function useElementRegistry() {
  /**
   * Register a static DOM element by selector
   */
  function registerStatic(
    id: string,
    selector: string,
    metadata?: Record<string, unknown>,
    getActivationAction?: (intent: ElementActivationIntent) => Action | null
  ): () => void {
    const element: RegisteredElement = {
      id,
      type: 'static',
      selector,
      getActivationAction,
      metadata,
      getPosition: () => {
        const el = document.querySelector(selector) as HTMLElement | null
        if (!el) return null

        const rect = el.getBoundingClientRect()
        return {
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
          width: rect.width,
          height: rect.height
        }
      }
    }

    const newRegistry = new Map(elementRegistry.value)
    newRegistry.set(id, element)
    elementRegistry.value = newRegistry

    // Notify callbacks
    registrationCallbacks.value.forEach(cb => cb(id, element))

    // Return unregister function
    return () => unregister(id)
  }

  /**
   * Register a virtual element (e.g., virtualized list row)
   */
  function registerVirtual(
    id: string,
    options: {
      getPosition: () => ElementPosition | null
      scrollIntoView?: () => Promise<void>
      getActivationAction?: (intent: ElementActivationIntent) => Action | null
      metadata?: Record<string, unknown>
    }
  ): () => void {
    const element: RegisteredElement = {
      id,
      type: 'virtual',
      getPosition: options.getPosition,
      scrollIntoView: options.scrollIntoView,
      getActivationAction: options.getActivationAction,
      metadata: options.metadata
    }

    const newRegistry = new Map(elementRegistry.value)
    newRegistry.set(id, element)
    elementRegistry.value = newRegistry

    // Notify callbacks
    registrationCallbacks.value.forEach(cb => cb(id, element))

    // Return unregister function
    return () => unregister(id)
  }

  /**
   * Register an element with full options
   */
  function registerElement(id: string, element: Omit<RegisteredElement, 'id'>): () => void {
    const fullElement: RegisteredElement = { id, ...element }

    const newRegistry = new Map(elementRegistry.value)
    newRegistry.set(id, fullElement)
    elementRegistry.value = newRegistry

    // Notify callbacks
    registrationCallbacks.value.forEach(cb => cb(id, fullElement))

    return () => unregister(id)
  }

  /**
   * Unregister an element
   */
  function unregister(id: string): void {
    if (elementRegistry.value.has(id)) {
      const newRegistry = new Map(elementRegistry.value)
      newRegistry.delete(id)
      elementRegistry.value = newRegistry

      // Notify callbacks
      unregistrationCallbacks.value.forEach(cb => cb(id))
    }
  }

  /**
   * Bulk register multiple elements
   */
  function registerBatch(
    elements: Array<{ id: string } & Omit<RegisteredElement, 'id'>>
  ): () => void {
    const unregisters: Array<() => void> = []

    for (const element of elements) {
      unregisters.push(registerElement(element.id, element))
    }

    // Return function to unregister all
    return () => unregisters.forEach(fn => fn())
  }

  /**
   * Get a registered element by ID
   */
  function getElement(id: string): RegisteredElement | undefined {
    return elementRegistry.value.get(id)
  }

  /**
   * Check if an element is registered
   */
  function hasElement(id: string): boolean {
    return elementRegistry.value.has(id)
  }

  /**
   * Get all registered element IDs
   */
  function getAllIds(): string[] {
    return Array.from(elementRegistry.value.keys())
  }

  /**
   * Get all elements matching a pattern
   */
  function getElementsMatching(pattern: RegExp): RegisteredElement[] {
    const matches: RegisteredElement[] = []
    elementRegistry.value.forEach((element, id) => {
      if (pattern.test(id)) {
        matches.push(element)
      }
    })
    return matches
  }

  /**
   * Get element position, handling both static and virtual elements
   */
  function getPosition(id: string): ElementPosition | null {
    const element = elementRegistry.value.get(id)
    if (!element) return null

    if (element.getPosition) {
      return element.getPosition()
    }

    if (element.type === 'static' && element.selector) {
      const el = document.querySelector(element.selector) as HTMLElement | null
      if (!el) return null

      const rect = el.getBoundingClientRect()
      return {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
        width: rect.width,
        height: rect.height
      }
    }

    return null
  }

  /**
   * Return the explicit action allowed for activating a registered target.
   */
  function getActivationAction(
    id: string,
    intent: ElementActivationIntent = 'primary'
  ): Action | null {
    const element = elementRegistry.value.get(id)
    return element?.getActivationAction?.(intent) ?? null
  }

  /**
   * Scroll element into view and return its position
   */
  async function scrollIntoViewAndGetPosition(id: string): Promise<ElementPosition | null> {
    const element = elementRegistry.value.get(id)
    if (!element) return null

    // If element has scroll handler, use it
    if (element.scrollIntoView) {
      await element.scrollIntoView()
      await nextTick()
    } else if (element.type === 'static' && element.selector) {
      // For static elements, use native scrollIntoView
      const el = document.querySelector(element.selector) as HTMLElement | null
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        // Wait for scroll animation
        await new Promise(resolve => setTimeout(resolve, 300))
      }
    }

    return getPosition(id)
  }

  /**
   * Subscribe to element registrations
   */
  function onRegister(callback: (id: string, element: RegisteredElement) => void): () => void {
    registrationCallbacks.value.add(callback)
    return () => registrationCallbacks.value.delete(callback)
  }

  /**
   * Subscribe to element unregistrations
   */
  function onUnregister(callback: (id: string) => void): () => void {
    unregistrationCallbacks.value.add(callback)
    return () => unregistrationCallbacks.value.delete(callback)
  }

  /**
   * Clear all registered elements
   */
  function clearAll(): void {
    const ids = getAllIds()
    elementRegistry.value = new Map()
    ids.forEach(id => unregistrationCallbacks.value.forEach(cb => cb(id)))
  }

  /**
   * Clear elements matching a pattern
   */
  function clearMatching(pattern: RegExp): void {
    const newRegistry = new Map(elementRegistry.value)
    const removed: string[] = []

    newRegistry.forEach((_, id) => {
      if (pattern.test(id)) {
        newRegistry.delete(id)
        removed.push(id)
      }
    })

    elementRegistry.value = newRegistry
    removed.forEach(id => unregistrationCallbacks.value.forEach(cb => cb(id)))
  }

  return {
    // State (readonly)
    registry: elementRegistry,

    // Registration
    registerStatic,
    registerVirtual,
    registerElement,
    registerBatch,
    unregister,

    // Queries
    getElement,
    hasElement,
    getAllIds,
    getElementsMatching,
    getPosition,
    getActivationAction,
    scrollIntoViewAndGetPosition,

    // Subscriptions
    onRegister,
    onUnregister,

    // Cleanup
    clearAll,
    clearMatching
  }
}
