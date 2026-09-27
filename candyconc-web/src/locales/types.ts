/**
 * Shape helpers for the message catalogs.
 *
 * German (`de`) is the source catalog. Every English namespace declares
 * `satisfies LocaleNamespace<typeof de>`, so a missing or extra key is a type
 * error. A runtime test (`locales.test.ts`) checks the same equality.
 */
export type LocaleNamespace<T> = {
  [K in keyof T]: T[K] extends string ? string : LocaleNamespace<T[K]>
}
