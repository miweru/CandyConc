/**
 * Copilot Store Tests
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCopilotStore } from '@/stores/copilot'

describe('CopilotStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('initial state', () => {
    it('should have correct initial state', () => {
      const store = useCopilotStore()

      expect(store.mode).toBe('minimized')
      expect(store.isOpen).toBe(false)
      // Default: Stufe 2 (Level 4) — Lese-Analysen frei, Schreibendes mit Bestätigung.
      expect(store.autonomyLevel).toBe(4)
      expect(store.autonomyStep.step).toBe(2)
      expect(store.messages).toHaveLength(0)
      expect(store.isThinking).toBe(false)
    })

    it('should have correct computed values', () => {
      const store = useCopilotStore()

      expect(store.isMinimized).toBe(true)
      expect(store.isFloating).toBe(false)
      expect(store.isDocked).toBe(false)
      expect(store.lastMessage).toBeNull()
      expect(store.pendingClarification).toBeNull()
    })
  })

  describe('mode and open/close', () => {
    it('should set mode', () => {
      const store = useCopilotStore()

      store.setMode('floating')

      expect(store.mode).toBe('floating')
      expect(store.isOpen).toBe(true)
      expect(store.isFloating).toBe(true)
    })

    it('should open with default mode', () => {
      const store = useCopilotStore()

      store.open()

      expect(store.isOpen).toBe(true)
      expect(store.mode).toBe('floating')
    })

    it('should open with specified mode', () => {
      const store = useCopilotStore()

      store.open('docked')

      expect(store.isOpen).toBe(true)
      expect(store.mode).toBe('docked')
    })

    it('should close and set to minimized', () => {
      const store = useCopilotStore()
      store.open('floating')

      store.close()

      expect(store.isOpen).toBe(false)
      expect(store.mode).toBe('minimized')
    })

    it('should toggle open state', () => {
      const store = useCopilotStore()

      store.toggle()
      expect(store.isOpen).toBe(true)

      store.toggle()
      expect(store.isOpen).toBe(false)
    })
  })

  describe('autonomy level', () => {
    it('should set autonomy level', () => {
      const store = useCopilotStore()

      store.setAutonomyLevel(8)

      expect(store.autonomyLevel).toBe(8)
    })

    it('should clamp autonomy level to 0-10', () => {
      const store = useCopilotStore()

      store.setAutonomyLevel(-5)
      expect(store.autonomyLevel).toBe(0)

      store.setAutonomyLevel(15)
      expect(store.autonomyLevel).toBe(10)
    })

    it('should map steps to the honest backend levels 1/4/7/10', () => {
      const store = useCopilotStore()

      store.setAutonomyStep(1)
      expect(store.autonomyLevel).toBe(1)
      store.setAutonomyStep(2)
      expect(store.autonomyLevel).toBe(4)
      store.setAutonomyStep(3)
      expect(store.autonomyLevel).toBe(7)
      store.setAutonomyStep(4)
      expect(store.autonomyLevel).toBe(10)

      // Unknown step values change nothing.
      store.setAutonomyStep(0)
      expect(store.autonomyLevel).toBe(10)
    })

    it('should return the step description as autonomy description', () => {
      const store = useCopilotStore()

      store.setAutonomyLevel(1)
      expect(store.autonomyDescription).toBe('Plan prüfen und bestätigen, dann ausführen')

      store.setAutonomyLevel(4)
      expect(store.autonomyDescription).toBe('Lese-Analysen frei, Schreib-/nicht umkehrbare Aktionen mit Bestätigung')

      store.setAutonomyLevel(7)
      expect(store.autonomyDescription).toBe('Frei außer destruktive Aktionen')

      store.setAutonomyLevel(10)
      expect(store.autonomyDescription).toBe('Vollständig autonom')
    })
  })

  describe('messages', () => {
    it('should add a message', () => {
      const store = useCopilotStore()

      const id = store.addMessage({ role: 'user', content: 'Hello' })

      expect(store.messages).toHaveLength(1)
      expect(store.messages[0]?.content).toBe('Hello')
      expect(store.messages[0]?.role).toBe('user')
      expect(id).toBeDefined()
    })

    it('should update a message', () => {
      const store = useCopilotStore()
      const id = store.addMessage({ role: 'assistant', content: 'Initial' })

      store.updateMessage(id, { content: 'Updated' })

      expect(store.messages[0]?.content).toBe('Updated')
    })

    it('should track last message', () => {
      const store = useCopilotStore()
      store.addMessage({ role: 'user', content: 'First' })
      store.addMessage({ role: 'assistant', content: 'Second' })

      expect(store.lastMessage?.content).toBe('Second')
    })

    it('should clear messages', () => {
      const store = useCopilotStore()
      store.addMessage({ role: 'user', content: 'Test' })
      store.setSession('session-1', 'conv-1')

      store.clearMessages()

      expect(store.messages).toHaveLength(0)
      expect(store.conversationId).toBeNull()
    })
  })

  describe('streaming', () => {
    it('should set streaming state', () => {
      const store = useCopilotStore()

      store.setStreaming(true, 'Initial content')

      expect(store.isThinking).toBe(true)
      expect(store.currentStreamingMessage).toBe('Initial content')
    })

    it('should append to streaming content', () => {
      const store = useCopilotStore()
      store.setStreaming(true, 'Hello')

      store.appendStreamingContent(' World')

      expect(store.currentStreamingMessage).toBe('Hello World')
    })
  })

  describe('clarification', () => {
    it('should detect pending clarification', () => {
      const store = useCopilotStore()
      store.addMessage({
        role: 'assistant',
        content: 'Please clarify',
        clarification: {
          id: 'q1',
          explanation: 'Which option?',
          options: [
            { id: 'a', label: 'Option A', value: 'a' },
            { id: 'b', label: 'Option B', value: 'b' }
          ]
        }
      })

      expect(store.pendingClarification).not.toBeNull()
      expect(store.pendingClarification?.id).toBe('q1')
    })

    it('should answer clarification', () => {
      const store = useCopilotStore()
      store.addMessage({
        role: 'assistant',
        content: 'Please clarify',
        clarification: {
          id: 'q1',
          explanation: 'Which option?',
          options: [
            { id: 'a', label: 'Option A', value: 'a' }
          ]
        }
      })

      store.answerClarification('q1', 'a')

      expect(store.pendingClarification).toBeNull()
      expect(store.messages[0]?.clarification?.answered).toBe(true)
      expect(store.messages[0]?.clarification?.selectedOption).toBe('a')
    })

    it('should timeout clarification', () => {
      const store = useCopilotStore()
      store.addMessage({
        role: 'assistant',
        content: 'Please clarify',
        clarification: {
          id: 'q1',
          explanation: 'Which option?',
          options: [{ id: 'a', label: 'Option A', value: 'a' }],
          timeout: 5000
        }
      })

      vi.advanceTimersByTime(5000)

      expect(store.messages[0]?.clarification?.answered).toBe(true)
      expect(store.messages[0]?.clarification?.selectedOption).toBe('__timeout__')
      expect(store.messages).toHaveLength(2) // Original + system message
    })

    it('should use fallback option on timeout', () => {
      const store = useCopilotStore()
      store.addMessage({
        role: 'assistant',
        content: 'Please clarify',
        clarification: {
          id: 'q1',
          explanation: 'Which option?',
          options: [{ id: 'a', label: 'Option A', value: 'a' }],
          timeout: 5000,
          fallbackOptionId: 'a'
        }
      })

      vi.advanceTimersByTime(5000)

      expect(store.messages[0]?.clarification?.selectedOption).toBe('a')
    })
  })

  describe('session', () => {
    it('should set session', () => {
      const store = useCopilotStore()

      store.setSession('session-123', 'conv-456')

      expect(store.sessionId).toBe('session-123')
      expect(store.conversationId).toBe('conv-456')
    })
  })
})
