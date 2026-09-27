<script setup lang="ts">
/**
 * PlanDisplay - Renders a structured Copilot plan
 *
 * Shows what the backend actually produces: goal, steps with their
 * expected output, and per-step execution status.
 */
import {
  Target, ListChecks,
  CheckCircle2, Circle, ChevronRight, X
} from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type { PlanV1, PlanStepV1 } from '@/types/copilot-protocol'

interface Props {
  plan: PlanV1
  currentStepId?: string
  completedStepIds?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  completedStepIds: () => []
})

const { t } = useI18n()

const emit = defineEmits<{
  'execute-step': [step: PlanStepV1]
  'skip-step': [stepId: string]
  'dismiss': []
}>()

function getStepStatus(step: PlanStepV1): 'completed' | 'current' | 'pending' {
  if (props.completedStepIds.includes(step.stepId)) return 'completed'
  if (step.stepId === props.currentStepId) return 'current'
  return 'pending'
}
</script>

<template>
  <div class="plan-display">
    <!-- Header -->
    <div class="plan-header">
      <div class="plan-icon">
        <Target class="w-5 h-5" />
      </div>
      <div class="plan-meta">
        <h3 class="plan-title">{{ t('copilot.plan.title') }}</h3>
        <div class="plan-contract">
          {{ t('copilot.plan.contract') }}
        </div>
      </div>
      <button
        class="btn-dismiss"
        @click="emit('dismiss')"
        :title="t('copilot.plan.close')"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- Goal -->
    <div class="plan-goal">
      <span class="goal-label">{{ t('copilot.plan.goal') }}</span>
      <span class="goal-text">{{ plan.goal }}</span>
    </div>

    <!-- Steps -->
    <div class="plan-steps">
      <h4 class="section-title">
        <ListChecks class="w-4 h-4" />
        {{ t('copilot.plan.steps') }}
      </h4>
      <ol class="steps-list">
        <li
          v-for="(step, idx) in plan.steps"
          :key="step.stepId"
          class="step-item"
          :class="getStepStatus(step)"
        >
          <div class="step-indicator">
            <CheckCircle2 v-if="getStepStatus(step) === 'completed'" class="w-5 h-5 text-green-500" />
            <div v-else-if="getStepStatus(step) === 'current'" class="current-indicator">
              <Circle class="w-5 h-5 text-copilot-primary animate-pulse" />
            </div>
            <span v-else class="step-number">{{ idx + 1 }}</span>
          </div>

          <div class="step-content">
            <div class="step-header">
              <span class="step-title">{{ step.title }}</span>
            </div>

            <p v-if="step.expectedOutput" class="step-expected">
              <ChevronRight class="w-3 h-3 inline" />
              {{ step.expectedOutput }}
            </p>

            <!-- Action Preview (if step has action) -->
            <div v-if="step.action && getStepStatus(step) === 'current'" class="step-action">
              <button
                class="btn-execute"
                @click="emit('execute-step', step)"
              >
                {{ t('copilot.plan.run') }}
              </button>
              <button
                class="btn-skip"
                @click="emit('skip-step', step.stepId)"
              >
                {{ t('copilot.plan.skip') }}
              </button>
            </div>
          </div>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.plan-display {
  @apply rounded-xl p-4;
  @apply bg-gradient-to-br from-copilot-bg/50 to-copilot-bg;
  @apply border border-copilot-primary/20;
}

.plan-header {
  @apply flex items-start gap-3 mb-3;
}

.btn-dismiss {
  @apply p-1.5 rounded-md;
  @apply text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300;
  @apply hover:bg-neutral-200/50 dark:hover:bg-neutral-700/50;
  @apply transition-colors;
}

.plan-icon {
  @apply p-2 rounded-lg;
  @apply bg-copilot-primary/10 text-copilot-primary;
}

.plan-meta {
  @apply flex-1;
}

.plan-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-200;
}

.plan-contract {
  @apply mt-0.5 text-[0.68rem] font-medium text-amber-700 dark:text-amber-300;
}

.plan-goal {
  @apply mb-3 p-2 rounded-lg;
  @apply bg-white/50 dark:bg-neutral-800/50;
}

.goal-label {
  @apply text-xs font-medium text-neutral-500 mr-1;
}

.goal-text {
  @apply text-sm text-neutral-800 dark:text-neutral-200;
}

.section-title {
  @apply flex items-center gap-1.5 mb-2;
  @apply text-xs font-semibold text-neutral-600 dark:text-neutral-400 uppercase tracking-wide;
}

.plan-steps {
  @apply mb-1;
}

.steps-list {
  @apply space-y-3;
}

.step-item {
  @apply flex gap-3;
}

.step-indicator {
  @apply flex-shrink-0 w-6 h-6 flex items-center justify-center;
}

.step-number {
  @apply w-5 h-5 rounded-full;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-400;
  @apply flex items-center justify-center;
}

.step-item.completed .step-number {
  @apply bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400;
}

.step-item.current .step-number {
  @apply bg-copilot-primary/20 text-copilot-primary;
}

.step-content {
  @apply flex-1 min-w-0;
}

.step-header {
  @apply flex items-start justify-between gap-2;
}

.step-title {
  @apply text-sm font-medium text-neutral-800 dark:text-neutral-200;
}

.step-item.completed .step-title {
  @apply text-neutral-500 line-through;
}

.step-expected {
  @apply mt-1 text-xs text-neutral-500 dark:text-neutral-400;
}

.step-action {
  @apply flex gap-2 mt-2;
}

.btn-execute {
  @apply px-3 py-1 text-xs rounded-md;
  @apply bg-copilot-primary text-white;
  @apply hover:bg-copilot-primary/90;
  @apply transition-colors;
}

.btn-skip {
  @apply px-3 py-1 text-xs rounded-md;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply hover:bg-neutral-300 dark:hover:bg-neutral-600;
  @apply transition-colors;
}
</style>
