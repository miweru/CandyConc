import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import CorpusImportPreflightEvidence from '@/components/corpus/CorpusImportPreflightEvidence.vue'
import type { CorpusImportPreflightResponse } from '@/api/client'

function prealignedPreflight(): CorpusImportPreflightResponse {
  return {
    schema_version: 'corpus-import-preflight-v1',
    method: 'prealigned_csv',
    input_path: '/imports/aligned.csv',
    status: 'warning',
    ok: true,
    blocking: false,
    max_severity: 'warning',
    summary: 'Preflight mit Warnungen.',
    errors: [],
    warnings: ['Reject-Policy prüft unvollständige Paare.'],
    checks: [
      {
        key: 'pair_key',
        label: 'Pair-Key',
        status: 'pass',
        severity: 'info',
        blocking: false,
        message: 'Pair-Key-Spalte vorhanden.',
        evidence: { column: 'pair_id', distinct_pairs: 42 },
      },
      {
        key: 'collect_policy',
        label: 'Collect-Policy',
        status: 'warn',
        severity: 'warning',
        blocking: false,
        message: 'Unvollständige Paare werden gesammelt.',
        evidence: { reject_policy: 'collect', incomplete_sample: ['p-7'] },
      },
    ],
    evidence: {
      path: '/imports/aligned.csv',
      exists: true,
      is_file: true,
      is_dir: false,
      size_bytes: 2048,
      suffix: '.csv',
      target_name: 'aligned-demo',
      managed_corpus_dir: '/corpora',
      target_path: '/corpora/aligned-demo',
      columns: ['group_id', 'pair_role', 'body', 'lang'],
      column_sample: {
        row_count_checked: 10,
        sample: [{ group_id: 'p-1', pair_role: 'source' }],
      },
      prealigned_pairing_sample: {
        sample_bounded: true,
        sample_rows: 10,
        sample_row_limit: 200,
        pair_key_column: 'group_id',
        pair_role_column: 'pair_role',
        anchor_role: 'source',
        pair_count: 5,
        role_counts: { source: 5, target: 5 },
        singleton_pair_count: 0,
        missing_anchor_pair_count: 0,
      },
      method_contract: {
        schema_version: 'corpus-import-method-v1',
        method: 'prealigned_csv',
        label: 'Prealigned CSV',
        description: 'Importiert bereits alignierte Parallel- oder Revisionsdaten.',
        input: {
          kind: 'server_file',
          extensions: ['.csv'],
          accepts_directories: false,
          path_hint: '/imports/*.csv',
        },
        availability: { status: 'available' },
        option_keys: ['text_column', 'pair_key_column', 'pair_role_column'],
        option_specs: [
          { key: 'text_column', default: 'text' }, { key: 'pair_key_column', default: 'pair_id' }, { key: 'pair_role_column', default: 'pair_role' },
        ],
        expected_columns: [
          { key: 'text', label: 'Text', required: true, configured_by: 'text_column' },
          { key: 'pair_id', label: 'Pair-ID', required: true, configured_by: 'pair_key_column' },
          { key: 'pair_role', label: 'Pair-Role', required: true, configured_by: 'pair_role_column' },
        ],
        output: {
          paired: true,
          paired_data_dependent: false,
          pairing_kind: 'prealigned',
          emitted_features: ['alignment.paired', 'alignment.parallel_kwic'],
          guarantees: ['Pair-Rollen bleiben explizit erhalten.'],
          limitations: ['Alignment-Qualität wird nicht semantisch neu bewertet.'],
        },
        emitted_features: ['alignment.paired', 'alignment.parallel_kwic'],
        reports: [{ key: 'rejects', label: 'Rejects' }],
      },
    },
    normalized_payload: {
      method: 'prealigned_csv',
      input_path: '/imports/aligned.csv',
      options: {
        target_name: 'aligned-demo',
        text_column: 'body',
        pair_key_column: 'group_id',
        pair_role_column: 'pair_role',
        reject_policy: 'collect',
      },
    },
  } as CorpusImportPreflightResponse
}

describe('CorpusImportPreflightEvidence', () => {
  it('renders import method facts without raw preflight payload dumps', () => {
    const wrapper = mount(CorpusImportPreflightEvidence, {
      props: { result: prealignedPreflight() },
    })

    expect(wrapper.text()).toContain('Quelle')
    expect(wrapper.text()).toContain('/imports/aligned.csv')
    expect(wrapper.text()).toContain('2.0 KB')
    expect(wrapper.text()).toContain('Eingabeanforderungen')
    expect(wrapper.text()).toContain('server_file')
    expect(wrapper.text()).toContain('.csv')
    expect(wrapper.text()).toContain('Ziel')
    expect(wrapper.text()).toContain('aligned-demo')
    expect(wrapper.text()).toContain('/corpora/aligned-demo')
    expect(wrapper.text()).toContain('Importmethode')
    expect(wrapper.text()).toContain('Prealigned CSV')
    expect(wrapper.text()).toContain('prealigned')
    expect(wrapper.text()).toContain('Geplante Build-Artefakte')
    expect(wrapper.text()).toContain('Verifizierte Korpusfähigkeiten')
    expect(wrapper.text()).toContain('alignment.parallel_kwic')
    expect(wrapper.text()).toContain('Aufgelöste Spaltenzuordnung')
    expect(wrapper.text()).toContain('Nutzer-Mapping text_column → body')
    expect(wrapper.text()).toContain('Nutzer-Mapping pair_key_column → group_id')
    expect(wrapper.text()).toContain('Nutzer-Mapping pair_role_column → pair_role')
    expect(wrapper.text()).toContain('Pair-Rollen bleiben explizit erhalten.')
    expect(wrapper.text()).toContain('Erwartete Reports')
    expect(wrapper.text()).toContain('Rejects')
    expect(wrapper.text()).not.toContain('Check-Evidenz')
    expect(wrapper.text()).not.toContain('distinct_pairs')
    expect(wrapper.text()).not.toContain('Spalten-/Sample-Evidenz')
    expect(wrapper.text()).not.toContain('Pairing-Sample-Evidenz')
    expect(wrapper.text()).not.toContain('Normalisierte Importanfrage')
    expect(wrapper.text()).not.toContain('reject_policy')
  })

  it('surfaces data-dependent pairing instead of reducing it to unpaired', () => {
    const result = prealignedPreflight()
    result.method = 'parquet'
    result.evidence.method_contract!.method = 'parquet'
    result.evidence.method_contract!.label = 'Parquet'
    result.evidence.method_contract!.output = {
      paired: false,
      paired_data_dependent: true,
      pairing_kind: 'row_metadata_if_present',
      emitted_features: ['kwic_ready'],
      guarantees: [],
      limitations: ['Paarmetadaten entstehen nur bei passenden Zeilenmetadaten.'],
    }

    const wrapper = mount(CorpusImportPreflightEvidence, {
      props: { result },
    })

    expect(wrapper.text()).toContain('datenabhängige Paarmetadaten')
    expect(wrapper.text()).toContain('row_metadata_if_present')
    expect(wrapper.text()).not.toContain('Outputnicht gepaart')
  })

  it('renders backend defaults for prealigned columns when no user mapping was sent', () => {
    const result = prealignedPreflight()
    Object.assign(result.evidence, {
      path: '/imports/missing.csv',
      exists: false,
      is_file: false,
      columns: [],
    })
    result.normalized_payload = {
      method: 'prealigned_csv',
      input_path: '/imports/missing.csv',
      options: { target_name: 'aligned-demo', reject_policy: 'collect' },
    }

    const wrapper = mount(CorpusImportPreflightEvidence, {
      props: { result },
    })

    for (const item of ['Default text_column → text', 'Default pair_key_column → pair_id', 'Default pair_role_column → pair_role']) {
      expect(wrapper.text()).toContain(item)
    }
    expect(wrapper.text()).not.toContain('nicht gesetzt')
  })

  it('renders backend column-mapping suggestions for csv/jsonl sources', () => {
    const result = prealignedPreflight()
    result.method = 'csv'
    Object.assign(result.evidence, {
      columns: ['body', 'content', 'id'],
      column_mapping_suggestions: [
        {
          missing_column: 'text',
          candidate_columns: ['body', 'content'],
          safe_mapping: 'text_column=body setzen, wenn diese Spalte den Dokumenttext enthält.',
          suggested_options: { text_column: 'body' },
          fallback_behavior: 'Der Import indexiert genau die konfigurierte Textspalte.',
        },
      ],
    })

    const wrapper = mount(CorpusImportPreflightEvidence, { props: { result } })

    expect(wrapper.text()).toContain('Mapping-Vorschläge')
    expect(wrapper.text()).toContain('nicht in der Quelle gefunden')
    expect(wrapper.text()).toContain('Kandidaten: body, content')
    expect(wrapper.text()).toContain('text_column=body setzen, wenn diese Spalte den Dokumenttext enthält.')
    expect(wrapper.text()).toContain('Der Import indexiert genau die konfigurierte Textspalte.')
  })

  it('summarises the bounded plaintext structure sample from the preflight evidence', () => {
    const result = prealignedPreflight()
    result.method = 'plaintext'
    Object.assign(result.evidence, {
      columns: [],
      is_file: false,
      is_dir: true,
      plaintext: {
        pattern: '*.txt',
        file_count: 12,
        total_size_bytes: 2048,
        file_scan_limit: 5000,
        file_scan_truncated: false,
        registers_preview: ['zeitung', 'chat'],
        encoding_sample: [{ file: 'a.txt', encoding: 'utf-8', sample_bytes: 64 }],
        encoding_utf8_files: 3,
        encoding_fallback_files: 1,
        encoding_sample_limit: 4,
      },
    })

    const wrapper = mount(CorpusImportPreflightEvidence, { props: { result } })

    expect(wrapper.text()).toContain('Plaintext-Struktur (begrenzter Scan)')
    expect(wrapper.text()).toContain('Dateimuster')
    expect(wrapper.text()).toContain('*.txt')
    expect(wrapper.text()).toContain('Dateien')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).toContain('Gesamtgröße')
    expect(wrapper.text()).toContain('2.0 KB')
    expect(wrapper.text()).toContain('Register-Vorschau')
    expect(wrapper.text()).toContain('zeitung, chat')
    expect(wrapper.text()).toContain('3 UTF-8, 1 mit Fallback-Dekodierung')
  })

  it('marks a truncated plaintext scan honestly as a lower bound', () => {
    const result = prealignedPreflight()
    result.method = 'plaintext'
    Object.assign(result.evidence, {
      columns: [],
      plaintext: {
        pattern: '*.txt',
        file_count: 5000,
        total_size_bytes: 1024,
        file_scan_truncated: true,
      },
    })

    const wrapper = mount(CorpusImportPreflightEvidence, { props: { result } })

    expect(wrapper.text()).toContain('mindestens 5000 (Scan begrenzt)')
  })

  it('shows the honest offline marker for hf descriptor-only preflights', () => {
    const result = prealignedPreflight()
    result.method = 'hf'
    Object.assign(result.evidence, {
      path: 'wikimedia/wikipedia',
      columns: [],
      exists: undefined,
      is_file: undefined,
      is_dir: undefined,
      size_bytes: undefined,
      suffix: '',
      hf: {
        dataset: 'wikimedia/wikipedia',
        network_access: false,
        descriptor_only: true,
      },
    })

    const wrapper = mount(CorpusImportPreflightEvidence, { props: { result } })

    expect(wrapper.text()).toContain('Dataset-ID')
    expect(wrapper.text()).toContain('wikimedia/wikipedia')
    expect(wrapper.text()).toContain('Offline-Preflight')
    expect(wrapper.text()).toContain('nur Descriptor validiert, ohne Netzzugriff')
  })
})
