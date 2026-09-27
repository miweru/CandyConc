import type { CorpusImportOptionChoice, CorpusImportOptionSpec } from '@/api/client'
import { t } from '@/i18n'

export type CorpusImportParsedOptions =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; error: string }

export type CorpusImportChoicePrimitive = string | number | boolean

export const RESERVED_IMPORT_PAYLOAD_KEYS = new Set([
  'method',
  'importMethod',
  'input',
  'path',
  'input_path',
  'input-path',
  'inputPath',
  'serverPath',
  'sourcePath',
  'target',
  'target_name',
  'target-name',
  'targetName',
  'target_path',
  'target-path',
  'targetPath',
  'staging_path',
  'staging-path',
  'stagingPath',
  'corpus',
  'corpusName',
  'activate_on_success',
  'activate-on-success',
  'activateOnSuccess',
  'activate',
])

export function parseAdvancedImportOptions(text: string): CorpusImportParsedOptions {
  const trimmed = text.trim()
  if (!trimmed) return { ok: true, value: {} }
  try {
    const value = JSON.parse(trimmed)
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return { ok: false, error: t('corpus.importContract.advancedNotObject') }
    }
    return { ok: true, value: value as Record<string, unknown> }
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error
        ? t('corpus.importContract.invalidJsonMessage', { message: err.message })
        : t('corpus.importContract.invalidJson'),
    }
  }
}

export function choiceValue(choice: CorpusImportOptionChoice): CorpusImportChoicePrimitive {
  if (typeof choice === 'object' && choice !== null) return choice.value
  return choice
}

export function choiceKey(choice: CorpusImportOptionChoice): string {
  return String(choiceValue(choice))
}

export function choiceLabel(choice: CorpusImportOptionChoice): string {
  if (typeof choice === 'object' && choice !== null) return choice.label ?? String(choice.value)
  return String(choice)
}

export function choiceDescription(choice: CorpusImportOptionChoice): string | null {
  if (typeof choice === 'object' && choice !== null) return choice.description ?? null
  return null
}

export function optionLabel(spec: CorpusImportOptionSpec): string {
  return spec.label || spec.key
}

export function optionTypeLabel(spec: CorpusImportOptionSpec): string {
  const labelKeys: Record<string, string> = {
    string: 'corpus.importContract.typeText',
    path: 'corpus.importContract.typePath',
    integer: 'corpus.importContract.typeInteger',
    number: 'corpus.importContract.typeNumber',
    boolean: 'corpus.importContract.typeBoolean',
    string_list: 'corpus.importContract.typeList',
    choice: 'corpus.importContract.typeChoice',
  }
  const key = labelKeys[spec.type]
  return key ? t(key) : spec.type
}

export function defaultUiValue(spec: CorpusImportOptionSpec): unknown {
  const value = spec.default
  if (spec.type === 'boolean') return Boolean(value)
  if (spec.type === 'choice') return value ?? (spec.choices.length ? choiceValue(spec.choices[0]!) : '')
  if (Array.isArray(value)) return value.join(', ')
  if (value === undefined || value === null) return ''
  return String(value)
}

export function optionDefaultLabel(spec: CorpusImportOptionSpec): string | null {
  if (spec.default === undefined || spec.default === null || spec.default === '') return null
  return Array.isArray(spec.default) ? spec.default.join(', ') : String(spec.default)
}

export function listValue(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean)
  return String(value ?? '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

function valuesEqual(left: unknown, right: unknown): boolean {
  if (Array.isArray(left) || Array.isArray(right)) {
    return JSON.stringify(Array.isArray(left) ? left : listValue(left)) === JSON.stringify(Array.isArray(right) ? right : listValue(right))
  }
  return left === right || String(left ?? '') === String(right ?? '')
}

function isEmptyOptionValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'boolean') return false
  return value === undefined || value === null || String(value).trim() === ''
}

export function coerceOptionValue(
  spec: CorpusImportOptionSpec,
  raw: unknown,
): { present: boolean; value?: unknown; error?: string } {
  if (spec.type === 'boolean') {
    const value = raw === true || raw === 'true'
    const defaultValue = typeof spec.default === 'boolean' ? spec.default : false
    return value === defaultValue ? { present: false } : { present: true, value }
  }
  if (isEmptyOptionValue(raw)) {
    return spec.required
      ? { present: false, error: t('corpus.importContract.optionMissing', { label: optionLabel(spec) }) }
      : { present: false }
  }
  if (spec.type === 'integer' || spec.type === 'number') {
    const value = Number(raw)
    if (!Number.isFinite(value) || (spec.type === 'integer' && !Number.isInteger(value))) {
      return {
        present: false,
        error: spec.type === 'integer'
          ? t('corpus.importContract.optionInteger', { label: optionLabel(spec) })
          : t('corpus.importContract.optionNumber', { label: optionLabel(spec) }),
      }
    }
    return valuesEqual(value, spec.default) ? { present: false } : { present: true, value }
  }
  if (spec.type === 'string_list') {
    const value = listValue(raw)
    if (spec.required && value.length === 0) {
      return { present: false, error: t('corpus.importContract.optionListEmpty', { label: optionLabel(spec) }) }
    }
    return valuesEqual(value, spec.default) ? { present: false } : { present: true, value }
  }
  if (spec.type === 'choice' && spec.choices.length) {
    const allowed = spec.choices.map(choiceValue)
    const matched = allowed.find((item) => valuesEqual(item, raw))
    if (matched === undefined) {
      return { present: false, error: t('corpus.importContract.optionChoice', { label: optionLabel(spec) }) }
    }
    return valuesEqual(matched, spec.default) ? { present: false } : { present: true, value: matched }
  }
  const value = String(raw)
  return valuesEqual(value, spec.default) ? { present: false } : { present: true, value }
}

export function typedOptionsFromSpecs(
  specs: readonly CorpusImportOptionSpec[],
  values: Record<string, unknown>,
): CorpusImportParsedOptions {
  const result: Record<string, unknown> = {}
  for (const spec of specs) {
    const coerced = coerceOptionValue(spec, values[spec.key])
    if (coerced.error) return { ok: false, error: coerced.error }
    if (coerced.present) result[spec.key] = coerced.value
  }
  return { ok: true, value: result }
}

export function advancedImportWarnings(
  declaredContract: readonly (string | CorpusImportOptionSpec)[],
  typedOptions: CorpusImportParsedOptions,
  advancedOptions: CorpusImportParsedOptions,
): string[] {
  if (!typedOptions.ok || !advancedOptions.ok) return []
  const acceptedKeys = new Map<string, string>()
  for (const item of declaredContract) {
    const key = typeof item === 'string' ? item : item.key
    if (!key) continue
    acceptedKeys.set(key, key)
    acceptedKeys.set(key.replace(/_/g, '-'), key)
    if (typeof item !== 'string') {
      for (const alias of item.aliases ?? []) {
        if (alias) acceptedKeys.set(alias, key)
      }
    }
  }
  const typedKeys = new Set(Object.keys(typedOptions.value))
  const advancedKeys = Object.keys(advancedOptions.value).sort()
  const collisions = advancedKeys.filter((key) => {
    const canonical = acceptedKeys.get(key) ?? key
    return typedKeys.has(canonical)
  })
  const reserved = advancedKeys.filter((key) => RESERVED_IMPORT_PAYLOAD_KEYS.has(key))
  const unknown = advancedKeys.filter((key) => !acceptedKeys.has(key) && !RESERVED_IMPORT_PAYLOAD_KEYS.has(key))
  const warnings: string[] = []
  if (collisions.length) {
    warnings.push(t('corpus.importContract.warnCollisions', { keys: collisions.join(', ') }))
  }
  if (reserved.length) {
    warnings.push(t('corpus.importContract.warnReserved', { keys: reserved.join(', ') }))
  }
  if (unknown.length) {
    warnings.push(t('corpus.importContract.warnUnknown', { keys: unknown.join(', ') }))
  }
  return warnings
}
