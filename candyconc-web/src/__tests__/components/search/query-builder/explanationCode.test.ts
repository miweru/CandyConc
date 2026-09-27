/**
 * Explanations in the query studio show query syntax as code.
 *
 * The explanation texts mark syntax with backticks. The editors printed them
 * as plain text, so "`[...]`" appeared with its backticks on screen.
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import CqlNodeEditor from '@/components/search/query-builder/CqlNodeEditor.vue'
import CqlMetaExprEditor from '@/components/search/query-builder/CqlMetaExprEditor.vue'
import KeynessRenderer from '@/components/copilot/tools/KeynessRenderer.vue'
import { createBuilderNode, createMetaCond, createTokenCondition } from '@/lib/queryBuilder/ast'
import { splitCodeSpans } from '@/lib/codeSpans'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('splitCodeSpans', () => {
  it('splits text into plain and code segments', () => {
    expect(splitCodeSpans('A clause is `[...]`, joined with `&`.')).toEqual([
      { code: false, text: 'A clause is ' },
      { code: true, text: '[...]' },
      { code: false, text: ', joined with ' },
      { code: true, text: '&' },
      { code: false, text: '.' },
    ])
  })

  it('keeps an unpaired backtick as text', () => {
    expect(splitCodeSpans('one ` alone')).toEqual([{ code: false, text: 'one ` alone' }])
    expect(splitCodeSpans('')).toEqual([])
  })
})

function mountNode(node: ReturnType<typeof createBuilderNode>) {
  return mount(CqlNodeEditor, {
    props: {
      node,
      metaFieldOptions: ['genre'],
      metaValueChoices: () => [],
      level: 0,
    },
  })
}

describe('explanations in the node editors', () => {
  it('renders the token clause explanation with code elements and no backticks', () => {
    const wrapper = mountNode(createBuilderNode('tok'))
    const help = wrapper.find('.node-help')
    expect(help.exists()).toBe(true)
    expect(help.text()).not.toContain('`')
    const codes = help.findAll('code').map((node) => node.text())
    expect(codes).toContain('[...]')
    expect(codes).toContain('&')
    expect(codes.some((code) => code.startsWith('[word="'))).toBe(true)
  })

  it('renders condition and literal explanations as code', () => {
    const node = createBuilderNode('tok')
    if (node.type === 'tok') node.conditions.splice(0, node.conditions.length, createTokenCondition())
    const wrapper = mountNode(node)
    for (const selector of ['.condition-help', '.literal-help']) {
      const help = wrapper.find(selector)
      expect(help.exists(), selector).toBe(true)
      expect(help.text(), selector).not.toContain('`')
      expect(help.findAll('code').length, selector).toBeGreaterThan(0)
    }
  })

  it('renders the where() and metadata explanations as code', () => {
    const where = mountNode(createBuilderNode('where'))
    const help = where.find('.node-help')
    expect(help.text()).not.toContain('`')
    expect(help.find('code').text()).toBe('where(meta_expr, query)')

    const meta = mount(CqlMetaExprEditor, {
      props: {
        expr: createMetaCond(),
        metaFieldOptions: ['genre'],
        metaValueChoices: () => [],
      },
    })
    const metaHelp = meta.find('.node-help')
    expect(metaHelp.text()).not.toContain('`')
    expect(metaHelp.findAll('code').map((node) => node.text())).toContain('field op value')
  })
})

describe('other texts with query syntax in backticks', () => {
  it('within scope label in the studio', () => {
    const wrapper = mountNode(createBuilderNode('within'))
    const hint = wrapper.get('.wrapper-hint')
    expect(hint.text()).not.toContain('`')
    expect(hint.find('code').text()).toBe('within(...)')
  })

  it('keyness note of the copilot renderer', () => {
    const wrapper = mount(KeynessRenderer, {
      props: { data: [{ word: 'freedom', log_ratio: 1.2, chi2_cell: 3.4 }] },
      global: { stubs: { Scale: true } },
    })
    const note = wrapper.get('.method-note')
    expect(note.text()).not.toContain('`')
    expect(note.find('code').text()).toBe('chi2_cell')
  })
})
