import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import AuthSessionPanel from '@/components/auth/AuthSessionPanel.vue'
import { useUiStore } from '@/stores/ui'

const getAuthSession = vi.fn()
const loginUser = vi.fn()
const logoutUser = vi.fn()

vi.mock('@/api/client', () => ({
  getAuthSession: (...args: unknown[]) => getAuthSession(...args),
  loginUser: (...args: unknown[]) => loginUser(...args),
  logoutUser: (...args: unknown[]) => logoutUser(...args),
}))

function session(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 'auth-session-v1',
    authenticated: false,
    token_present: false,
    username: null,
    role: null,
    effective_role: null,
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
    ...overrides,
  }
}

describe('AuthSessionPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    window.sessionStorage.clear()
    window.localStorage.clear()
    getAuthSession.mockResolvedValue(session())
  })

  it('shows release login state and authenticates through the session store', async () => {
    loginUser.mockResolvedValue({ token: 'admin-token' })
    getAuthSession
      .mockResolvedValueOnce(session())
      .mockResolvedValueOnce(session({
        authenticated: true,
        token_present: true,
        username: 'admin',
        role: 'admin',
        effective_role: 'admin',
      }))
    const wrapper = mount(AuthSessionPanel, {
      global: {
        plugins: [createPinia()],
        stubs: {
          Teleport: true,
          Modal: {
            props: ['modelValue'],
            template: '<div v-if="modelValue" class="modal-stub"><slot /><slot name="footer" /></div>',
          },
        },
      },
    })
    await flushPromises()

    await wrapper.find('button.session-trigger').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Nicht angemeldet')
    expect(wrapper.text()).toContain('Release-Modus')

    await wrapper.find('input[autocomplete="username"]').setValue('admin')
    await wrapper.find('input[autocomplete="current-password"]').setValue('pw')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(loginUser).toHaveBeenCalledWith({ username: 'admin', password: 'pw' })
    expect(window.sessionStorage.getItem('auth_token')).toBe('admin-token')
    expect(useUiStore().authOpen).toBe(false)
  })
})
