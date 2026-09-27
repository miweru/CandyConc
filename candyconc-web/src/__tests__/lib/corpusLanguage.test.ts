import { afterEach, describe, expect, it } from 'vitest'

import { applyLocale } from '@/i18n/locale'
import { corpusLanguageLabel, corpusLanguageName, suggestedPipeline } from '@/lib/corpusLanguage'

describe('corpus language', () => {
  afterEach(() => applyLocale('de'))

  it('names the language in the interface language', () => {
    expect(corpusLanguageName('en')).toBe('Englisch (en)')
    applyLocale('en')
    expect(corpusLanguageName('de')).toBe('German (de)')
    expect(corpusLanguageLabel({ language: 'en' })).toBe('Language: English (en)')
  })

  it('shows unknown for an index without a recorded language instead of guessing', () => {
    expect(corpusLanguageName(null)).toBe('unbekannt')
    expect(corpusLanguageLabel({ language: null })).toBe('Sprache: unbekannt')
    applyLocale('en')
    expect(corpusLanguageLabel({})).toBe('Language: unknown')
  })

  it('reads the suggested pipeline from the language choice', () => {
    const choices = [
      { value: '', label: '' },
      { value: 'en', label: 'en', pipeline: 'en_core_web_md' },
    ]
    expect(suggestedPipeline(choices, 'en')).toBe('en_core_web_md')
    expect(suggestedPipeline(choices, '')).toBeNull()
    expect(suggestedPipeline(choices, 'fr')).toBeNull()
  })
})
