/**
 * The one place that decides and applies the interface language.
 *
 * Source of truth is `preferences.language` in the settings store. Without a
 * stored preference the store starts from `detectBrowserLocale()`. The store
 * calls `applyLocale` on every change, which sets the vue-i18n locale and the
 * `lang` attribute of the document. Number and date formatting, the
 * `Accept-Language` header and the copilot context all read `currentLocale()`.
 */
import { FALLBACK_LOCALE, i18n, SUPPORTED_LOCALES, type AppLocale } from './index'

/** Intl tag per interface language. English follows US conventions. */
const INTL_TAGS: Record<AppLocale, string> = {
  de: 'de-DE',
  en: 'en-US',
}

export function isAppLocale(value: unknown): value is AppLocale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

/** Map a stored or browser language tag to a supported locale, or null. */
export function normalizeLocale(value: unknown): AppLocale | null {
  if (typeof value !== 'string') return null
  const lower = value.trim().toLowerCase()
  if (lower.startsWith('en')) return 'en'
  if (lower.startsWith('de')) return 'de'
  return null
}

/**
 * `navigator.language` starting with `de` gives German, any other language
 * English, so readers who do not read German get the English interface. A
 * stored preference takes precedence (settings store).
 */
export function detectBrowserLocale(): AppLocale {
  if (typeof navigator === 'undefined' || !navigator.language) return 'en'
  return navigator.language.trim().toLowerCase().startsWith('de') ? 'de' : 'en'
}

export function currentLocale(): AppLocale {
  const value = i18n.global.locale.value
  return isAppLocale(value) ? value : FALLBACK_LOCALE
}

export function intlLocale(locale: AppLocale = currentLocale()): string {
  return INTL_TAGS[locale]
}

export function applyLocale(locale: AppLocale): void {
  i18n.global.locale.value = locale
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.lang = locale
  }
}

/** Value for the `Accept-Language` request header. */
export function acceptLanguageHeader(locale: AppLocale = currentLocale()): string {
  return locale === 'en' ? 'en, de;q=0.5' : 'de, en;q=0.5'
}
