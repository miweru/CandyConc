/**
 * Copilot tool renderers format numbers in the interface language.
 *
 * Before, scores, intervals, percentages and durations went through
 * toFixed(), which always writes a decimal point: the German interface
 * showed "9.12" next to "1.234" as a thousands separator.
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import CollocationsRenderer from '@/components/copilot/tools/CollocationsRenderer.vue'
import DocumentSearchRenderer from '@/components/copilot/tools/DocumentSearchRenderer.vue'
import GenericEvidenceRenderer from '@/components/copilot/tools/GenericEvidenceRenderer.vue'
import KeynessRenderer from '@/components/copilot/tools/KeynessRenderer.vue'
import QueryResultsRenderer from '@/components/copilot/tools/QueryResultsRenderer.vue'
import SemanticResultsRenderer from '@/components/copilot/tools/SemanticResultsRenderer.vue'
import WordSketchRenderer from '@/components/copilot/tools/WordSketchRenderer.vue'
import { applyLocale } from '@/i18n/locale'
import { formatDurationMs, formatSuccessRate } from '@/lib/copilotNumbers'

const stubs = { Search: true, Clock: true, Network: true, Scale: true, BookOpen: true, Brain: true, ExternalLink: true, FileText: true }

beforeEach(() => {
  setActivePinia(createPinia())
})

afterEach(() => applyLocale('de'))

function keyness() {
  return mount(KeynessRenderer, {
    props: {
      data: [{ word: 'freedom', log_ratio: 1.2345, log_ratio_ci_low: 0.51, log_ratio_ci_high: 2.09, chi2_cell: 12.3456, q_value: 0.0123 }],
    },
    global: { stubs },
  })
}

function collocations() {
  return mount(CollocationsRenderer, {
    props: { data: [{ word: 'peace', frequency: 1234, observed: 1234, score: 9.87654, measure: 'chi2_cell', expected: 3.14159 }] },
    global: { stubs },
  })
}

describe('copilot renderers in German', () => {
  it('keyness: log ratio, interval, chi2 and q value', () => {
    const text = keyness().text()
    expect(text).toContain('1,23 (0,5 bis 2,1)')
    expect(text).toContain('12,35')
    expect(text).toContain('0,012')
    expect(text).not.toContain('1.23')
  })

  it('collocations: frequency, score, observed and expected', () => {
    const text = collocations().text()
    expect(text).toContain('1.234×')
    expect(text).toContain('9,877')
    expect(text).toContain('O11 1.234')
    expect(text).toContain('E11 3,14')
  })

  it('word sketch: score', () => {
    const wrapper = mount(WordSketchRenderer, {
      props: { data: { tables: { amod: [{ word: 'religious', score: 9.1234, frequency: 12 }] } } },
      global: { stubs },
    })
    expect(wrapper.get('.item-score').text()).toBe('9,12')
  })

  it('semantic search: score in the tooltip', () => {
    const wrapper = mount(SemanticResultsRenderer, {
      props: { data: [{ doc_id: '1', chunk_id: 'c1', text: 'Freiheit', score: 0.12345 }] },
      global: { stubs },
    })
    expect(wrapper.get('.result-score').attributes('title')).toContain('0,123')
  })

  it('document search: score as a percentage', () => {
    const wrapper = mount(DocumentSearchRenderer, {
      props: { data: { rows: [{ doc_id: 1, title: 'Rede', snippet: 'Freiheit', score: 0.876 }] } },
      global: { stubs },
    })
    expect(wrapper.text()).toMatch(/88\s%/)
  })

  it('query results: duration', () => {
    const wrapper = mount(QueryResultsRenderer, {
      props: { data: { total: 5, sampleCount: 5, queryTime: 1234.5 } },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('1,23 s')
  })

  it('generic evidence: decimal metrics', () => {
    const wrapper = mount(GenericEvidenceRenderer, {
      props: { toolName: 'lexical_diversity', data: { ttr: 0.4567, token_count: 403284 } },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('0,4567')
    expect(wrapper.text()).toContain('403.284')
  })

  it('research tools: success rate and duration', () => {
    expect(formatSuccessRate(2, 3)).toMatch(/^67\s%$/)
    expect(formatDurationMs(1234.5)).toBe('1,23 s')
    expect(formatDurationMs(12.4)).toBe('12 ms')
    expect(formatDurationMs(0.25)).toBe('250 µs')
  })
})

describe('copilot renderers in English', () => {
  it('uses English separators', () => {
    applyLocale('en')
    expect(keyness().text()).toContain('1.23 (0.5 to 2.1)')
    expect(collocations().text()).toContain('O11 1,234')
    expect(formatSuccessRate(2, 3)).toBe('67%')
    expect(formatDurationMs(1234.5)).toBe('1.23 s')
  })
})
