/**
 * useAnnounce - Screen reader announcements via live regions
 */

import { onMounted } from 'vue'
import { t } from '@/i18n'

const ANNOUNCER_ID = 'a11y-announcer'
const ANNOUNCER_ASSERTIVE_ID = 'a11y-announcer-assertive'

let politeAnnouncer: HTMLElement | null = null
let assertiveAnnouncer: HTMLElement | null = null

function createAnnouncer(id: string, ariaLive: 'polite' | 'assertive'): HTMLElement {
  const existing = document.getElementById(id)
  if (existing) return existing

  const el = document.createElement('div')
  el.id = id
  el.setAttribute('role', 'status')
  el.setAttribute('aria-live', ariaLive)
  el.setAttribute('aria-atomic', 'true')
  el.className = 'sr-only'
  el.style.cssText = `
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  `
  document.body.appendChild(el)
  return el
}

function ensureAnnouncers() {
  if (!politeAnnouncer) {
    politeAnnouncer = createAnnouncer(ANNOUNCER_ID, 'polite')
  }
  if (!assertiveAnnouncer) {
    assertiveAnnouncer = createAnnouncer(ANNOUNCER_ASSERTIVE_ID, 'assertive')
  }
}

/**
 * Announce a message to screen readers
 * @param message - The message to announce
 * @param priority - 'polite' waits for user to finish, 'assertive' interrupts
 */
export function announce(message: string, priority: 'polite' | 'assertive' = 'polite'): void {
  ensureAnnouncers()

  const announcer = priority === 'assertive' ? assertiveAnnouncer : politeAnnouncer
  if (!announcer) return

  // Clear and re-set to ensure announcement is made
  announcer.textContent = ''

  // Use requestAnimationFrame to ensure the clear is processed
  requestAnimationFrame(() => {
    if (announcer) {
      announcer.textContent = message
    }
  })
}

/**
 * Composable version for Vue components
 */
export function useAnnounce() {
  onMounted(() => {
    ensureAnnouncers()
  })

  return {
    /**
     * Announce a message to screen readers
     * @param message - The message to announce
     * @param priority - 'polite' (default) or 'assertive'
     */
    announce,

    /**
     * Announce search results count
     */
    announceResults(count: number, term?: string) {
      if (count === 0) {
        announce(term ? t('layout.announce.noResultsFor', { term }) : t('layout.announce.noResults'))
      } else {
        const msg = term
          ? t('layout.announce.resultsFor', { count, term }, count)
          : t('layout.announce.results', { count }, count)
        announce(msg)
      }
    },

    /**
     * Announce loading state
     */
    announceLoading(isLoading: boolean, context?: string) {
      if (isLoading) {
        announce(context ? t('layout.announce.loadingContext', { context }) : t('layout.announce.loading'))
      }
    },

    /**
     * Announce error
     */
    announceError(message: string) {
      announce(message, 'assertive')
    },

    /**
     * Announce success
     */
    announceSuccess(message: string) {
      announce(message, 'polite')
    }
  }
}
