import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import AppShell from '@/components/layout/AppShell.vue'

describe('AppShell layout slots', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.innerWidth = 1024
  })

  it('renders the footer slot so global status remains visible', () => {
    const wrapper = mount(AppShell, {
      slots: {
        header: '<div data-test="header-slot">Header</div>',
        default: '<div data-test="main-slot">Main</div>',
        footer: '<div data-test="footer-slot">Status</div>',
      },
      global: {
        stubs: {
          CopilotTrigger: true,
          ToastContainer: true,
          MobileNav: true,
          BottomSheet: true,
        },
      },
    })

    expect(wrapper.find('[data-test="header-slot"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="main-slot"]').exists()).toBe(true)
    expect(wrapper.find('.app-footer [data-test="footer-slot"]').exists()).toBe(true)
  })
})
