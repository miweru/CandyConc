import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FilterSpecChips from '@/components/filters/FilterSpecChips.vue'

describe('FilterSpecChips', () => {
  it('shows generic filters instead of legacy all-filter placeholders', () => {
    const wrapper = mount(FilterSpecChips, {
      props: {
        spec: {
          genre: ['Essay', 'Brief'],
          year: { op: 'between', lo: 1800, hi: 1850 },
        },
      },
    })

    expect(wrapper.text()).toContain('genre')
    expect(wrapper.text()).toContain('Essay, Brief')
    expect(wrapper.text()).toContain('year')
    expect(wrapper.text()).toContain('1800 bis 1850')
    expect(wrapper.text()).not.toContain('Alle Modelle')
  })

  it('uses an explicit empty label when no filter spec exists', () => {
    const wrapper = mount(FilterSpecChips, {
      props: { spec: null, emptyLabel: 'Gesamtkorpus' },
    })

    expect(wrapper.text()).toBe('Gesamtkorpus')
  })
})
