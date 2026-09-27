import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import MobileNav from '@/components/layout/MobileNav.vue'

/**
 * DESIGN-UX-GLOBAL-02: at a 375px viewport the page scrolled ~280px sideways
 * into blank space. Two structural guarantees keep that from happening:
 *  1. the document clamps overflow-x (html,body { overflow-x:hidden }), and
 *  2. the FIXED mobile nav is anchored to both horizontal insets and scrolls its
 *     tab strip INTERNALLY (overflow-x-auto) instead of widening the page.
 *
 * jsdom has no layout engine, so we assert these structural facts directly: the
 * global clamp rule in the shipped stylesheet, and the nav's scoped styles.
 */

function readStyleBlock(componentPath: string): string {
  const src = readFileSync(componentPath, 'utf8')
  const match = src.match(/<style[^>]*>([\s\S]*?)<\/style>/)
  return (match?.[1] ?? '').replace(/\s+/g, ' ')
}

describe('mobile viewport horizontal overflow clamp (DESIGN-UX-GLOBAL-02)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.innerWidth = 375
  })

  it('the global stylesheet clamps overflow-x on html and body', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/style.css'), 'utf8').replace(/\s+/g, ' ')
    // A single rule covering both html and body with overflow-x: hidden.
    expect(css).toMatch(/html,\s*body\s*\{[^}]*overflow-x:\s*hidden/)
  })

  it('the fixed bottom nav is clamped and scrolls its tab strip internally', () => {
    // Render so a regression that removes the nav element also fails here.
    const wrapper = mount(MobileNav, { global: { stubs: { Sparkles: true } } })
    expect(wrapper.find('.mobile-nav').exists()).toBe(true)
    expect(wrapper.find('.nav-scroll').exists()).toBe(true)

    const css = readStyleBlock(resolve(process.cwd(), 'src/components/layout/MobileNav.vue'))
    // Fixed + anchored to both insets → width tracks the viewport (cannot overflow).
    expect(css).toMatch(/\.mobile-nav\s*\{[^}]*fixed[^}]*inset-x-0/)
    // The tab strip absorbs many tabs by scrolling inside the nav, not widening it.
    expect(css).toMatch(/\.nav-scroll\s*\{[^}]*overflow-x-auto/)
  })
})
