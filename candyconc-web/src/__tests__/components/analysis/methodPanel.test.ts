import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MethodPanel from '@/components/analysis/MethodPanel.vue'
import type { MethodBlock } from '@/api/client'

describe('MethodPanel (F1 provenance)', () => {
  it('renders stats, formulas and reproducibility from the server method block', () => {
    const method: MethodBlock = {
      stats: {
        ll_signed: { name: 'Signed Log-Likelihood', latex_formula: '2 Σ O ln(O/E)', sort_key: 'll_signed' },
        log_ratio: { name: 'Log Ratio', latex_formula: 'log2(t/r)', smoothing: 'Haldane-Anscombe +0.5' },
      },
      target_total: 12345,
      reference_total: 67890,
      window: 5,
      within_sentence: true,
      event_space: 'anchor_token_pairs',
      event_total_definition: 'anchor_count_times_scope_tokens',
      anchor_span_policy: 'own_match_span_excluded',
      index_fingerprint: 'fp-abc',
    }

    const wrapper = mount(MethodPanel, { props: { method } })
    const text = wrapper.text()
    expect(text).toContain('Methode / Reproduzierbarkeit')
    expect(text).toContain('Signed Log-Likelihood')
    expect(text).toContain('2 Σ O ln(O/E)')
    expect(text).toContain('Haldane-Anscombe +0.5')
    expect(text).toContain('12.345')
    expect(text).toContain('Anker-Token-Paare')
    expect(text).toContain('Ankerzahl × Bezugs-Tokens')
    expect(text).toContain('je Anker aus eigenem Kontext ausgeschlossen')
    expect(text).toContain('fp-abc')
  })

  it('renders the authoritative `statistics` array shape from the backend', () => {
    const method: MethodBlock = {
      family: 'keyness',
      statistics: [
        { key: 'll_signed', name: 'Signed Log-Likelihood', latex_formula: '2 Σ O ln(O/E)', sort_key: 'll_signed' },
        { key: 'log_ratio', name: 'Log Ratio', latex_formula: 'log2(t/r)', smoothing: 'Haldane-Anscombe +0.5' },
      ],
      default_sort: 'll_signed',
      target_total: 12345,
      reference_total: 67890,
      indexFingerprint: 'fp-xyz',
    }

    const wrapper = mount(MethodPanel, { props: { method } })
    const text = wrapper.text()
    expect(text).toContain('Signed Log-Likelihood')
    expect(text).toContain('2 Σ O ln(O/E)')
    expect(text).toContain('Haldane-Anscombe +0.5')
    expect(text).toContain('fp-xyz')
  })

  it('renders the four new r7 METHOD_META stats (chi2 / chi2_signed / delta_p_*) (D-meta)', () => {
    // Mirrors the extended backend METHOD_META (analysis_defaults.py): the panel
    // must render the full 2x2 Pearson chi-square family and directional delta-P
    // descriptors once the backend ships them. Defensive: any subset is valid.
    const method: MethodBlock = {
      family: 'keyness',
      statistics: [
        { key: 'chi2', name: 'Chi² (2x2 Pearson)', latex_formula: 'Σ_ij (O_ij - E_ij)² / E_ij' },
        { key: 'chi2_signed', name: 'Chi² (signiert)', latex_formula: 'sign(O-E) · χ²' },
        { key: 'delta_p_nc', name: 'Delta-P (Node→Collocate)', latex_formula: 'P(c|node) - P(c|¬node)' },
        { key: 'delta_p_cn', name: 'Delta-P (Collocate→Node)', latex_formula: 'P(node|c) - P(node|¬c)' },
      ],
      default_sort: 'chi2',
      indexFingerprint: 'fp-r7',
    }

    const wrapper = mount(MethodPanel, { props: { method } })
    const text = wrapper.text()
    expect(text).toContain('Chi² (2x2 Pearson)')
    expect(text).toContain('Chi² (signiert)')
    expect(text).toContain('Delta-P (Node→Collocate)')
    expect(text).toContain('Delta-P (Collocate→Node)')
    expect(text).toContain('P(c|node) - P(c|¬node)')
    expect(text).toContain('fp-r7')
  })

  it('shows the server counts needed to reproduce collocation scores', () => {
    const wrapper = mount(MethodPanel, { props: { method: {
      family: 'collocates', scope_tokens: 162, window_union_size: 74,
      node_frequency: 17, effective_min_cooccurrence: 2,
    } } })
    const values = Object.fromEntries(wrapper.findAll('dt').map(term => [
      term.text(), term.element.nextElementSibling?.textContent,
    ]))
    expect(values).toMatchObject({
      'Suchbereich-Tokens (N)': '162', 'Fenstervereinigung (R₁)': '74',
      'Knotenfrequenz f(u)': '17', 'Min. Frequenz': '2',
    })
  })

  it('renders nothing when the method block is absent', () => {
    const wrapper = mount(MethodPanel, { props: { method: null } })
    expect(wrapper.find('.method-panel').exists()).toBe(false)
  })

  it('renders nothing for an empty method block', () => {
    const wrapper = mount(MethodPanel, { props: { method: {} } })
    expect(wrapper.find('.method-panel').exists()).toBe(false)
  })
})

describe('MethodPanel formulas', () => {
  const mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mn>14</mn><mo>+</mo><mi>x</mi></math>'

  it('shows the formula as MathML, not as LaTeX source', () => {
    const method: MethodBlock = {
      statistics: [
        { key: 'logdice', name: 'logDice', latex_formula: '14 + \\log_2 x', formula_mathml: mathml, sort_key: 'dice' },
      ],
    }
    const wrapper = mount(MethodPanel, { props: { method } })
    const cell = wrapper.get('.stat-formula')
    expect(cell.find('math').exists()).toBe(true)
    expect(cell.find('code').exists()).toBe(false)
    expect(cell.text()).not.toContain('\\log_2')
    expect(cell.get('.stat-math').attributes('title')).toBe('14 + \\log_2 x')
  })

  it('falls back to the LaTeX source when the MathML is not plain presentation markup', () => {
    const method: MethodBlock = {
      statistics: [
        { key: 'logdice', name: 'logDice', latex_formula: '14 + \\log_2 x', formula_mathml: '<math><img src=x onerror=alert(1)></math>' },
      ],
    }
    const wrapper = mount(MethodPanel, { props: { method } })
    const cell = wrapper.get('.stat-formula')
    expect(cell.find('math').exists()).toBe(false)
    expect(cell.get('code').text()).toBe('14 + \\log_2 x')
  })
})
