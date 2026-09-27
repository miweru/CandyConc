import { describe, expect, it } from 'vitest'

import {
  advancedImportWarnings,
  choiceDescription,
  defaultUiValue,
  parseAdvancedImportOptions,
  typedOptionsFromSpecs,
} from '@/lib/corpusImportContract'
import type { CorpusImportOptionSpec } from '@/api/client'

function spec(patch: Partial<CorpusImportOptionSpec> & { key: string }): CorpusImportOptionSpec {
  return {
    key: patch.key,
    label: patch.label,
    type: patch.type ?? 'string',
    required: patch.required ?? false,
    description: patch.description,
    default: patch.default,
    choices: patch.choices ?? [],
    aliases: patch.aliases ?? [],
    placeholder: patch.placeholder,
  }
}

describe('corpus import contract UI adapter', () => {
  it('coerces typed backend option specs without method-specific branches', () => {
    const specs = [
      spec({ key: 'reject_policy', type: 'choice', default: 'collect', choices: ['collect', 'fail_fast'] }),
      spec({ key: 'quality_level', type: 'choice', default: 1, choices: [{ value: 1, label: 'schnell' }, { value: 3, label: 'präzise' }] }),
      spec({ key: 'meta_columns', type: 'string_list', default: [] }),
      spec({ key: 'enable_deps', type: 'boolean', default: false }),
      spec({ key: 'batch_size', type: 'integer', default: 0 }),
    ]

    expect(defaultUiValue(specs[1]!)).toBe(1)
    expect(typedOptionsFromSpecs(specs, {
      reject_policy: 'fail_fast',
      quality_level: '3',
      meta_columns: 'date, genre',
      enable_deps: true,
      batch_size: '64',
    })).toEqual({
      ok: true,
      value: {
        reject_policy: 'fail_fast',
        quality_level: 3,
        meta_columns: ['date', 'genre'],
        enable_deps: true,
        batch_size: 64,
      },
    })
  })

  it('keeps expert overrides auditable against declared contract keys', () => {
    const typed = { ok: true as const, value: { reject_policy: 'fail_fast' } }
    const advanced = parseAdvancedImportOptions('{"reject_policy":"collect","target_path":"/tmp/out","staging_path":"/tmp/stage","target_name":"json-demo","custom":true}')

    expect(advancedImportWarnings(['reject_policy'], typed, advanced)).toEqual([
      'Erweiterte Optionen überschreiben Formularwerte: reject_policy.',
      'Reservierte Felder werden aus dem Formular übernommen, nicht aus JSON-Optionen: staging_path, target_name, target_path.',
      'Nicht in der Methodenliste deklarierte Optionen: custom.',
    ])
  })

  it('preserves backend choice descriptions for first-class UI hints', () => {
    expect(choiceDescription({ value: 'collect', label: 'Sammeln', description: 'Unvollständige Paare als Reject-Report erfassen.' })).toBe('Unvollständige Paare als Reject-Report erfassen.')
    expect(choiceDescription('collect')).toBeNull()
  })

  it('treats dashed option keys and aliases as declared contract keys', () => {
    const typed = { ok: true as const, value: { reject_policy: 'fail_fast', pair_key_column: 'pair_id' } }
    const advanced = parseAdvancedImportOptions('{"reject-policy":"collect","pair-key":"pair","custom":true}')
    const specs = [
      spec({ key: 'reject_policy' }),
      spec({ key: 'pair_key_column', aliases: ['pair-key'] }),
    ]

    expect(advancedImportWarnings(specs, typed, advanced)).toEqual([
      'Erweiterte Optionen überschreiben Formularwerte: pair-key, reject-policy.',
      'Nicht in der Methodenliste deklarierte Optionen: custom.',
    ])
  })

  it('rejects invalid advanced JSON before import start', () => {
    expect(parseAdvancedImportOptions('[]')).toEqual({
      ok: false,
      error: 'Erweiterte Optionen müssen ein JSON-Objekt sein.',
    })
    expect(parseAdvancedImportOptions('{')).toMatchObject({ ok: false })
  })
})
