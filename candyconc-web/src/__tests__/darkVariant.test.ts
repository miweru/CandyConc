import { describe, it, expect } from 'vitest'
import { compile } from 'tailwindcss'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const here = dirname(fileURLToPath(import.meta.url))
const styleCss = resolve(here, '../style.css')
const twDir = dirname(require.resolve('tailwindcss/package.json'))

async function buildUtilities(css: string, candidates: string[]): Promise<string> {
  const compiled = await compile(css, {
    base: process.cwd(),
    loadStylesheet: async (id: string, base: string) => {
      const file = id === 'tailwindcss' ? resolve(twDir, 'index.css') : resolve(base, id)
      return { base: dirname(file), content: readFileSync(file, 'utf8'), path: file }
    },
  })
  return compiled.build(candidates)
}

/**
 * DESIGN-UX-GLOBAL-1: the in-app dark-mode toggle adds `.dark` to <html>. In
 * Tailwind v4 the `dark:` utilities only follow that class when `@custom-variant
 * dark` is declared; otherwise they react only to the OS `prefers-color-scheme`
 * and the toggle is dead. This compiles the real style.css and asserts the
 * project's `dark:` utilities resolve to a class-based selector.
 */
describe('dark mode @custom-variant (DESIGN-UX-GLOBAL-1)', () => {
  it('makes dark: utilities follow the .dark class, not prefers-color-scheme', async () => {
    const css = readFileSync(styleCss, 'utf8')
    const out = await buildUtilities(css, ['dark:bg-neutral-950', 'dark:text-neutral-100'])

    // Class-based dark selector is emitted.
    expect(out).toContain(':where(.dark')
    // The toggle path is wired, not the OS media query.
    expect(out).not.toContain('prefers-color-scheme:dark')
  })

  it('red baseline: without the variant, dark: does NOT produce a .dark class selector', async () => {
    // Same imports but WITHOUT the @custom-variant line — proves the directive is
    // load-bearing (this is what the dead toggle looked like before the fix).
    const cssWithoutVariant = '@import "tailwindcss";'
    const out = await buildUtilities(cssWithoutVariant, ['dark:bg-neutral-950'])
    expect(out).not.toContain(':where(.dark')
    // It falls back to the OS media query instead.
    expect(out.toLowerCase()).toContain('prefers-color-scheme')
  })
})
