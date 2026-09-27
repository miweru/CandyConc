import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import LineChart, { type LineChartPoint } from '@/components/analysis/charts/LineChart.vue'

const POINTS: LineChartPoint[] = [
  { label: '2019', value: 120, ciLow: 90, ciHigh: 160, hits: 12, tokens: 100_000 },
  { label: '2020', value: 300, ciLow: 210.12, ciHigh: 428.57, hits: 30, tokens: 100_000 },
  { label: '2021', value: 100, ciLow: 42.7, ciHigh: 233.9, hits: 5, tokens: 50_000 },
]

describe('LineChart (trend)', () => {
  let clientWidthDescriptor: PropertyDescriptor | undefined
  let resizeObserver: typeof ResizeObserver

  beforeEach(() => {
    clientWidthDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get: () => 600,
    })
    resizeObserver = globalThis.ResizeObserver
    class TestResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver
  })

  afterEach(() => {
    globalThis.ResizeObserver = resizeObserver
    if (clientWidthDescriptor) {
      Object.defineProperty(HTMLElement.prototype, 'clientWidth', clientWidthDescriptor)
    } else {
      delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth
    }
  })

  async function mountChart(data: LineChartPoint[] = POINTS) {
    const wrapper = mount(LineChart, { props: { data, height: 320 } })
    await nextTick()
    await nextTick()
    return wrapper
  }

  it('renders CI band, trend line and one point per period', async () => {
    const wrapper = await mountChart()
    const el = wrapper.element

    expect(el.querySelector('path.ci-band')).not.toBeNull()
    expect(el.querySelector('path.trend-line')).not.toBeNull()
    expect(el.querySelectorAll('circle.trend-point')).toHaveLength(3)

    const labels = [...el.querySelectorAll('.tick text')].map((node) => node.textContent?.trim())
    expect(labels).toContain('2019')
    expect(labels).toContain('2020')
    expect(labels).toContain('2021')
  })

  it('scales the y-domain from the CI upper bound, not just the point value', async () => {
    const wrapper = await mountChart()
    const el = wrapper.element

    // Max ciHigh is 428.57 -> the nice()d axis must reach at least 450,
    // which only happens when the band bound drives the domain.
    const yTickValues = [...el.querySelectorAll('.tick text')]
      .map((node) => Number((node.textContent ?? '').replace(/\./g, '')))
      .filter((value) => Number.isFinite(value))
    expect(Math.max(...yTickValues)).toBeGreaterThanOrEqual(428)
  })

  it('shows a tooltip with period, hits, tokens, rate and CI on hover', async () => {
    const wrapper = await mountChart()

    expect(wrapper.find('.line-chart-tooltip').exists()).toBe(false)

    const point = wrapper.element.querySelectorAll('circle.trend-point')[1]!
    point.dispatchEvent(new MouseEvent('mouseover'))
    await nextTick()

    const tooltip = wrapper.find('.line-chart-tooltip')
    expect(tooltip.exists()).toBe(true)
    expect(tooltip.text()).toContain('2020')
    expect(tooltip.text()).toContain('30')
    expect(tooltip.text()).toContain('100.000')
    expect(tooltip.text()).toContain('300,00')
    expect(tooltip.text()).toContain('210,12 bis 428,57')

    point.dispatchEvent(new MouseEvent('mouseout'))
    await nextTick()
    expect(wrapper.find('.line-chart-tooltip').exists()).toBe(false)
  })

  it('renders nothing for an empty series without crashing', async () => {
    const wrapper = await mountChart([])
    expect(wrapper.element.querySelector('svg')).toBeNull()
  })
})
