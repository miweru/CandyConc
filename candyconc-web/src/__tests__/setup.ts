/**
 * Vitest Setup File
 */
import { afterEach, vi } from 'vitest'
import { config } from '@vue/test-utils'
import { i18n } from '@/i18n'
import { applyLocale } from '@/i18n/locale'

// The suite asserts German interface texts. The browser language decides the
// interface language when no preference is stored, so tests run with a German
// browser and the i18n plugin on every mount. Tests that switch to English
// are reset to German afterwards.
Object.defineProperty(window.navigator, 'language', { value: 'de-DE', configurable: true })
config.global.plugins = [...(config.global.plugins ?? []), i18n]
applyLocale('de')
afterEach(() => {
  applyLocale('de')
})

// Mock ResizeObserver as a constructor; @tanstack/vue-virtual uses `new ResizeObserver(...)`.
class TestResizeObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

global.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  }))
})

// Mock localStorage
const localStorageMock = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn()
}
Object.defineProperty(window, 'localStorage', { value: localStorageMock })

// Mock IntersectionObserver
global.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn()
}))

vi.stubGlobal('confirm', vi.fn(() => true))
