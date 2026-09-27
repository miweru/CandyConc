import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import QueryResultsRenderer from '@/components/copilot/tools/QueryResultsRenderer.vue'

describe('QueryResultsRenderer truth labels', () => {
  it('labels sampled KWIC rows as evidence rows, not as a complete hit count', () => {
    const wrapper = mount(QueryResultsRenderer, {
      props: {
        data: {
          total: null,
          sampleCount: 2,
          truncated: true,
        },
      },
      global: {
        stubs: {
          Search: true,
          Clock: true,
        },
      },
    })

    expect(wrapper.text()).toContain('2 geladene Belegzeilen')
    expect(wrapper.text()).toContain('Stichprobe, keine Gesamtzählung')
    expect(wrapper.text()).not.toContain('2 Treffer')
  })

  it('marks known truncated totals as partial', () => {
    const wrapper = mount(QueryResultsRenderer, {
      props: {
        data: {
          total: 50,
          sampleCount: 50,
          truncated: true,
        },
      },
      global: {
        stubs: {
          Search: true,
          Clock: true,
        },
      },
    })

    expect(wrapper.text()).toContain('50 Treffer')
    expect(wrapper.text()).toContain('partiell')
  })
})
