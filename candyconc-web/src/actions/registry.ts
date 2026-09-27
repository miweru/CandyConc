/**
 * Action Metadata Registry
 *
 * Provides metadata for each action type including:
 * - Policy information (autonomy thresholds, confirmation requirements)
 * - Gate classification (what the action does: parameter changes, exports, ...)
 * - Cost estimates
 * - Preconditions
 *
 * This registry is used by the Policy Gate to determine whether
 * Copilot actions should be executed, previewed, or blocked.
 */

import type { ActionMeta, ScientificRisk } from '@/types/copilot-protocol'
import type { Action, ActionPolicyDecision, ActionSource } from './types'
import { t } from '@/i18n'

// ============================================================================
// Action Metadata Definitions
// ============================================================================

const actionMetaRegistry: Record<string, ActionMeta> = {
  // ---- Query Actions ----
  'query/execute': {
    type: 'query/execute',
    get label() { return t('actions.registry.queryExecute') },
    reversible: true, // Can clear/change query
    userVisible: true,
    cost: 'high', // API call, potentially slow
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['payload.term is non-empty'],
  },

  'query/setFilters': {
    type: 'query/setFilters',
    get label() { return t('actions.registry.querySetfilters') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 4,
  },

  'query/clear': {
    type: 'query/clear',
    get label() { return t('actions.registry.queryClear') },
    reversible: false, // Data is lost
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 3,
  },

  'query/loadMore': {
    type: 'query/loadMore',
    get label() { return t('actions.registry.queryLoadmore') },
    reversible: true,
    userVisible: true,
    cost: 'medium',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 4,
  },

  // ---- KWIC Actions ----
  'kwic/scrollToRow': {
    type: 'kwic/scrollToRow',
    get label() { return t('actions.registry.kwicScrolltorow') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0, // Always auto
  },

  'kwic/selectRows': {
    type: 'kwic/selectRows',
    get label() { return t('actions.registry.kwicSelectrows') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 2,
  },

  'kwic/highlightRow': {
    type: 'kwic/highlightRow',
    get label() { return t('actions.registry.kwicHighlightrow') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0, // Always auto
  },

  'kwic/expandContext': {
    type: 'kwic/expandContext',
    get label() { return t('actions.registry.kwicExpandcontext') },
    reversible: true,
    userVisible: true,
    cost: 'medium', // May need API call
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 3,
  },

  // ---- Analysis Actions ----
  'analysis/collocations': {
    type: 'analysis/collocations',
    get label() { return t('actions.registry.analysisCollocations') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift'], // Window size, measure can affect results
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['query.hasResults'],
  },

  'analysis/collocationNetwork': {
    type: 'analysis/collocationNetwork',
    get label() { return t('actions.registry.analysisCollocationnetwork') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['interpretation_leap', 'parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['query.term is non-empty'],
  },

  'analysis/frequency': {
    type: 'analysis/frequency',
    get label() { return t('actions.registry.analysisFrequency') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift'], // GroupBy affects interpretation
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['query.hasResults'],
  },

  'analysis/ngramFrequency': {
    type: 'analysis/ngramFrequency',
    get label() { return t('actions.registry.analysisNgramfrequency') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['active corpus or docset is available'],
  },

  'analysis/ngramContrast': {
    type: 'analysis/ngramContrast',
    get label() { return t('actions.registry.analysisNgramcontrast') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['target docset and reference docset are available'],
  },

  'analysis/keyness': {
    type: 'analysis/keyness',
    get label() { return t('actions.registry.analysisKeyness') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['target docset and explicit reference source/docset are available'],
  },

  'analysis/freeContrast': {
    type: 'analysis/freeContrast',
    get label() { return t('actions.registry.analysisFreecontrast') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift', 'interpretation_leap'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['term and two explicit docset/subcorpus sides are available'],
  },

  'analysis/collocationContrast': {
    type: 'analysis/collocationContrast',
    get label() { return t('actions.registry.analysisCollocationcontrast') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift', 'interpretation_leap'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['term, target docset and reference docset are available'],
  },

  'analysis/lexicalDiversity': {
    type: 'analysis/lexicalDiversity',
    get label() { return t('actions.registry.analysisLexicaldiversity') },
    reversible: true,
    userVisible: true,
    cost: 'medium',
    scientificRisk: ['interpretation_leap', 'parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['active corpus, active docset, or explicit target/reference docsets are available'],
  },

  'analysis/wordSketch': {
    type: 'analysis/wordSketch',
    get label() { return t('actions.registry.analysisWordsketch') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['interpretation_leap', 'parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['payload.term is non-empty', 'active corpus exposes relation attributes'],
  },

  'analysis/wordSketchDiff': {
    type: 'analysis/wordSketchDiff',
    get label() { return t('actions.registry.analysisWordsketchdiff') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['interpretation_leap', 'parameter_drift'],
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['payload.termA and payload.termB are non-empty', 'active corpus exposes relation attributes'],
  },

  'analysis/dispersion': {
    type: 'analysis/dispersion',
    get label() { return t('actions.registry.analysisDispersion') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['parameter_drift'], // Partition count matters
    requiresConfirmationAtOrBelowAutonomy: 5,
    preconditions: ['payload.term is non-empty'],
  },

  'analysis/semantic': {
    type: 'analysis/semantic',
    get label() { return t('actions.registry.analysisSemantic') },
    reversible: true,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['interpretation_leap'], // Semantic similarity is interpretive
    requiresConfirmationAtOrBelowAutonomy: 6,
    preconditions: ['payload.query is non-empty'],
  },

  // ---- Copilot Flow ----
  'copilot/continue': {
    type: 'copilot/continue',
    get label() { return t('actions.registry.copilotContinue') },
    reversible: true,
    userVisible: false,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0,
  },

  // ---- Navigation Actions ----
  'nav/switchTab': {
    type: 'nav/switchTab',
    get label() { return t('actions.registry.navSwitchtab') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0, // Always auto
  },

  'nav/openDocument': {
    type: 'nav/openDocument',
    get label() { return t('actions.registry.navOpendocument') },
    reversible: true,
    userVisible: true,
    cost: 'medium',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 2,
  },

  // ---- Copilot Actions ----
  'copilot/setAutonomy': {
    type: 'copilot/setAutonomy',
    get label() { return t('actions.registry.copilotSetautonomy') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 10, // Always requires user confirmation
  },

  'copilot/open': {
    type: 'copilot/open',
    get label() { return t('actions.registry.copilotOpen') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0,
  },

  'copilot/close': {
    type: 'copilot/close',
    get label() { return t('actions.registry.copilotClose') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0,
  },

  'copilot/sendMessage': {
    type: 'copilot/sendMessage',
    get label() { return t('actions.registry.copilotSendmessage') },
    reversible: false,
    userVisible: true,
    cost: 'high',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 10, // User always controls chat input
  },

  'copilot/answerClarification': {
    type: 'copilot/answerClarification',
    get label() { return t('actions.registry.copilotAnswerclarification') },
    reversible: false,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 10, // User must answer
  },

  // ---- Bookmark Actions ----
  'bookmark/add': {
    type: 'bookmark/add',
    get label() { return t('actions.registry.bookmarkAdd') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 3,
  },

  'bookmark/remove': {
    type: 'bookmark/remove',
    get label() { return t('actions.registry.bookmarkRemove') },
    reversible: false,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 4,
  },

  'bookmark/clear': {
    type: 'bookmark/clear',
    get label() { return t('actions.registry.bookmarkClear') },
    reversible: false,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 4,
  },

  // ---- Export Actions ----
  'export/data': {
    type: 'export/data',
    get label() { return t('actions.registry.exportData') },
    reversible: false, // File is created
    userVisible: true,
    cost: 'high',
    scientificRisk: ['export_privacy'], // May contain sensitive data
    requiresConfirmationAtOrBelowAutonomy: 7,
  },

  // ---- UI Actions ----
  'ui/toast': {
    type: 'ui/toast',
    get label() { return t('actions.registry.uiToast') },
    reversible: true,
    userVisible: true,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0,
  },

  'ui/setLoading': {
    type: 'ui/setLoading',
    get label() { return t('actions.registry.uiSetloading') },
    reversible: true,
    userVisible: false,
    cost: 'low',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 0,
  },
}

// ============================================================================
// Registry Access Functions
// ============================================================================

/**
 * Get metadata for an action type
 */
export function getActionMeta(type: string): ActionMeta | undefined {
  return actionMetaRegistry[type]
}

/**
 * Get metadata for an action (by action object)
 */
export function getActionMetaFromAction(action: Action): ActionMeta | undefined {
  return actionMetaRegistry[action.type]
}

/**
 * Check if an action requires confirmation at a given autonomy level
 */
export function requiresConfirmation(
  action: Action,
  autonomyLevel: number,
  source: 'user' | 'copilot'
): boolean {
  // User actions never require confirmation
  if (source === 'user') return false

  const meta = getActionMeta(action.type)
  if (!meta) {
    // Unknown actions always require confirmation from copilot
    return true
  }

  return autonomyLevel <= meta.requiresConfirmationAtOrBelowAutonomy
}

/**
 * Check if an action has any scientific risks
 */
export function hasScientificRisk(action: Action): boolean {
  const meta = getActionMeta(action.type)
  if (!meta) return true // Unknown actions are risky

  return meta.scientificRisk.some(r => r !== 'none')
}

/**
 * Get scientific risks for an action
 */
export function getScientificRisks(action: Action): ScientificRisk[] {
  const meta = getActionMeta(action.type)
  return meta?.scientificRisk ?? ['none']
}

/**
 * Check if an action is reversible
 */
export function isReversible(action: Action): boolean {
  const meta = getActionMeta(action.type)
  return meta?.reversible ?? false
}

/**
 * Check if an action is high cost (triggers API calls or heavy computation)
 */
export function isHighCost(action: Action): boolean {
  const meta = getActionMeta(action.type)
  return meta?.cost === 'high'
}

/**
 * Get all registered action types
 */
export function getAllActionTypes(): string[] {
  return Object.keys(actionMetaRegistry)
}

/**
 * Get action metadata registry (for debugging/inspection)
 */
export function getRegistry(): Readonly<Record<string, ActionMeta>> {
  return actionMetaRegistry
}

// ============================================================================
// Policy Helpers
// ============================================================================

/**
 * Determine the policy action for a copilot action at a given autonomy level
 */
export type PolicyDecision = ActionPolicyDecision

export function getPolicyDecision(
  action: Action,
  autonomyLevel: number,
  source: ActionSource
): PolicyDecision {
  // Only Copilot-origin actions are gated here. Other sources must be explicit
  // named execution modes, not the generic system superuser path.
  if (source !== 'copilot') return 'execute'

  const meta = getActionMeta(action.type)
  if (!meta) {
    // Unknown backend actions are not a product surface. Previewing them at high
    // autonomy would let the model mint new UI verbs outside the capability contract.
    return 'block'
  }

  // Check if action requires confirmation
  if (autonomyLevel <= meta.requiresConfirmationAtOrBelowAutonomy) {
    return 'preview'
  }

  // Check scientific risks at medium autonomy
  if (autonomyLevel <= 8 && hasScientificRisk(action)) {
    return 'preview'
  }

  // High cost actions always preview below autonomy 8
  if (autonomyLevel <= 7 && meta.cost === 'high') {
    return 'preview'
  }

  return 'execute'
}

/**
 * Get a factual description of why an action is gated behind confirmation.
 * States what the action does, not a risk diagnosis.
 */
export function getConfirmationReason(action: Action): string | null {
  const meta = getActionMeta(action.type)
  if (!meta) return t('actions.registry.unknownAction')

  const reasons: string[] = []

  if (!meta.reversible) {
    reasons.push(t('actions.registry.irreversible'))
  }

  if (meta.cost === 'high') {
    reasons.push(t('actions.registry.expensive'))
  }

  const gateClasses = meta.scientificRisk.filter(r => r !== 'none')
  if (gateClasses.length > 0) {
    const gateLabels: Record<ScientificRisk, string> = {
      none: '',
      parameter_drift: t('actions.registry.parameterDrift'),
      interpretation_leap: t('actions.registry.interpretation'),
      export_privacy: t('actions.registry.exportsData'),
    }
    const gateStrings = gateClasses.map(r => gateLabels[r]).filter(Boolean)
    if (gateStrings.length > 0) {
      reasons.push(gateStrings.join(', '))
    }
  }

  return reasons.length > 0 ? reasons.join(t('actions.registry.reasonSeparator')) : null
}
