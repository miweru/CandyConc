/**
 * Action Bus - Central dispatcher for all actions
 *
 * Usage:
 *   // From UI component
 *   await actionBus.dispatch({ type: 'query/execute', payload: { term: 'Klimawandel' } })
 *
 *   // From Copilot (with source tracking)
 *   await actionBus.dispatch({ type: 'kwic/scrollToRow', payload: { index: 42 } }, 'copilot')
 */

import { ref, shallowRef } from 'vue'
import type {
  Action,
  ActionDispatchContext,
  ActionDispatchOptions,
  ActionHandler,
  ActionMiddleware,
  ActionResult,
  ActionSource,
} from './types'

type ActionType = Action['type']

const isDev = import.meta.env.DEV

// Extract action by type
type ActionOfType<T extends ActionType> = Extract<Action, { type: T }>

// Actions that can conflict with each other
const CONFLICTING_ACTION_PREFIXES = [
  'query/',
  'kwic/',
  'analysis/',
  'copilot/setAutonomy'
] as const

export interface PendingAction {
  action: Action
  source: ActionSource
  timestamp: number
  context: ActionDispatchContext
}

export interface ActionHistoryEntry {
  action: Action
  result: ActionResult
  timestamp: number
  source: ActionSource
  context: ActionDispatchContext
}

export interface ActionBusConfig {
  /** Max lock duration in ms for short actions (default: 10000) */
  lockTimeout?: number
  /** Callback when lock timeout is reached */
  onLockTimeout?: (action: Action) => void
  /** Max history size (default: 100) */
  maxHistorySize?: number
}

export class ActionBus {
  private handlers = new Map<ActionType, ActionHandler[]>()
  private middlewares: ActionMiddleware[] = []

  // Observable state for debugging/logging
  public lastAction = shallowRef<Action | null>(null)
  public lastResult = shallowRef<ActionResult | null>(null)
  public isDispatching = ref(false)

  // Race condition prevention
  private actionLock = false
  private pendingAction: PendingAction | null = null
  private userPriority = true  // User actions have priority by default
  private defaultLockTimeout: number
  private lockTimer: ReturnType<typeof setTimeout> | null = null
  private onLockTimeout?: (action: Action) => void

  // History for undo/replay
  public history: ActionHistoryEntry[] = []
  private maxHistorySize: number

  constructor(config: ActionBusConfig = {}) {
    this.defaultLockTimeout = config.lockTimeout ?? 10000
    this.onLockTimeout = config.onLockTimeout
    this.maxHistorySize = config.maxHistorySize ?? 100
  }

  /**
   * Update lock timeout at runtime
   */
  setLockTimeout(ms: number): void {
    this.defaultLockTimeout = Math.max(1000, ms)  // Minimum 1 second
  }

  private getLockTimeout(actionType: string): number {
    if (actionType === 'query/execute') {
      return Math.max(this.defaultLockTimeout, 120000)
    }
    if (actionType.startsWith('query/')) {
      return Math.max(this.defaultLockTimeout, 60000)
    }
    if (actionType.startsWith('analysis/')) {
      return Math.max(this.defaultLockTimeout, 60000)
    }
    return this.defaultLockTimeout
  }

  /**
   * Register a handler for an action type
   */
  register<T extends ActionType>(type: T, handler: ActionHandler<ActionOfType<T>>): () => void {
    const stack = this.handlers.get(type) ?? []
    stack.push(handler as ActionHandler)
    this.handlers.set(type, stack)

    let active = true
    return () => {
      if (!active) return
      active = false

      const currentStack = this.handlers.get(type)
      if (!currentStack) return

      const index = currentStack.lastIndexOf(handler as ActionHandler)
      if (index !== -1) {
        currentStack.splice(index, 1)
      }

      if (currentStack.length === 0) {
        this.handlers.delete(type)
      }
    }
  }

  /**
   * Add middleware (e.g., for logging, analytics, copilot observation)
   */
  use(middleware: ActionMiddleware): () => void {
    this.middlewares.push(middleware)
    return () => {
      const idx = this.middlewares.indexOf(middleware)
      if (idx > -1) this.middlewares.splice(idx, 1)
    }
  }

  private createDispatchContext(input?: ActionSource | ActionDispatchOptions): ActionDispatchContext {
    const timestamp = Date.now()
    if (!input || typeof input === 'string') {
      return Object.freeze({ source: input ?? 'user', timestamp })
    }

    const context: ActionDispatchContext = {
      source: input.source ?? 'user',
      timestamp: input.timestamp ?? timestamp,
    }
    return Object.freeze({
      ...context,
      ...(input.requestId === undefined ? {} : { requestId: input.requestId }),
      ...(input.runId === undefined ? {} : { runId: input.runId }),
    })
  }

  /**
   * Check if an action type can conflict with others
   */
  private canConflict(actionType: string): boolean {
    return CONFLICTING_ACTION_PREFIXES.some(prefix => actionType.startsWith(prefix))
  }

  /**
   * Check if two actions conflict
   */
  private actionsConflict(a: Action, b: Action): boolean {
    // Actions of the same type always conflict
    if (a.type === b.type) return true

    // Check if they share the same prefix (e.g., query/execute and query/clear)
    const aPrefix = a.type.split('/')[0]
    const bPrefix = b.type.split('/')[0]
    return aPrefix === bPrefix && this.canConflict(a.type)
  }

  /**
   * Set user priority mode
   */
  setUserPriority(enabled: boolean): void {
    this.userPriority = enabled
  }

  /**
   * Release the action lock (for error recovery)
   */
  releaseLock(): void {
    this.actionLock = false
    this.pendingAction = null
    if (this.lockTimer) {
      clearTimeout(this.lockTimer)
      this.lockTimer = null
    }
  }

  /**
   * Dispatch an action with optional source tracking
   */
  async dispatch<T extends ActionType>(
    action: ActionOfType<T>,
    sourceOrContext: ActionSource | ActionDispatchOptions = 'user'
  ): Promise<ActionResult> {
    const context = this.createDispatchContext(sourceOrContext)
    const source = context.source

    // Check for conflicts if lock is active
    if (this.actionLock && this.pendingAction && this.canConflict(action.type)) {
      const conflicts = this.actionsConflict(action, this.pendingAction.action)

      if (conflicts) {
        // User priority: copilot action gets blocked
        if (source === 'copilot' && this.pendingAction.source === 'user' && this.userPriority) {
          console.info(`[ActionBus] Copilot action blocked: ${action.type} (user action in progress)`)
          return {
            success: false,
            error: 'User action in progress',
            blocked: true,
            source
          }
        }

        // Copilot already running: user action waits briefly then proceeds
        if (source === 'user' && this.pendingAction.source === 'copilot') {
          if (isDev) {
            console.info(`[ActionBus] User action taking priority over copilot: ${action.type}`)
          }
          // Release lock to let user action proceed
          this.releaseLock()
        }
      }
    }

    // Acquire lock for potentially conflicting actions
    const shouldLock = this.canConflict(action.type)
    if (shouldLock) {
      this.actionLock = true
      this.pendingAction = { action, source, timestamp: context.timestamp, context }
      const lockTimeout = this.getLockTimeout(action.type)

      // Safety timeout to prevent deadlocks
      this.lockTimer = setTimeout(() => {
        if (isDev) {
          console.warn(`[ActionBus] Lock timeout for action: ${action.type}`)
        }
        this.onLockTimeout?.(action)
        this.releaseLock()
      }, lockTimeout)
    }

    this.isDispatching.value = true
    this.lastAction.value = action

    try {
      // Build middleware chain
      const handlerStack = this.handlers.get(action.type)
      const handler = handlerStack?.[handlerStack.length - 1]

      const executeHandler = async (): Promise<ActionResult> => {
        if (!handler) {
          if (isDev) {
            console.warn(`[ActionBus] No handler registered for action: ${action.type}`)
          }
          return { success: false, error: `No handler for ${action.type}`, source }
        }
        const result = await handler(action as Action, context)
        return { ...result, source }
      }

      // Apply middlewares in order
      let chain = executeHandler
      for (let i = this.middlewares.length - 1; i >= 0; i--) {
        const middleware = this.middlewares[i]!
        const next = chain
        chain = () => middleware(action, next, context)
      }

      const result = { ...(await chain()), source }

      this.lastResult.value = result

      // Add to history
      this.history.push({
        action,
        result,
        timestamp: context.timestamp,
        source,
        context,
      })

      // Trim history if needed
      if (this.history.length > this.maxHistorySize) {
        this.history = this.history.slice(-this.maxHistorySize)
      }

      return result
    } finally {
      this.isDispatching.value = false

      // Release lock
      if (shouldLock) {
        this.releaseLock()
      }
    }
  }

  /**
   * Batch dispatch multiple actions (all from same source)
   */
  async dispatchBatch(
    actions: Action[],
    sourceOrContext: ActionSource | ActionDispatchOptions = 'user'
  ): Promise<ActionResult[]> {
    return Promise.all(actions.map(action => this.dispatch(action, sourceOrContext)))
  }

  /**
   * Get action history (for debugging/replay)
   */
  getHistory(limit?: number): typeof this.history {
    const slice = limit ? this.history.slice(-limit) : this.history
    return [...slice]
  }

  /**
   * Get history filtered by source
   */
  getHistoryBySource(source: ActionSource, limit?: number): typeof this.history {
    const filtered = this.history.filter(h => h.source === source)
    return limit ? filtered.slice(-limit) : [...filtered]
  }

  /**
   * Clear history
   */
  clearHistory(): void {
    this.history = []
  }

  /**
   * Check if a conflicting action is in progress
   */
  isActionInProgress(actionType?: string): boolean {
    if (!this.actionLock || !this.pendingAction) return false
    if (!actionType) return true
    return this.actionsConflict({ type: actionType } as Action, this.pendingAction.action)
  }

  /**
   * Get current pending action info (for debugging)
   */
  getPendingAction(): PendingAction | null {
    return this.pendingAction
  }
}

// Singleton instance
export const actionBus = new ActionBus()

// Logging middleware (dev only)
if (import.meta.env.DEV) {
  actionBus.use(async (action, next) => {
    const start = performance.now()
    console.groupCollapsed(`[Action] ${action.type}`)
    console.log('Payload:', 'payload' in action ? action.payload : undefined)
    
    const result = await next()
    
    const duration = (performance.now() - start).toFixed(2)
    console.log('Result:', result)
    console.log(`Duration: ${duration}ms`)
    console.groupEnd()
    
    return result
  })
}
