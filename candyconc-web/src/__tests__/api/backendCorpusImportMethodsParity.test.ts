import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  CorpusImportMethodsResponseSchema,
} from '@/api/schemas'

const REQUIRED_BASE_IMPORT_METHODS = [
  'parquet',
  'vrt',
  'prealigned_parquet',
  'prealigned_csv',
  'prealigned_jsonl',
  'plaintext',
  'csv',
  'jsonl',
  'hf',
] as const

const UNPAIRED_ADAPTER_METHODS = ['plaintext', 'csv', 'jsonl', 'hf'] as const

function pythonExecutable(repoRoot: string): string {
  const venvPython = resolve(repoRoot, '.venv/bin/python')
  if (existsSync(venvPython)) return venvPython
  return process.env.PYTHON ?? 'python3'
}

function backendImportMethods(): ReturnType<typeof CorpusImportMethodsResponseSchema.parse>['methods'] {
  const repoRoot = resolve(process.cwd(), '..')
  const python = pythonExecutable(repoRoot)
  const sourceRoot = resolve(repoRoot, 'app/src')
  const output = execFileSync(python, [
    '-c',
    [
      'import json',
      'from candyconc.services.backend import corpus_import_jobs',
      'print(json.dumps({"methods": corpus_import_jobs.import_method_descriptors()}, ensure_ascii=False))',
    ].join('; '),
  ], {
    cwd: repoRoot,
    encoding: 'utf8',
    env: {
      ...process.env,
      PYTHONPATH: [sourceRoot, process.env.PYTHONPATH].filter(Boolean).join(':'),
    },
  })
  return CorpusImportMethodsResponseSchema.parse(JSON.parse(output)).methods
}

function byMethod(methods: ReturnType<typeof backendImportMethods>) {
  return new Map(methods.map((method) => [method.method, method]))
}

describe('backend corpus import methods parity', () => {
  it('keeps the frontend schema compatible with every backend-declared import method', () => {
    const methods = backendImportMethods()
    const methodByName = byMethod(methods)

    expect(methods.length).toBeGreaterThanOrEqual(REQUIRED_BASE_IMPORT_METHODS.length)
    expect([...methodByName.keys()]).toEqual(expect.arrayContaining([...REQUIRED_BASE_IMPORT_METHODS]))

    for (const method of methods) {
      const name = method.method
      expect(method, name).toBeDefined()
      expect(method?.schema_version).toBe('corpus-import-method-v1')
      expect(['server_file', 'server_directory', 'hf_dataset']).toContain(method?.input.kind)
      expect(method?.option_specs.length, `${name} option specs`).toBeGreaterThan(0)
      expect(method?.output.emitted_features.length, `${name} emitted features`).toBeGreaterThan(0)
      expect(method?.reports.map((report) => report.key), `${name} reports`).toContain('build_report')
      expect(method?.reports.map((report) => report.key), `${name} reports`).toContain('manifest')
    }
  })

  it('preserves the methodological distinction between generic and pre-aligned imports', () => {
    const methodByName = byMethod(backendImportMethods())
    const parquet = methodByName.get('parquet')
    const vrt = methodByName.get('vrt')
    const prealigned = ['prealigned_parquet', 'prealigned_csv', 'prealigned_jsonl']
      .map((method) => methodByName.get(method))

    expect(parquet?.output).toMatchObject({
      paired: false,
      paired_data_dependent: false,
      pairing_kind: 'none',
    })
    expect(vrt?.output).toMatchObject({
      paired: false,
      pairing_kind: 'none',
    })
    expect(vrt?.reports.map((report) => report.key)).toContain('vrt_import_report')

    for (const method of prealigned) {
      expect(method).toBeDefined()
      expect(method?.ui_workflow).toMatchObject({
        status: 'first_class',
        label: 'First-class Import',
      })
      expect(method?.output).toMatchObject({
        paired: true,
        pairing_kind: 'external_pair_keys',
      })
      expect(method?.option_keys).toEqual(expect.arrayContaining([
        'text_column',
        'pair_key_column',
        'pair_role_column',
        'anchor_role',
        'pair_axis',
        'reject_policy',
      ]))
      expect(method?.expected_columns.map((column) => column.key)).toEqual(expect.arrayContaining([
        'text',
        'pair_id',
        'pair_role',
      ]))
      expect(method?.reports.map((report) => report.key)).toContain('reject_report')
    }

    expect(methodByName.get('prealigned_csv')?.option_keys).toContain('delimiter')
  })

  it('exposes the unpaired CSV/JSONL/plaintext/HF adapters as honest first-class import methods', () => {
    const methodByName = byMethod(backendImportMethods())

    for (const methodName of UNPAIRED_ADAPTER_METHODS) {
      const method = methodByName.get(methodName)
      expect(method, methodName).toBeDefined()
      expect(method?.ui_workflow?.status, methodName).toBe('first_class')
      expect(method?.output).toMatchObject({
        paired: false,
        pairing_kind: 'none',
      })
      // The word-FAISS post-step is declared everywhere with its cost documented.
      expect(method?.option_keys, methodName).toContain('build_word_faiss')
    }

    const plaintext = methodByName.get('plaintext')
    expect(plaintext?.input.accepts_directories).toBe(true)

    const hf = methodByName.get('hf')
    expect(hf?.input.kind).toBe('hf_dataset')
    // Security boundary stays descriptor-documented, never an opt-in option.
    expect(hf?.option_keys).not.toContain('trust_remote_code')
    expect(hf?.output.limitations.join(' ')).toContain('trust_remote_code')
  })

})
