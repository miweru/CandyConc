/**
 * useAnimation - Animation utilities with prefers-reduced-motion support
 */

import { computed, ref, onMounted, onUnmounted } from 'vue'

export function useAnimation() {
  const mediaQuery = ref<MediaQueryList | null>(null)
  const prefersReducedMotionValue = ref(false)

  // Update on media query change
  function updateMotionPreference() {
    prefersReducedMotionValue.value = mediaQuery.value?.matches ?? false
  }

  onMounted(() => {
    mediaQuery.value = window.matchMedia('(prefers-reduced-motion: reduce)')
    updateMotionPreference()
    mediaQuery.value.addEventListener('change', updateMotionPreference)
  })

  onUnmounted(() => {
    mediaQuery.value?.removeEventListener('change', updateMotionPreference)
  })

  const prefersReducedMotion = computed(() => prefersReducedMotionValue.value)

  // Duration presets (0 when reduced motion is preferred)
  const duration = computed(() => ({
    instant: 0,
    fast: prefersReducedMotion.value ? 0 : 150,
    normal: prefersReducedMotion.value ? 0 : 300,
    slow: prefersReducedMotion.value ? 0 : 500,
    slower: prefersReducedMotion.value ? 0 : 700,
  }))

  // Easing presets
  const easing = {
    linear: 'linear',
    easeIn: 'cubic-bezier(0.4, 0, 1, 1)',
    easeOut: 'cubic-bezier(0, 0, 0.2, 1)',
    easeInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
    smooth: 'cubic-bezier(0.4, 0, 0.2, 1)',
    bounce: 'cubic-bezier(0.68, -0.55, 0.265, 1.55)',
    spring: 'cubic-bezier(0.175, 0.885, 0.32, 1.275)',
    snappy: 'cubic-bezier(0.2, 0.9, 0.3, 1)',
  }

  // Get CSS transition string
  function getTransition(
    property: string | string[] = 'all',
    speed: keyof typeof duration.value = 'normal',
    easingName: keyof typeof easing = 'smooth'
  ): string {
    const properties = Array.isArray(property) ? property : [property]
    const dur = duration.value[speed]
    const ease = easing[easingName]
    return properties.map(p => `${p} ${dur}ms ${ease}`).join(', ')
  }

  // Stagger delay for list items
  function getStaggerDelay(index: number, baseDelay = 50): number {
    if (prefersReducedMotion.value) return 0
    return index * baseDelay
  }

  return {
    prefersReducedMotion,
    duration,
    easing,
    getTransition,
    getStaggerDelay
  }
}
