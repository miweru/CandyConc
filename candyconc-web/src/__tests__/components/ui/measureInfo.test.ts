import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MeasureInfo from '@/components/ui/MeasureInfo.vue'
import type { MethodBlock } from '@/api/client'

/**
 * MeasureInfo (Messlatte S3): Formel-Tooltip statt Empfehlungslabel.
 * Verifiziert Hover- UND Fokus-Öffnung (a11y), natives MathML-Rendering aus
 * dem Katalog-Spiegel bzw. dem method-Block (Server-Wahrheit hat Vorrang),
 * Escape-Schließen und den Markup-Wächter gegen Nicht-MathML.
 */
describe('MeasureInfo', () => {
  function mountInfo(props: Record<string, unknown>) {
    return mount(MeasureInfo, { props })
  }

  /**
   * v-show-Sichtbarkeit über style.display prüfen: jsdoms checkVisibility()
   * (Basis von DOMWrapper.isVisible in aktuellen test-utils) liefert hier
   * layoutlose Scheinwerte.
   */
  function popoverDisplayed(wrapper: ReturnType<typeof mountInfo>): boolean {
    const el = wrapper.find('.measure-info-popover').element as HTMLElement
    return el.style.display !== 'none'
  }

  it('renders the catalog formula as native MathML on hover and hides on leave', async () => {
    const wrapper = mountInfo({ measureKey: 'logdice' })
    const popover = wrapper.find('.measure-info-popover')
    expect(popover.exists()).toBe(true)
    expect(popoverDisplayed(wrapper)).toBe(false)

    await wrapper.find('.measure-info').trigger('mouseenter')
    expect(popoverDisplayed(wrapper)).toBe(true)
    // Natives Präsentations-MathML, keine Rendering-Library.
    expect(popover.find('math').exists()).toBe(true)
    expect(popover.html()).toContain('MathML')
    expect(popover.text()).toContain('logDice')
    expect(popover.text()).toContain('Rychlý 2008')
    // Erklärung ist die wissenschaftliche Lesehilfe, keine Empfehlung.
    expect(popover.text()).toContain('Korpusgröße')
    expect(popover.text().toLowerCase()).not.toContain('empfohlen')

    await wrapper.find('.measure-info').trigger('mouseleave')
    expect(popoverDisplayed(wrapper)).toBe(false)
  })

  it('opens on keyboard focus, wires aria-describedby, and closes on Escape', async () => {
    const wrapper = mountInfo({ measureKey: 'mi3' })
    const button = wrapper.find('button.measure-info-btn')
    const popover = wrapper.find('.measure-info-popover')

    expect(button.attributes('aria-expanded')).toBe('false')
    expect(button.attributes('aria-describedby')).toBeUndefined()

    await button.trigger('focus')
    expect(popoverDisplayed(wrapper)).toBe(true)
    expect(button.attributes('aria-expanded')).toBe('true')
    const describedBy = button.attributes('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(popover.attributes('id')).toBe(describedBy)
    expect(popover.attributes('role')).toBe('tooltip')
    expect(popover.text()).toContain('Oakes 1998')

    await button.trigger('keydown', { key: 'Escape' })
    expect(popoverDisplayed(wrapper)).toBe(false)

    // Blur nach erneutem Fokus schließt ebenfalls.
    await button.trigger('focus')
    expect(popoverDisplayed(wrapper)).toBe(true)
    await button.trigger('blur')
    expect(popoverDisplayed(wrapper)).toBe(false)
  })

  it('prefers the server method block over the static catalog mirror', async () => {
    const method: MethodBlock = {
      family: 'collocation',
      statistics: [
        {
          key: 'mi3',
          name: 'MI3 (Server)',
          formula_mathml: '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>S</mi></math>',
          explanation: 'Serverseitige Erklärung mit familienspezifischem Override.',
          reference: 'Serverquelle 2026',
        },
      ],
    }
    const wrapper = mountInfo({ measureKey: 'mi3', method })
    await wrapper.find('.measure-info').trigger('mouseenter')
    const popover = wrapper.find('.measure-info-popover')
    expect(popover.text()).toContain('MI3 (Server)')
    expect(popover.text()).toContain('Serverseitige Erklärung')
    expect(popover.text()).toContain('Serverquelle 2026')
    expect(popover.find('math').text()).toBe('S')
  })

  it('normalizes UI spellings (tscore -> t) against the catalog', async () => {
    const wrapper = mountInfo({ measureKey: 'tscore' })
    await wrapper.find('.measure-info').trigger('mouseenter')
    const popover = wrapper.find('.measure-info-popover')
    expect(popover.text()).toContain('t-Score')
    expect(popover.text()).toContain('Church et al. 1991')
    expect(popover.find('math').exists()).toBe(true)
  })

  it('refuses to render non-MathML markup from a malformed method block', async () => {
    const method: MethodBlock = {
      statistics: [
        {
          key: 'custom_stat',
          name: 'Custom',
          formula_mathml: '<script>alert(1)</script>',
          explanation: 'Erklärung bleibt sichtbar, Markup nicht.',
          reference: 'Q',
        },
      ],
    }
    const wrapper = mountInfo({ measureKey: 'custom_stat', method })
    await wrapper.find('.measure-info').trigger('mouseenter')
    const popover = wrapper.find('.measure-info-popover')
    expect(popover.find('math').exists()).toBe(false)
    expect(popover.html()).not.toContain('<script')
    expect(popover.text()).toContain('Erklärung bleibt sichtbar')
  })

  it('rejects event handlers and embedded script inside a <math> wrapper', async () => {
    const method: MethodBlock = {
      statistics: [
        {
          key: 'custom_stat',
          name: 'Custom',
          formula_mathml: '<math onmouseover="alert(1)"><mi>x</mi></math>',
          explanation: 'x',
          reference: 'Q',
        },
      ],
    }
    const wrapper = mountInfo({ measureKey: 'custom_stat', method })
    await wrapper.find('.measure-info').trigger('mouseenter')
    expect(wrapper.find('.measure-info-popover').find('math').exists()).toBe(false)
  })

  it('renders nothing at all for an unknown measure without content', () => {
    const wrapper = mountInfo({ measureKey: 'does_not_exist' })
    expect(wrapper.find('.measure-info').exists()).toBe(false)
  })
})
