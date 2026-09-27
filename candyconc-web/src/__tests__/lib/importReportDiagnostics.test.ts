import { describe, expect, it } from 'vitest'

import {
  importReportEntriesFromPayload,
  importReportOutcomeFromPayload,
} from '@/lib/importReportDiagnostics'

describe('import report diagnostics adapter', () => {
  it('turns flattened backend reports into structured diagnostics', () => {
    const entries = importReportEntriesFromPayload({
      job_id: 'import-123',
      manifest: {
        data: {
          import_mode: 'prealigned_csv',
          token_count: 1200,
          doc_count: 12,
          complete: false,
          capabilities: { kwic_ready: true, semantic: false, parallel: true },
          paired: true,
          pair_axes: ['model'],
          annotation_source: 'native',
        },
      },
      reject_report: {
        rejected_rows: 2,
        total_rows: 42,
        rejection_rate: 0.0476,
        by_reason: { missing_text: 2 },
        samples: [{ row: 7, reason: 'missing_text', text: 'sensitive row' }],
        reject_policy: 'collect',
      },
      build_report: {
        status: 'done',
        builder: 'build_fast_index_from_csv',
        output_path: '/indexes/demo',
      },
      build_report_md: null,
      raw: {
        'build_report.json': { data: { status: 'done' } },
        'index_manifest.json': { data: { import_mode: 'prealigned_csv' } },
      },
    })

    expect(entries.map((entry) => entry.key)).toEqual([
      'build_report',
      'reject_report',
      'manifest',
      'raw',
    ])
    const manifest = entries.find((entry) => entry.key === 'manifest')
    const rejects = entries.find((entry) => entry.key === 'reject_report')
    const build = entries.find((entry) => entry.key === 'build_report')
    const raw = entries.find((entry) => entry.key === 'raw')

    expect(build).toMatchObject({ known: true, role: 'build', expertOnly: false })
    expect(build?.fullText).toContain('"status": "done"')
    expect(manifest?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Importmodus', value: 'prealigned_csv' }),
      expect.objectContaining({ label: 'Tokens', value: '1.200' }),
      expect.objectContaining({
        label: 'Manifest vollständig',
        severity: 'error',
        value: 'nein',
        note: expect.stringContaining('releasebereiter Zielkorpus'),
      }),
      expect.objectContaining({ label: 'Manifest-Fähigkeiten', value: 'kwic_ready, parallel' }),
      expect.objectContaining({
        label: 'Paarmetadaten',
        note: expect.stringContaining('nicht automatisch inhaltliche Alignmentqualität'),
      }),
    ]))
    expect(rejects?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({
        label: 'Verworfene Zeilen',
        severity: 'warning',
        value: '2',
      }),
      expect.objectContaining({
        label: 'Reject-Gründe',
        severity: 'warning',
        value: '1',
        note: expect.stringContaining('Rohzeilen bleiben Debug-Evidenz'),
      }),
      expect.objectContaining({
        label: 'Reject-Samples',
        severity: 'warning',
        value: '1',
        note: expect.stringContaining('nicht als Rohdaten'),
      }),
      expect.objectContaining({ label: 'Reject-Policy', value: 'collect' }),
    ]))
    expect(rejects?.snippet).not.toContain('sensitive row')
    expect(rejects?.snippet).toContain('redigierte Samples')
    expect(build?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Status', value: 'done' }),
      expect.objectContaining({ label: 'Ausgabe', value: '/indexes/demo' }),
    ]))
    expect(raw).toMatchObject({
      label: 'Rohreports (Debug)',
      role: 'debug',
      known: true,
      expertOnly: true,
    })
    expect(raw?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({
        label: 'Debug-Scope',
        severity: 'warning',
        note: expect.stringContaining('kein normalisierter wissenschaftlicher Report'),
      }),
      expect.objectContaining({ label: 'Report-Schlüssel', value: 'build_report.json, index_manifest.json' }),
    ]))
  })

  it('derives a conservative import outcome from reject and manifest reports', () => {
    const outcome = importReportOutcomeFromPayload({
      reject_report: {
        rejected_rows: 2,
        total_rows: 42,
        reject_policy: 'collect',
      },
      manifest: {
        complete: false,
        incomplete_pair_count: 3,
      },
    })

    expect(outcome).toMatchObject({
      partialInput: true,
      rejectedRows: 2,
      readiness: 'partial_input',
    })
    expect(outcome.warnings.join(' ')).toContain('Eingabezeile')
    expect(outcome.warnings.join(' ')).toContain('nicht vollständig')
    expect(outcome.warnings.join(' ')).toContain('Paar-/Alignment')
  })

  it('keeps array report descriptors readable without inventing diagnostics', () => {
    const entries = importReportEntriesFromPayload([
      { kind: 'manifest', label: 'Manifest', url: '/reports/manifest.json' },
    ])

    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      key: 'manifest',
      label: 'Manifest',
      summary: 'URL: /reports/manifest.json',
      diagnostics: [],
    })
  })

  it('unwraps versioned build-report envelopes before rendering entries', () => {
    const entries = importReportEntriesFromPayload({
      schema_version: 'corpus-build-report-v1',
      corpus: 'demo',
      path: '/indexes/demo',
      reports: {
        manifest: { import_mode: 'parquet' },
        build_report: { status: 'ok' },
        reject_report: null,
      },
      build_report: { status: 'ok' },
    })

    expect(entries.map((entry) => entry.key)).toEqual(['build_report', 'manifest'])
    expect(entries.some((entry) => entry.key === 'schema_version')).toBe(false)
    expect(entries.find((entry) => entry.key === 'manifest')?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Importmodus', value: 'parquet' }),
    ]))
  })

  it('normalizes pairing-schema and incomplete-pair evidence from manifests', () => {
    const entries = importReportEntriesFromPayload({
      manifest: {
        data: {
          import_mode: 'prealigned_csv',
          paired: true,
          pairing_kind: 'external_pair_keys',
          pair_count: 42,
          incomplete_pair_count: 3,
          pairing_schema: {
            schema_id: 'axis_pairing_v1',
            group_key_field: 'pair_id',
            anchor_role_field: 'role',
            default_anchor_role: 'source',
            variant_axis_fields: ['language', 'version'],
          },
        },
      },
    })

    const manifest = entries[0]

    expect(manifest?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Paarmetadaten', value: 'ja' }),
      expect.objectContaining({ label: 'Pairing-Art', value: 'external_pair_keys' }),
      expect.objectContaining({ label: 'Pairing-Schema', value: 'axis_pairing_v1' }),
      expect.objectContaining({ label: 'Pairing-Gruppenfeld', value: 'pair_id' }),
      expect.objectContaining({ label: 'Ankerrollenfeld', value: 'role' }),
      expect.objectContaining({ label: 'Default-Ankerrolle', value: 'source' }),
      expect.objectContaining({ label: 'Paarachsen', value: 'language, version' }),
      expect.objectContaining({
        label: 'Unvollständige Paare',
        severity: 'warning',
        value: '3',
        note: expect.stringContaining('Pairing-Lücken'),
      }),
      expect.objectContaining({ label: 'Paaranzahl', value: '42' }),
    ]))
  })

  it('shows data-dependent pairing from nested feature metadata', () => {
    const entries = importReportEntriesFromPayload({
      manifest: {
        features: {
          alignment: {
            paired: false,
            paired_data_dependent: true,
            pairing_schema: {
              schema_id: 'legacy_ref_doc_v1',
              group_key_field: 'ref_doc',
            },
          },
        },
      },
    })

    const manifest = entries[0]

    expect(manifest?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({
        label: 'Paarmetadaten',
        value: 'datenabhängig',
        note: expect.stringContaining('passende Zeilen-/Dokumentmetadaten'),
      }),
      expect.objectContaining({ label: 'Pairing-Schema', value: 'legacy_ref_doc_v1' }),
      expect.objectContaining({ label: 'Pairing-Gruppenfeld', value: 'ref_doc' }),
    ]))
  })

  it('keeps VRT reports first-class instead of treating them as anonymous raw JSON', () => {
    const entries = importReportEntriesFromPayload({
      vrt_import_report: {
        documents: 3,
        tokens: 150,
        regions: ['doc', 's'],
        skipped_short_docs: 2,
        inconsistent_column_lines: 1,
        annotation_mode: 'native',
        warnings: ['ein leeres Element ignoriert'],
      },
    })

    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      key: 'vrt_import_report',
      label: 'VRT-Import-Report',
      role: 'quality',
      known: true,
      expertOnly: false,
    })
    expect(entries[0]?.diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'VRT-Dokumente', value: '3' }),
      expect.objectContaining({ label: 'VRT-Tokens', value: '150' }),
      expect.objectContaining({ label: 'Annotationsmodus', value: 'native' }),
      expect.objectContaining({ label: 'Übersprungene Kurztexte', severity: 'warning', value: '2' }),
      expect.objectContaining({ label: 'Inkonsistente Spaltenzeilen', severity: 'warning', value: '1' }),
      expect.objectContaining({ label: 'Warnungen', severity: 'warning' }),
    ]))
  })

  it('marks unknown backend report types as expert evidence', () => {
    const entries = importReportEntriesFromPayload({
      custom_future_report: {
        status: 'ok',
        count: 2,
      },
    })

    expect(entries[0]).toMatchObject({
      key: 'custom_future_report',
      label: 'Nicht typisierter Report: custom_future_report',
      role: 'unknown',
      known: false,
      expertOnly: true,
    })
    expect(entries[0]?.summary).toContain('Backend-Report ohne bekannten UI-Typ')
  })
})
