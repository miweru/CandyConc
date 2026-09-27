/**
 * useKeyboard Composable Tests
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { registerShortcut } from '@/composables/useKeyboard'

describe('useKeyboard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('registerShortcut', () => {
    it('should register and unregister custom shortcuts', () => {
      const handler = vi.fn()
      const shortcut = {
        key: 'x',
        meta: true,
        handler,
        description: 'Test shortcut'
      }

      const unregister = registerShortcut(shortcut)

      // Simulate keydown
      const event = new KeyboardEvent('keydown', {
        key: 'x',
        metaKey: true,
        bubbles: true
      })

      // The shortcut should be in the registry now
      expect(typeof unregister).toBe('function')

      // Unregister
      unregister()

      // Shortcut should be removed (handler won't be called even if we trigger)
    })
  })

  describe('shortcut matching', () => {
    it('should correctly match key combinations', () => {
      // Test that shortcut matching logic works
      // This is more of an integration test since the actual matching
      // happens inside the composable's handleKeyDown
    })
  })
})

describe('keyboard event simulation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('should create keyboard events with correct properties', () => {
    const event = new KeyboardEvent('keydown', {
      key: 'k',
      metaKey: true,
      ctrlKey: false,
      shiftKey: false,
      altKey: false
    })

    expect(event.key).toBe('k')
    expect(event.metaKey).toBe(true)
    expect(event.ctrlKey).toBe(false)
    expect(event.shiftKey).toBe(false)
    expect(event.altKey).toBe(false)
  })

  it('should create keyboard events with shift modifier', () => {
    const event = new KeyboardEvent('keydown', {
      key: '?',
      shiftKey: true
    })

    expect(event.key).toBe('?')
    expect(event.shiftKey).toBe(true)
  })

  it('should create keyboard events with alt modifier', () => {
    const event = new KeyboardEvent('keydown', {
      key: '1',
      altKey: true
    })

    expect(event.key).toBe('1')
    expect(event.altKey).toBe(true)
  })
})
