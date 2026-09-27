<script setup lang="ts">
/**
 * CopilotTrigger - button that opens the copilot.
 *
 * It sits at the left end of the page footer, next to the status bar, so it
 * never covers the content of a view (AppShell.vue).
 */
import { computed } from 'vue'
import { useCopilot, useOnlineStatus } from '@/composables'
import { Sparkles, WifiOff } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
})

const { open, isThinking } = useCopilot()
const { copilotAvailable } = useOnlineStatus()

const isDisabled = computed(() => props.disabled || !copilotAvailable.value)

function handleClick() {
  if (!isDisabled.value) {
    open('floating')
  }
}
</script>

<template>
  <button
    class="copilot-trigger"
    :class="{
      'is-thinking': isThinking,
      'is-disabled': isDisabled
    }"
    :disabled="isDisabled"
    @click="handleClick"
    data-onboarding="copilot"
    :aria-label="isDisabled ? t('copilot.trigger.unavailable') : t('copilot.trigger.open')"
    :title="isDisabled ? t('copilot.trigger.unavailableTitle') : t('copilot.trigger.open')"
  >
    <WifiOff v-if="isDisabled && !copilotAvailable" class="w-4 h-4" />
    <Sparkles v-else class="w-4 h-4" />

    <!-- Thinking indicator -->
    <span v-if="isThinking && !isDisabled" class="thinking-dot" />
  </button>
</template>

<style scoped>
@reference "../../style.css";

.copilot-trigger {
  @apply relative w-8 h-8 rounded-full shrink-0;
  @apply flex items-center justify-center;
  @apply bg-copilot-primary text-white;
  @apply shadow-sm hover:shadow-md;
  @apply transition-all duration-200;
  @apply hover:scale-105 active:scale-95;
}

.copilot-trigger:hover:not(:disabled) {
  box-shadow: var(--shadow-copilot);
}

.copilot-trigger.is-thinking {
  @apply animate-pulse;
}

.copilot-trigger.is-disabled {
  @apply bg-neutral-400 dark:bg-neutral-600;
  @apply cursor-not-allowed;
  @apply hover:scale-100 active:scale-100;
  @apply shadow-none;
}

.thinking-dot {
  @apply absolute top-0 right-0;
  @apply w-3 h-3 rounded-full;
  @apply bg-copilot-thinking;
  @apply border-2 border-white;
  animation: thinking-pulse 1s ease-in-out infinite;
}

@keyframes thinking-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(0.9); }
}
</style>
