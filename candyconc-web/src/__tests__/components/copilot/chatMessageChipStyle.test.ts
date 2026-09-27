/**
 * Evidence chips carry the chip style.
 *
 * Englischprobe 2026-09-27: the chips rendered with no background, no border
 * and `cursor: default`. The rules for `.ev-chip` stood in `<style scoped>`,
 * the compiler bound them to the scope attribute (`.ev-chip[data-v-...]`), and
 * the buttons come from `v-html` (`belegChipsEinsetzen`) without that
 * attribute. The test compiles the style block of ChatMessage.vue the way the
 * build does and checks every `.ev-chip` rule against the rendered button.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compileStyle, parse } from '@vue/compiler-sfc'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatMessage from '@/components/copilot/ChatMessage.vue'

const FILE = resolve(dirname(fileURLToPath(import.meta.url)), '../../../components/copilot/ChatMessage.vue')

/** Selectors of the compiled rules that style the chip itself (pseudo-classes removed). */
function chipSelectors(scopeId: string): string[] {
  const { descriptor } = parse(readFileSync(FILE, 'utf8'), { filename: FILE })
  const block = descriptor.styles.find((style) => style.scoped)
  expect(block).toBeTruthy()
  const compiled = compileStyle({
    source: block!.content,
    filename: FILE,
    id: scopeId,
    scoped: true,
  })
  const selectors: string[] = []
  const css = compiled.code.replace(/\/\*[\s\S]*?\*\//g, '')
  for (const match of css.matchAll(/([^{}]+)\{/g)) {
    const selector = match[1]!.trim()
    if (!selector.includes('ev-chip') || selector.startsWith('@')) continue
    for (const part of selector.split(',')) {
      selectors.push(part.trim().replace(/:(hover|focus-visible)\b/g, ''))
    }
  }
  return selectors
}

describe('evidence chip style', () => {
  it('every .ev-chip rule reaches the chip that v-html renders', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'm1',
          role: 'assistant',
          content: 'Wert 436 [[beleg:E_collocate_stats_1]].',
          timestamp: 1,
          evidence: [{ id: 'E_collocate_stats_1', tool: 'collocate_stats', query: '{"term": "economy"}', status: 'success' }],
        },
      },
      global: { stubs: { ToolCallResult: true } },
    })
    const button = wrapper.find('button.ev-chip').element as HTMLElement
    expect(button).toBeTruthy()
    const scopeId = (ChatMessage as { __scopeId?: string }).__scopeId
    expect(scopeId).toMatch(/^data-v-/)
    // The rendered component carries the scope attribute, the chip does not.
    expect(wrapper.find('.message-text').attributes()).toHaveProperty(scopeId!)
    const selectors = chipSelectors(scopeId!)
    expect(selectors.length).toBeGreaterThanOrEqual(3)
    for (const selector of selectors) {
      expect(button.matches(selector), selector).toBe(true)
    }
  })
})
