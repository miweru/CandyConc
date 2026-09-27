<script setup lang="ts">
/**
 * AutonomySlider - Vier ehrliche Autonomiestufen
 *
 * Die Stufen bilden die reale Backend-Approval-Matrix ab; die Texte kommen
 * ausschließlich aus stores/copilot.ts (AUTONOMY_STEPS / autonomyDescription).
 */
import { computed } from 'vue'
import { useCopilotStore } from '@/stores'
import { AUTONOMY_STEPS } from '@/stores/copilot'
import { Zap } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const copilotStore = useCopilotStore()

const step = computed({
  get: () => copilotStore.autonomyStep.step,
  set: (val: number) => copilotStore.setAutonomyStep(val)
})

const stepColor = computed(() => {
  switch (copilotStore.autonomyStep.step) {
    case 1: return 'bg-neutral-400'
    case 2: return 'bg-primary-500'
    case 3: return 'bg-copilot-primary'
    default: return 'bg-copilot-thinking'
  }
})

const firstStepLabel = computed(() => AUTONOMY_STEPS[0]!.label)
const lastStepLabel = computed(() => AUTONOMY_STEPS[AUTONOMY_STEPS.length - 1]!.label)
</script>

<template>
  <div class="autonomy-slider">
    <div class="slider-header">
      <div class="flex items-center gap-2">
        <Zap class="w-4 h-4 text-copilot-primary" />
        <span class="text-sm font-medium">{{ t('copilot.autonomy.title') }}</span>
      </div>
      <span class="level-badge" :class="stepColor">
        {{ t('copilot.autonomy.level', { step: copilotStore.autonomyStep.step, label: copilotStore.autonomyStep.label }) }}
      </span>
    </div>

    <input
      v-model.number="step"
      type="range"
      min="1"
      max="4"
      step="1"
      class="slider-input"
      :aria-label="t('copilot.autonomy.sliderAria')"
    />

    <div class="slider-labels">
      <span>{{ firstStepLabel }}</span>
      <span>{{ lastStepLabel }}</span>
    </div>

    <p class="step-description">
      {{ copilotStore.autonomyDescription }}
    </p>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.autonomy-slider {
  @apply space-y-2;
}

.slider-header {
  @apply flex items-center justify-between;
}

.level-badge {
  @apply px-2 py-0.5 text-xs rounded-full text-white;
}

.slider-input {
  @apply w-full h-2 rounded-full appearance-none cursor-pointer;
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.slider-input::-webkit-slider-thumb {
  @apply appearance-none w-4 h-4 rounded-full;
  @apply bg-copilot-primary;
  @apply shadow-md;
  @apply hover:scale-110;
  @apply transition-transform;
}

.slider-input::-moz-range-thumb {
  @apply w-4 h-4 rounded-full border-0;
  @apply bg-copilot-primary;
}

.slider-labels {
  @apply flex justify-between text-xs text-neutral-500;
}

.step-description {
  @apply text-xs text-neutral-600 dark:text-neutral-400;
}
</style>
