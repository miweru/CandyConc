/**
 * useActions Composable - Register action handlers for components
 */

import { onMounted, onUnmounted } from 'vue'
import { actionBus, type Action, type ActionHandler } from '@/actions'

type ActionType = Action['type']
type ActionOfType<T extends ActionType> = Extract<Action, { type: T }>

/**
 * Register action handlers that auto-cleanup on unmount
 * 
 * Usage:
 * ```ts
 * useActions({
 *   'query/execute': async (action) => {
 *     // Handle query execution
 *     return { success: true, data: results }
 *   },
 *   'kwic/scrollToRow': async (action) => {
 *     // Scroll to specific row
 *     tableRef.value?.scrollToIndex(action.payload.index)
 *     return { success: true }
 *   }
 * })
 * ```
 */
export function useActions(
  handlers: Partial<{ [K in ActionType]: ActionHandler<ActionOfType<K>> }>
) {
  const cleanups: Array<() => void> = []

  onMounted(() => {
    for (const [type, handler] of Object.entries(handlers)) {
      if (handler) {
        const cleanup = actionBus.register(type as ActionType, handler as ActionHandler)
        cleanups.push(cleanup)
      }
    }
  })

  onUnmounted(() => {
    cleanups.splice(0).forEach(cleanup => cleanup())
  })

  return {
    dispatch: actionBus.dispatch.bind(actionBus)
  }
}

/**
 * Simple dispatch helper without handler registration
 */
export function useDispatch() {
  return {
    dispatch: actionBus.dispatch.bind(actionBus),
    dispatchBatch: actionBus.dispatchBatch.bind(actionBus)
  }
}
