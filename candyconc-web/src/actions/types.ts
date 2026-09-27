/**
 * Action System - Shared between UI and Copilot
 * 
 * Both UI components and the Copilot execute actions through this unified system.
 * This enables the Copilot to "use" the UI just like a human would.
 */

import type { RunRecordResearchScopeEvidence } from '@/types/copilot-protocol'
import type { CollocationNetworkMeasure } from '@/api/client'
import type { CollocationMeasure } from '@/lib/collocationMeasure'

// ============================================
// Query Actions
// ============================================

export interface ExecuteQueryAction {
  type: 'query/execute'
  payload: {
    term: string
    contextSize?: number
    docsetId?: string
    filters?: QueryFilters
  }
}

export interface SetFiltersAction {
  type: 'query/setFilters'
  payload: QueryFilters
}

export interface ClearQueryAction {
  type: 'query/clear'
}

export interface LoadMoreQueryAction {
  type: 'query/loadMore'
  payload?: {
    direction?: 'next' | 'prev'
  }
}

export interface QueryFilters {
  corpus?: string
  dateRange?: { from: string; to: string }
  metadata?: Record<string, string>
}

// ============================================
// KWIC Table Actions
// ============================================

export interface ScrollToRowAction {
  type: 'kwic/scrollToRow'
  payload: { index: number }
}

export interface SelectRowsAction {
  type: 'kwic/selectRows'
  payload: { indices: number[] }
}

export interface HighlightRowAction {
  type: 'kwic/highlightRow'
  payload: { index: number; source: 'user' | 'copilot' }
}

export interface ExpandContextAction {
  type: 'kwic/expandContext'
  payload: { index: number; contextSize: number }
}

// ============================================
// Analysis Actions
// ============================================

export interface RunCollocationsAction {
  type: 'analysis/collocations'
  payload: {
    term?: string
    windowSize?: number
    withinSentence?: boolean
    measure?: CollocationMeasure
    minFreq?: number
    limit?: number
    corpus?: string
    docsetId?: string
  }
}

export interface RunCollocationNetworkAction {
  type: 'analysis/collocationNetwork'
  payload: {
    term?: string
    windowSize?: number
    measure?: CollocationNetworkMeasure
    maxNodes?: number
    expandDepth?: 1 | 2
    minCount?: number
    withinSentence?: boolean
  }
}

export interface RunFrequencyAction {
  type: 'analysis/frequency'
  payload: {
    groupBy?: 'word' | 'lemma' | 'pos'
    sortBy?: 'freq' | 'alpha'
    limit?: number
    stopwords?: string[] | string
  }
}

export interface RunNgramFrequencyAction {
  type: 'analysis/ngramFrequency'
  payload: {
    n?: number
    minN?: number
    maxN?: number
    minFreq?: number
    limit?: number
    sortBy?: 'frequency' | 'relative'
  }
}

export interface RunNgramContrastAction {
  type: 'analysis/ngramContrast'
  payload: {
    targetDocsetId?: string
    referenceDocsetId?: string
    n?: number
    minN?: number
    maxN?: number
    minFreq?: number
    limit?: number
    corpus?: string
  }
}

export interface RunKeynessAction {
  type: 'analysis/keyness'
  payload: {
    targetDocsetId?: string
    referenceDocsetId?: string
    pos?: string
    corpus?: string
    referenceSource?: 'docset' | 'corpus' | 'whole'
    referenceCorpus?: string
    minFreq?: number
    limit?: number
  }
}

export interface RunFreeContrastAction {
  type: 'analysis/freeContrast'
  payload: {
    term?: string
    targetDocsetId?: string
    targetSubcorpus?: string
    referenceDocsetId?: string
    referenceSubcorpus?: string
    windowSize?: number
    withinSentence?: boolean
    measure?: 'mi' | 'logdice' | 'tscore' | 'lmi' | 'npmi' | 'z'
    limit?: number
    corpus?: string
  }
}

export interface RunCollocationContrastAction {
  type: 'analysis/collocationContrast'
  payload: {
    term?: string
    targetDocsetId?: string
    referenceDocsetId?: string
    windowSize?: number
    withinSentence?: boolean
    measure?: 'mi' | 'logdice' | 'tscore' | 'lmi' | 'npmi' | 'z'
    limit?: number
    corpus?: string
  }
}

export interface RunLexicalDiversityAction {
  type: 'analysis/lexicalDiversity'
  payload: {
    targetDocsetId?: string
    referenceDocsetId?: string
    docsetId?: string
    corpus?: string
    window?: number
  }
}

export interface RunWordSketchAction {
  type: 'analysis/wordSketch'
  payload: {
    term?: string
    limit?: number
    docsetId?: string
    corpus?: string
  }
}

export interface RunWordSketchDiffAction {
  type: 'analysis/wordSketchDiff'
  payload: {
    termA?: string
    termB?: string
    limit?: number
    docsetId?: string
    corpus?: string
  }
}

export interface RunDispersionAction {
  type: 'analysis/dispersion'
  payload: {
    term?: string
    partitions?: number
  }
}

export interface RunSemanticSearchAction {
  type: 'analysis/semantic'
  payload: {
    query: string
    topK?: number
    mode?: 'passage' | 'thesaurus'
  }
}

// ============================================
// Navigation Actions
// ============================================

export interface SwitchTabAction {
  type: 'nav/switchTab'
  payload: { tab: 'kwic' | 'frequency' | 'collocations' | 'collocation_network' | 'dispersion' | 'semantic' | 'ngrams' | 'contrast' | 'keyness' | 'wordsketch' }
}

export interface OpenDocumentAction {
  type: 'nav/openDocument'
  payload: {
    docId: string
    corpus?: string
    fallbackLabel?: string
    fallbackMeta?: Record<string, string>
    highlightPosition?: number
    highlight?: string
    highlightLeft?: string
    highlightRight?: string
  }
}

// ============================================
// Copilot Actions
// ============================================

export interface SetAutonomyAction {
  type: 'copilot/setAutonomy'
  payload: {
    level: number  // 0-10
  }
}

export interface OpenCopilotAction {
  type: 'copilot/open'
  payload?: { mode?: 'minimized' | 'floating' | 'docked' }
}

export interface CloseCopilotAction {
  type: 'copilot/close'
}

export interface SendMessageAction {
  type: 'copilot/sendMessage'
  payload: { message: string }
}

export interface AnswerClarificationAction {
  type: 'copilot/answerClarification'
  payload: { questionId: string; optionId: string }
}

export interface ContinueCopilotAction {
  type: 'copilot/continue'
  payload: { sessionId: string }
}

// ============================================
// Bookmark Actions
// ============================================

export interface AddBookmarkAction {
  type: 'bookmark/add'
  payload: {
    positions: number[]
    label?: string
    color?: string
  }
}

export interface RemoveBookmarkAction {
  type: 'bookmark/remove'
  payload: { id: string }
}

export interface ClearBookmarksAction {
  type: 'bookmark/clear'
}

// ============================================
// Export Actions
// ============================================

export interface ExportDataAction {
  type: 'export/data'
  payload: {
    format: 'pdf' | 'docx' | 'csv' | 'tsv' | 'json' | 'jsonl' | 'latex' | 'evidence-json'
    selection?: 'all' | 'selected' | 'filtered'
    scope?: 'loaded' | 'all-server'
  }
}

// ============================================
// UI Actions
// ============================================

export interface ShowToastAction {
  type: 'ui/toast'
  payload: {
    message: string
    type: 'info' | 'success' | 'warning' | 'error'
    duration?: number
  }
}

export interface SetLoadingAction {
  type: 'ui/setLoading'
  payload: {
    key: string
    loading: boolean
  }
}

// ============================================
// Union Type
// ============================================

export type Action =
  // Query
  | ExecuteQueryAction
  | SetFiltersAction
  | ClearQueryAction
  | LoadMoreQueryAction
  // KWIC
  | ScrollToRowAction
  | SelectRowsAction
  | HighlightRowAction
  | ExpandContextAction
  // Analysis
  | RunCollocationsAction
  | RunCollocationNetworkAction
  | RunFrequencyAction
  | RunNgramFrequencyAction
  | RunNgramContrastAction
  | RunKeynessAction
  | RunFreeContrastAction
  | RunCollocationContrastAction
  | RunLexicalDiversityAction
  | RunWordSketchAction
  | RunWordSketchDiffAction
  | RunDispersionAction
  | RunSemanticSearchAction
  // Navigation
  | SwitchTabAction
  | OpenDocumentAction
  // Copilot
  | SetAutonomyAction
  | OpenCopilotAction
  | CloseCopilotAction
  | SendMessageAction
  | AnswerClarificationAction
  | ContinueCopilotAction
  // Bookmarks
  | AddBookmarkAction
  | RemoveBookmarkAction
  | ClearBookmarksAction
  // Export
  | ExportDataAction
  // UI
  | ShowToastAction
  | SetLoadingAction

// ============================================
// Action Source
// ============================================

export type ActionSource = 'user' | 'copilot' | 'system' | 'restore' | 'template'
export type ActionPolicyDecision = 'execute' | 'preview' | 'block'

export interface ActionDispatchContext {
  /** Who initiated the dispatch. This is authoritative for policy checks. */
  readonly source: ActionSource
  /** Dispatch start time in epoch milliseconds. */
  readonly timestamp: number
  /** Optional upstream request id, e.g. from a Copilot ActionRequestV1. */
  readonly requestId?: string
  /** Optional backend run id, e.g. from a committed backend action. */
  readonly runId?: string
}

export type ActionDispatchOptions = Partial<ActionDispatchContext>

// ============================================
// Action Result
// ============================================

export interface ActionResult<T = unknown> {
  success: boolean
  data?: T
  error?: string
  /** Action was blocked due to conflict */
  blocked?: boolean
  /** Who initiated the action */
  source?: ActionSource
  /** Upstream action-request id, preserved for trace/replay joins. */
  requestId?: string
  /** Backend or trace run id, preserved for run/trace joins. */
  runId?: string
  /** Policy decision applied to the dispatch, if a gate evaluated it. */
  policyDecision?: ActionPolicyDecision
  /** Human-readable policy reason for blocked/previewed actions. */
  policyReason?: string
  /** Scope actually sent to the backend/API by this action. */
  executionScope?: Partial<RunRecordResearchScopeEvidence>
}

// ============================================
// Action Handler Type
// ============================================

export type ActionHandler<A extends Action = Action> = (
  action: A,
  context: ActionDispatchContext
) => Promise<ActionResult>

export type ActionMiddleware = (
  action: Action,
  next: () => Promise<ActionResult>,
  context: ActionDispatchContext
) => Promise<ActionResult>
