import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CqlSuggestionsPanel from '@/components/search/query-builder/CqlSuggestionsPanel.vue'

describe('CqlSuggestionsPanel', () => {
  it('shows unavailable backend diagnostics as not validated instead of silence', () => {
    const wrapper = mount(CqlSuggestionsPanel, {
      props: {
        isSuggesting: false,
        analysisErrors: [],
        analysisWarnings: [],
        diagnosticsStatus: 'unavailable',
        diagnosticsError: 'Backend nicht erreichbar',
        salientSuggestions: [],
        otherCompletionSuggestions: [],
        fixSuggestions: [],
      },
    })

    expect(wrapper.text()).toContain('Backend-Diagnostik nicht verfügbar')
    expect(wrapper.text()).toContain('Backend nicht erreichbar')
    expect(wrapper.text()).toContain('Keine Warnung bedeutet hier nicht')
  })
})
