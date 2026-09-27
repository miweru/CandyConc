import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CorpusReportList from '@/components/corpus/CorpusReportList.vue'
import { importReportEntriesFromPayload } from '@/lib/importReportDiagnostics'

describe('CorpusReportList', () => {
  it('renders typed reports and hides raw expert evidence until explicitly requested', async () => {
    const entries = importReportEntriesFromPayload({
      build_report: { status: 'done', token_count: 42 },
      raw: {
        'build_report.json': { status: 'done' },
      },
    })

    const wrapper = mount(CorpusReportList, {
      props: {
        title: 'Build-Report und Manifest',
        ariaLabel: 'Build-Report',
        entries,
      },
    })

    expect(wrapper.attributes('aria-label')).toBe('Build-Report')
    expect(wrapper.text()).toContain('Build-Report und Manifest')
    expect(wrapper.text()).toContain('Build-Report')
    expect(wrapper.text()).toContain('Build')
    expect(wrapper.text()).toContain('Vollreport anzeigen')
    expect(wrapper.text()).toContain('backendseitig bereits größenbegrenzte Report-Evidenz')
    expect(wrapper.text()).not.toContain('Rohreports (Debug)')
    expect(wrapper.text()).toContain('Debug-Reports anzeigen (1)')

    await wrapper.find('button').trigger('click')

    expect(wrapper.text()).toContain('Rohreports (Debug)')
    expect(wrapper.text()).toContain('Expert')
    expect(wrapper.text()).toContain('nicht als normalisierter Import- oder Build-Report')
    expect(wrapper.find('.report-card--expert').exists()).toBe(true)
  })
})
