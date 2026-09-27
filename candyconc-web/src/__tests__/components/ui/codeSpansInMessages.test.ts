import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import EmptyState from '@/components/ui/EmptyState.vue'
import ToastContainer from '@/components/ui/ToastContainer.vue'
import { t } from '@/i18n'
import { applyLocale } from '@/i18n/locale'
import { useUiStore } from '@/stores/ui'

// Action errors name payload parameters in backticks (`targetDocsetId`). The
// toast and the empty state showed the backticks as text.

describe('backtick spans in messages render as code', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    applyLocale('de')
  })

  it.each(['de', 'en'] as const)('shows an action error toast with its parameter as code (%s)', async (lang) => {
    applyLocale(lang)
    const uiStore = useUiStore()
    uiStore.showToast(t('actions.handlers.keynessReference'), 'warning')
    const wrapper = mount(ToastContainer, { global: { stubs: { teleport: true } } })
    await wrapper.vm.$nextTick()
    const message = wrapper.get('.toast p')
    expect(message.text()).not.toContain('`')
    expect(message.findAll('code').map((node) => node.text())).toEqual(['referenceDocsetId', 'referenceSource'])
  })

  it('shows an empty state description with code spans', () => {
    const wrapper = mount(EmptyState, {
      props: { title: 'Fehler beim Laden', description: t('analysis.wordSketch.needsRel') },
    })
    const description = wrapper.get('.empty-description')
    expect(description.text()).not.toContain('`')
    expect(description.get('code').text()).toBe('rel')
  })
})
