<script setup lang="ts">
/**
 * LoadingSpinner - Various loading indicator styles
 */
import { computed } from 'vue'
import { useAnimation } from '@/composables/useAnimation'

interface Props {
  variant?: 'spinner' | 'dots' | 'pulse' | 'progress'
  size?: 'xs' | 'sm' | 'md' | 'lg'
  label?: string
  progress?: number
  color?: 'primary' | 'neutral' | 'white'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'spinner',
  size: 'md',
  progress: 0,
  color: 'primary'
})

const { prefersReducedMotion } = useAnimation()

const sizeClasses = computed(() => {
  switch (props.size) {
    case 'xs': return 'w-4 h-4'
    case 'sm': return 'w-5 h-5'
    case 'lg': return 'w-8 h-8'
    default: return 'w-6 h-6'
  }
})

const colorClasses = computed(() => {
  switch (props.color) {
    case 'neutral': return 'text-neutral-500'
    case 'white': return 'text-white'
    default: return 'text-primary-500'
  }
})
</script>

<template>
  <div class="loading-container" :class="[colorClasses]">
    <!-- Spinner -->
    <div v-if="variant === 'spinner'" class="spinner" :class="[sizeClasses]">
      <svg viewBox="0 0 24 24" fill="none" :class="{ 'animate-spin': !prefersReducedMotion }">
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          stroke-width="3"
          stroke-opacity="0.25"
        />
        <path
          d="M12 2a10 10 0 0 1 10 10"
          stroke="currentColor"
          stroke-width="3"
          stroke-linecap="round"
        />
      </svg>
    </div>

    <!-- Dots -->
    <div v-else-if="variant === 'dots'" class="dots">
      <span
        v-for="i in 3"
        :key="i"
        class="dot"
        :class="{ 'animate-bounce-dot': !prefersReducedMotion }"
        :style="{ animationDelay: `${(i - 1) * 0.15}s` }"
      />
    </div>

    <!-- Pulse -->
    <div v-else-if="variant === 'pulse'" class="pulse-container" :class="[sizeClasses]">
      <div class="pulse-ring" :class="{ 'animate-pulse-ring': !prefersReducedMotion }" />
      <div class="pulse-core" />
    </div>

    <!-- Progress Bar -->
    <div v-else-if="variant === 'progress'" class="progress-bar">
      <div class="progress-track">
        <div
          class="progress-fill"
          :style="{ width: `${Math.min(100, Math.max(0, progress))}%` }"
        />
      </div>
      <span v-if="label" class="progress-label">{{ Math.round(progress) }}%</span>
    </div>

    <!-- Label -->
    <span v-if="label && variant !== 'progress'" class="loading-label">
      {{ label }}
    </span>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.loading-container {
  @apply inline-flex items-center gap-2;
}

/* Spinner */
.spinner {
  @apply relative;
}

.spinner svg {
  @apply w-full h-full;
}

/* Dots */
.dots {
  @apply flex items-center gap-1;
}

.dot {
  @apply w-2 h-2 rounded-full bg-current;
}

.animate-bounce-dot {
  animation: bounceDot 0.6s ease-in-out infinite;
}

@keyframes bounceDot {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-6px); }
}

/* Pulse */
.pulse-container {
  @apply relative flex items-center justify-center;
}

.pulse-ring {
  @apply absolute inset-0 rounded-full;
  border: 2px solid currentColor;
}

.animate-pulse-ring {
  animation: pulseRing 1.5s ease-out infinite;
}

@keyframes pulseRing {
  0% { transform: scale(0.8); opacity: 1; }
  100% { transform: scale(1.5); opacity: 0; }
}

.pulse-core {
  @apply w-1/2 h-1/2 rounded-full bg-current;
}

/* Progress Bar */
.progress-bar {
  @apply flex items-center gap-3 w-full;
}

.progress-track {
  @apply flex-1 h-2 rounded-full overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.progress-fill {
  @apply h-full rounded-full;
  @apply bg-gradient-to-r from-primary-400 to-primary-600;
  transition: width 0.3s ease;
}

.progress-label {
  @apply text-sm font-medium text-neutral-600 dark:text-neutral-400;
  @apply min-w-[3rem] text-right;
}

/* Label */
.loading-label {
  @apply text-sm text-neutral-600 dark:text-neutral-400;
}
</style>
