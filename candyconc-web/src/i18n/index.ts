/**
 * vue-i18n instance (Composition API mode).
 *
 * The active locale is set only by `applyLocale` in `./locale`, which the
 * settings store calls whenever `preferences.language` changes. German is the
 * fallback: a key missing in English renders the German text.
 *
 * Components use `const { t } = useI18n()`. Modules outside components
 * (stores, actions, lib) import `t` from here. Both read the same global
 * composer, so a locale switch re-renders every computed that called `t`.
 */
import { createI18n } from 'vue-i18n'
import de from '@/locales/de'
import en from '@/locales/en'

export type AppLocale = 'de' | 'en'
export const SUPPORTED_LOCALES: readonly AppLocale[] = ['de', 'en'] as const
export const FALLBACK_LOCALE: AppLocale = 'de'

export type MessageSchema = typeof de

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: FALLBACK_LOCALE,
  fallbackLocale: FALLBACK_LOCALE,
  messages: { de, en },
  // English falls back to German key by key while areas are still being
  // translated. The catalog test keeps both key sets equal, so a fallback
  // warning would only repeat what that test already reports.
  fallbackWarn: false,
  missingWarn: import.meta.env.DEV,
})

/** Translate outside of components. Reactive inside computed and templates. */
export const t = i18n.global.t

/** True when the key exists in the active or fallback catalog. */
export const te = (key: string): boolean => i18n.global.te(key) || i18n.global.te(key, FALLBACK_LOCALE)
