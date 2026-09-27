/**
 * Message catalogs: German and English have the same keys per namespace,
 * every message parses, English uses no placeholder German does not provide,
 * and every literal key the source passes to t() exists.
 */
import { createParser } from '@intlify/message-compiler'
import { describe, expect, it } from 'vitest'

import de from '@/locales/de'
import en from '@/locales/en'
import { i18n } from '@/i18n'
import { analysisTabSurfaces, productCapabilitySurfaces } from '@/lib/productCapabilities'

type Tree = { [key: string]: string | Tree }

function leaves(tree: Tree, prefix = ''): Map<string, string> {
  const out = new Map<string, string>()
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out.set(path, value)
    else for (const [k, v] of leaves(value, path)) out.set(k, v)
  }
  return out
}

function placeholders(message: string): Set<string> {
  return new Set([...message.matchAll(/\{\s*([A-Za-z_]\w*)\s*\}/g)].map((m) => m[1]!))
}

const deTree = de as unknown as Tree
const enTree = en as unknown as Tree

describe('message catalogs', () => {
  it('have the same namespaces', () => {
    expect(Object.keys(enTree).sort()).toEqual(Object.keys(deTree).sort())
  })

  for (const namespace of Object.keys(deTree)) {
    it(`namespace ${namespace}: same keys in de and en`, () => {
      const deKeys = [...leaves(deTree[namespace] as Tree).keys()].sort()
      const enKeys = [...leaves(enTree[namespace] as Tree).keys()].sort()
      expect(enKeys).toEqual(deKeys)
    })
  }

  it('every message parses without compile errors', () => {
    const problems: string[] = []
    for (const [locale, tree] of [['de', deTree], ['en', enTree]] as const) {
      for (const [key, message] of leaves(tree)) {
        const parser = createParser({
          onError: (error) => problems.push(`${locale}:${key}: ${error.message}`),
        })
        parser.parse(message)
      }
    }
    expect(problems).toEqual([])
  })

  it('English uses only placeholders that the German message provides', () => {
    const deLeaves = leaves(deTree)
    const problems: string[] = []
    for (const [key, message] of leaves(enTree)) {
      const provided = placeholders(deLeaves.get(key) ?? '')
      provided.add('n').add('count')
      for (const name of placeholders(message)) {
        if (!provided.has(name)) problems.push(`${key}: {${name}}`)
      }
    }
    expect(problems).toEqual([])
  })

  it('every literal key used in the source exists in the German catalog', () => {
    const sources = import.meta.glob(['/src/**/*.ts', '/src/**/*.vue', '!/src/__tests__/**', '!/src/**/*.test.ts'], {
      query: '?raw',
      import: 'default',
      eager: true,
    }) as Record<string, string>
    const known = new Set(leaves(deTree).keys())
    const namespaces = new Set(Object.keys(deTree))
    const missing: string[] = []
    const keyPattern = /(?:\b(?:t|te|\$t)\(\s*|[A-Za-z]Key:\s*|keypath=)['"]([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_]+)+)['"]/g
    for (const [file, code] of Object.entries(sources)) {
      for (const match of code.matchAll(keyPattern)) {
        const key = match[1]!
        if (!namespaces.has(key.split('.')[0]!)) continue
        if (!known.has(key)) missing.push(`${file}: ${key}`)
      }
    }
    expect(missing).toEqual([])
  })

  it('surface labels given as keys resolve in both languages', () => {
    const unresolved: string[] = []
    for (const locale of ['de', 'en'] as const) {
      i18n.global.locale.value = locale
      for (const surface of [...analysisTabSurfaces, ...productCapabilitySurfaces]) {
        for (const text of [surface.label, surface.commandLabel]) {
          if (text !== undefined && /^[a-z]+\.[A-Za-z]+\.[A-Za-z]+$/.test(text)) unresolved.push(`${locale}:${text}`)
        }
      }
    }
    i18n.global.locale.value = 'de'
    expect(unresolved).toEqual([])
  })
})
