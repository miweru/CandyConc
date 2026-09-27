/**
 * Policy Gate Middleware
 *
 * Enforces autonomy-based policies for Copilot actions.
 * Determines whether an action should be executed, previewed, or blocked.
 *
 * This is the frontend enforcement layer. The backend has a mirror policy
 * for defense in depth.
 */

import { ref, shallowRef } from 'vue'
import { useCopilotStore } from '@/stores'
import {
  getActionMeta,
  getPolicyDecision,
  getConfirmationReason,
  type PolicyDecision,
} from './registry'
import type {
  Action,
  ActionDispatchOptions,
  ActionMiddleware,
  ActionResult,
  ActionSource,
} from './types'
import type { ActionMeta, ActionRequestV1 } from '@/types/copilot-protocol'
import { generateRequestId } from '@/utils/hashing'
import { t } from '@/i18n'

// ============================================================================
// Pending Action Preview State
// ============================================================================

export interface PendingActionPreview {
  requestId: string
  action: Action
  meta: ActionMeta | undefined
  decision: PolicyDecision
  rationale?: string
  confirmationReason: string | null
  timestamp: number
  resolved: boolean
  resolution?: 'approved' | 'rejected' | 'timeout'
}

// Reactive state for pending previews
export const pendingPreviews = ref<PendingActionPreview[]>([])
export const currentPreview = shallowRef<PendingActionPreview | null>(null)

// Callbacks for preview resolution
type PreviewCallback = (approved: boolean) => void
const previewCallbacks = new Map<string, PreviewCallback>()

// ============================================================================
// Preview Management
// ============================================================================

/**
 * Add a new action preview for user confirmation
 */
export function addActionPreview(
  action: Action,
  meta: ActionMeta | undefined,
  decision: PolicyDecision,
  rationale?: string,
  requestId?: string
): string {
  const resolvedId = requestId || generateRequestId()
  const preview: PendingActionPreview = {
    requestId: resolvedId,
    action,
    meta,
    decision,
    rationale,
    confirmationReason: getConfirmationReason(action),
    timestamp: Date.now(),
    resolved: false,
  }

  pendingPreviews.value.push(preview)
  currentPreview.value = preview

  return resolvedId
}

/**
 * Wait for user to approve or reject a preview
 */
export function waitForPreviewResolution(requestId: string): Promise<boolean> {
  return new Promise((resolve) => {
    previewCallbacks.set(requestId, resolve)

    // Timeout after 60 seconds
    setTimeout(() => {
      const callback = previewCallbacks.get(requestId)
      if (callback) {
        resolvePreview(requestId, false, 'timeout')
      }
    }, 60000)
  })
}

/**
 * Resolve a pending preview (approve or reject)
 */
export function resolvePreview(
  requestId: string,
  approved: boolean,
  resolution: 'approved' | 'rejected' | 'timeout' = approved ? 'approved' : 'rejected'
): void {
  const preview = pendingPreviews.value.find(p => p.requestId === requestId)
  if (preview && !preview.resolved) {
    preview.resolved = true
    preview.resolution = resolution
  }

  // Call and remove callback
  const callback = previewCallbacks.get(requestId)
  if (callback) {
    previewCallbacks.delete(requestId)
    callback(approved)
  }

  // Clear current preview if it was this one
  if (currentPreview.value?.requestId === requestId) {
    currentPreview.value = null
  }
}

/**
 * Get all unresolved previews
 */
export function getUnresolvedPreviews(): PendingActionPreview[] {
  return pendingPreviews.value.filter(p => !p.resolved)
}

/**
 * Clear all previews (for reset)
 */
export function clearPreviews(): void {
  // Reject all pending callbacks
  for (const [requestId, callback] of previewCallbacks) {
    callback(false)
    previewCallbacks.delete(requestId)
  }
  pendingPreviews.value = []
  currentPreview.value = null
}

// ============================================================================
// Policy Gate Middleware
// ============================================================================

/**
 * Create the policy gate middleware for the action bus
 */
export function createPolicyGateMiddleware(): ActionMiddleware {
  return async (
    action: Action,
    next: () => Promise<ActionResult>,
    context
  ): Promise<ActionResult> => {
    const source = context.source

    // User actions always pass through
    if (source === 'user') {
      return next()
    }

    // Get policy decision
    const copilotStore = useCopilotStore()
    const autonomyLevel = copilotStore.autonomyLevel
    const meta = getActionMeta(action.type)
    const decision = getPolicyDecision(action, autonomyLevel, source)

    // Execute: action can proceed
    if (decision === 'execute') {
      const result = await next()
      return { ...result, requestId: context.requestId, policyDecision: decision }
    }

    // Block: action is not allowed at this autonomy level
    if (decision === 'block') {
      const reason = meta
        ? t('capabilities.policy.blockedAtLevel', { label: meta.label, level: autonomyLevel })
        : t('capabilities.policy.unknownBlocked', { action: action.type })

      return {
        success: false,
        error: reason,
        blocked: true,
        source,
        requestId: context.requestId,
        policyDecision: decision,
        policyReason: reason,
      }
    }

    // Preview: show to user for confirmation
    if (decision === 'preview') {
      const requestId = addActionPreview(action, meta, decision, undefined, context.requestId)
      const policyReason = getConfirmationReason(action) ?? undefined

      // Wait for user decision
      const approved = await waitForPreviewResolution(requestId)

      if (!approved) {
        return {
          success: false,
          error: t('capabilities.policy.rejected'),
          blocked: true,
          source,
          requestId,
          policyDecision: decision,
          policyReason,
        }
      }

      // User approved, execute
      const result = await next()
      return { ...result, requestId, policyDecision: decision, policyReason }
    }

    // Fallback: execute
    return next()
  }
}

// ============================================================================
// Legacy Copilot Context Helpers
// ============================================================================

// Retained for existing imports. Policy decisions use ActionDispatchContext.
let inCopilotContext = false

/**
 * Mark that we're entering copilot action context
 */
export function enterCopilotContext(): void {
  inCopilotContext = true
}

/**
 * Mark that we're leaving copilot action context
 */
export function exitCopilotContext(): void {
  inCopilotContext = false
}

/**
 * Check if we're in copilot context
 */
export function isInCopilotContext(): boolean {
  return inCopilotContext
}

// ============================================================================
// Convert ActionRequestV1 to Action
// ============================================================================

/**
 * Convert a Copilot ActionRequestV1 to an internal Action
 */
export function actionRequestToAction(request: ActionRequestV1): Action {
  return {
    type: request.type,
    payload: request.payload,
  } as Action
}

/**
 * Execute a Copilot action request through the policy gate
 */
export async function executeCopilotActionRequest(
  request: ActionRequestV1,
  dispatch: (action: Action, context: ActionSource | ActionDispatchOptions) => Promise<ActionResult>
): Promise<ActionResult> {
  const action = actionRequestToAction(request)

  // Mark that we're in copilot context
  enterCopilotContext()

  try {
    return await dispatch(action, { source: 'copilot', requestId: request.requestId })
  } finally {
    exitCopilotContext()
  }
}
