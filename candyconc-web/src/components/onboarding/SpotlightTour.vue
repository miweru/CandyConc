<script setup lang="ts">
/**
 * SpotlightTour - Guided tour with spotlight effect
 */
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { ChevronLeft, ChevronRight, X } from 'lucide-vue-next'
import { useOnboardingStore } from '@/stores/onboarding'
import Button from '@/components/ui/Button.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const onboardingStore = useOnboardingStore()

const targetRect = ref<DOMRect | null>(null)
const tooltipPosition = ref({ top: 0, left: 0 })
let missingTargetGuard = 0

// Calculate spotlight and tooltip position
function updatePosition() {
  const step = onboardingStore.currentStep
  if (!step) return

  const target = document.querySelector(step.target)
  if (!target) {
    targetRect.value = null
    return
  }

  const rect = target.getBoundingClientRect()
  targetRect.value = rect

  // Calculate tooltip position based on step.position
  const padding = 16
  const tooltipWidth = 320
  const tooltipHeight = 180

  let top = 0
  let left = 0

  switch (step.position) {
    case 'top':
      top = rect.top - tooltipHeight - padding
      left = rect.left + rect.width / 2 - tooltipWidth / 2
      break
    case 'bottom':
      top = rect.bottom + padding
      left = rect.left + rect.width / 2 - tooltipWidth / 2
      break
    case 'left':
      top = rect.top + rect.height / 2 - tooltipHeight / 2
      left = rect.left - tooltipWidth - padding
      break
    case 'right':
      top = rect.top + rect.height / 2 - tooltipHeight / 2
      left = rect.right + padding
      break
  }

  // Keep tooltip in viewport
  left = Math.max(padding, Math.min(left, window.innerWidth - tooltipWidth - padding))
  top = Math.max(padding, Math.min(top, window.innerHeight - tooltipHeight - padding))

  tooltipPosition.value = { top, left }
}

async function updateOrSkipMissingTarget() {
  if (!onboardingStore.isActive) return
  await nextTick()
  const step = onboardingStore.currentStep
  if (!step) {
    onboardingStore.complete()
    return
  }
  if (document.querySelector(step.target)) {
    missingTargetGuard = 0
    updatePosition()
    return
  }
  missingTargetGuard += 1
  if (onboardingStore.isLastStep || missingTargetGuard > onboardingStore.totalSteps) {
    onboardingStore.complete()
    return
  }
  onboardingStore.next()
}

// Watch for step changes
watch(() => onboardingStore.currentStepIndex, () => {
  void updateOrSkipMissingTarget()
})
watch(() => onboardingStore.isActive, () => {
  void updateOrSkipMissingTarget()
})

// Handle resize
onMounted(() => {
  void updateOrSkipMissingTarget()
  window.addEventListener('resize', updatePosition)
  window.addEventListener('scroll', updatePosition)
})

onUnmounted(() => {
  window.removeEventListener('resize', updatePosition)
  window.removeEventListener('scroll', updatePosition)
})

const spotlightStyle = computed(() => {
  if (!targetRect.value) return {}
  const padding = 8
  return {
    top: `${targetRect.value.top - padding}px`,
    left: `${targetRect.value.left - padding}px`,
    width: `${targetRect.value.width + padding * 2}px`,
    height: `${targetRect.value.height + padding * 2}px`,
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="spotlight">
      <div v-if="onboardingStore.isActive" class="spotlight-overlay">
        <!-- SVG Mask for spotlight effect -->
        <svg class="spotlight-mask">
          <defs>
            <mask id="spotlight-mask">
              <rect width="100%" height="100%" fill="white" />
              <rect
                v-if="targetRect"
                :x="targetRect.left - 8"
                :y="targetRect.top - 8"
                :width="targetRect.width + 16"
                :height="targetRect.height + 16"
                rx="8"
                fill="black"
              />
            </mask>
          </defs>
          <rect
            width="100%"
            height="100%"
            fill="rgba(0, 0, 0, 0.75)"
            mask="url(#spotlight-mask)"
          />
        </svg>

        <!-- Spotlight ring animation -->
        <div
          v-if="targetRect"
          class="spotlight-ring"
          :style="spotlightStyle"
        />

        <!-- Tooltip -->
        <div
          class="spotlight-tooltip"
          :style="{
            top: `${tooltipPosition.top}px`,
            left: `${tooltipPosition.left}px`,
          }"
        >
          <!-- Header -->
          <div class="tooltip-header">
            <span class="step-counter">
              {{ onboardingStore.currentStepIndex + 1 }} / {{ onboardingStore.totalSteps }}
            </span>
            <button type="button" class="close-btn" @click="onboardingStore.skip()" :aria-label="t('layout.tour.skipTour')">
              <X class="w-4 h-4" />
            </button>
          </div>

          <!-- Content -->
          <div class="tooltip-content">
            <h3 class="tooltip-title">{{ onboardingStore.currentStep?.title }}</h3>
            <p class="tooltip-desc">{{ onboardingStore.currentStep?.description }}</p>
            <p v-if="onboardingStore.currentStep?.action" class="tooltip-action">
              {{ onboardingStore.currentStep.action }}
            </p>
          </div>

          <!-- Progress bar -->
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${onboardingStore.progress}%` }" />
          </div>

          <!-- Navigation -->
          <div class="tooltip-nav">
            <Button
              v-if="!onboardingStore.isFirstStep"
              variant="ghost"
              size="sm"
              :icon="ChevronLeft"
              @click="onboardingStore.previous()"
            >
              {{ t('layout.tour.back') }}
            </Button>
            <Button
              v-else
              variant="ghost"
              size="sm"
              @click="onboardingStore.skip()"
            >
              {{ t('layout.tour.skip') }}
            </Button>

            <Button
              variant="primary"
              size="sm"
              :icon="onboardingStore.isLastStep ? undefined : ChevronRight"
              icon-position="right"
              @click="onboardingStore.next()"
            >
              {{ onboardingStore.isLastStep ? t('layout.tour.done') : t('layout.tour.next') }}
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
@reference "../../style.css";

.spotlight-overlay {
  @apply fixed inset-0;
  z-index: 9999;
  /* Visual-only backdrop: do not intercept pointer events across the whole
     header/tabs. Only the tooltip card below re-enables interaction so its
     navigation/skip controls stay clickable while the rest stays usable. */
  pointer-events: none;
}

.spotlight-mask {
  @apply absolute inset-0 w-full h-full;
  pointer-events: none;
}

.spotlight-ring {
  @apply absolute rounded-lg;
  @apply border-2 border-primary-400;
  @apply pointer-events-none;
  animation: pulse-ring 2s ease-in-out infinite;
}

@keyframes pulse-ring {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(99, 102, 241, 0);
  }
}

.spotlight-tooltip {
  @apply absolute w-80;
  @apply bg-white dark:bg-neutral-800;
  @apply rounded-2xl shadow-2xl;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply overflow-hidden;
  /* Keep the tour card interactive even though the backdrop ignores clicks. */
  pointer-events: auto;
}

.tooltip-header {
  @apply flex items-center justify-between;
  @apply px-4 py-3;
  @apply bg-neutral-50 dark:bg-neutral-900;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.step-counter {
  @apply text-sm font-medium text-neutral-500 dark:text-neutral-400;
}

.close-btn {
  @apply p-1 rounded;
  @apply text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-200;
  @apply transition-colors;
}

.tooltip-content {
  @apply px-4 py-4;
}

.tooltip-title {
  @apply text-lg font-semibold;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply mb-2;
}

.tooltip-desc {
  @apply text-sm text-neutral-600 dark:text-neutral-400;
  @apply leading-relaxed;
}

.tooltip-action {
  @apply mt-3 px-3 py-2 rounded-lg;
  @apply bg-primary-50 dark:bg-primary-900/30;
  @apply text-sm font-medium text-primary-700 dark:text-primary-300;
}

.progress-bar {
  @apply h-1 bg-neutral-200 dark:bg-neutral-700;
}

.progress-fill {
  @apply h-full bg-primary-500;
  transition: width 0.3s ease;
}

.tooltip-nav {
  @apply flex items-center justify-between;
  @apply px-4 py-3;
  @apply bg-neutral-50 dark:bg-neutral-900;
}

/* Transitions */
.spotlight-enter-active {
  @apply transition-opacity duration-300;
}

.spotlight-leave-active {
  @apply transition-opacity duration-200;
}

.spotlight-enter-from,
.spotlight-leave-to {
  @apply opacity-0;
}
</style>
