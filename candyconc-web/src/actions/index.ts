export * from './types'
export { actionBus } from './bus'

// Action Metadata Registry
export {
  getActionMeta,
  getActionMetaFromAction,
  requiresConfirmation,
  hasScientificRisk,
  getScientificRisks,
  isReversible,
  isHighCost,
  getAllActionTypes,
  getRegistry,
  getPolicyDecision,
  getConfirmationReason,
  type PolicyDecision,
} from './registry'

// Policy Gate Middleware
export {
  createProductCapabilityGateMiddleware,
  capabilityBlockReasonForAction,
} from './productGate'

export {
  createPolicyGateMiddleware,
  pendingPreviews,
  currentPreview,
  addActionPreview,
  resolvePreview,
  getUnresolvedPreviews,
  clearPreviews,
  enterCopilotContext,
  exitCopilotContext,
  isInCopilotContext,
  actionRequestToAction,
  executeCopilotActionRequest,
  type PendingActionPreview,
} from './policyGate'

// Trace Recorder Middleware
export {
  createTraceRecorderMiddleware,
  traceHistory,
  runRecords,
  currentStateHash,
  updateStateHash,
  shouldCreateRun,
  createRunRecord,
  addRunNote,
  getRunRecord,
  getRunsForQuery,
  getRecentRuns,
  setCurrentActionSource,
  getCurrentActionSource,
  exportTraceHistory,
  clearTraceData,
  getTraceSummary,
} from './traceRecorder'
