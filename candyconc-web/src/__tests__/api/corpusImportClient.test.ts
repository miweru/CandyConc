/**
 * Corpus import API client tests — lock down the intended frontend contract for
 * durable import jobs without requiring a backend. If the client exports are not
 * wired yet, these tests should fail at import time and guide implementation.
 */
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import {
  activateCorpus,
  cancelCorpusImportJob,
  createCorpusImportJob,
  getCorpusBuildReport,
  getCorpusImportJob,
  getCorpusImportMethods,
  getCorpusImportReports,
  listCorpusImportJobs,
  preflightCorpusImport,
} from '@/api/client'

let captured: Array<{ method: string; url: string; body: unknown }> = []

function stubFetch(payload: unknown, status = 200) {
  captured = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      let method = init?.method ?? 'GET'
      let url = String(input)
      let body: unknown = null

      if (input instanceof Request) {
        method = input.method
        url = input.url
        const text = await input.clone().text()
        body = text ? JSON.parse(text) : null
      } else if (init?.body) {
        body = JSON.parse(String(init.body))
      }

      captured.push({ method, url, body })
      return new Response(JSON.stringify(payload), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

function requestFromCall(index = 0) {
  const call = captured[index]
  expect(call).toBeDefined()
  return call!
}

const queuedJob = {
  job_id: 'import-123',
  status: 'queued',
  progress: 0,
  corpus: 'bundestag-2026',
  message: 'Queued',
  created_at: 1770883200,
  updated_at: 1770883200,
}

const reports = {
  schema_version: 'corpus-import-reports-v1',
  job_id: 'import-123',
  reports: {
    manifest: {
      label: 'Import manifest',
      url: '/api/v1/corpora/imports/import-123/reports',
      content_type: 'application/json',
    },
  },
}

const preflight = {
  schema_version: 'corpus-import-preflight-v1',
  method: 'prealigned_csv',
  input_path: '/safe/imports/paired.csv',
  status: 'warning',
  ok: true,
  blocking: false,
  max_severity: 'warning',
  summary: 'Preflight mit Warnungen abgeschlossen.',
  errors: [],
  warnings: ['Reject-Policy collect kann verworfene Zeilen sammeln.'],
  checks: [
    {
      key: 'reject_policy',
      label: 'Reject-Policy',
      status: 'warn',
      severity: 'warning',
      blocking: false,
      message: 'collect',
      evidence: {},
    },
  ],
  evidence: {
    path: '/safe/imports/paired.csv',
    exists: true,
    is_file: true,
    suffix: '.csv',
    columns: ['text', 'pair_id', 'pair_role'],
  },
}

describe('corpus import API client', () => {
  beforeEach(() => {
    stubFetch(queuedJob)
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('creates an import job with the backend payload shape and omits unset options', async () => {
    const result = await createCorpusImportJob({
      method: 'vrt',
      input_path: '/safe/imports/bundestag.vrt',
      target_name: 'bundestag-2026',
      activate_on_success: true,
      metadata: { language: 'de', license: 'internal' },
    })

    expect(result.job_id).toBe('import-123')
    const { method, url, body } = requestFromCall()
    expect(method).toBe('POST')
    expect(url).toContain('/api/v1/corpora/imports')
    expect(body).toEqual({
      method: 'vrt',
      input_path: '/safe/imports/bundestag.vrt',
      target_name: 'bundestag-2026',
      activate_on_success: true,
      metadata: { language: 'de', license: 'internal' },
    })
  })

  it('sends the explicit partial-import acknowledgement only when requested', async () => {
    stubFetch({ name: 'partial-demo', path: '/indexes/partial-demo', partial_input: true })

    await activateCorpus('partial-demo', { acknowledgePartialInput: true })

    const { method, url, body } = requestFromCall()
    expect(method).toBe('POST')
    expect(url).toContain('/api/v1/corpora/partial-demo/activate')
    expect(body).toEqual({ acknowledge_partial_input: true })
  })

  it('validates the create-job response instead of accepting malformed snapshots', async () => {
    stubFetch({ status: 'queued' })

    await expect(
      createCorpusImportJob({ method: 'parquet', input_path: '/safe/imports/broken.parquet' })
    ).rejects.toThrow()
  })

  it('gets and cancels a corpus import job by id', async () => {
    await getCorpusImportJob('import-123')
    await cancelCorpusImportJob('import-123')

    expect(captured.map((call) => [call.method, call.url])).toEqual([
      ['GET', expect.stringContaining('/api/v1/corpora/imports/import-123')],
      ['POST', expect.stringContaining('/api/v1/corpora/imports/import-123/cancel')],
    ])
  })

  it('lists retained corpus import jobs for observable reload recovery', async () => {
    stubFetch({ jobs: [queuedJob], count: 1 })

    const result = await listCorpusImportJobs()

    expect(result).toHaveLength(1)
    expect(result[0]?.job_id).toBe('import-123')
    const { method, url } = requestFromCall()
    expect(method).toBe('GET')
    expect(url).toContain('/api/v1/corpora/imports')
  })

  it('fetches available report descriptors for a completed import job', async () => {
    stubFetch(reports)

    const result = await getCorpusImportReports('import-123')

    expect(result.schema_version).toBe('corpus-import-reports-v1')
    expect(result.job_id).toBe('import-123')
    expect(result.reports.manifest).toMatchObject({ label: 'Import manifest' })
    const { method, url } = requestFromCall()
    expect(method).toBe('GET')
    expect(url).toContain('/api/v1/corpora/imports/import-123/reports')
  })

  it('rejects malformed versioned import-report envelopes', async () => {
    stubFetch({
      schema_version: 'corpus-import-reports-v1',
      job_id: 'import-123',
      reports: [{ kind: 'manifest' }],
    })

    await expect(getCorpusImportReports('import-123')).rejects.toThrow(/did not match the expected schema/)
  })

  it('loads typed import method descriptors for generic UI rendering', async () => {
    stubFetch({
      methods: [
        {
          schema_version: 'corpus-import-method-v1',
          method: 'prealigned_csv',
          label: 'Pre-grouped CSV/TSV',
          input: {
            kind: 'server_file',
            extensions: ['.csv', '.tsv'],
            accepts_directories: false,
            path_hint: '/data/imports/paired.csv',
          },
          option_keys: ['text_column', 'pair_key_column', 'reject_policy'],
          option_specs: [
            { key: 'text_column', type: 'string', required: true, default: 'text' },
            { key: 'pair_key_column', type: 'string', required: true, default: 'pair_id' },
            {
              key: 'reject_policy',
              type: 'choice',
              default: 'collect',
              choices: [{ value: 'collect', label: 'collect' }, { value: 'fail_fast', label: 'fail_fast' }],
            },
          ],
          expected_columns: [{ key: 'pair_id', required: true, configured_by: 'pair_key_column' }],
          output: {
            paired: true,
            pairing_kind: 'external_pair_keys',
            emitted_features: ['pair_metadata'],
            limitations: ['Keine inhaltliche Alignmentprüfung.'],
          },
          emitted_features: ['pair_metadata'],
          reports: [{ key: 'reject_report', label: 'Reject-Report' }],
        },
      ],
    })

    const result = await getCorpusImportMethods()

    expect(result[0]?.option_specs[2]?.choices).toHaveLength(2)
    expect(result[0]?.expected_columns[0]?.configured_by).toBe('pair_key_column')
    expect(result[0]?.output?.limitations[0]).toContain('Alignmentprüfung')
    const { method, url } = requestFromCall()
    expect(method).toBe('GET')
    expect(url).toContain('/api/v1/corpora/import-methods')
  })

  it('rejects stripped import method descriptors without the typed contract', async () => {
    stubFetch({ methods: [{ method: 'parquet' }] })

    await expect(getCorpusImportMethods()).rejects.toThrow()
  })

  it('runs corpus import preflight with the same payload shape as job creation', async () => {
    stubFetch(preflight)

    const result = await preflightCorpusImport({
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      reject_policy: 'collect',
    })

    expect(result.status).toBe('warning')
    expect(result.blocking).toBe(false)
    expect(result.evidence.columns).toEqual(['text', 'pair_id', 'pair_role'])
    const { method, url, body } = requestFromCall()
    expect(method).toBe('POST')
    expect(url).toContain('/api/v1/corpora/import-preflight')
    expect(body).toEqual({
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      reject_policy: 'collect',
    })
  })

  it('rejects stripped preflight responses without the typed evidence contract', async () => {
    stubFetch({ ok: true })

    await expect(
      preflightCorpusImport({ method: 'parquet', input_path: '/safe/imports/demo.parquet' })
    ).rejects.toThrow()
  })

  it('accepts flattened import report responses from the backend', async () => {
    stubFetch({
      job_id: 'import-123',
      build_report: { status: 'ok' },
      reject_report: { rejected_rows: 2 },
      manifest: { paired: true },
    })

    const result = await getCorpusImportReports('import-123')

    expect(result.schema_version).toBe('legacy-flattened-import-reports')
    expect(result.job_id).toBe('import-123')
    expect(Array.isArray(result.reports)).toBe(false)
    expect((result.reports as Record<string, unknown>).reject_report).toEqual({ rejected_rows: 2 })
  })

  it('accepts versioned report envelopes and preserves legacy top-level keys', async () => {
    stubFetch({
      schema_version: 'corpus-import-reports-v1',
      job_id: 'import-123',
      reports: {
        build_report: { status: 'ok' },
        reject_report: { rejected_rows: 0 },
      },
      build_report: { status: 'ok' },
    })

    const result = await getCorpusImportReports('import-123')

    expect(result.schema_version).toBe('corpus-import-reports-v1')
    expect((result.reports as Record<string, unknown>).build_report).toEqual({ status: 'ok' })
    expect((result as unknown as Record<string, unknown>).build_report).toEqual({ status: 'ok' })
  })

  it('loads versioned corpus build-report envelopes', async () => {
    stubFetch({
      schema_version: 'corpus-build-report-v1',
      corpus: 'demo',
      path: '/indexes/demo',
      reports: {
        build_report: { status: 'ok' },
        manifest: { import_mode: 'parquet' },
      },
      build_report: { status: 'ok' },
    })

    const result = await getCorpusBuildReport('demo')

    expect(result.schema_version).toBe('corpus-build-report-v1')
    expect(result.corpus).toBe('demo')
    expect(result.path).toBe('/indexes/demo')
    expect((result.reports as Record<string, unknown>).manifest).toEqual({ import_mode: 'parquet' })
    expect((result as unknown as Record<string, unknown>).build_report).toEqual({ status: 'ok' })
    const { method, url } = requestFromCall()
    expect(method).toBe('GET')
    expect(url).toContain('/api/v1/corpora/demo/build-report')
  })

  it('normalizes legacy flattened corpus build-report responses explicitly', async () => {
    stubFetch({
      corpus: 'demo',
      path: '/indexes/demo',
      build_report: { status: 'ok' },
      manifest: { import_mode: 'parquet' },
    })

    const result = await getCorpusBuildReport('demo')

    expect(result.schema_version).toBe('legacy-flattened-corpus-build-report')
    expect(result.corpus).toBe('demo')
    expect((result.reports as Record<string, unknown>).build_report).toEqual({ status: 'ok' })
  })
})
