import { beforeEach, describe, expect, it } from 'vitest'
import {
  createRunPackage,
  createRunsPackage,
  exportPackageAsJson,
  exportRunAsBibTeX,
} from '@/services/runExportService'
import type { RunRecordV1 } from '@/types/copilot-protocol'
import { runRecords } from '@/actions/traceRecorder'

function sensitiveRun(overrides: Partial<RunRecordV1> = {}): RunRecordV1 {
  return {
    schemaVersion: '2.0',
    runId: 'run-secret',
    ts: 1,
    kind: 'query',
    actionType: 'query/execute',
    actionPayload: { term: 'vertrauliche-suche' },
    corpus: { corpusId: 'demo', subcorpusHash: 'scope-abc' },
    resultRef: { type: 'query/execute', hash: 'result-hash', rows: 3 },
    summary: 'Sensitive run',
    notes: [],
    evidence: {
      schemaVersion: '2.0',
      provenance: 'frontend_actionbus',
      completeness: 'partial',
      corpusFingerprint: {
        corpusId: 'demo',
        subcorpusHash: 'scope-abc',
        metadataSchemaHash: 'meta-fp',
      },
      researchScope: {
        corpusId: 'demo',
        scopeHash: 'scope-hash',
        scopeStatus: 'fresh',
        metadataSchemaHash: 'meta-fp',
      },
      toolFingerprint: { actionType: 'query/execute' },
      resultFingerprint: { resultType: 'query/execute', resultHash: 'result-hash', rows: 3 },
      warnings: [],
    },
    ...overrides,
  }
}

describe('runExportService', () => {
  beforeEach(() => {
    runRecords.value = []
  })

  it('redacts action payloads when creating a single-run package', () => {
    runRecords.value = [sensitiveRun()]

    const pkg = createRunPackage('run-secret')

    expect(pkg).not.toBeNull()
    expect(pkg!.type).toBe('run')
    expect(pkg!.run?.actionPayload).toEqual({ redacted: true, reason: 'run_export_default' })
    expect(JSON.stringify(pkg)).not.toContain('vertrauliche-suche')
  })

  it('returns null for unknown run ids', () => {
    expect(createRunPackage('missing-run')).toBeNull()
    expect(createRunsPackage(['missing-run'])).toBeNull()
  })

  it('deep-redacts payloads in multi-run JSON exports', () => {
    runRecords.value = [
      sensitiveRun(),
      sensitiveRun({ runId: 'run-secret-2', actionPayload: { term: 'zweite-geheime-suche' } }),
    ]

    const pkg = createRunsPackage(['run-secret', 'run-secret-2'])
    expect(pkg).not.toBeNull()

    const json = exportPackageAsJson(pkg!)
    const parsed = JSON.parse(json)

    expect(json).not.toContain('vertrauliche-suche')
    expect(json).not.toContain('zweite-geheime-suche')
    expect(parsed.type).toBe('runs')
    expect(parsed.runs).toHaveLength(2)
    expect(parsed.runs[0].actionPayload.redacted).toBe(true)
    expect(parsed.runs[1].actionPayload.redacted).toBe(true)
  })

  it('includes research scope evidence in BibTeX run citations', () => {
    const bibtex = exportRunAsBibTeX(sensitiveRun())

    expect(bibtex).toContain('ScopeHash: scope-hash')
    expect(bibtex).toContain('ScopeStatus: fresh')
    expect(bibtex).toContain('MetadataSchemaHash: meta-fp')
    expect(bibtex).toContain('run JSON export')
  })

  it('does not cite the fictional candyconc:// URL scheme', () => {
    const bibtex = exportRunAsBibTeX(sensitiveRun())

    expect(bibtex).not.toContain('candyconc://')
    expect(bibtex).not.toMatch(/^\s*url\s*=/m)
  })
})
