import type { McpToolStatus } from '@/api/client'
import type { CopilotToolContractStatus } from '@/lib/copilotTools'
import { t } from '@/i18n'

export interface ToolCallEvidenceLike {
  status: string
  result?: unknown
}

export function toolResultHasSyntaxDiagnostic(result: unknown): boolean {
  const record = result && typeof result === 'object' && !Array.isArray(result)
    ? result as Record<string, unknown>
    : null
  if (!record || record.status !== 'error' || typeof record.query !== 'string') return false
  const diagnostics = record.diagnostics
  if (!diagnostics || typeof diagnostics !== 'object' || Array.isArray(diagnostics)) return false
  const errors = (diagnostics as { errors?: unknown }).errors
  return Array.isArray(errors) && errors.some((error) => typeof error === 'string' && error.trim())
}

export function copilotToolOperationIds(
  status: CopilotToolContractStatus,
): string[] {
  return status.status === 'unknown'
    ? []
    : [...new Set(status.operationIds ?? [])]
}

export function toolResultIntegrityReason(result: unknown): string | null {
  const record = result && typeof result === 'object' && !Array.isArray(result)
    ? result as Record<string, unknown>
    : null
  if (!record) return null
  if (record.blocked === true) {
    return String(record.error ?? record.reason ?? t('copilot.toolRuntime.blockedByPolicy'))
  }
  if (record.ok === false) {
    return String(record.error ?? record.reason ?? t('copilot.toolRuntime.resultError'))
  }
  if (record.status === 'error') {
    return String(record.error ?? record.reason ?? t('copilot.toolRuntime.resultError'))
  }
  if (record.status === 'not_applicable') {
    return String(record.reason ?? record.detail ?? t('copilot.toolRuntime.notApplicable'))
  }
  if (typeof record.error === 'string' && record.error.trim()) {
    return record.error
  }
  return null
}

export function toolCallHasComputedEvidenceCandidate(
  toolCall: ToolCallEvidenceLike,
): boolean {
  if (toolResultHasSyntaxDiagnostic(toolCall.result)) return true
  if (toolCall.status !== 'success') return false
  if (toolResultIntegrityReason(toolCall.result)) return false
  const result = toolCall.result
  return !(
    result &&
    typeof result === 'object' &&
    !Array.isArray(result) &&
    (result as { status?: unknown }).status === 'no-action'
  )
}

export function mcpToolRuntimeLabel(toolStatus: McpToolStatus | undefined): string | null {
  if (!toolStatus) return null
  if (toolStatus.dispatchable && toolStatus.status === 'operation_bound') {
    return t('copilot.toolRuntime.available')
  }
  if (!toolStatus.dispatchable) {
    return t('copilot.toolRuntime.blocked')
  }
  return t('copilot.toolRuntime.open')
}

export function mcpToolRuntimeBlockReason(
  toolName: string,
  contractStatus: CopilotToolContractStatus,
  toolStatus: McpToolStatus | undefined,
): string | null {
  if (!toolStatus) return null
  if (!toolStatus.dispatchable) {
    return t('copilot.toolRuntime.blockedNotEvidence', { tool: toolName })
  }

  const contractOperationIds = copilotToolOperationIds(contractStatus)
  const runtimeOperationIds = toolStatus.product_operation_ids ?? []
  if (
    contractOperationIds.length &&
    runtimeOperationIds.length &&
    !contractOperationIds.some((operationId) => runtimeOperationIds.includes(operationId))
  ) {
    return t('copilot.toolRuntime.mismatch', { tool: toolName })
  }
  return null
}
