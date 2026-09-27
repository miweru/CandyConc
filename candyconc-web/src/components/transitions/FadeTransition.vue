<script setup lang="ts">
/**
 * FadeTransition - Simple fade transition
 */
import { computed } from 'vue'
import { useAnimation } from '@/composables/useAnimation'

interface Props {
  mode?: 'default' | 'out-in' | 'in-out'
  duration?: 'fast' | 'normal' | 'slow'
}

const props = withDefaults(defineProps<Props>(), {
  mode: 'out-in',
  duration: 'normal'
})

const { prefersReducedMotion } = useAnimation()

const durationMs = computed(() => {
  if (prefersReducedMotion.value) return 50
  switch (props.duration) {
    case 'fast': return 150
    case 'slow': return 400
    default: return 250
  }
})
</script>

<template>
  <Transition name="fade" :mode="mode" :duration="durationMs">
    <slot />
  </Transition>
</template>

<style scoped>
.fade-enter-active {
  transition: opacity v-bind('durationMs + "ms"') ease;
}

.fade-leave-active {
  transition: opacity v-bind('durationMs + "ms"') ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
