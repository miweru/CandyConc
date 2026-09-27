<script setup lang="ts">
/**
 * ClarifyModal - Structured clarification questions from Copilot
 *
 * Renders options with sources (snapshot/user/assistant), free input,
 * and timeout countdown if blocking.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { HelpCircle, Clock, Check, MessageSquare, Database, Bot, User } from 'lucide-vue-next'
import type { ClarifyV1, ClarifyOptionV1 } from '@/types/copilot-protocol'

interface Props {
  question: ClarifyV1
  timeoutMs?: number
}

const props = withDefaults(defineProps<Props>(), {
  timeoutMs: 60000
})

const { t } = useI18n()

const emit = defineEmits<{
  answer: [optionId: string, value: unknown]
  'free-input': [text: string]
  timeout: []
}>()

const selectedOption = ref<string | null>(null)
const freeInputText = ref('')
const showFreeInput = ref(false)

// Timeout countdown
const remainingMs = ref(props.question.blocking ? props.timeoutMs : 0)
let countdownInterval: ReturnType<typeof setInterval> | null = null

const remainingSeconds = computed(() => Math.ceil(remainingMs.value / 1000))
const timeoutProgress = computed(() =>
  props.question.blocking ? (remainingMs.value / props.timeoutMs) * 100 : 100
)

onMounted(() => {
  if (props.question.blocking) {
    countdownInterval = setInterval(() => {
      remainingMs.value = Math.max(0, remainingMs.value - 100)
      if (remainingMs.value <= 0) {
        if (countdownInterval) clearInterval(countdownInterval)
        emit('timeout')
      }
    }, 100)
  }
})

onUnmounted(() => {
  if (countdownInterval) clearInterval(countdownInterval)
})

function getSourceIcon(source?: ClarifyOptionV1['source']) {
  switch (source) {
    case 'snapshot': return Database
    case 'assistant': return Bot
    case 'user': return User
    default: return null
  }
}

function getSourceLabel(source?: ClarifyOptionV1['source']) {
  switch (source) {
    case 'snapshot': return t('copilot.clarification.sourceSnapshot')
    case 'assistant': return t('copilot.clarification.sourceAssistant')
    case 'user': return t('copilot.clarification.sourceUser')
    default: return ''
  }
}

function selectOption(option: ClarifyOptionV1) {
  selectedOption.value = option.id
  showFreeInput.value = false
}

function confirmSelection() {
  if (selectedOption.value) {
    const option = props.question.options.find(o => o.id === selectedOption.value)
    if (option) {
      emit('answer', option.id, option.value)
    }
  } else if (showFreeInput.value && freeInputText.value.trim()) {
    emit('free-input', freeInputText.value.trim())
  }
}

function toggleFreeInput() {
  showFreeInput.value = !showFreeInput.value
  if (showFreeInput.value) {
    selectedOption.value = null
  }
}

const canSubmit = computed(() =>
  selectedOption.value !== null || (showFreeInput.value && freeInputText.value.trim().length > 0)
)

const defaultOption = computed(() =>
  props.question.options.find(o => o.isDefault)
)
</script>

<template>
  <div class="clarify-modal" :class="{ blocking: question.blocking }">
    <!-- Header -->
    <div class="clarify-header">
      <div class="header-icon">
        <HelpCircle class="w-5 h-5" />
      </div>
      <div class="header-content">
        <h3 class="header-title">{{ t('copilot.clarification.title') }}</h3>
        <p v-if="question.blocking" class="header-blocking">
          {{ t('copilot.clarification.answerRequired') }}
        </p>
      </div>
      <div v-if="question.blocking && remainingMs > 0" class="timeout-indicator">
        <Clock class="w-4 h-4" />
        <span>{{ remainingSeconds }}s</span>
      </div>
    </div>

    <!-- Timeout Progress Bar -->
    <div v-if="question.blocking" class="timeout-bar">
      <div
        class="timeout-progress"
        :style="{ width: `${timeoutProgress}%` }"
        :class="{ warning: remainingSeconds <= 10 }"
      />
    </div>

    <!-- Question -->
    <div class="clarify-prompt">
      {{ question.prompt }}
    </div>

    <!-- Rationale -->
    <p v-if="question.rationale" class="clarify-rationale">
      {{ question.rationale }}
    </p>

    <!-- Options -->
    <div class="clarify-options">
      <button
        v-for="option in question.options"
        :key="option.id"
        class="option-button"
        :class="{
          selected: selectedOption === option.id,
          default: option.isDefault
        }"
        @click="selectOption(option)"
      >
        <div class="option-content">
          <span class="option-label">{{ option.label }}</span>
          <span v-if="option.source" class="option-source">
            <component :is="getSourceIcon(option.source)" class="w-3 h-3" />
            {{ getSourceLabel(option.source) }}
          </span>
        </div>
        <Check v-if="selectedOption === option.id" class="w-4 h-4 text-copilot-primary" />
      </button>
    </div>

    <!-- Free Input Toggle -->
    <div v-if="question.freeInput" class="free-input-section">
      <button
        class="free-input-toggle"
        :class="{ active: showFreeInput }"
        @click="toggleFreeInput"
      >
        <MessageSquare class="w-4 h-4" />
        {{ question.freeInput.label }}
      </button>

      <div v-if="showFreeInput" class="free-input-wrapper">
        <textarea
          v-model="freeInputText"
          class="free-input-textarea"
          :placeholder="question.freeInput.placeholder || t('copilot.clarification.freeInputPlaceholder')"
          rows="2"
        />
      </div>
    </div>

    <!-- Actions -->
    <div class="clarify-actions">
      <button
        class="btn-confirm"
        :disabled="!canSubmit"
        @click="confirmSelection"
      >
        <Check class="w-4 h-4" />
        {{ t('copilot.clarification.confirm') }}
      </button>
      <span v-if="defaultOption && !selectedOption && !showFreeInput" class="default-hint">
        {{ t('copilot.clarification.defaultHint', { label: defaultOption.label }) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.clarify-modal {
  @apply rounded-xl overflow-hidden;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply shadow-lg;
}

.clarify-modal.blocking {
  @apply border-amber-300 dark:border-amber-600;
}

.clarify-header {
  @apply flex items-center gap-3 p-4 pb-3;
  @apply bg-gradient-to-r from-copilot-bg/50 to-transparent;
}

.header-icon {
  @apply p-2 rounded-lg;
  @apply bg-copilot-primary/10 text-copilot-primary;
}

.header-content {
  @apply flex-1;
}

.header-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-200;
}

.header-blocking {
  @apply text-xs text-amber-600 dark:text-amber-400 font-medium;
}

.timeout-indicator {
  @apply flex items-center gap-1;
  @apply text-sm font-mono text-neutral-500;
}

.timeout-bar {
  @apply h-1 bg-neutral-200 dark:bg-neutral-700;
}

.timeout-progress {
  @apply h-full bg-copilot-primary;
  @apply transition-all duration-100;
}

.timeout-progress.warning {
  @apply bg-amber-500;
}

.clarify-prompt {
  @apply px-4 py-3;
  @apply text-sm text-neutral-800 dark:text-neutral-200;
  @apply font-medium;
}

.clarify-rationale {
  @apply px-4 pb-3 -mt-1;
  @apply text-xs text-neutral-500 dark:text-neutral-400 italic;
}

.clarify-options {
  @apply px-4 pb-3 space-y-2;
}

.option-button {
  @apply w-full flex items-center justify-between;
  @apply px-3 py-2.5 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-700/50;
  @apply border border-transparent;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors;
  @apply text-left;
}

.option-button.selected {
  @apply bg-copilot-primary/10 border-copilot-primary/30;
}

.option-button.default:not(.selected) {
  @apply border-neutral-300 dark:border-neutral-600;
}

.option-content {
  @apply flex flex-col gap-0.5;
}

.option-label {
  @apply text-sm text-neutral-800 dark:text-neutral-200;
}

.option-source {
  @apply flex items-center gap-1;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.free-input-section {
  @apply px-4 pb-3;
}

.free-input-toggle {
  @apply flex items-center gap-2;
  @apply px-3 py-2 rounded-lg;
  @apply text-sm text-neutral-600 dark:text-neutral-400;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.free-input-toggle.active {
  @apply text-copilot-primary;
}

.free-input-wrapper {
  @apply mt-2;
}

.free-input-textarea {
  @apply w-full px-3 py-2 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-700;
  @apply border border-neutral-200 dark:border-neutral-600;
  @apply text-sm text-neutral-800 dark:text-neutral-200;
  @apply placeholder:text-neutral-400;
  @apply focus:outline-none focus:ring-2 focus:ring-copilot-primary/30;
  @apply resize-none;
}

.clarify-actions {
  @apply flex items-center justify-between gap-3;
  @apply px-4 py-3;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}

.btn-confirm {
  @apply inline-flex items-center gap-2;
  @apply px-4 py-2 rounded-lg;
  @apply bg-copilot-primary text-white;
  @apply hover:bg-copilot-primary/90;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
  @apply text-sm font-medium;
}

.default-hint {
  @apply text-xs text-neutral-500;
}
</style>
