/**
 * The copilot button used to float above the content (fixed, bottom left) and
 * covered the first column of tables: the collocate "own" in the word sketch,
 * the period 1947 in the trend table, the positions in the concordance. It
 * now takes the left end of the footer, next to the status bar, and is part
 * of the layout instead of lying on top of it.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppShell from '@/components/layout/AppShell.vue'
import CopilotTrigger from '@/components/copilot/CopilotTrigger.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'

describe('copilot button in the footer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.innerWidth = 1440
  })

  it('has no position of its own', () => {
    const wrapper = mount(CopilotTrigger)
    const button = wrapper.get('.copilot-trigger')
    expect(button.attributes('style') ?? '').not.toContain('bottom')
  })

  it('renders inside the footer, before the status bar', async () => {
    vi.spyOn(useProductCapabilitiesStore(), 'isVisible').mockReturnValue(true)
    const wrapper = mount(AppShell, {
      slots: { footer: '<div class="status-stub">sotu_en | 403,284 tokens</div>' },
      global: {
        stubs: {
          CopilotTrigger: { props: ['disabled'], template: '<button class="trigger-stub" />' },
          ToastContainer: true,
          MobileNav: true,
          BottomSheet: true,
          ArbeitsspurLeiste: true,
        },
      },
    })
    await flushPromises()
    const footer = wrapper.get('.app-footer')
    const children = footer.element.querySelectorAll('.trigger-stub, .status-stub')
    expect([...children].map((el) => el.className)).toEqual(['trigger-stub', 'status-stub'])
    expect(wrapper.get('main').find('.trigger-stub').exists()).toBe(false)
  })
})
