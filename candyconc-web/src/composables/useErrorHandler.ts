/**
 * useErrorHandler Composable - Centralized error handling with retry logic
 */

import { ref, shallowRef } from 'vue'
import { useUiStore } from '@/stores'
import type { Action } from '@/actions/types'
import { t } from '@/i18n'

export type ErrorType = 'network' | 'auth' | 'validation' | 'server' | 'unknown'

export interface AppError {
  id: string
  message: string
  type: ErrorType
  context: ErrorContext
  timestamp: number
  retryable: boolean
  originalError?: Error
}

export interface ErrorContext {
  action?: Action
  component?: string
  operation?: string
}

export interface RetryableAction {
  action: Action
  attempts: number
  maxAttempts: number
  backoffMs: number
  lastError?: AppError
}

// Singleton state (shared across all usages)
const errors = ref<AppError[]>([])
const retryQueue = shallowRef<RetryableAction[]>([])
const isRetrying = ref(false)
const maxErrorHistory = 50

/**
 * Classify error type based on error characteristics
 */
function classifyError(error: Error): ErrorType {
  const message = error.message.toLowerCase()
  const name = error.name.toLowerCase()

  // Network errors (note: parentheses fix operator precedence bug)
  if (
    (name === 'typeerror' && message.includes('failed to fetch')) ||
    message.includes('network') ||
    message.includes('timeout') ||
    message.includes('abort') ||
    message.includes('econnrefused') ||
    message.includes('offline')
  ) {
    return 'network'
  }

  // Authentication errors
  if (
    message.includes('401') ||
    message.includes('403') ||
    message.includes('unauthorized') ||
    message.includes('forbidden') ||
    message.includes('authentication')
  ) {
    return 'auth'
  }

  // Validation errors
  if (
    message.includes('400') ||
    message.includes('422') ||
    message.includes('validation') ||
    message.includes('invalid')
  ) {
    return 'validation'
  }

  // Server errors
  if (
    message.includes('500') ||
    message.includes('502') ||
    message.includes('503') ||
    message.includes('504') ||
    message.includes('server')
  ) {
    return 'server'
  }

  return 'unknown'
}

/**
 * Determine if an error is retryable
 */
function isRetryable(error: Error, type: ErrorType): boolean {
  // Network and server errors are generally retryable
  if (type === 'network' || type === 'server') {
    return true
  }

  // Specific HTTP codes that are retryable
  const message = error.message
  if (message.includes('429') || message.includes('503') || message.includes('504')) {
    return true
  }

  // Auth and validation errors are not retryable
  return false
}

/**
 * Get user-friendly error message
 */
function getDisplayMessage(type: ErrorType, originalMessage: string): string {
  switch (type) {
    case 'network':
      return t('errors.handler.network')
    case 'auth':
      return t('errors.handler.auth')
    case 'validation':
      return t('errors.handler.validation', { message: originalMessage })
    case 'server':
      return t('errors.handler.server')
    default:
      return originalMessage || t('errors.handler.unexpected')
  }
}

export function useErrorHandler() {
  const uiStore = useUiStore()

  /**
   * Handle an error with optional context
   */
  async function handleError(error: Error, context: ErrorContext = {}): Promise<AppError> {
    const type = classifyError(error)
    const retryable = isRetryable(error, type)

    const appError: AppError = {
      id: crypto.randomUUID(),
      message: getDisplayMessage(type, error.message),
      type,
      context,
      timestamp: Date.now(),
      retryable,
      originalError: error
    }

    // Add to error history
    errors.value = [appError, ...errors.value.slice(0, maxErrorHistory - 1)]

    // Add to retry queue if retryable and has action
    if (retryable && context.action) {
      const existingRetry = retryQueue.value.find(
        r => r.action.type === context.action!.type
      )

      if (!existingRetry) {
        retryQueue.value = [
          ...retryQueue.value,
          {
            action: context.action,
            attempts: 0,
            maxAttempts: 3,
            backoffMs: 1000,
            lastError: appError
          }
        ]
      }
    }

    // Show toast notification
    const toastType = type === 'network' ? 'warning' : 'error'
    uiStore.showToast(appError.message, toastType)

    // Log in dev mode
    if (import.meta.env.DEV) {
      console.error(`[ErrorHandler] ${type}:`, error, context)
    }

    return appError
  }

  /**
   * Retry a specific action
   */
  async function retryAction(
    item: RetryableAction,
    dispatcher: (action: Action) => Promise<unknown>
  ): Promise<boolean> {
    if (item.attempts >= item.maxAttempts) {
      return false
    }

    // Exponential backoff
    const delay = item.backoffMs * Math.pow(2, item.attempts)
    await new Promise(resolve => setTimeout(resolve, delay))

    item.attempts++

    try {
      await dispatcher(item.action)

      // Remove from retry queue on success
      retryQueue.value = retryQueue.value.filter(r => r !== item)

      uiStore.showToast(t('errors.handler.retried'), 'success')
      return true
    } catch (error) {
      if (error instanceof Error) {
        item.lastError = await handleError(error, { action: item.action })
      }
      return false
    }
  }

  /**
   * Retry all pending actions
   */
  async function retryAll(
    dispatcher: (action: Action) => Promise<unknown>
  ): Promise<{ succeeded: number; failed: number }> {
    if (isRetrying.value || retryQueue.value.length === 0) {
      return { succeeded: 0, failed: 0 }
    }

    isRetrying.value = true
    let succeeded = 0
    let failed = 0

    // Create a copy to iterate over (original will be modified)
    const itemsToRetry = [...retryQueue.value]

    for (const item of itemsToRetry) {
      if (item.attempts < item.maxAttempts) {
        const success = await retryAction(item, dispatcher)
        if (success) {
          succeeded++
        } else {
          failed++
        }
      } else {
        // Max attempts reached, remove from queue
        retryQueue.value = retryQueue.value.filter(r => r !== item)
        failed++
      }
    }

    isRetrying.value = false
    return { succeeded, failed }
  }

  /**
   * Clear a specific error from history
   */
  function clearError(errorId: string): void {
    errors.value = errors.value.filter(e => e.id !== errorId)
  }

  /**
   * Clear all errors
   */
  function clearAllErrors(): void {
    errors.value = []
  }

  /**
   * Clear retry queue
   */
  function clearRetryQueue(): void {
    retryQueue.value = []
  }

  /**
   * Remove a specific item from retry queue
   */
  function removeFromRetryQueue(action: Action): void {
    retryQueue.value = retryQueue.value.filter(r => r.action !== action)
  }

  /**
   * Get errors filtered by type
   */
  function getErrorsByType(type: ErrorType): AppError[] {
    return errors.value.filter(e => e.type === type)
  }

  /**
   * Get recent errors (last N)
   */
  function getRecentErrors(count: number = 5): AppError[] {
    return errors.value.slice(0, count)
  }

  return {
    // State (reactive)
    errors,
    retryQueue,
    isRetrying,

    // Actions
    handleError,
    retryAction,
    retryAll,
    clearError,
    clearAllErrors,
    clearRetryQueue,
    removeFromRetryQueue,

    // Queries
    getErrorsByType,
    getRecentErrors,

    // Utilities
    classifyError,
    isRetryable: (error: Error) => isRetryable(error, classifyError(error))
  }
}
