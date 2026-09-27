/**
 * FIX 2 (round 5) — dialog focus-on-open / focus-trap arming on FIRST open.
 *
 * Modal.vue and SlideOver.vue arm their focus trap + body scroll-lock from a
 * `watch(() => props.modelValue, ...)`. Without `{ immediate: true }` the watcher
 * never fires for a dialog that is ALREADY open on its first render (mounted with
 * modelValue=true, the common Settings/Export/Bookmarks pattern), so the trap and
 * scroll-lock never engage and Escape-to-close is dead. This test mounts each
 * dialog already-open and asserts the trap armed (focus moved inside, body locked,
 * Escape closes).
 */
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import Modal from '@/components/ui/Modal.vue'
import SlideOver from '@/components/ui/SlideOver.vue'

function settleTrap(): Promise<void> {
  // The watcher arms the trap behind setTimeout(..., 50), and useFocusTrap then
  // focuses inside a requestAnimationFrame. Wait past both before asserting focus.
  return new Promise((resolve) =>
    setTimeout(() => requestAnimationFrame(() => resolve()), 80),
  )
}

afterEach(() => {
  // The watcher locks body scroll; make sure nothing leaks across tests.
  document.body.style.overflow = ''
})

describe('Modal focus-on-open arms the trap on first open', () => {
  it('locks body scroll, moves focus inside, and closes on Escape when mounted open', async () => {
    const wrapper = mount(Modal, {
      attachTo: document.body,
      props: {
        modelValue: true,
        title: 'Einstellungen',
      },
      slots: {
        default: '<button class="inner-btn">Inneres Ziel</button>',
      },
    })

    // Watcher with { immediate: true } fired on mount → body scroll locked.
    expect(document.body.style.overflow).toBe('hidden')

    await settleTrap()
    await wrapper.vm.$nextTick()

    // Focus moved into the dialog panel (trap armed on first open).
    const panel = document.body.querySelector('.modal-panel') as HTMLElement
    expect(panel).not.toBeNull()
    expect(panel.contains(document.activeElement)).toBe(true)

    // Escape-to-close is wired through the armed trap.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    const closeEvents = wrapper.emitted('update:modelValue')
    expect(closeEvents?.some((e) => e[0] === false)).toBe(true)

    wrapper.unmount()
  })
})

describe('SlideOver focus-on-open arms the trap on first open', () => {
  it('locks body scroll, moves focus inside, and closes on Escape when mounted open', async () => {
    const wrapper = mount(SlideOver, {
      attachTo: document.body,
      props: {
        modelValue: true,
        title: 'Lesezeichen',
      },
      slots: {
        default: '<button class="inner-btn">Inneres Ziel</button>',
      },
    })

    expect(document.body.style.overflow).toBe('hidden')

    await settleTrap()
    await wrapper.vm.$nextTick()

    const panel = document.body.querySelector('.slide-over-panel') as HTMLElement
    expect(panel).not.toBeNull()
    expect(panel.contains(document.activeElement)).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    const closeEvents = wrapper.emitted('update:modelValue')
    expect(closeEvents?.some((e) => e[0] === false)).toBe(true)

    wrapper.unmount()
  })
})
