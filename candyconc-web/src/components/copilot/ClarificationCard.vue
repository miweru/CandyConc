<script setup lang="ts">
/**
 * ClarificationCard - Structured question for user clarification
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ClarificationQuestion } from '@/stores'
import { HelpCircle, Clock } from 'lucide-vue-next'

interface Props {
  question: ClarificationQuestion
}

const props = defineProps<Props>()
const { t } = useI18n()
const emit = defineEmits<{
  answer: [optionId: string]
}>()

// Timeout countdown
const remainingTime = ref(0)
let countdownInterval: ReturnType<typeof setInterval> | null = null

const remainingSeconds = computed(() => Math.ceil(remainingTime.value / 1000))

const remainingPercent = computed(() => {
  if (!props.question.timeout || !props.question.expiresAt) return 100
  const total = props.question.timeout
  return Math.max(0, Math.min(100, (remainingTime.value / total) * 100))
})

const showTimeout = computed(() =>
  props.question.expiresAt && remainingTime.value > 0 && !props.question.answered
)

function updateRemainingTime() {
  if (props.question.expiresAt) {
    remainingTime.value = Math.max(0, props.question.expiresAt - Date.now())
    if (remainingTime.value <= 0 && countdownInterval) {
      clearInterval(countdownInterval)
      countdownInterval = null
    }
  }
}

onMounted(() => {
  updateRemainingTime()
  countdownInterval = setInterval(updateRemainingTime, 100)
})

onUnmounted(() => {
  if (countdownInterval) {
    clearInterval(countdownInterval)
    countdownInterval = null
  }
})

function selectOption(optionId: string) {
  emit('answer', optionId)
}
</script>

<template>
  <div class="clarification-card">
    <!-- Header -->
    <div class="card-header">
      <HelpCircle class="w-5 h-5 text-copilot-primary" />
      <span class="font-medium">{{ t('copilot.clarification.title') }}</span>

      <!-- Timeout indicator -->
      <div v-if="showTimeout" class="timeout-indicator">
        <Clock class="w-3.5 h-3.5" />
        <span>{{ remainingSeconds }}s</span>
      </div>
    </div>

    <!-- Timeout progress bar -->
    <div v-if="showTimeout" class="timeout-bar">
      <div
        class="timeout-progress"
        :style="{ width: `${remainingPercent}%` }"
        :class="{ 'urgent': remainingPercent < 25 }"
      />
    </div>

    <!-- Explanation -->
    <p class="card-explanation">
      {{ question.explanation }}
    </p>

    <!-- Options -->
    <div class="card-options">
      <button
        v-for="option in question.options"
        :key="option.id"
        class="option-btn"
        :class="{ 'is-fallback': option.id === question.fallbackOptionId }"
        @click="selectOption(option.id)"
      >
        {{ option.label }}
        <span v-if="option.id === question.fallbackOptionId" class="fallback-badge">
          {{ t('copilot.clarification.default') }}
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.clarification-card {
  @apply p-4 rounded-xl;
  @apply bg-copilot-bg;
  @apply border border-copilot-primary/30;
}

.card-header {
  @apply flex items-center gap-2 mb-2;
}

.timeout-indicator {
  @apply ml-auto flex items-center gap-1;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.timeout-bar {
  @apply h-1 mb-3 rounded-full overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.timeout-progress {
  @apply h-full rounded-full;
  @apply bg-copilot-primary;
  @apply transition-all duration-100 ease-linear;
}

.timeout-progress.urgent {
  @apply bg-copilot-thinking;
  animation: pulse-urgent 0.5s ease-in-out infinite;
}

@keyframes pulse-urgent {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.card-explanation {
  @apply text-sm text-neutral-700 dark:text-neutral-300;
  @apply mb-4;
}

.card-options {
  @apply flex flex-col gap-2;
}

.option-btn {
  @apply w-full px-4 py-2.5 text-left text-sm rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply hover:border-copilot-primary hover:bg-copilot-bg;
  @apply transition-colors;
  @apply flex items-center justify-between;
}

.option-btn:hover {
  @apply text-copilot-primary;
}

.option-btn.is-fallback {
  @apply border-dashed;
}

.fallback-badge {
  @apply text-xs px-1.5 py-0.5 rounded;
  @apply bg-neutral-100 dark:bg-neutral-700;
  @apply text-neutral-500 dark:text-neutral-400;
}
</style>
