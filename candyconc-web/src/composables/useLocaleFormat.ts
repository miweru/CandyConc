/**
 * Formatting helpers bound to the active interface language.
 *
 * `locale` is reactive. The format functions read the locale when they run,
 * so calling them in a template or computed re-renders on a language switch.
 */
import { computed } from 'vue'
import {
  currentLocale,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatNumber,
  formatPercent,
  formatTime,
  intlLocale,
} from '@/i18n/format'

export function useLocaleFormat() {
  const locale = computed(() => currentLocale())
  const intlTag = computed(() => intlLocale(locale.value))
  return {
    locale,
    intlTag,
    formatNumber,
    formatDecimal,
    formatPercent,
    formatDate,
    formatTime,
    formatDateTime,
  }
}
