/**
 * Copilot Protocol Types v1.0
 *
 * Structured contracts between Frontend and Backend for a scientifically
 * reproducible, auditable corpus assistant.
 *
 * Core principles:
 * - Perception: UIContextSnapshot (serialized UI state)
 * - Planning: PlanV1 (explicit goals, hypotheses, steps)
 * - Execution: ActionRequestV1 (via Action Bus, not direct mutations)
 */

// ============================================================================
// Gate Classification
// ============================================================================

/**
 * Gate classification for copilot-initiated actions.
 *
 * Each class describes what an action does (not a risk diagnosis) and feeds
 * the policy gate: any non-'none' class forces a preview at autonomy <= 8.
 * Only classes that are actually assigned in the action registry may exist
 * here (enforced by scientificRiskClasses.test.ts).
 */
export type ScientificRisk =
  | 'none'
  | 'parameter_drift'    // Action changes analysis parameters
  | 'interpretation_leap' // Action output requires interpretation beyond computed evidence
  | 'export_privacy'     // Action exports data out of the application

// ============================================================================
// Action Metadata (for Policy Gate)
// ============================================================================

export interface ActionMeta {
  type: string
  label: string
  reversible: boolean
  userVisible: boolean
  cost: 'low' | 'medium' | 'high'
  scientificRisk: ScientificRisk[]
  requiresConfirmationAtOrBelowAutonomy: number // 0-10
  preconditions?: string[] // e.g., "query.term exists"
}

// ============================================================================
// UI Context Snapshot (Frontend → Backend)
// ============================================================================

export interface SubcorpusFilter {
  field: string
  op: 'eq' | 'in' | 'range' | 'contains'
  value: unknown
}

export interface KwicPreviewRow {
  rowId: string
  left: string
  match: string
  right: string
  docId?: string
  position?: number
}

export interface RecentActionSummary {
  id: string
  ts: number
  source: 'user' | 'copilot'
  type: string
  ok: boolean
  summary?: string
  payloadHash?: string
}

export interface UIContextSnapshotV1 {
  version: '1.0'
  ts: number // epoch ms

  session: {
    userId?: string
    workspaceId?: string
    conversationId: string
    autonomy: number // 0-10
    locale: 'de' | 'en'
  }

  view: {
    activeTab: 'kwic' | 'frequency' | 'collocations' | 'dispersion' | 'semantic' | 'keyness' | 'contrast' | 'wordsketch' | 'ngrams'
    theme: 'dark' | 'light'
  }

  corpus: {
    corpusId: string
    subcorpus: {
      filters: SubcorpusFilter[]
      size?: { docs?: number; tokens?: number }
      hash?: string // stable hash of filters + corpusId
    }
  }

  query: {
    mode: 'term' | 'cqlf'
    term?: string
    cqlf?: string
    context: { left: number; right: number }
    options: {
      caseSensitive: boolean
      diacriticsSensitive?: boolean
      lemmatize?: boolean
      regex?: boolean
    }
    lastExecuted?: { ts: number; hash: string }
  }

  kwic: {
    resultSet?: { hash: string; rows: number }
    selection: {
      rowIds: string[]
      anchorRowId?: string
    }
    preview: KwicPreviewRow[] // 5-20 exemplary rows
  }

  analyses: {
    collocations?: {
      term?: string
      measure?: 'mi' | 'logDice' | 'tScore'
      window?: { left: number; right: number }
      direction?: 'both' | 'left' | 'right'
      lastRunId?: string
    }
    frequency?: {
      groupBy?: 'word' | 'lemma' | 'pos' | string
      lastRunId?: string
    }
    dispersion?: {
      measure?: 'griesDP' | string
      strata?: string
      lastRunId?: string
    }
    semantic?: {
      lastQuery?: string
      lastRunId?: string
    }
  }

  history: {
    recentActions: RecentActionSummary[] // last 10-20 actions
  }
}

// ============================================================================
// Copilot SSE Events (Backend → Frontend)
// ============================================================================

export type CopilotEventType =
  | 'copilot.delta'
  | 'copilot.message'
  | 'copilot.plan'
  | 'copilot.clarify'
  | 'copilot.action_request'
  | 'copilot.action_preview'
  | 'copilot.action_commit'
  | 'copilot.action_result'
  | 'copilot.tool_result'
  | 'copilot.error'
  | 'copilot.heartbeat'

export interface CopilotEventEnvelope<T = unknown> {
  event: CopilotEventType
  id: string
  ts: number
  payload: T
}

// Event Payloads

export interface DeltaPayload {
  text: string
}

export interface MessagePayload {
  text: string
  messageId: string
}

export interface PlanPayload {
  plan: PlanV1
}

export interface ClarifyPayload {
  question: ClarifyV1
}

export interface ActionPreviewPayload {
  request: ActionRequestV1
  meta: ActionMeta
  rationale?: string
}

export interface ActionCommitPayload {
  requestId: string
  request?: ActionRequestV1
  runId?: string
  ok?: boolean
  resultSummary?: string
  error?: string
}

export interface ActionResultPayload {
  requestId: string
  ok: boolean
  request?: ActionRequestV1
  output?: unknown
  result?: unknown
  resultRef?: {
    type?: string
    hash?: string
    rows?: number
  }
  corpus?: {
    corpusId?: string
    subcorpusHash?: string
  }
  queryHash?: string
  evidence?: RunRecordEvidenceV2
  resultSummary?: string
  error?: string
  runId?: string
  ts?: number
}

export interface ToolResultPayload {
  toolResult: ToolResultV1
}

export interface ErrorPayload {
  where: string
  message: string
  details?: Record<string, unknown>
}

// ============================================================================
// Plan (Assistant → UI)
// ============================================================================

export interface PlanStepV1 {
  stepId: string
  title: string
  id?: string
  description?: string
  action?: ActionRequestV1
  expectedOutput: string
  rationale?: string
  /** Toolname aus Backend-Plan-Gate-Steps ({tool: name}); Titel-Fallback. */
  tool?: string
}

export interface PlanV1 {
  goal: string
  steps: PlanStepV1[]
  /** Overall expected outcome as emitted by the backend plan events. */
  expectedOutcome?: string
  /** Plan status as emitted by the backend (e.g. pending approval). */
  status?: string
}

// ============================================================================
// Clarification (Assistant → UI)
// ============================================================================

export interface ClarifyOptionV1 {
  id: string
  label: string
  value: unknown
  source?: 'snapshot' | 'user' | 'assistant'
  isDefault?: boolean
}

export interface ClarifyV1 {
  questionId: string
  prompt: string
  blocking: boolean // if true, no meaningful action possible without answer
  options: ClarifyOptionV1[]
  freeInput?: {
    label: string
    placeholder?: string
  }
  rationale?: string
}

// ============================================================================
// Action Request (Assistant → Frontend Action Bus)
// ============================================================================

export interface RunRecordHint {
  kind: 'analysis' | 'query'
  label?: string
}

export interface ActionRequestV1 {
  requestId: string
  type: string // e.g., "query/execute"
  payload: Record<string, unknown>
  autonomyHint?: number // 0-10, how confident the assistant is
  rationale?: string // brief methodological justification
  runRecord?: RunRecordHint
}

// ============================================================================
// Tool Result (MCP or Backend Tools → Frontend)
// ============================================================================

export interface ToolCitation {
  label: string
  ref: string
}

export interface ToolResultV1 {
  toolName: string
  ok: boolean
  ts: number
  input?: unknown
  output?: unknown
  citations?: ToolCitation[]
  suggestedActions?: ActionRequestV1[]
  /**
   * Der Aufruf wurde aus dem Zwischenspeicher bedient, es lief keine
   * Abfrage. Das Backend sendet das Flag als Geschwister von `output`
   * (orchestrator.py:3520), das Frontend hat es verworfen. Eine Ansicht,
   * die einen Zwischenspeicher-Treffer als geleistete Arbeit zeigt,
   * erzeugt Belege fuer Arbeit, die nicht stattgefunden hat.
   */
  reused?: boolean
  /** Der Aufruf wurde uebersprungen (orchestrator.py:3562). */
  skipped?: boolean
}

// ============================================================================
// Run Record (Frontend, for reproducibility)
// ============================================================================

export type RunRecordSchemaVersion = '1.0' | '2.0'
export type RunEvidenceProvenance = 'frontend_actionbus' | 'backend_action_result' | 'imported_legacy'
export type RunEvidenceCompleteness = 'full' | 'partial' | 'legacy_partial'
export type RunEvidenceResearchScopeStatus = 'corpus' | 'fresh' | 'dirty' | 'stale' | 'warning' | 'unknown'

export interface RunRecordResearchScopeEvidence {
  corpusId: string
  scopeHash: string
  scopeStatus: RunEvidenceResearchScopeStatus
  label?: string
  docsetId?: string
  subcorpusName?: string
  queryHash?: string
  filterSpecHash?: string
  metadataSchemaHash?: string
}

export interface RunRecordEvidenceV2 {
  schemaVersion: '2.0'
  provenance: RunEvidenceProvenance
  completeness: RunEvidenceCompleteness
  corpusFingerprint: {
    corpusId: string
    subcorpusHash: string
    queryHash?: string
    indexFingerprint?: string
    metadataSchemaHash?: string
  }
  researchScope?: RunRecordResearchScopeEvidence
  toolFingerprint: {
    actionType: string
    toolSchemaHash?: string
  }
  resultFingerprint: {
    resultType: string
    resultHash?: string
    rows?: number
    queryTraceId?: string
    backendQueryTraceId?: string
  }
  warnings: string[]
}

export interface RunRecordV1 {
  schemaVersion: RunRecordSchemaVersion
  runId: string
  requestId?: string
  ts: number
  kind: 'query' | 'analysis'
  actionType: string
  actionPayload: Record<string, unknown>
  corpus: {
    corpusId: string
    subcorpusHash: string
  }
  queryHash?: string
  resultRef: {
    type: string
    hash?: string
    rows?: number
  }
  summary: string
  notes?: string[] // methodological notes
  evidence: RunRecordEvidenceV2
}

// ============================================================================
// Trace Event (Frontend, for audit)
// ============================================================================

export interface TraceEventV1 {
  id: string
  ts: number
  actor: 'user' | 'copilot' | 'backend'
  source?: 'user' | 'copilot' | 'system' | 'restore' | 'template' | 'backend'
  requestId?: string
  actionType: string
  payloadHash: string
  ok: boolean
  policyDecision?: 'execute' | 'preview' | 'block'
  policyReason?: string
  uiStateHashBefore?: string
  uiStateHashAfter?: string
  linkRunId?: string
}

// ============================================================================
// Policy Levels (deterministic autonomy mapping)
// ============================================================================

export const AUTONOMY_POLICY = {
  // 0-2: Suggest only, no auto-execution
  SUGGEST_ONLY: { min: 0, max: 2 },
  // 3-5: Reversible UI actions auto, API calls need confirmation
  REVERSIBLE_AUTO: { min: 3, max: 5 },
  // 6-8: Queries/analyses auto if preconditions met, risks need preview
  ANALYSIS_AUTO: { min: 6, max: 8 },
  // 9-10: Action chains auto
  FULL_AUTO: { min: 9, max: 10 },
} as const

export function getAutonomyTier(level: number): keyof typeof AUTONOMY_POLICY {
  if (level <= 2) return 'SUGGEST_ONLY'
  if (level <= 5) return 'REVERSIBLE_AUTO'
  if (level <= 8) return 'ANALYSIS_AUTO'
  return 'FULL_AUTO'
}
