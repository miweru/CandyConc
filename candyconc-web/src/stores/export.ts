/**
 * Export Store - Handle server replay exports and clearly marked local excerpts.
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useQueryStore, type KwicRow } from './query'
import { useSettingsStore } from './settings'
import { useDocsetStore, useAnalysisPresetsStore, useAnnotationsStore, rowIdFor } from './index'
import { useCorpusCapabilitiesStore } from './corpusCapabilities'
import { useProductCapabilitiesStore } from './productCapabilities'
import {
  exportPdf,
  exportDocx,
  getFrequency,
  getExportConcordance,
  getExportEvidencePackage,
  type ExportConcordanceFormat,
  type ExportEvidencePackage,
} from '@/api/client'
import { csvEscape, csvRow, csvMeta } from '@/utils/csv'
import { kwicHitSpan } from '@/lib/kwicCitation'
import { downloadBlob } from '@/utils/download'
import {
  ensureUsableResearchScope,
  researchScopeCsvMeta,
} from '@/lib/researchScope'
import { formatNumber } from '@/i18n/format'
import { t } from '@/i18n'

// ============================================
// Types
// ============================================

export type ExportFormat = 'pdf' | 'docx' | 'csv' | 'tsv' | 'json' | 'jsonl' | 'xlsx' | 'latex' | 'evidence-json'

/**
 * Treffer-Scope of an export:
 * - `loaded`: only the rows currently loaded in the browser window (client slice).
 * - `all-server`: re-run the query on the backend with an exact count and a
 *   bounded row stream (F2).
 */
export type ExportScope = 'loaded' | 'all-server'

export interface ExportOptions {
  format: ExportFormat
  includeResults: boolean
  includeFrequency: boolean
  includeCollocations: boolean
  includeStatistics: boolean
  includeContext: boolean
  includeMetadata: boolean
  includeReproMeta: boolean
  /** F7: emit one row per KWIC line with its category + note + annotator. */
  includeAnnotations?: boolean
  rowRange: 'all' | 'selected' | 'range' | 'annotated' | 'category'
  rangeStart?: number
  rangeEnd?: number
  /** When `rowRange === 'category'`, the category id to restrict to ('' = uncategorized). */
  rangeCategoryId?: string | null
  /** Which match set to export (default `loaded`). */
  scope?: ExportScope
  /**
   * Server-CSV im Excel-kompatiblen Dialekt (Semikolon, UTF-8-BOM).
   * Nur für `format === 'csv'` mit Server-Scope wirksam; Standard-CSV bleibt
   * byte-identisch.
   */
  excelDe?: boolean
}

export interface ExportJob {
  id: string
  format: ExportFormat
  operationIds?: string[]
  status: 'pending' | 'processing' | 'completed' | 'error'
  progress: number
  filename?: string
  message?: string
  warning?: string
  /** Exact search denominator returned by the backend. */
  total?: number | null
  /** Rows physically present in a bounded server export. */
  exportedRows?: number | null
  /** Backend row ceiling that governed this export. */
  exportCap?: number | null
  truncated?: boolean
  error?: string
  timestamp: number
}

export const REPLAY_EXPORT_OPERATIONS = {
  concordance: 'research.replay_export.concordance',
  evidencePackage: 'research.replay_export.evidence_package',
  pdf: 'research.replay_export.pdf',
  docx: 'research.replay_export.docx',
} as const

const REPLAY_EXPORT_CAPABILITY_ID = 'research.replay_export'
const FREQUENCY_EXPORT_OPERATION_ID = 'analysis.frequency.list'
const ANNOTATION_EXPORT_OPERATION_ID = 'research.annotations.read'
const localBrowserExportNotReleased = (): string => t('export.store.localNotReleased')

/**
 * Columns of the whole hit, named and placed like in the server concordance
 * export. A loaded row holds the node token in `match` and the offsets of the
 * other hit tokens in `matchOffsets`, so the local tables write the node as
 * `node` and append the whole hit.
 */
const HIT_SPAN_COLUMNS = ['match', 'match_start', 'match_end'] as const

function hitSpanCells(row: KwicRow): [string, number | string, number | string] {
  const span = kwicHitSpan(row)
  return [span.match, span.matchStart ?? '', span.matchEnd ?? '']
}

/**
 * Max KWIC rows rendered into a human-readable EvidencePackage report
 * (Markdown/LaTeX). Shared so both report formats cap identically and stay
 * honest about it; the row_hash_sha256 stays the integrity anchor.
 */
const EVIDENCE_REPORT_MAX_ROWS = 500

export interface ExportCapabilityAvailability {
  enabled: boolean
  disabledReason: string | null
  operationIds: string[]
}

// ============================================
// Store
// ============================================

export const useExportStore = defineStore('export', () => {
  // ============================================
  // State
  // ============================================

  const queryStore = useQueryStore()
  const settingsStore = useSettingsStore()
  const docsetStore = useDocsetStore()
  const presetsStore = useAnalysisPresetsStore()
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const productCapabilities = useProductCapabilitiesStore()

  const isExporting = ref(false)
  const exportProgress = ref(0)
  const currentJob = ref<ExportJob | null>(null)
  const exportHistory = ref<ExportJob[]>([])
  const preselectedFormat = ref<ExportFormat | null>(null)

  const defaultOptions = ref<ExportOptions>({
    format: 'csv',
    includeResults: true,
    includeFrequency: false,
    includeCollocations: false,
    includeStatistics: false,
    includeContext: true,
    includeMetadata: true,
    includeReproMeta: false,
    includeAnnotations: false,
    rowRange: 'all',
    scope: 'loaded',
    excelDe: false,
  })

  function totalHitsLabel(locale?: string): string {
    const sample = queryStore.sampleProvenance
    if (!sample && !queryStore.totalKnown && !queryStore.totalPartial) return 'n/a'
    const total = sample?.population ?? queryStore.totalHits
    const formatted = locale ? total.toLocaleString(locale) : String(total)
    return (sample ? sample.populationPartial : queryStore.totalPartial) ? `≥ ${formatted}` : formatted
  }

  // ============================================
  // Actions
  // ============================================

  function rememberExportJob(job: ExportJob) {
    exportHistory.value = [
      { ...job },
      ...exportHistory.value.filter((entry) => entry.id !== job.id),
    ].slice(0, 50)
  }

  function startCurrentExportJob(job: ExportJob): ExportJob {
    currentJob.value = { ...job }
    return currentJob.value
  }

  function patchCurrentExportJob(patch: Partial<ExportJob>): ExportJob {
    if (!currentJob.value) {
      throw new Error(t('export.store.noActiveJob'))
    }
    currentJob.value = {
      ...currentJob.value,
      ...patch,
    }
    if (typeof patch.progress === 'number') {
      exportProgress.value = patch.progress
    }
    return currentJob.value
  }

  function escapeMarkdown(value: string): string {
    return value.replace(/\|/g, '\\|').replace(/\n/g, ' ')
  }

  /**
   * A query or a value as a code span of the report. In the PDF a code span is
   * set in the monospace font without typographic quotes, so a query such as
   * cql:[pos="ADJ"] can be copied from the report and run again. In body text
   * pandoc and the TeX font turn " into curly quotes. A code span breaks at
   * its spaces.
   */
  function markdownCode(value: string): string {
    const text = value.replace(/\s*\n\s*/g, ' ')
    const longestRun = Math.max(0, ...[...text.matchAll(/`+/g)].map((match) => match[0].length))
    const fence = '`'.repeat(longestRun + 1)
    const pad = text.startsWith('`') || text.endsWith('`') ? ' ' : ''
    return `${fence}${pad}${text}${pad}${fence}`
  }

  /** One line per parameter: long values wrap in the PDF instead of running off the page. */
  function markdownParameters(parameters: Record<string, unknown>): string[] {
    return Object.entries(parameters).map(([key, value]) => {
      // Spaces after commas and colons give the line break points.
      const text = typeof value === 'string' ? value : JSON.stringify(value, null, 1)?.replace(/\n\s*/g, ' ')
      return `  - ${escapeMarkdown(key)}: ${markdownCode(text ?? String(value))}`
    })
  }

  function escapeLatex(value: string): string {
    return value
      .replace(/\\/g, '\\textbackslash{}')
      .replace(/&/g, '\\&')
      .replace(/%/g, '\\%')
      .replace(/\$/g, '\\$')
      .replace(/#/g, '\\#')
      .replace(/_/g, '\\_')
      .replace(/{/g, '\\{')
      .replace(/}/g, '\\}')
      .replace(/~/g, '\\textasciitilde{}')
      .replace(/\^/g, '\\textasciicircum{}')
  }

  function formatFilterList(values: string[]): string {
    if (!values.length) return 'all'
    return values.join(' | ')
  }

  function rowRangeLabel(options: ExportOptions): string {
    if (options.rowRange === 'selected') return t('export.store.rangeSelected')
    if (options.rowRange === 'annotated') return t('export.store.rangeAnnotated')
    if (options.rowRange === 'category') {
      const annotationsStore = useAnnotationsStore()
      const cat = options.rangeCategoryId
        ? annotationsStore.categories.find((c) => c.id === options.rangeCategoryId)?.label
        : t('export.store.uncategorized')
      return t('export.store.rangeCategory', { category: cat ?? options.rangeCategoryId ?? '' })
    }
    if (options.rowRange === 'range') {
      const start = Math.max(1, options.rangeStart ?? 1)
      const end = Math.max(start, options.rangeEnd ?? start)
      return t('export.store.rangeSpan', { start: String(start), end: String(end) })
    }
    return t('export.store.rangeAll')
  }

  function activeAnalysisScope(operation = t('export.store.operationExportAnalysis')) {
    const scope = ensureUsableResearchScope(docsetStore, { operation })
    if (!scope.ok) throw new Error(scope.message)
    return {
      corpus: docsetStore.activeCorpus || undefined,
      docsetId: scope.docsetId,
    }
  }

  function activeScopeTokenCount(): number {
    if (docsetStore.hasActiveDocset) return docsetStore.stats.tokenCount
    return corpusCapabilities.activeCorpusTokenCount || (
      settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.tokenCount : 0
    )
  }

  function activeScopeDocumentCount(): number {
    if (docsetStore.hasActiveDocset) return docsetStore.stats.docCount
    return corpusCapabilities.activeCorpusDocCount || (
      settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.documentCount : 0
    )
  }

  /** Source of truth for docset filter provenance as label/value pairs. */
  function docsetFilterMetaPairs(): Array<[string, string]> {
    const filters = docsetStore.filters
    return [
      ['Filter.prompting_method', formatFilterList(filters.prompting_method)],
      ['Filter.model', formatFilterList(filters.model)],
      ['Filter.register', formatFilterList(filters.register)],
      ['Filter.source', formatFilterList(filters.source)],
      ['IncludeAI', String(docsetStore.includeAi)],
      ['IncludeHuman', String(docsetStore.includeHuman)],
    ]
  }


  /** Injection-safe `# label: value` comment lines for the CSV path. */
  function buildDocsetFilterCsvMeta(): string[] {
    return docsetFilterMetaPairs().map(([label, value]) => csvMeta(label, value))
  }

  function getRowsForExport(options: ExportOptions) {
    const allRows = queryStore.results

    if (options.rowRange === 'selected') {
      return allRows.filter((_, index) => queryStore.selectedRows.has(index))
    }

    if (options.rowRange === 'annotated') {
      const annotationsStore = useAnnotationsStore()
      const corpus = docsetStore.activeCorpus
      return allRows.filter((row) => Boolean(annotationsStore.getAnnotation(rowIdFor(row, corpus))))
    }

    if (options.rowRange === 'category') {
      const annotationsStore = useAnnotationsStore()
      const corpus = docsetStore.activeCorpus
      const target = options.rangeCategoryId ?? null
      return allRows.filter((row) => {
        const record = annotationsStore.getAnnotation(rowIdFor(row, corpus))
        if (!record) return false
        if (target === '' || target === null) return !record.categoryId && Boolean(record.note)
        return record.categoryId === target
      })
    }

    if (options.rowRange === 'range') {
      const start = Math.max(1, options.rangeStart ?? 1)
      const end = Math.max(start, options.rangeEnd ?? start)
      return allRows.slice(start - 1, end)
    }

    return allRows
  }

  /**
   * Build the annotation CSV section (F7): one row per KWIC line that carries an
   * annotation, with its category, note and annotator. Reuses the hardened CSV
   * helpers (injection-safe). The export honors the active row range, so an
   * "annotated-only" / "by-category" range narrows the emitted lines.
   */
  function appendAnnotationCsv(csvLines: string[], options: ExportOptions): void {
    const annotationsStore = useAnnotationsStore()
    const corpus = docsetStore.activeCorpus
    const rows = getRowsForExport(options)
    const annotatedRows = rows
      .map((row) => ({ row, record: annotationsStore.getAnnotation(rowIdFor(row, corpus)) }))
      .filter((entry): entry is { row: typeof entry.row; record: NonNullable<typeof entry.record> } =>
        Boolean(entry.record)
      )
    appendCsvTable(
      csvLines,
      t('export.store.sectionAnnotations'),
      ['row_id', 'position', 'left', 'node', 'right', 'docId', 'category', 'note', 'annotator', ...HIT_SPAN_COLUMNS],
      annotatedRows.map(({ row, record }) => {
        const category = record.categoryId
          ? annotationsStore.categoryById.get(record.categoryId)?.label ?? record.categoryId
          : ''
        return [
          rowIdFor(row, corpus),
          row.position,
          row.left,
          row.match,
          row.right,
          row.docId,
          category,
          record.note ?? '',
          record.annotator ?? '',
          ...hitSpanCells(row),
        ]
      })
    )
  }

  /**
   * Build the annotation CSV section for a SERVER-scope export (F2). The stream can
   * contain rows the browser has never loaded, while annotations are local KWIC-row
   * state. To avoid mixing unrelated corpus/query notes into a full server export,
   * append only annotations attached to the current loaded row range.
   */
  function buildServerAnnotationCsvSection(options: ExportOptions): string | null {
    const annotationsStore = useAnnotationsStore()
    const corpus = docsetStore.activeCorpus
    const annotatedRows = getRowsForExport(options)
      .map((row) => {
        const rowId = rowIdFor(row, corpus)
        return { row, rowId, record: annotationsStore.getAnnotation(rowId) }
      })
      .filter((entry): entry is { row: typeof entry.row; rowId: string; record: NonNullable<typeof entry.record> } =>
        Boolean(entry.record)
      )
    if (annotatedRows.length === 0) return null
    const lines: string[] = []
    appendCsvTable(
      lines,
      t('export.store.sectionAnnotations'),
      ['row_id', 'docId', 'position', 'category', 'note', 'annotator'],
      annotatedRows.map(({ row, rowId, record }) => {
        const category = record.categoryId
          ? annotationsStore.categoryById.get(record.categoryId)?.label ?? record.categoryId
          : ''
        return [rowId, row.docId, row.position, category, record.note ?? '', record.annotator ?? '']
      })
    )
    return lines.join('\n')
  }

  function appendCsvTable(
    csvLines: string[],
    title: string,
    headers: string[],
    rows: Array<Array<unknown>>
  ): void {
    csvLines.push('')
    csvLines.push(t('export.store.csvSection', { title }))
    csvLines.push(csvRow(headers))
    rows.forEach((row) => {
      // Cells are unknown values; csvEscape coerces + hardens each one.
      csvLines.push(row.map((cell) => csvEscape(cell as never)).join(','))
    })
  }

  async function buildResultsCsv(options: ExportOptions): Promise<string> {
    const rows = getRowsForExport(options)
    // Every line carrying a DYNAMIC value (search term, corpus, filter values,
    // versions, …) is routed through csvMeta so a hostile value (leading
    // =/+/-/@ formula trigger, or an embedded newline) cannot break out of the
    // comment line. Purely static labels stay verbatim.
    const metaLines: string[] = []
    metaLines.push('# CandyConc Export')
    metaLines.push(csvMeta(t('export.store.csvTimestamp'), new Date().toISOString()))
    metaLines.push(csvMeta(t('export.store.csvSearchTerm'), queryStore.term || 'n/a'))
    metaLines.push(csvMeta(t('export.store.csvContextSize'), queryStore.contextSize))
    metaLines.push(csvMeta(t('export.store.csvTotalCount'), totalHitsLabel()))
    metaLines.push(csvMeta(t('export.store.csvRowsInExport'), options.includeResults ? rows.length : 0))
    metaLines.push(csvMeta(t('export.store.csvRowScope'), rowRangeLabel(options)))
    metaLines.push(csvMeta(t('export.store.csvCorpus'), docsetStore.activeCorpus))
    metaLines.push(csvMeta(t('export.store.csvDocset'), docsetStore.activeDocsetId ?? 'all'))
    researchScopeCsvMeta(docsetStore).forEach((line) => metaLines.push(line))
    buildDocsetFilterCsvMeta().forEach((line) => metaLines.push(line))

    if (options.includeStatistics) {
      metaLines.push(csvMeta(t('export.store.csvTokens'), activeScopeTokenCount()))
      metaLines.push(csvMeta(t('export.store.csvDocuments'), activeScopeDocumentCount() || 'n/a'))
    }
    if (options.includeReproMeta) {
      metaLines.push('# ReproMeta:')
      metaLines.push(csvMeta('BackendVersion', settingsStore.systemInfo.backendVersion))
      metaLines.push(csvMeta('CorpusLastUpdated', settingsStore.systemInfo.lastUpdated ?? 'n/a'))
      metaLines.push(csvMeta('CacheVersion', presetsStore.cacheVersion))
    }
    const csvRows = [...metaLines]

    if (options.includeResults) {
      appendCsvTable(
        csvRows,
        t('export.store.sectionLoadedRows'),
        ['position', 'left', 'node', 'right', 'docId', 'docTitle', 'metadata', ...HIT_SPAN_COLUMNS],
        rows.map((row) => [
          row.position,
          row.left,
          row.match,
          row.right,
          row.docId,
          row.docTitle ?? '',
          row.metadata ? JSON.stringify(row.metadata) : '',
          ...hitSpanCells(row),
        ])
      )
    }

    if (options.includeFrequency) {
      const frequencyRows = await getFrequency({
        ...activeAnalysisScope(t('export.store.operationFrequencyExport')),
        limit: 50,
        tokenCount: activeScopeTokenCount(),
      })
      appendCsvTable(
        csvRows,
        t('export.store.sectionFrequency'),
        ['rank', 'token', 'frequency', 'relative'],
        frequencyRows.map((row, index) => [
          index + 1,
          row.item,
          row.frequency,
          row.relative,
        ])
      )
    }

    if (options.includeAnnotations) {
      appendAnnotationCsv(csvRows, options)
    }

    return csvRows.join('\n')
  }

  async function loadEvidencePackageForReport(options: ExportOptions): Promise<ExportEvidencePackage> {
    if (!queryStore.term.trim()) {
      throw new Error(t('export.store.evidenceNeedsSearch'))
    }
    const scope = ensureUsableResearchScope(docsetStore, { operation: t('export.store.operationEvidencePackage') })
    if (!scope.ok) throw new Error(scope.message)
    return getExportEvidencePackage({
      query: queryStore.term,
      corpus: docsetStore.activeCorpus || undefined,
      docsetId: scope.docsetId,
      context: queryStore.contextSize,
      sort: queryStore.sortBy ?? null,
      sortDir: queryStore.sortDir,
      caseInsensitive: !queryStore.caseSensitive,
      includeRows: options.includeResults,
    })
  }

  function evidencePackageFilename(pkg: ExportEvidencePackage): string {
    return `${pkg.package_id || 'candyconc_evidence_package'}.json`
  }

  function evidenceText(value: unknown): string {
    if (value === null || value === undefined) return ''
    if (typeof value === 'string') return value
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
    return JSON.stringify(value)
  }

  /** The whole hit of a package row (`match`). Older packages have only `node`. */
  function evidenceHit(row: Record<string, unknown>): string {
    return evidenceText(row.match ?? row.node)
  }

  function evidenceRows(pkg: ExportEvidencePackage): Array<Record<string, unknown>> {
    return Array.isArray(pkg.rows) ? pkg.rows : []
  }

  function nonNegativeInteger(value: unknown): number | null {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
      ? value
      : null
  }

  interface EvidenceResultCounts {
    totalMatches: number | null
    exportedRows: number | null
    exportCap: number | null
    rowsIncluded: number
  }

  /**
   * New evidence packages distinguish the exact denominator from the bounded
   * row collection. Older packages do not, so reports must keep that fact
   * visible instead of inferring completeness from a legacy count.
   */
  function evidenceResultCounts(pkg: ExportEvidencePackage): EvidenceResultCounts {
    const summary = pkg.result_summary
    return {
      totalMatches: nonNegativeInteger(summary.total_matches),
      exportedRows: nonNegativeInteger(summary.exported_rows),
      exportCap: nonNegativeInteger(summary.export_cap),
      rowsIncluded: nonNegativeInteger(summary.rows_included) ?? 0,
    }
  }

  function formatExportCapWarning(
    totalMatches: number | null,
    exportedRows: number | null,
    exportCap: number | null,
  ): string {
    if (totalMatches !== null && exportedRows !== null) {
      const values = { rows: formatNumber(exportedRows), total: formatNumber(totalMatches) }
      return exportCap !== null
        ? t('export.store.capWarningRowsLimit', { ...values, cap: formatNumber(exportCap) })
        : t('export.store.capWarningRows', values)
    }
    return t('export.store.capWarningGeneric')
  }

  function evidenceReportCoverage(pkg: ExportEvidencePackage, options: ExportOptions) {
    const rows = evidenceRows(pkg)
    const counts = evidenceResultCounts(pkg)
    const reportTruncatesRows = options.includeResults && rows.length > EVIDENCE_REPORT_MAX_ROWS
    const rowsInReport = options.includeResults
      ? Math.min(rows.length, EVIDENCE_REPORT_MAX_ROWS)
      : 0
    const packageContainsEveryMatch =
      counts.totalMatches !== null &&
      counts.exportedRows !== null &&
      !pkg.result_summary.truncated &&
      counts.totalMatches === counts.exportedRows &&
      counts.rowsIncluded === counts.exportedRows &&
      rows.length === counts.rowsIncluded
    return {
      rows,
      counts,
      reportTruncatesRows,
      rowsInReport,
      completeInReport: options.includeResults && packageContainsEveryMatch && rowsInReport === counts.totalMatches,
    }
  }

  function evidenceJobFacts(pkg: ExportEvidencePackage): Pick<
    ExportJob,
    'total' | 'exportedRows' | 'exportCap' | 'truncated' | 'warning'
  > {
    const counts = evidenceResultCounts(pkg)
    return {
      total: counts.totalMatches,
      exportedRows: counts.exportedRows,
      exportCap: counts.exportCap,
      truncated: pkg.result_summary.truncated,
      warning: pkg.result_summary.truncated
        ? formatExportCapWarning(counts.totalMatches, counts.exportedRows, counts.exportCap)
        : counts.totalMatches === null
          ? t('export.store.legacyPackageNoTotal')
          : undefined,
    }
  }

  function requestedEvidenceSectionsNotRendered(options: ExportOptions): string[] {
    const unsupportedSections: string[] = []
    if (options.includeFrequency) unsupportedSections.push(t('export.store.sectionFrequencyName'))
    if (options.includeAnnotations) unsupportedSections.push(t('export.store.sectionAnnotations'))
    if (options.includeCollocations) unsupportedSections.push(t('export.store.sectionCollocationsName'))
    return unsupportedSections
  }

  function yesNo(value: boolean): string {
    return value ? t('export.report.yes') : t('export.report.no')
  }

  function buildEvidencePackageMarkdown(
    pkg: ExportEvidencePackage,
    options: ExportOptions,
  ): string {
    const summary = pkg.result_summary
    const coverage = evidenceReportCoverage(pkg, options)
    const { rows, counts, reportTruncatesRows, rowsInReport, completeInReport } = coverage
    const notStated = t('export.report.notStated')
    const lines: string[] = []
    lines.push('# CandyConc Evidence Report')
    lines.push('')
    lines.push(t('export.report.intro'))
    lines.push('')
    lines.push(`## ${t('export.report.provenance')}`)
    lines.push('')
    lines.push(`- EvidencePackage: ${pkg.package_id}`)
    lines.push(`- ${t('export.report.generated')}: ${pkg.generated_at}`)
    lines.push(`- Query-Trace-ID: ${pkg.query_trace_id}`)
    lines.push(`- Query: ${markdownCode(evidenceText(pkg.scope.query))}`)
    lines.push(`- ${t('export.report.corpus')}: ${evidenceText(pkg.corpus.name)}`)
    lines.push(`- Docset: ${evidenceText(pkg.scope.docset_id ?? pkg.corpus.docset_id ?? 'all')}`)
    lines.push(`- Corpus-Fingerprint: ${evidenceText(pkg.corpus.fingerprint_sha256)}`)
    if (pkg.corpus.docset_fingerprint_sha256) {
      lines.push(`- Docset-Fingerprint: ${evidenceText(pkg.corpus.docset_fingerprint_sha256)}`)
    }
    lines.push('')
    lines.push(`## ${t('export.report.resultEvidence')}`)
    lines.push('')
    lines.push(`- ${t('export.report.totalMatches')}: ${counts.totalMatches ?? notStated}`)
    lines.push(`- ${t('export.report.serverRows')}: ${counts.exportedRows ?? notStated}`)
    lines.push(`- ${t('export.report.exportCap')}: ${counts.exportCap ?? notStated}`)
    lines.push(`- ${t('export.report.embeddedRows')}: ${counts.rowsIncluded}`)
    lines.push(`- ${t('export.report.rowsInReport')}: ${rowsInReport}`)
    if (reportTruncatesRows) {
      lines.push(`- ${t('export.report.excerptFirst', { shown: String(EVIDENCE_REPORT_MAX_ROWS), total: String(rows.length) })}`)
    }
    lines.push(`- ${t('export.report.completeInReport')}: ${yesNo(completeInReport)}`)
    lines.push(`- ${t('export.report.truncated')}: ${yesNo(summary.truncated)}`)
    lines.push(`- row_hash_sha256: ${summary.row_hash_sha256}`)
    lines.push('')
    if (summary.truncated) {
      lines.push(`> ${t('export.report.note', { text: formatExportCapWarning(counts.totalMatches, counts.exportedRows, counts.exportCap) })}`)
      lines.push('')
    }
    if (counts.totalMatches === null) {
      lines.push(`> ${t('export.report.legacyNoTotal')}`)
      lines.push('')
    } else if (!completeInReport && !summary.truncated) {
      lines.push(`> ${t('export.report.notAllRows')}`)
      lines.push('')
    }

    lines.push(`## ${t('export.report.methodBlocks')}`)
    lines.push('')
    for (const block of pkg.method_blocks ?? []) {
      const id = evidenceText(block.id)
      const label = evidenceText(block.label) || id
      lines.push(`### ${label}`)
      lines.push('')
      lines.push(`- ID: ${id}`)
      if (block.parameters) {
        lines.push(`- ${t('export.report.parameters')}:`)
        lines.push(...markdownParameters(block.parameters as Record<string, unknown>))
      }
      if (Array.isArray(block.limits) && block.limits.length) {
        lines.push(`- ${t('export.report.limits')}:`)
        for (const limit of block.limits) {
          lines.push(`  - ${evidenceText(limit)}`)
        }
      }
      lines.push('')
    }

    if (options.includeResults) {
      lines.push(`## ${t('export.report.rowsFromPackage')}`)
      lines.push('')
      if (!rows.length) {
        lines.push(`_${t('export.report.noRows')}_`)
      } else {
        const shownRows = rows.slice(0, EVIDENCE_REPORT_MAX_ROWS)
        const header = [
          t('export.report.colLeft'),
          t('export.report.colNode'),
          t('export.report.colRight'),
          t('export.report.colMatch'),
          t('export.report.colDocument'),
        ].map(escapeMarkdown)
        lines.push(`| # | ${header.join(' | ')} |`)
        lines.push('|---:|---|---|---|---|---|')
        shownRows.forEach((row, index) => {
          lines.push(
            `| ${index + 1} | ${escapeMarkdown(evidenceText(row.left))} | ${escapeMarkdown(evidenceText(row.node))} | ${escapeMarkdown(evidenceText(row.right))} | ${escapeMarkdown(evidenceHit(row))} | ${escapeMarkdown(evidenceText(row.doc ?? row.docId))} |`,
          )
        })
        if (rows.length > shownRows.length) {
          const omitted = rows.length - shownRows.length
          lines.push('')
          lines.push(`_${t('export.report.rowsOmitted', { count: String(omitted) }, omitted)}_`)
        }
      }
      lines.push('')
    }

    const unsupportedSections = requestedEvidenceSectionsNotRendered(options)
    if (unsupportedSections.length) {
      lines.push(`## ${t('export.report.notRenderedTitle')}`)
      lines.push('')
      lines.push(t('export.report.notRenderedText', { sections: unsupportedSections.join(', ') }))
      lines.push(t('export.report.notRenderedWarning'))
      lines.push('')
    }

    return lines.join('\n')
  }

  function buildEvidencePackageLatex(
    pkg: ExportEvidencePackage,
    options: ExportOptions,
  ): string {
    const summary = pkg.result_summary
    const coverage = evidenceReportCoverage(pkg, options)
    const { rows, counts, reportTruncatesRows, rowsInReport, completeInReport } = coverage
    const notStated = t('export.report.notStated')
    const latexHash = 'row\\_hash\\_sha256'
    const lines: string[] = []
    lines.push('\\documentclass[11pt]{article}')
    lines.push('\\usepackage[margin=2.5cm]{geometry}')
    lines.push('\\usepackage{booktabs}')
    lines.push('\\usepackage{longtable}')
    lines.push('\\usepackage{hyperref}')
    lines.push('\\title{CandyConc Evidence Report}')
    lines.push(`\\date{${escapeLatex(pkg.generated_at)}}`)
    lines.push('\\begin{document}')
    lines.push('\\maketitle')
    lines.push(`\\section*{${escapeLatex(t('export.report.provenance'))}}`)
    lines.push(`EvidencePackage: ${escapeLatex(pkg.package_id)}\\\\`)
    lines.push(`${escapeLatex(t('export.report.generated'))}: ${escapeLatex(pkg.generated_at)}\\\\`)
    lines.push(`Query-Trace-ID: ${escapeLatex(pkg.query_trace_id)}\\\\`)
    lines.push(`Query: ${escapeLatex(evidenceText(pkg.scope.query))}\\\\`)
    lines.push(`${escapeLatex(t('export.report.corpus'))}: ${escapeLatex(evidenceText(pkg.corpus.name))}\\\\`)
    lines.push(`Docset: ${escapeLatex(evidenceText(pkg.scope.docset_id ?? pkg.corpus.docset_id ?? 'all'))}\\\\`)
    lines.push(`Corpus-Fingerprint: \\texttt{${escapeLatex(evidenceText(pkg.corpus.fingerprint_sha256))}}\\\\`) // i18n-ignore: LaTeX markup around identifiers
    if (pkg.corpus.docset_fingerprint_sha256) {
      lines.push(`Docset-Fingerprint: \\texttt{${escapeLatex(evidenceText(pkg.corpus.docset_fingerprint_sha256))}}\\\\`) // i18n-ignore: LaTeX markup around identifiers
    }
    lines.push(`\\section*{${escapeLatex(t('export.report.resultEvidence'))}}`)
    lines.push(`${escapeLatex(t('export.report.totalMatches'))}: ${counts.totalMatches ?? escapeLatex(notStated)}\\\\`)
    lines.push(`${escapeLatex(t('export.report.serverRows'))}: ${counts.exportedRows ?? escapeLatex(notStated)}\\\\`)
    lines.push(`${escapeLatex(t('export.report.exportCap'))}: ${counts.exportCap ?? escapeLatex(notStated)}\\\\`)
    lines.push(`${escapeLatex(t('export.report.embeddedRows'))}: ${counts.rowsIncluded}\\\\`)
    lines.push(`${escapeLatex(t('export.report.rowsInReport'))}: ${rowsInReport}\\\\`)
    if (reportTruncatesRows) {
      lines.push(`${escapeLatex(t('export.report.excerptFirst', { shown: String(EVIDENCE_REPORT_MAX_ROWS), total: String(rows.length) }))}\\\\`)
    }
    lines.push(`${escapeLatex(t('export.report.completeInReport'))}: ${escapeLatex(yesNo(completeInReport))}\\\\`)
    lines.push(`${escapeLatex(t('export.report.truncated'))}: ${escapeLatex(yesNo(summary.truncated))}\\\\`)
    lines.push(`${latexHash}: \\texttt{${escapeLatex(summary.row_hash_sha256)}}\\\\`) // i18n-ignore: LaTeX markup around identifiers
    if (summary.truncated) {
      lines.push(`${escapeLatex(t('export.report.note', { text: formatExportCapWarning(counts.totalMatches, counts.exportedRows, counts.exportCap) }))}\\\\`)
    }
    if (counts.totalMatches === null) {
      lines.push(`${escapeLatex(t('export.report.legacyNoTotal'))}\\\\`)
    }
    if (!completeInReport) {
      lines.push(`${t('export.report.latexExcerptNote', { hash: latexHash })}\\\\`)
    }
    lines.push(`\\section*{${escapeLatex(t('export.report.methodBlocks'))}}`)
    for (const block of pkg.method_blocks ?? []) {
      lines.push(`\\subsection*{${escapeLatex(evidenceText(block.label ?? block.id))}}`)
      lines.push(`ID: ${escapeLatex(evidenceText(block.id))}\\\\`)
      if (block.parameters) {
        lines.push(`${escapeLatex(t('export.report.parameters'))}: \\texttt{${escapeLatex(JSON.stringify(block.parameters))}}\\\\`) // i18n-ignore: LaTeX markup around identifiers
      }
      if (Array.isArray(block.limits) && block.limits.length) {
        lines.push(`${escapeLatex(t('export.report.limits'))}:\\\\`)
        for (const limit of block.limits) {
          lines.push(`-- ${escapeLatex(evidenceText(limit))}\\\\`)
        }
      }
    }
    if (options.includeResults) {
      lines.push(`\\section*{${escapeLatex(t('export.report.rowsFromPackage'))}}`)
      if (rows.length) {
        const shownRows = rows.slice(0, EVIDENCE_REPORT_MAX_ROWS)
        if (rows.length > shownRows.length) {
          lines.push(
            `${t('export.report.latexRowsExcerpt', { shown: String(shownRows.length), total: String(rows.length), hash: latexHash })}\\\\`,
          )
        }
        const header = [
          t('export.report.colIndex'),
          t('export.report.colLeft'),
          t('export.report.colNode'),
          t('export.report.colRight'),
          t('export.report.colMatch'),
          t('export.report.colDocument'),
        ].map(escapeLatex)
        lines.push('\\begin{longtable}{rlllll}')
        lines.push('\\toprule')
        lines.push(`${header.join(' & ')} \\\\`)
        lines.push('\\midrule')
        shownRows.forEach((row, index) => {
          lines.push(
            `${index + 1} & ${escapeLatex(evidenceText(row.left))} & ${escapeLatex(evidenceText(row.node))} & ${escapeLatex(evidenceText(row.right))} & ${escapeLatex(evidenceHit(row))} & ${escapeLatex(evidenceText(row.doc ?? row.docId))} \\\\`,
          )
        })
        lines.push('\\bottomrule')
        lines.push('\\end{longtable}')
      } else {
        lines.push(`${escapeLatex(t('export.report.noRows'))}\\\\`)
      }
    }
    const unsupportedSections = requestedEvidenceSectionsNotRendered(options)
    if (unsupportedSections.length) {
      lines.push(`\\section*{${escapeLatex(t('export.report.notRenderedTitle'))}}`)
      lines.push(`${escapeLatex(t('export.report.notRenderedText', { sections: unsupportedSections.join(', ') }))}\\\\`)
      lines.push(`${escapeLatex(t('export.report.notRenderedWarning'))}\\\\`)
    }
    lines.push('\\end{document}')
    return lines.join('\n')
  }

  /**
   * Map the export `format` to a server concordance stream format. Returns
   * null for non-streamable report formats (pdf/docx/latex), which always use
   * the client report path regardless of scope.
   */
  function serverStreamFormat(format: ExportFormat): ExportConcordanceFormat | null {
    if (
      format === 'csv' || format === 'tsv' || format === 'json' ||
      format === 'jsonl' || format === 'xlsx'
    ) {
      return format
    }
    return null
  }

  function usesServerConcordance(options: ExportOptions): boolean {
    if (!serverStreamFormat(options.format)) return false
    return options.scope === 'all-server' || options.format !== 'csv'
  }

  function uniqueOperationIds(operationIds: readonly string[]): string[] {
    return Array.from(new Set(operationIds))
  }

  function replayOperationIdsForFormat(format: ExportFormat): string[] {
    if (format === 'pdf') return [REPLAY_EXPORT_OPERATIONS.evidencePackage, REPLAY_EXPORT_OPERATIONS.pdf]
    if (format === 'docx') return [REPLAY_EXPORT_OPERATIONS.evidencePackage, REPLAY_EXPORT_OPERATIONS.docx]
    if (format === 'latex' || format === 'evidence-json') return [REPLAY_EXPORT_OPERATIONS.evidencePackage]
    return []
  }

  function usesEvidencePackageWorkflow(format: ExportFormat): boolean {
    return ['pdf', 'docx', 'latex', 'evidence-json'].includes(format)
  }

  function normalizeExportOptions(options: ExportOptions): ExportOptions {
    return usesEvidencePackageWorkflow(options.format)
      ? { ...options, scope: 'all-server' }
      : options
  }

  function includesLocalKwicRowsWithoutReplayAuthority(options: ExportOptions): boolean {
    return options.format === 'csv' && options.scope !== 'all-server' && options.includeResults
  }

  function operationIdsForExportOptions(options: ExportOptions): string[] {
    const operationIds: string[] = []
    if (options.format === 'evidence-json') {
      operationIds.push(REPLAY_EXPORT_OPERATIONS.evidencePackage)
    } else if (usesServerConcordance(options)) {
      operationIds.push(REPLAY_EXPORT_OPERATIONS.concordance)
    } else {
      operationIds.push(...replayOperationIdsForFormat(options.format))
    }
    if (options.format === 'csv' && options.scope !== 'all-server' && options.includeFrequency) {
      operationIds.push(FREQUENCY_EXPORT_OPERATION_ID)
    }
    if (options.format === 'csv' && options.scope !== 'all-server' && options.includeAnnotations) {
      operationIds.push(ANNOTATION_EXPORT_OPERATION_ID)
    }
    return uniqueOperationIds(operationIds)
  }

  function exportFormatAvailability(
    format: ExportFormat,
    scope: ExportScope = 'loaded',
  ): ExportCapabilityAvailability {
    const operationIds =
      (scope === 'all-server' || format !== 'csv') && serverStreamFormat(format)
        ? [REPLAY_EXPORT_OPERATIONS.concordance]
        : replayOperationIdsForFormat(format)
    return exportOperationAvailability(operationIds)
  }

  function exportOptionsAvailability(options: ExportOptions): ExportCapabilityAvailability {
    const effectiveOptions = normalizeExportOptions(options)
    const operationIds = operationIdsForExportOptions(effectiveOptions)
    if (productCapabilities.hasContract && includesLocalKwicRowsWithoutReplayAuthority(effectiveOptions)) {
      return {
        enabled: false,
        disabledReason: localBrowserExportNotReleased(),
        operationIds,
      }
    }
    if (productCapabilities.hasContract && operationIds.length === 0) {
      return {
        enabled: false,
        disabledReason: localBrowserExportNotReleased(),
        operationIds,
      }
    }
    return exportOperationAvailability(operationIds)
  }

  function exportOperationAvailability(
    operationIds: readonly string[],
  ): ExportCapabilityAvailability {
    const ids = uniqueOperationIds(operationIds)
    if (!productCapabilities.hasContract) {
      const enabled = productCapabilities.allowsMissingContractFallback
      return {
        enabled,
        disabledReason: enabled
          ? null
          : t('export.store.waitingForCatalogue'),
        operationIds: ids,
      }
    }
    const surface = productCapabilities.surfaceAvailability(REPLAY_EXPORT_CAPABILITY_ID)
    if (!surface.enabled) {
      return {
        enabled: false,
        disabledReason: surface.disabledReason ?? t('export.store.notEnabledContext'),
        operationIds: ids,
      }
    }
    for (const operationId of ids) {
      const availability = productCapabilities.productOperationAvailability(operationId)
      if (!availability.enabled) {
        return {
          enabled: false,
          disabledReason: availability.disabledReason
            ?? t('export.store.serverFunctionNotEnabled'),
          operationIds: ids,
        }
      }
    }
    return { enabled: true, disabledReason: null, operationIds: ids }
  }

  async function assertExportOperations(options: ExportOptions): Promise<void> {
    const effectiveOptions = normalizeExportOptions(options)
    await productCapabilities.ensureAccessContext()
    const surfaceAccess = await productCapabilities.ensureCapabilityAccess(
      REPLAY_EXPORT_CAPABILITY_ID,
      'Export',
    )
    if (!surfaceAccess.allowed) {
      throw new Error(surfaceAccess.reason ?? t('export.store.notEnabledContext'))
    }
    const operationIds = operationIdsForExportOptions(effectiveOptions)
    if (productCapabilities.hasContract && includesLocalKwicRowsWithoutReplayAuthority(effectiveOptions)) {
      throw new Error(localBrowserExportNotReleased())
    }
    if (productCapabilities.hasContract && operationIds.length === 0) {
      throw new Error(localBrowserExportNotReleased())
    }
    const availability = exportOperationAvailability(operationIds)
    if (!availability.enabled) {
      throw new Error(availability.disabledReason ?? t('export.store.operationNotEnabled'))
    }
  }

  /** Re-run the active search server-side with exact count and bounded rows. */
  async function exportConcordanceFromServer(
    options: ExportOptions
  ): Promise<ExportJob> {
    let job: ExportJob = {
      id: crypto.randomUUID(),
      format: options.format,
      operationIds: [REPLAY_EXPORT_OPERATIONS.concordance],
      status: 'pending',
      progress: 0,
      timestamp: Date.now(),
    }
    job = startCurrentExportJob(job)
    isExporting.value = true
    exportProgress.value = 0

    try {
      if (!queryStore.term.trim()) {
        throw new Error(t('export.store.serverNeedsSearch'))
      }
      const scope = ensureUsableResearchScope(docsetStore, { operation: t('export.store.operationServerExport') })
      if (!scope.ok) throw new Error(scope.message)
      const format = serverStreamFormat(options.format) ?? 'csv'
      job = patchCurrentExportJob({ status: 'processing', progress: 20 })

      const sort = queryStore.sortBy ?? undefined
      const {
        blob,
        filename,
        total,
        totalMatches = total,
        exportedRows = null,
        exportCap = null,
        truncated,
      } = await getExportConcordance({
        query: queryStore.term,
        corpus: docsetStore.activeCorpus || undefined,
        docsetId: scope.docsetId,
        context: queryStore.contextSize,
        sort: sort ?? null,
        sortDir: queryStore.sortDir,
        // UI default is case-insensitive (caseSensitive === false).
        caseInsensitive: !queryStore.caseSensitive,
        format,
        excelDe: format === 'csv' && options.excelDe === true,
      })

      // The server stream may be row-bounded and carries no annotations. Only
      // CSV can honestly carry an appended annotation section; tsv/json/jsonl/
      // xlsx disable the box, so this only fires for CSV. The excel-de dialect
      // uses ';' as delimiter — the comma-built annotation section would break
      // that file, so it is not appended there (the dialog disables the box).
      let outBlob = blob
      if (format === 'csv' && options.includeAnnotations && options.excelDe !== true) {
        const annotationSection = buildServerAnnotationCsvSection(options)
        if (annotationSection) {
          const base = await blob.text()
          outBlob = new Blob([base, '\n', annotationSection, '\n'], {
            type: 'text/csv;charset=utf-8;',
          })
        }
      }

      job = patchCurrentExportJob({
        progress: 90,
        filename,
        total: totalMatches,
        exportedRows,
        exportCap,
        truncated,
        warning: truncated
          ? formatExportCapWarning(totalMatches, exportedRows, exportCap)
          : undefined,
      })
      downloadBlob(outBlob, filename)

      job = patchCurrentExportJob({ status: 'completed', progress: 100 })
      rememberExportJob(job)
      return job
    } catch (error) {
      job = patchCurrentExportJob({
        status: 'error',
        error: error instanceof Error ? error.message : t('export.store.serverFailed'),
      })
      rememberExportJob(job)
      throw error
    } finally {
      isExporting.value = false
      currentJob.value = null
    }
  }

  async function exportEvidencePackageFromServer(
    options: ExportOptions
  ): Promise<ExportJob> {
    await assertExportOperations({ ...options, format: 'evidence-json' })
    let job: ExportJob = {
      id: crypto.randomUUID(),
      format: options.format,
      operationIds: [REPLAY_EXPORT_OPERATIONS.evidencePackage],
      status: 'pending',
      progress: 0,
      timestamp: Date.now(),
    }
    job = startCurrentExportJob(job)
    isExporting.value = true
    exportProgress.value = 0

    try {
      if (!queryStore.term.trim()) {
        throw new Error(t('export.store.evidenceNeedsSearch'))
      }
      const scope = ensureUsableResearchScope(docsetStore, { operation: t('export.store.operationEvidencePackage') })
      if (!scope.ok) throw new Error(scope.message)
      job = patchCurrentExportJob({ status: 'processing', progress: 20 })

      const pkg = await getExportEvidencePackage({
        query: queryStore.term,
        corpus: docsetStore.activeCorpus || undefined,
        docsetId: scope.docsetId,
        context: queryStore.contextSize,
        sort: queryStore.sortBy ?? null,
        sortDir: queryStore.sortDir,
        caseInsensitive: !queryStore.caseSensitive,
        includeRows: options.includeResults,
      })
      const filename = evidencePackageFilename(pkg)
      const blob = new Blob([JSON.stringify(pkg, null, 2)], {
        type: 'application/json;charset=utf-8;',
      })

      job = patchCurrentExportJob({
        progress: 90,
        filename,
        ...evidenceJobFacts(pkg),
      })
      downloadBlob(blob, filename)

      job = patchCurrentExportJob({ status: 'completed', progress: 100 })
      rememberExportJob(job)
      return job
    } catch (error) {
      job = patchCurrentExportJob({
        status: 'error',
        error: error instanceof Error ? error.message : t('export.store.evidenceFailed'),
      })
      rememberExportJob(job)
      throw error
    } finally {
      isExporting.value = false
      currentJob.value = null
    }
  }

  async function exportData(options: ExportOptions): Promise<ExportJob> {
    const effectiveOptions = normalizeExportOptions(options)
    await assertExportOperations(effectiveOptions)
    if (effectiveOptions.format === 'evidence-json') {
      return exportEvidencePackageFromServer(effectiveOptions)
    }
    if (effectiveOptions.includeCollocations && effectiveOptions.format === 'csv') {
      throw new Error(t('export.store.collocationBlocked'))
    }
    // Exact-count server export bypasses the client report builder.
    if (usesServerConcordance(effectiveOptions)) {
      return exportConcordanceFromServer(effectiveOptions)
    }
    let job: ExportJob = {
      id: crypto.randomUUID(),
      format: effectiveOptions.format,
      operationIds: operationIdsForExportOptions(effectiveOptions),
      status: 'pending',
      progress: 0,
      timestamp: Date.now()
    }

    job = startCurrentExportJob(job)
    isExporting.value = true
    exportProgress.value = 0

    try {
      job = patchCurrentExportJob({ status: 'processing', progress: 10 })

      // Generate filename
      const date = new Date().toISOString().slice(0, 10)
      const ext =
        effectiveOptions.format === 'docx'
          ? 'docx'
          : effectiveOptions.format === 'latex'
            ? 'tex'
            : effectiveOptions.format
      job = patchCurrentExportJob({ filename: `candyconc_export_${date}.${ext}` })

      if (effectiveOptions.format === 'csv') {
        const csv = await buildResultsCsv(effectiveOptions)
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
        downloadBlob(blob, job.filename!)
        job = patchCurrentExportJob({ status: 'completed', progress: 100 })
      } else if (effectiveOptions.format === 'latex') {
        const pkg = await loadEvidencePackageForReport(effectiveOptions)
        job = patchCurrentExportJob({
          progress: 40,
          ...evidenceJobFacts(pkg),
        })
        const latex = buildEvidencePackageLatex(pkg, effectiveOptions)
        const blob = new Blob([latex], { type: 'text/x-tex;charset=utf-8;' })
        downloadBlob(blob, job.filename!)
        job = patchCurrentExportJob({ status: 'completed', progress: 100 })
      } else {
        const pkg = await loadEvidencePackageForReport(effectiveOptions)
        const markdown = buildEvidencePackageMarkdown(pkg, effectiveOptions)
        job = patchCurrentExportJob({
          progress: 40,
          ...evidenceJobFacts(pkg),
        })

        const blob = effectiveOptions.format === 'pdf'
          ? await exportPdf(markdown)
          : await exportDocx(markdown)

        job = patchCurrentExportJob({ progress: 90 })

        downloadBlob(blob, job.filename!)
        job = patchCurrentExportJob({ status: 'completed', progress: 100 })
      }

      rememberExportJob(job)

      return job
    } catch (error) {
      job = patchCurrentExportJob({
        status: 'error',
        error: error instanceof Error ? error.message : t('export.store.failed'),
      })
      rememberExportJob(job)
      throw error
    } finally {
      isExporting.value = false
      currentJob.value = null
    }
  }

  async function exportPDF(options: Partial<ExportOptions> = {}): Promise<ExportJob> {
    return exportData({
      ...defaultOptions.value,
      ...options,
      format: 'pdf'
    })
  }

  async function exportDOCX(options: Partial<ExportOptions> = {}): Promise<ExportJob> {
    return exportData({
      ...defaultOptions.value,
      ...options,
      format: 'docx'
    })
  }

  async function exportCSV(options: Partial<ExportOptions> = {}): Promise<ExportJob> {
    return exportData({
      ...defaultOptions.value,
      ...options,
      format: 'csv'
    })
  }

  async function exportLaTeX(options: Partial<ExportOptions> = {}): Promise<ExportJob> {
    return exportData({
      ...defaultOptions.value,
      ...options,
      format: 'latex',
    })
  }

  function setDefaultOptions(options: Partial<ExportOptions>) {
    defaultOptions.value = { ...defaultOptions.value, ...options }
  }

  function clearHistory() {
    exportHistory.value = []
  }

  function setPreselectedFormat(format: ExportFormat | null) {
    preselectedFormat.value = format
  }

  return {
    // State
    isExporting,
    exportProgress,
    currentJob,
    exportHistory,
    defaultOptions,
    preselectedFormat,
    exportFormatAvailability,
    exportOptionsAvailability,
    exportOperationAvailability,

    // Actions
    exportData,
    exportPDF,
    exportDOCX,
    exportCSV,
    exportLaTeX,
    exportEvidencePackageFromServer,
    setDefaultOptions,
    clearHistory,
    setPreselectedFormat,
  }
})
