/**
 * Wheel scrolling for a scroll area that contains its own scroll areas.
 *
 * The analysis tabs scroll as a whole, and their result tables scroll inside,
 * at most as high as the tab. A browser scrolls the innermost area under the
 * pointer first. When the table still reaches below the visible tab, the
 * reader would scroll rows whose lower part stays hidden. Downward wheel
 * movement over such an inner area therefore scrolls the tab first, until the
 * inner area is fully visible. Upward movement keeps the browser behaviour:
 * the table scrolls back to its top, then the tab follows.
 */
import { onBeforeUnmount, watch, type Ref } from 'vue'

const LINE_PX = 16

function deltaPixels(event: WheelEvent, page: number): number {
  if (event.deltaMode === 1) return event.deltaY * LINE_PX
  if (event.deltaMode === 2) return event.deltaY * page
  return event.deltaY
}

function scrollsDown(el: HTMLElement): boolean {
  const overflowY = getComputedStyle(el).overflowY
  if (overflowY !== 'auto' && overflowY !== 'scroll') return false
  return el.scrollTop + el.clientHeight < el.scrollHeight - 1
}

/** Innermost element between target and outer that can still scroll down. */
export function innerScroller(target: EventTarget | null, outer: HTMLElement): HTMLElement | null {
  let node = target instanceof Element ? target : null
  while (node && node !== outer) {
    if (node instanceof HTMLElement && scrollsDown(node)) return node
    node = node.parentElement
  }
  return null
}

/**
 * Pixels the outer area should scroll for a downward wheel step, or 0 when
 * the browser should handle the step itself.
 */
export function handoffDistance(event: WheelEvent, outer: HTMLElement): number {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey) return 0
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return 0
  const delta = deltaPixels(event, outer.clientHeight)
  if (delta <= 0) return 0
  const outerLeft = outer.scrollHeight - outer.clientHeight - outer.scrollTop
  if (outerLeft <= 1) return 0
  const inner = innerScroller(event.target, outer)
  if (!inner) return 0
  const hidden = inner.getBoundingClientRect().bottom - outer.getBoundingClientRect().bottom
  if (hidden <= 1) return 0
  return Math.min(delta, outerLeft, hidden)
}

export function useScrollHandoff(outerRef: Ref<HTMLElement | null>) {
  const onWheel = (event: WheelEvent) => {
    const outer = outerRef.value
    if (!outer) return
    const distance = handoffDistance(event, outer)
    if (distance <= 0) return
    event.preventDefault()
    outer.scrollTop += distance
  }

  let bound: HTMLElement | null = null
  const unbind = () => {
    bound?.removeEventListener('wheel', onWheel)
    bound = null
  }
  watch(
    outerRef,
    (el) => {
      unbind()
      if (!el) return
      el.addEventListener('wheel', onWheel, { passive: false })
      bound = el
    },
    { immediate: true, flush: 'post' },
  )
  onBeforeUnmount(unbind)
}
