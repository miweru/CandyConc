/**
 * One language source: the settings preference `language`, or the browser
 * language when nothing is stored. It sets the vue-i18n locale, the document
 * `lang`, number formats, the Accept-Language header and the copilot context.
 */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { i18n } from '@/i18n'
import { formatDate, formatDecimal, formatNumber, formatPercent } from '@/i18n/format'
import { acceptLanguageHeader, applyLocale, currentLocale } from '@/i18n/locale'
import { withAuthHeaders } from '@/api/auth'
import { useSettingsStore } from '@/stores/settings'

const apiMocks = vi.hoisted(() => ({ updatePrefs: vi.fn(async () => ({ ok: true })) }))
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, updatePrefs: apiMocks.updatePrefs }
})

function setBrowserLanguage(value: string) {
  Object.defineProperty(window.navigator, 'language', { value, configurable: true })
}

describe('interface language source', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
    ;(window.localStorage.setItem as Mock).mockClear()
    apiMocks.updatePrefs.mockClear()
  })

  afterEach(() => {
    setBrowserLanguage('de-DE')
  })

  it('follows an English browser when no preference is stored', () => {
    setBrowserLanguage('en-GB')
    const settings = useSettingsStore()
    expect(settings.preferences.language).toBe('en')
    expect(currentLocale()).toBe('en')
    expect(i18n.global.locale.value).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })

  it('follows a German browser in any region', () => {
    for (const tag of ['de-DE', 'de-AT', 'de-CH', 'de']) {
      setActivePinia(createPinia())
      setBrowserLanguage(tag)
      const settings = useSettingsStore()
      expect(settings.preferences.language).toBe('de')
      expect(currentLocale()).toBe('de')
      expect(document.documentElement.lang).toBe('de')
    }
  })

  it('uses English for any browser language other than German', () => {
    for (const tag of ['fr-FR', 'es', 'ja-JP', 'nl-NL', 'pt-BR']) {
      setActivePinia(createPinia())
      applyLocale('de')
      setBrowserLanguage(tag)
      const settings = useSettingsStore()
      expect(settings.preferences.language).toBe('en')
      expect(currentLocale()).toBe('en')
      expect(document.documentElement.lang).toBe('en')
    }
  })

  it('prefers a stored German preference over a French browser', () => {
    setBrowserLanguage('fr-FR')
    ;(window.localStorage.getItem as Mock).mockImplementation((key: string) =>
      key === 'candyconc_preferences' ? JSON.stringify({ language: 'de' }) : null
    )
    const settings = useSettingsStore()
    settings.init({ loadPreferences: false, loadEmbeddings: false, loadSystemInfo: false })
    expect(settings.preferences.language).toBe('de')
    expect(currentLocale()).toBe('de')
  })

  it('prefers the stored preference over the browser language', () => {
    setBrowserLanguage('en-US')
    ;(window.localStorage.getItem as Mock).mockImplementation((key: string) =>
      key === 'candyconc_preferences' ? JSON.stringify({ language: 'de' }) : null
    )
    const settings = useSettingsStore()
    settings.init({ loadPreferences: false, loadEmbeddings: false, loadSystemInfo: false })
    expect(settings.preferences.language).toBe('de')
    expect(currentLocale()).toBe('de')
    expect(document.documentElement.lang).toBe('de')
  })

  it('setLanguage switches locale and lang at once and stores the choice', async () => {
    const settings = useSettingsStore()
    expect(currentLocale()).toBe('de')
    const pending = settings.setLanguage('en')
    expect(currentLocale()).toBe('en')
    expect(document.documentElement.lang).toBe('en')
    await pending
    const cached = (window.localStorage.setItem as Mock).mock.calls.find(([key]) => key === 'candyconc_preferences')
    expect(JSON.parse(cached![1] as string).language).toBe('en')
  })
})

describe('locale-aware formats', () => {
  it('switch number and date conventions with the active locale', () => {
    applyLocale('de')
    expect(formatNumber(1234567)).toBe('1.234.567')
    expect(formatDecimal(6585.456, 2)).toBe('6.585,46')
    expect(formatPercent(0.425)).toBe('42,5\u00a0%')
    expect(formatDecimal(Number.NaN)).toBe('—')
    expect(formatDate(new Date(2026, 8, 26))).toBe('26.9.2026')

    applyLocale('en')
    expect(formatNumber(1234567)).toBe('1,234,567')
    expect(formatDecimal(6585.456, 2)).toBe('6,585.46')
    expect(formatPercent(0.425)).toBe('42.5%')
    expect(formatDate(new Date(2026, 8, 26))).toBe('9/26/2026')
  })
})

describe('Accept-Language', () => {
  it('names the active locale first', () => {
    applyLocale('en')
    expect(acceptLanguageHeader()).toBe('en, de;q=0.5')
    expect(withAuthHeaders().get('Accept-Language')).toBe('en, de;q=0.5')
    applyLocale('de')
    expect(withAuthHeaders().get('Accept-Language')).toBe('de, en;q=0.5')
  })

  it('is sent by the ky API client', async () => {
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify({ fields: {} }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchSpy)
    try {
      applyLocale('en')
      const { getMetaSchema } = await import('@/api/client')
      await getMetaSchema().catch(() => undefined)
      const request = (fetchSpy.mock.calls as unknown[][])[0]![0] as Request
      expect(request.headers.get('Accept-Language')).toBe('en, de;q=0.5')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
