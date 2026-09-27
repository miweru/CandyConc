<script setup lang="ts">
/**
 * Skeleton - Loading placeholder component with shimmer animation
 */
import { computed } from 'vue'
import { useAnimation } from '@/composables/useAnimation'

interface Props {
  width?: string
  height?: string
  variant?: 'text' | 'circle' | 'rect' | 'card'
  rounded?: 'none' | 'sm' | 'md' | 'lg' | 'xl' | 'full'
  lines?: number
  animate?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '1rem',
  variant: 'rect',
  rounded: 'md',
  lines: 1,
  animate: true
})

const { prefersReducedMotion } = useAnimation()

const shouldAnimate = computed(() => props.animate && !prefersReducedMotion.value)

const skeletonStyle = computed(() => {
  if (props.variant === 'circle') {
    return {
      width: props.width,
      height: props.width, // Circle uses width for both
    }
  }
  if (props.variant === 'text') {
    return {
      width: props.width,
      height: '0.875rem',
    }
  }
  return {
    width: props.width,
    height: props.height,
  }
})

const roundedClass = computed(() => {
  if (props.variant === 'circle') return 'rounded-full'
  return `rounded-${props.rounded}`
})
</script>

<template>
  <div v-if="lines > 1" class="skeleton-lines">
    <div
      v-for="i in lines"
      :key="i"
      class="skeleton"
      :class="[
        roundedClass,
        variant,
        { 'animate-shimmer': shouldAnimate }
      ]"
      :style="{
        ...skeletonStyle,
        width: i === lines ? '70%' : skeletonStyle.width
      }"
    />
  </div>
  <div
    v-else
    class="skeleton"
    :class="[
      roundedClass,
      variant,
      { 'animate-shimmer': shouldAnimate }
    ]"
    :style="skeletonStyle"
  >
    <slot />
  </div>
</template>

<style scoped>
@reference "../../style.css";

.skeleton {
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.skeleton.text {
  @apply h-4 rounded-sm;
}

.skeleton.circle {
  @apply rounded-full aspect-square;
}

.skeleton.card {
  @apply rounded-xl p-4;
}

.skeleton-lines {
  @apply flex flex-col gap-2;
}

/* Shimmer Animation */
.animate-shimmer {
  background: linear-gradient(
    90deg,
    var(--color-neutral-200) 25%,
    var(--color-neutral-100) 50%,
    var(--color-neutral-200) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

.dark .animate-shimmer {
  background: linear-gradient(
    90deg,
    var(--color-neutral-700) 25%,
    var(--color-neutral-600) 50%,
    var(--color-neutral-700) 75%
  );
  background-size: 200% 100%;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
