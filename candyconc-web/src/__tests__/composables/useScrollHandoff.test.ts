/**
 * Downward wheel steps over a result table that still reaches below the tab
 * scroll the tab first. The geometry is set by hand, because jsdom has no
 * layout.
 */
import { describe, expect, it } from 'vitest'

import { handoffDistance, innerScroller } from '@/composables/useScrollHandoff'

function box(el: HTMLElement, top: number, height: number, scroll: { height: number, top: number }) {
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: height })
  Object.defineProperty(el, 'scrollHeight', { configurable: true, value: scroll.height })
  Object.defineProperty(el, 'scrollTop', { configurable: true, writable: true, value: scroll.top })
  el.getBoundingClientRect = () => ({ top, bottom: top + height, height, left: 0, right: 100, width: 100, x: 0, y: top, toJSON: () => ({}) }) as DOMRect
}

function layout({ outerTop = 0, innerTop }: { outerTop?: number, innerTop: number }) {
  const outer = document.createElement('div')
  const inner = document.createElement('div')
  const row = document.createElement('span')
  inner.style.overflowY = 'auto'
  inner.appendChild(row)
  outer.appendChild(inner)
  document.body.appendChild(outer)
  // Tab: 600 px visible, 900 px content (300 px toolbars + 600 px table).
  box(outer, 0, 600, { height: 900, top: outerTop })
  // Table: 600 px high, 5000 px of rows.
  box(inner, innerTop, 600, { height: 5000, top: 0 })
  return { outer, inner, row }
}

function wheel(target: Element, deltaY: number, init: WheelEventInit = {}) {
  const event = new WheelEvent('wheel', { deltaY, bubbles: true, cancelable: true, ...init })
  Object.defineProperty(event, 'target', { value: target })
  return event
}

describe('scroll handoff', () => {
  it('scrolls the tab first while the table reaches below it', () => {
    const { outer, row } = layout({ innerTop: 300 })
    expect(handoffDistance(wheel(row, 120), outer)).toBe(120)
  })

  it('never scrolls the tab further than the hidden part of the table', () => {
    const { outer, row } = layout({ outerTop: 250, innerTop: 50 })
    expect(handoffDistance(wheel(row, 120), outer)).toBe(50)
  })

  it('leaves the step to the table once the table is fully visible', () => {
    const { outer, row } = layout({ outerTop: 300, innerTop: 0 })
    expect(handoffDistance(wheel(row, 120), outer)).toBe(0)
  })

  it('leaves upward steps and zoom gestures to the browser', () => {
    const { outer, row } = layout({ innerTop: 300 })
    expect(handoffDistance(wheel(row, -120), outer)).toBe(0)
    expect(handoffDistance(wheel(row, 120, { ctrlKey: true }), outer)).toBe(0)
  })

  it('finds no inner scroller outside a scrolling element', () => {
    const { outer } = layout({ innerTop: 300 })
    const plain = document.createElement('p')
    outer.appendChild(plain)
    expect(innerScroller(plain, outer)).toBeNull()
    expect(handoffDistance(wheel(plain, 120), outer)).toBe(0)
  })
})
