<script setup lang="ts">
import { computed } from 'vue'
import { XCircle, Loader2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const props = withDefaults(defineProps<{
  status: string
  progress?: number
  message?: string
  canCancel?: boolean
}>(), {
  progress: 0,
  message: '',
  canCancel: false,
})

const emit = defineEmits<{
  (e: 'cancel'): void
}>()

const { t } = useI18n()

const isRunning = computed(() => props.status === 'running' || props.status === 'queued')
const statusLabel = computed(() => {
  if (props.status === 'queued') return t('analysis.jobPill.queued')
  if (props.status === 'running') return t('analysis.jobPill.running')
  if (props.status === 'cancelled') return t('analysis.jobPill.cancelled')
  if (props.status === 'error') return t('analysis.jobPill.error')
  return props.status
})
</script>

<template>
  <div class="job-pill" :class="{ 'job-pill--running': isRunning }">
    <div class="job-header">
      <div class="job-status">
        <Loader2 v-if="isRunning" class="w-3.5 h-3.5 animate-spin" />
        <span class="job-label">{{ statusLabel }}</span>
      </div>
      <button
        v-if="canCancel && isRunning"
        class="job-cancel"
        type="button"
        :title="t('analysis.jobPill.cancel')"
        :aria-label="t('analysis.jobPill.cancel')"
        @click="emit('cancel')"
      >
        <XCircle class="w-4 h-4" />
      </button>
    </div>
    <div class="job-progress">
      <div class="job-bar">
        <div class="job-bar-fill" :style="{ width: `${Math.min(Math.max(progress ?? 0, 0), 100)}%` }" />
      </div>
      <span class="job-text">{{ message || `${Math.round(progress ?? 0)}%` }}</span>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.job-pill {
  @apply flex flex-col gap-1 px-2.5 py-1.5 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-[11px] text-neutral-600 dark:text-neutral-300;
  min-width: 160px;
}

.job-pill--running {
  @apply border-primary-200 dark:border-primary-700/60;
}

.job-header {
  @apply flex items-center justify-between gap-2;
}

.job-status {
  @apply flex items-center gap-1.5 font-medium;
}

.job-label {
  @apply uppercase tracking-wide;
}

.job-cancel {
  @apply text-error-500 hover:text-error-600;
}

.job-progress {
  @apply flex items-center gap-2;
}

.job-bar {
  @apply flex-1 h-1.5 rounded-full bg-neutral-200 dark:bg-neutral-700 overflow-hidden;
}

.job-bar-fill {
  @apply h-full bg-primary-500;
}

.job-text {
  @apply text-[10px] text-neutral-500 dark:text-neutral-400;
  min-width: 60px;
  text-align: right;
}
</style>
