/**
 * Reproducibility Service
 *
 * Re-dispatcht gespeicherte Run-Payloads über den ActionBus und vergleicht
 * Scope-, Result-Hash- und Zeilen-Evidenz mit dem Original-RunRecord.
 * Jeder Replay führt die Analyse tatsächlich erneut aus; ein Scope-Preflight
 * blockiert Replays, deren aktueller Forschungs-Scope nicht zum Original passt.
 */

import { ref } from 'vue'
import type { RunRecordV1 } from '@/types/copilot-protocol'
import { actionBus } from '@/actions/bus'
import { enterCopilotContext, exitCopilotContext } from '@/actions/policyGate'
import { getRunRecord, getRecentRuns, addRunNote } from './runRecordService'
import { stableResultHash } from '@/utils/runEvidence'
import type { Action, ActionResult } from '@/actions/types'
import { useDocsetStore } from '@/stores/docset'
import { executionScopeForApi } from '@/lib/researchScope'
import { formatDateTime } from '@/i18n/format'
import { t } from '@/i18n'

// ============================================================================
// Types
// ============================================================================

export interface ReproducibilityResult {
  runId: string
  originalRunId: string
  timestamp: number
  /** false nur, wenn der Scope-Preflight den Re-Dispatch blockiert hat */
  executed: boolean

  // Comparison results
  matched: boolean
  resultHashOriginal?: string
  resultHashNew?: string
  rowCountOriginal?: number
  rowCountNew?: number

  // Differences
  differences?: {
    field: string
    original: unknown
    new: unknown
  }[]

  // Execution info
  durationMs: number
  error?: string
}

export interface ReproducibilityReport {
  id: string
  createdAt: number
  originalRun: RunRecordV1
  results: ReproducibilityResult[]
  summary: {
    totalAttempts: number
    /** identisch: Ergebnis- und Scope-Evidenz stimmen überein */
    successfulMatches: number
    /** abweichend: ausgeführt, aber Evidenz weicht ab */
    failedMatches: number
    /** fehlgeschlagen: Fehler oder blockierter Preflight */
    errors: number
    averageDurationMs: number
  }
}

type ReproducibilityDifference = NonNullable<ReproducibilityResult['differences']>[number]
type ReproducibilityDifferences = ReproducibilityDifference[]

// ============================================================================
// State
// ============================================================================

const reproductionHistory = ref<ReproducibilityReport[]>([])
const isRunning = ref(false)
const currentProgress = ref<{ current: number; total: number } | null>(null)

const REPLAY_DISPATCH_SOURCE = 'copilot'
let replayAttemptCounter = 0

// ============================================================================
// Core Functions
// ============================================================================

/**
 * Run erneut ausführen und Ergebnisse vergleichen.
 */
export async function reproduceRun(runId: string): Promise<ReproducibilityResult> {
  const originalRun = getRunRecord(runId)
  if (!originalRun) {
    throw new Error(t('workspace.reproducibility.runNotFound', { runId }))
  }

  const startTime = performance.now()

  const preflightScopeDifferences = compareCurrentScopeBeforeReplay(originalRun)
  if (preflightScopeDifferences.length > 0) {
    return {
      runId: createReproductionRunId(),
      originalRunId: runId,
      timestamp: Date.now(),
      executed: false,
      matched: false,
      resultHashOriginal: originalRun.resultRef.hash,
      rowCountOriginal: originalRun.resultRef.rows,
      differences: preflightScopeDifferences,
      durationMs: performance.now() - startTime,
      error: t('workspace.reproducibility.replayBlocked'),
    }
  }

  try {
    // Dispatch the same action
    const action: Action = {
      type: originalRun.actionType,
      payload: normalizeActionPayload(originalRun.actionPayload),
    } as Action

    let result: ActionResult
    const replayRequestId = createReplayRequestId(originalRun.runId)
    enterCopilotContext()
    try {
      result = await actionBus.dispatch(action, {
        source: REPLAY_DISPATCH_SOURCE,
        requestId: replayRequestId,
      })
    } finally {
      exitCopilotContext()
    }

    const durationMs = performance.now() - startTime

    if (!result.success) {
      return {
        runId: createReproductionRunId(),
        originalRunId: runId,
        timestamp: Date.now(),
        executed: true,
        matched: false,
        durationMs,
        error: result.error ?? t('workspace.reproducibility.executionFailed'),
      }
    }

    // Compare results
    const newResultHash = result.data ? stableResultHash(result.data) : undefined
    const newRowCount = extractRowCount(result.data)

    const differences: ReproducibilityDifferences = []
    const replayRun = findReplayRunRecord(originalRun, result, replayRequestId)
    differences.push(...compareScopeFingerprint(originalRun, replayRun))

    const originalResultHash = originalRun.evidence.resultFingerprint.resultHash ?? originalRun.resultRef.hash
    if (originalResultHash !== newResultHash) {
      differences.push({
        field: 'resultHash',
        original: originalResultHash,
        new: newResultHash,
      })
    }

    const originalRows = originalRun.evidence.resultFingerprint.rows ?? originalRun.resultRef.rows
    if (originalRows !== newRowCount) {
      differences.push({
        field: 'rowCount',
        original: originalRows,
        new: newRowCount,
      })
    }
    const matched = compareResults(originalRun, result) && differences.length === 0

    return {
      runId: createReproductionRunId(),
      originalRunId: runId,
      timestamp: Date.now(),
      executed: true,
      matched,
      resultHashOriginal: originalRun.resultRef.hash,
      resultHashNew: newResultHash,
      rowCountOriginal: originalRun.resultRef.rows,
      rowCountNew: newRowCount,
      differences: differences.length > 0 ? differences : undefined,
      durationMs,
    }
  } catch (error) {
    return {
      runId: createReproductionRunId(),
      originalRunId: runId,
      timestamp: Date.now(),
      executed: true,
      matched: false,
      durationMs: performance.now() - startTime,
      error: error instanceof Error ? error.message : t('workspace.reproducibility.unknownError'),
    }
  }
}

/**
 * Mehrere Replay-Versuche ausführen und einen Report erzeugen.
 * Jeder Versuch dispatcht die Original-Aktion erneut.
 */
export async function generateReproducibilityReport(
  runId: string,
  attempts: number = 3
): Promise<ReproducibilityReport> {
  const originalRun = getRunRecord(runId)
  if (!originalRun) {
    throw new Error(t('workspace.reproducibility.runNotFound', { runId }))
  }

  isRunning.value = true
  currentProgress.value = { current: 0, total: attempts }

  const results: ReproducibilityResult[] = []

  try {
    for (let i = 0; i < attempts; i++) {
      currentProgress.value = { current: i + 1, total: attempts }

      const result = await reproduceRun(runId)
      results.push(result)
    }

    const report: ReproducibilityReport = {
      id: `report_${Date.now().toString(36)}`,
      createdAt: Date.now(),
      originalRun,
      results,
      summary: {
        totalAttempts: results.length,
        successfulMatches: results.filter(r => r.matched).length,
        failedMatches: results.filter(r => !r.matched && !r.error).length,
        errors: results.filter(r => r.error).length,
        averageDurationMs: results.reduce((sum, r) => sum + r.durationMs, 0) / results.length,
      },
    }

    reproductionHistory.value.push(report)

    // Add note to original run. The note is written once, in the interface
    // language at that moment. The rate keeps its fixed numeric form.
    const successRate = report.summary.totalAttempts > 0
      ? `${(report.summary.successfulMatches / report.summary.totalAttempts * 100).toFixed(0)}% (${report.summary.successfulMatches}/${report.summary.totalAttempts})`
      : t('workspace.reproducibility.notComputed')
    addRunNote(runId, t('workspace.reproducibility.runNote', { rate: successRate }))

    return report
  } finally {
    isRunning.value = false
    currentProgress.value = null
  }
}

function createReproductionRunId(): string {
  return `repro_${Date.now().toString(36)}`
}

function createReplayRequestId(runId: string): string {
  replayAttemptCounter += 1
  return `replay:${runId}:${Date.now().toString(36)}:${replayAttemptCounter}`
}

function normalizeActionPayload(payload: unknown): Record<string, unknown> {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    return payload as Record<string, unknown>
  }
  return {}
}

function compareCurrentScopeBeforeReplay(
  originalRun: RunRecordV1
): ReproducibilityDifferences {
  try {
    const docsetStore = useDocsetStore()
    const originalCorpusId = runScopeCorpusId(originalRun)
    const originalScopeHash = runScopeHash(originalRun)
    const originalDocsetId = originalRun.evidence.researchScope?.docsetId
    const currentScope = executionScopeForApi(
      docsetStore,
      originalCorpusId || docsetStore.activeCorpus || 'default',
      originalDocsetId,
    )
    const currentCorpusId = currentScope.corpusId || docsetStore.activeCorpus || 'default'
    const differences: ReproducibilityDifferences = []

    if (originalCorpusId && currentCorpusId !== originalCorpusId) {
      differences.push({
        field: 'corpusId',
        original: originalCorpusId,
        new: currentCorpusId,
      })
    }
    if (originalScopeHash && currentScope.scopeHash !== originalScopeHash) {
      differences.push({
        field: 'scopeHash',
        original: originalScopeHash,
        new: currentScope.scopeHash,
      })
    }

    return differences
  } catch {
    // Unit tests and non-Vue callers may not have an active Pinia context.
    // In that case the post-dispatch replay RunRecord comparison remains the
    // authoritative fallback.
    return []
  }
}

function findReplayRunRecord(
  originalRun: RunRecordV1,
  result: ActionResult,
  replayRequestId: string
): RunRecordV1 | undefined {
  if (result.runId) {
    const byRunId = getRunRecord(result.runId)
    if (byRunId && byRunId.runId !== originalRun.runId) return byRunId
  }
  return getRecentRuns(50).find((run) =>
    run.runId !== originalRun.runId && run.requestId === replayRequestId
  )
}

function compareScopeFingerprint(
  originalRun: RunRecordV1,
  replayRun: RunRecordV1 | undefined
): ReproducibilityDifferences {
  const differences: ReproducibilityDifferences = []
  const originalCorpusId = runScopeCorpusId(originalRun)
  const originalScopeHash = runScopeHash(originalRun)

  if (!replayRun) {
    differences.push({
      field: 'scopeHash',
      original: originalScopeHash || t('workspace.reproducibility.unknown'),
      new: t('workspace.reproducibility.notVerified'),
    })
    return differences
  }

  const replayCorpusId = runScopeCorpusId(replayRun)
  const replayScopeHash = runScopeHash(replayRun)

  if (originalCorpusId !== replayCorpusId) {
    differences.push({
      field: 'corpusId',
      original: originalCorpusId,
      new: replayCorpusId,
    })
  }

  if (originalScopeHash !== replayScopeHash) {
    differences.push({
      field: 'scopeHash',
      original: originalScopeHash || t('workspace.reproducibility.unknown'),
      new: replayScopeHash || t('workspace.reproducibility.unknown'),
    })
  }

  return differences
}

function runScopeCorpusId(run: RunRecordV1): string {
  return run.evidence.researchScope?.corpusId
    || run.evidence.corpusFingerprint.corpusId
    || run.corpus.corpusId
}

function runScopeHash(run: RunRecordV1): string {
  return run.evidence.researchScope?.scopeHash
    || run.evidence.corpusFingerprint.subcorpusHash
    || run.corpus.subcorpusHash
}

/**
 * Compare original run with new result
 */
function compareResults(originalRun: RunRecordV1, newResult: ActionResult): boolean {
  // If we have hashes, compare them
  const originalResultHash = originalRun.evidence.resultFingerprint.resultHash ?? originalRun.resultRef.hash
  if (originalResultHash && newResult.data) {
    const newHash = stableResultHash(newResult.data)
    return originalResultHash === newHash
  }

  // If we have row counts, compare them
  const newRowCount = extractRowCount(newResult.data)
  const originalRows = originalRun.evidence.resultFingerprint.rows ?? originalRun.resultRef.rows
  if (originalRows !== undefined && newRowCount !== undefined) {
    return originalRows === newRowCount
  }

  // Can't compare, assume success if no error
  return newResult.success
}

/**
 * Extract row count from result data
 */
function extractRowCount(data: unknown): number | undefined {
  if (!data || typeof data !== 'object') return undefined

  if ('total' in data && typeof (data as { total: number }).total === 'number') {
    return (data as { total: number }).total
  }

  if ('rows' in data && Array.isArray((data as { rows: unknown[] }).rows)) {
    return (data as { rows: unknown[] }).rows.length
  }

  if ('count' in data && typeof (data as { count: number }).count === 'number') {
    return (data as { count: number }).count
  }

  return undefined
}

// ============================================================================
// Export Functions
// ============================================================================

/**
 * Export reproducibility report as JSON
 */
export function exportReportAsJson(report: ReproducibilityReport): string {
  return JSON.stringify({
    version: '1.0',
    type: 'reproducibility_report',
    ...report,
  }, null, 2)
}

/**
 * Export reproducibility report as Markdown
 */
export function exportReportAsMarkdown(report: ReproducibilityReport): string {
  // Headings and labels follow the interface language at export time.
  // Research scope field names and the numeric forms (100.0%, 12ms) stay
  // fixed, reproducibilityService.test.ts pins them.
  const reproducibilityRate = report.summary.totalAttempts > 0
    ? `${(report.summary.successfulMatches / report.summary.totalAttempts * 100).toFixed(1)}%`
    : t('workspace.reproducibility.notComputed')
  const lines: string[] = [
    `# ${t('workspace.reproducibility.reportTitle')}`,
    '',
    `**${t('workspace.reproducibility.created')}:** ${formatDateTime(report.createdAt)}`,
    '',
    `## ${t('workspace.reproducibility.originalRun')}`,
    '',
    `- **${t('workspace.reproducibility.runId')}:** \`${report.originalRun.runId}\``,
    `- **${t('workspace.reproducibility.timestamp')}:** ${formatDateTime(report.originalRun.ts)}`,
    `- **${t('workspace.reproducibility.action')}:** \`${report.originalRun.actionType}\``,
    `- **${t('workspace.reproducibility.corpus')}:** ${report.originalRun.corpus.corpusId}`,
    '',
    `### ${t('workspace.reproducibility.originalScope')}`,
    '',
    `| ${t('workspace.reproducibility.field')} | ${t('workspace.reproducibility.value')} |`,
    `|------|------|`,
    ...researchScopeMarkdownRows(report.originalRun),
    '',
    `### ${t('workspace.reproducibility.payload')}`,
    '',
    '```json',
    JSON.stringify(report.originalRun.actionPayload, null, 2),
    '```',
    '',
    `## ${t('workspace.reproducibility.summary')}`,
    '',
    `| ${t('workspace.reproducibility.metric')} | ${t('workspace.reproducibility.value')} |`,
    `|--------|------|`,
    `| ${t('workspace.reproducibility.attempts')} | ${report.summary.totalAttempts} |`,
    `| ${t('workspace.reproducibility.identical')} | ${report.summary.successfulMatches} |`,
    `| ${t('workspace.reproducibility.deviating')} | ${report.summary.failedMatches} |`,
    `| ${t('workspace.reproducibility.failed')} | ${report.summary.errors} |`,
    `| ${t('workspace.reproducibility.averageDuration')} | ${report.summary.averageDurationMs.toFixed(0)}ms |`,
    '',
    `**${t('workspace.reproducibility.rate')}:** ${reproducibilityRate}`,
    '',
    `## ${t('workspace.reproducibility.results')}`,
    '',
  ]

  for (const result of report.results) {
    lines.push(`### ${t('workspace.reproducibility.attempt', { n: report.results.indexOf(result) + 1 })}`)
    lines.push('')
    lines.push(`- **${t('workspace.reproducibility.status')}:** ${getResultStatusLabel(result)}`)
    lines.push(`- **${t('workspace.reproducibility.duration')}:** ${result.durationMs.toFixed(0)}ms`)

    if (result.error) {
      lines.push(`- **${t('workspace.reproducibility.error')}:** ${result.error}`)
    }

    if (result.differences && result.differences.length > 0) {
      lines.push('')
      lines.push(`**${t('workspace.reproducibility.differences')}:**`)
      for (const diff of result.differences) {
        lines.push(`- ${diff.field}: \`${diff.original}\` → \`${diff.new}\``)
      }
    }

    lines.push('')
  }

  return lines.join('\n')
}

function researchScopeMarkdownRows(run: RunRecordV1): string[] {
  const scope = run.evidence.researchScope
  const rows: Array<[string, string | undefined]> = [
    ['ScopeHash', scope?.scopeHash ?? run.evidence.corpusFingerprint.subcorpusHash ?? run.corpus.subcorpusHash],
    ['ScopeStatus', scope?.scopeStatus],
    ['ScopeLabel', scope?.label],
    ['ScopeDocset', scope?.docsetId],
    ['ScopeName', scope?.subcorpusName],
    ['ScopeQueryHash', scope?.queryHash ?? run.queryHash],
    ['ScopeFilterSpecHash', scope?.filterSpecHash],
    ['ScopeMetadataSchemaHash', scope?.metadataSchemaHash ?? run.evidence.corpusFingerprint.metadataSchemaHash],
  ]
  return rows
    .filter(([, value]) => value !== undefined && value !== '')
    .map(([field, value]) => `| ${field} | \`${String(value).replace(/`/g, '\\`')}\` |`)
}

function getResultStatusLabel(result: ReproducibilityResult): string {
  if (result.matched) return t('workspace.reproducibility.statusMatch')
  if (result.error) return t('workspace.reproducibility.statusError')
  return t('workspace.reproducibility.statusMismatch')
}

// ============================================================================
// Getters
// ============================================================================

export function getReproductionHistory(): ReproducibilityReport[] {
  return reproductionHistory.value
}

export function getReproductionState(): {
  isRunning: boolean
  progress: { current: number; total: number } | null
} {
  return {
    isRunning: isRunning.value,
    progress: currentProgress.value,
  }
}

export function clearReproductionHistory(): void {
  reproductionHistory.value = []
}
