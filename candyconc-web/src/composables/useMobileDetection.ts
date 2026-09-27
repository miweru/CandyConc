/**
 * useMobileDetection - Reactive mobile breakpoint detection
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'

const MOBILE_BREAKPOINT = 768

// Shared state for performance (single resize listener)
const windowWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1024)
let listenerCount = 0

function handleResize() {
  windowWidth.value = window.innerWidth
}

export function useMobileDetection() {
  onMounted(() => {
    if (listenerCount === 0) {
      window.addEventListener('resize', handleResize)
    }
    listenerCount++
    // Update on mount in case window size changed
    windowWidth.value = window.innerWidth
  })

  onUnmounted(() => {
    listenerCount--
    if (listenerCount === 0) {
      window.removeEventListener('resize', handleResize)
    }
  })

  const isMobile = computed(() => windowWidth.value < MOBILE_BREAKPOINT)
  const isTablet = computed(() => windowWidth.value >= MOBILE_BREAKPOINT && windowWidth.value < 1024)
  const isDesktop = computed(() => windowWidth.value >= 1024)

  return {
    windowWidth,
    isMobile,
    isTablet,
    isDesktop,
    MOBILE_BREAKPOINT
  }
}
