import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import Heatmap from '@/components/analysis/charts/Heatmap.vue'

describe('Heatmap dispersion axis', () => {
  let clientWidthDescriptor: PropertyDescriptor | undefined
  let resizeObserver: typeof ResizeObserver

  beforeEach(() => {
    clientWidthDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get: () => 500,
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

  it('derives percentage ticks from rendered bins and never from a slider partition value', async () => {
    const wrapper = mount(Heatmap, {
      props: {
        data: Array.from({ length: 40 }, (_, index) => ({
          x: index * 100,
          value: (index % 4) + 1,
        })),
        height: 120,
      },
    })

    await nextTick()
    await nextTick()

    const percentLabels = [...wrapper.element.querySelectorAll('text')]
      .map((node) => node.textContent?.trim() ?? '')
      .filter((label) => label.endsWith('%'))
    const numericLabels = percentLabels.map((label) => Number.parseInt(label, 10))

    expect(percentLabels).toContain('0%')
    expect(percentLabels).toContain('100%')
    expect(Math.max(...numericLabels)).toBe(100)
    expect(percentLabels).not.toContain('3900%')
  })
})
