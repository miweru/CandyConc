import { afterEach, describe, expect, it } from 'vitest'

import { t } from '@/i18n'
import { applyLocale } from '@/i18n/locale'

// Loaded lines (for example a random sample) are not written to a file on
// purpose: file exports come from the server, which runs the search again.
// The disabled export must say so and name the two ways that work.
describe('reason for the disabled export of loaded lines', () => {
  afterEach(() => {
    applyLocale('de')
  })

  it('names the reason and the alternatives in English', () => {
    applyLocale('en')
    const reason = t('export.store.localNotReleased')
    expect(reason).toContain('runs the search again')
    expect(reason).toContain(t('export.dialog.serverConcordance'))
    expect(reason).toContain(t('kwic.table.copyRows'))
  })

  it('names the reason and the alternatives in German', () => {
    applyLocale('de')
    const reason = t('export.store.localNotReleased')
    expect(reason).toContain('lokaler Auszug')
    expect(reason).toContain('erneut ausführt')
    expect(reason).toContain(t('export.dialog.serverConcordance'))
    expect(reason).toContain(t('kwic.table.copyRows'))
  })
})
