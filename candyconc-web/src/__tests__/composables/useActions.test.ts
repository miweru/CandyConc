import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { actionBus } from '@/actions/bus'
import { useActions } from '@/composables/useActions'

function toastAction(message: string) {
  return {
    type: 'ui/toast' as const,
    payload: { message, type: 'info' as const },
  }
}

describe('useActions handler lifecycle', () => {
  it('restores a global handler after a component-local handler unmounts', async () => {
    const globalHandler = vi.fn(async () => ({ success: true, data: 'global' }))
    const localHandler = vi.fn(async () => ({ success: true, data: 'local' }))
    const cleanupGlobal = actionBus.register('ui/toast', globalHandler)
    let wrapper: VueWrapper | undefined
    let unmounted = false

    try {
      await expect(actionBus.dispatch(toastAction('before mount'))).resolves.toMatchObject({
        success: true,
        data: 'global',
      })

      wrapper = mount(defineComponent({
        setup() {
          useActions({
            'ui/toast': localHandler,
          })
          return () => null
        },
      }))
      await nextTick()

      await expect(actionBus.dispatch(toastAction('while mounted'))).resolves.toMatchObject({
        success: true,
        data: 'local',
      })

      wrapper.unmount()
      unmounted = true
      await nextTick()

      await expect(actionBus.dispatch(toastAction('after unmount'))).resolves.toMatchObject({
        success: true,
        data: 'global',
      })

      expect(globalHandler).toHaveBeenCalledTimes(2)
      expect(localHandler).toHaveBeenCalledTimes(1)
    } finally {
      if (wrapper && !unmounted) {
        wrapper.unmount()
      }
      cleanupGlobal()
    }
  })
})
