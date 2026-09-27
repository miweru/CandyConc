import type { CorpusImportOptionChoice, CorpusSummary } from '@/api/client'
import { t } from '@/i18n'
import { intlLocale } from '@/i18n/locale'

/**
 * Name of a corpus language (ISO 639 code) in the interface language.
 * An index without a recorded language shows "unknown", never a guess.
 */
export function corpusLanguageName(code: string | null | undefined): string {
  const value = String(code ?? '').trim()
  if (!value) return t('corpus.language.unknown')
  let name: string | undefined
  try {
    name = new Intl.DisplayNames([intlLocale()], { type: 'language' }).of(value)
  } catch {
    name = undefined
  }
  return name && name !== value ? t('corpus.language.named', { name, code: value }) : value
}

export function corpusLanguageLabel(summary: Pick<CorpusSummary, 'language'> | null | undefined): string {
  return t('corpus.language.label', { language: corpusLanguageName(summary?.language) })
}

/** The pipeline a language choice of the import form suggests. */
export function suggestedPipeline(
  choices: readonly CorpusImportOptionChoice[],
  language: unknown,
): string | null {
  const code = String(language ?? '').trim()
  if (!code) return null
  for (const choice of choices) {
    if (typeof choice === 'object' && choice !== null && String(choice.value) === code) {
      const pipeline = (choice as { pipeline?: unknown }).pipeline
      return typeof pipeline === 'string' && pipeline ? pipeline : null
    }
  }
  return null
}
