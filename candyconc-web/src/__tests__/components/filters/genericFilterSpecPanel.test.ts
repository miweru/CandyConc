import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import GenericFilterSpecPanel from '@/components/filters/GenericFilterSpecPanel.vue'

describe('GenericFilterSpecPanel', () => {
  it('rehydrates enum and range controls from modelValue and emits typed specs', async () => {
    const wrapper = mount(GenericFilterSpecPanel, {
      props: {
        modelValue: {
          genre: ['Essay'],
          year: { op: 'between', lo: 1800, hi: 1850 },
        },
        enumFields: [{ name: 'genre', kind: 'enum' }],
        rangeFields: [{ name: 'year', kind: 'number' }],
        enumOptions: { genre: ['Essay', 'Brief'] },
      },
    })

    const select = wrapper.get('select')
    expect((select.element as HTMLSelectElement).selectedOptions[0]?.value).toBe('Essay')
    expect(wrapper.text()).toContain('1800 bis 1850')

    await select.setValue(['Brief'])
    const emitted = wrapper.emitted('update:modelValue')?.at(-1)?.[0]
    expect(emitted).toMatchObject({
      genre: ['Brief'],
      year: { op: 'between', lo: 1800, hi: 1850 },
    })
  })

  it('shows no legacy paired placeholders for generic-only corpora', () => {
    const wrapper = mount(GenericFilterSpecPanel, {
      props: {
        modelValue: null,
        enumFields: [{ name: 'genre', kind: 'enum' }],
        rangeFields: [],
        enumOptions: { genre: ['Essay'] },
      },
    })

    expect(wrapper.text()).toContain('genre')
    expect(wrapper.text()).not.toContain('Alle Modelle')
    expect(wrapper.text()).not.toContain('Alle Register')
  })

  it('keeps high-cardinality fields usable as exact values without materialising a select', async () => {
    const wrapper = mount(GenericFilterSpecPanel, {
      props: {
        modelValue: null,
        enumFields: [{ name: 'register', kind: 'enum' }],
        rangeFields: [],
        textFields: [{ name: 'author', kind: 'text' }],
        enumOptions: { register: ['Presse'] },
      },
    })

    expect(wrapper.findAll('select')).toHaveLength(1)
    expect(wrapper.text()).toContain('Weitere Metadaten mit exaktem Wert')
    const input = wrapper.get('input[placeholder="Exakter Wert, weitere mit Komma"]')
    await input.setValue('42, 87, 42')

    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({
      author: ['42', '87'],
    })
  })
})
