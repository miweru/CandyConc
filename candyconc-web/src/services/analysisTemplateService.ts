/**
 * Analysis Template Service
 *
 * Drei eingebaute Analyse-Pipelines (Sequenzen von ActionBus-Aktionen)
 * mit Parameter-Validierung, Ausführung und JSON-Export.
 * Es gibt keine benutzerdefinierten Templates und keine Persistenz.
 */

import { actionBus } from '@/actions/bus'
import { getActionMeta } from '@/actions/registry'
import type { Action, ActionResult } from '@/actions/types'
import { t } from '@/i18n'

// ============================================================================
// Types
// ============================================================================

export interface TemplateStep {
  id: string
  order: number
  actionType: string
  /** Payload with placeholders like {{query}}, {{corpus}} */
  payloadTemplate: Record<string, unknown>
  /** Human-readable description */
  description?: string
  /** Condition to skip this step */
  skipIf?: string
  /** Stop pipeline if this step fails */
  stopOnError?: boolean
}

export interface AnalysisTemplate {
  id: string
  name: string
  description?: string
  category?: 'corpus' | 'frequency' | 'collocation' | 'comparison'
  createdAt: number
  updatedAt: number
  author?: string
  tags?: string[]

  /** Template parameters that users must fill */
  parameters: TemplateParameter[]

  /** Ordered sequence of steps */
  steps: TemplateStep[]

  version?: string
}

export interface TemplateParameter {
  name: string
  type: 'string' | 'number' | 'boolean' | 'select' | 'corpus'
  label: string
  description?: string
  required: boolean
  defaultValue?: unknown
  options?: { value: unknown; label: string }[] // for select type
  validation?: {
    min?: number
    max?: number
    pattern?: string
  }
}

export interface TemplateExecutionContext {
  parameters: Record<string, unknown>
  corpusId?: string
  subcorpusHash?: string
}

export interface TemplateExecutionResult {
  templateId: string
  startedAt: number
  completedAt: number
  context: TemplateExecutionContext
  stepResults: {
    stepId: string
    success: boolean
    skipped: boolean
    data?: unknown
    error?: string
    durationMs: number
  }[]
  success: boolean
  error?: string
}

// ============================================================================
// Action Allowlist
// ============================================================================

const TEMPLATE_ALLOWED_ACTION_TYPES = new Set([
  'query/execute',
  'analysis/collocations',
  'analysis/frequency',
  'analysis/dispersion',
  'analysis/semantic',
  'nav/switchTab',
])

function isTemplateActionAllowed(actionType: string): boolean {
  return TEMPLATE_ALLOWED_ACTION_TYPES.has(actionType) && !!getActionMeta(actionType)
}

function templateActionError(actionType: string): string {
  return `Template action not allowed: ${actionType}`
}

// ============================================================================
// Built-in Templates
// ============================================================================

function builtinTemplates(): AnalysisTemplate[] {
  return [
    {
      id: 'builtin_basic_query',
      name: t('analysis.templates.basicName'),
      description: t('analysis.templates.basicDescription'),
      category: 'corpus',
      createdAt: 0,
      updatedAt: 0,
      author: 'CandyConc',
      tags: ['basic', 'search'],
      parameters: [
        {
          name: 'query',
          type: 'string',
          label: t('analysis.templates.searchTerm'),
          required: true,
        },
        {
          name: 'contextSize',
          type: 'number',
          label: t('analysis.templates.contextSize'),
          required: false,
          defaultValue: 5,
          validation: { min: 1, max: 20 },
        },
      ],
      steps: [
        {
          id: 'step_query',
          order: 1,
          actionType: 'query/execute',
          payloadTemplate: {
            term: '{{query}}',
            contextSize: '{{contextSize}}',
          },
          description: t('analysis.templates.runKwic'),
          stopOnError: true,
        },
        {
          id: 'step_collocations',
          order: 2,
          actionType: 'analysis/collocations',
          payloadTemplate: {
            term: '{{query}}',
          },
          description: t('analysis.templates.computeCollocations'),
        },
      ],
    },
    {
      id: 'builtin_frequency_analysis',
      name: t('analysis.templates.frequencyName'),
      description: t('analysis.templates.frequencyDescription'),
      category: 'frequency',
      createdAt: 0,
      updatedAt: 0,
      author: 'CandyConc',
      tags: ['frequency', 'dispersion'],
      parameters: [
        {
          name: 'query',
          type: 'string',
          label: t('analysis.templates.searchTerm'),
          required: true,
        },
        {
          name: 'groupBy',
          type: 'select',
          label: t('analysis.templates.grouping'),
          required: false,
          defaultValue: 'word',
          options: [
            { value: 'word', label: t('analysis.templates.wordForm') },
            { value: 'lemma', label: t('analysis.templates.lemma') },
            { value: 'pos', label: t('analysis.templates.pos') },
          ],
        },
      ],
      steps: [
        {
          id: 'step_query',
          order: 1,
          actionType: 'query/execute',
          payloadTemplate: { term: '{{query}}' },
          description: t('analysis.templates.runKwic'),
          stopOnError: true,
        },
        {
          id: 'step_frequency',
          order: 2,
          actionType: 'nav/switchTab',
          payloadTemplate: { tab: 'frequency' },
          description: t('analysis.templates.toFrequency'),
        },
        {
          id: 'step_dispersion',
          order: 3,
          actionType: 'nav/switchTab',
          payloadTemplate: { tab: 'dispersion' },
          description: t('analysis.templates.toDispersion'),
        },
      ],
    },
    {
      id: 'builtin_collocation_deep',
      name: t('analysis.templates.deepName'),
      description: t('analysis.templates.deepDescription'),
      category: 'collocation',
      createdAt: 0,
      updatedAt: 0,
      author: 'CandyConc',
      tags: ['collocation', 'advanced'],
      parameters: [
        {
          name: 'query',
          type: 'string',
          label: t('analysis.templates.searchTerm'),
          required: true,
        },
      ],
      steps: [
        {
          id: 'step_query',
          order: 1,
          actionType: 'query/execute',
          payloadTemplate: { term: '{{query}}' },
          stopOnError: true,
        },
        {
          id: 'step_coll_narrow',
          order: 2,
          actionType: 'analysis/collocations',
          payloadTemplate: { term: '{{query}}', windowSize: 3 },
          description: t('analysis.templates.narrow'),
        },
        {
          id: 'step_coll_wide',
          order: 3,
          actionType: 'analysis/collocations',
          payloadTemplate: { term: '{{query}}', windowSize: 10 },
          description: t('analysis.templates.wide'),
        },
        {
          id: 'step_tab',
          order: 4,
          actionType: 'nav/switchTab',
          payloadTemplate: { tab: 'collocations' },
        },
      ],
    },
  ]
}

// ============================================================================
// Template Access
// ============================================================================

/**
 * Get all templates (built-in only)
 */
export function getAllTemplates(): AnalysisTemplate[] {
  return builtinTemplates()
}

/**
 * Get template by ID
 */
export function getTemplate(id: string): AnalysisTemplate | undefined {
  return getAllTemplates().find((template) => template.id === id)
}

// ============================================================================
// Template Execution
// ============================================================================

/**
 * Resolve template placeholders
 */
function resolvePayload(
  template: Record<string, unknown>,
  context: TemplateExecutionContext
): Record<string, unknown> {
  const result: Record<string, unknown> = {}

  for (const [key, value] of Object.entries(template)) {
    if (typeof value === 'string' && value.startsWith('{{') && value.endsWith('}}')) {
      const paramName = value.slice(2, -2)
      result[key] = context.parameters[paramName] ?? value
    } else if (typeof value === 'object' && value !== null) {
      result[key] = resolvePayload(value as Record<string, unknown>, context)
    } else {
      result[key] = value
    }
  }

  return result
}

/**
 * Execute a template with given parameters
 */
export async function executeTemplate(
  templateId: string,
  parameters: Record<string, unknown>,
  options: {
    onStepStart?: (stepId: string, order: number) => void
    onStepComplete?: (stepId: string, success: boolean) => void
  } = {}
): Promise<TemplateExecutionResult> {
  const template = getTemplate(templateId)
  if (!template) {
    throw new Error(`Template ${templateId} not found`)
  }

  const context: TemplateExecutionContext = {
    parameters,
  }

  const result: TemplateExecutionResult = {
    templateId,
    startedAt: Date.now(),
    completedAt: 0,
    context,
    stepResults: [],
    success: true,
  }

  // Sort steps by order
  const sortedSteps = [...template.steps].sort((a, b) => a.order - b.order)

  for (const step of sortedSteps) {
    options.onStepStart?.(step.id, step.order)

    const stepStartTime = performance.now()

    // Check skip condition
    if (step.skipIf) {
      // Simple condition evaluation (could be expanded)
      const shouldSkip = evaluateCondition(step.skipIf, context, result.stepResults)
      if (shouldSkip) {
        result.stepResults.push({
          stepId: step.id,
          success: true,
          skipped: true,
          durationMs: 0,
        })
        options.onStepComplete?.(step.id, true)
        continue
      }
    }

    try {
      if (!isTemplateActionAllowed(step.actionType)) {
        const durationMs = performance.now() - stepStartTime
        const error = templateActionError(step.actionType)
        result.stepResults.push({
          stepId: step.id,
          success: false,
          skipped: false,
          error,
          durationMs,
        })
        options.onStepComplete?.(step.id, false)
        result.success = false
        result.error = `Step ${step.id} failed: ${error}`
        break
      }

      const payload = resolvePayload(step.payloadTemplate, context)

      const action: Action = {
        type: step.actionType,
        payload,
      } as Action

      const actionResult: ActionResult = await actionBus.dispatch(action, {
        source: 'template',
        requestId: `template:${templateId}:${step.id}`,
      })

      const stepResult = {
        stepId: step.id,
        success: actionResult.success,
        skipped: false,
        data: actionResult.data,
        error: actionResult.error,
        durationMs: performance.now() - stepStartTime,
      }

      result.stepResults.push(stepResult)
      options.onStepComplete?.(step.id, actionResult.success)

      if (!actionResult.success && step.stopOnError) {
        result.success = false
        result.error = `Step ${step.id} failed: ${actionResult.error}`
        break
      }
    } catch (error) {
      const stepResult = {
        stepId: step.id,
        success: false,
        skipped: false,
        error: error instanceof Error ? error.message : 'Unknown error',
        durationMs: performance.now() - stepStartTime,
      }

      result.stepResults.push(stepResult)
      options.onStepComplete?.(step.id, false)

      if (step.stopOnError) {
        result.success = false
        result.error = `Step ${step.id} failed: ${stepResult.error}`
        break
      }
    }
  }

  result.completedAt = Date.now()

  return result
}

/**
 * Simple condition evaluation
 */
function evaluateCondition(
  condition: string,
  context: TemplateExecutionContext,
  previousResults: TemplateExecutionResult['stepResults']
): boolean {
  // Support simple conditions like "stepId.failed" or "param.empty"
  if (condition.endsWith('.failed')) {
    const stepId = condition.replace('.failed', '')
    return previousResults.some(r => r.stepId === stepId && !r.success)
  }

  if (condition.endsWith('.empty')) {
    const paramName = condition.replace('.empty', '')
    const value = context.parameters[paramName]
    return value === undefined || value === null || value === ''
  }

  return false
}

// ============================================================================
// Template Validation
// ============================================================================

/**
 * Validate template parameters
 */
export function validateParameters(
  template: AnalysisTemplate,
  parameters: Record<string, unknown>
): { valid: boolean; errors: string[] } {
  const errors: string[] = []

  for (const param of template.parameters) {
    const value = parameters[param.name]

    if (param.required && (value === undefined || value === null || value === '')) {
      errors.push(t('analysis.templates.paramRequired', { label: param.label }))
      continue
    }

    if (value !== undefined && value !== null) {
      if (param.type === 'number') {
        const num = Number(value)
        if (isNaN(num)) {
          errors.push(t('analysis.templates.paramNumber', { label: param.label }))
        } else {
          if (param.validation?.min !== undefined && num < param.validation.min) {
            errors.push(t('analysis.templates.paramMin', { label: param.label, min: param.validation.min }))
          }
          if (param.validation?.max !== undefined && num > param.validation.max) {
            errors.push(t('analysis.templates.paramMax', { label: param.label, max: param.validation.max }))
          }
        }
      }

      if (param.type === 'string' && param.validation?.pattern) {
        const regex = new RegExp(param.validation.pattern)
        if (!regex.test(String(value))) {
          errors.push(t('analysis.templates.paramFormat', { label: param.label }))
        }
      }
    }
  }

  return { valid: errors.length === 0, errors }
}

// ============================================================================
// Export
// ============================================================================

/**
 * Export template as JSON
 */
export function exportTemplateAsJson(templateId: string): string | null {
  const template = getTemplate(templateId)
  if (!template) return null

  return JSON.stringify({
    version: '1.0',
    type: 'analysis_template',
    template,
  }, null, 2)
}
