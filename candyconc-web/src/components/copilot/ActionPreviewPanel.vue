<script setup lang="ts">
/**
 * ActionPreviewPanel - Preview and approve/reject Copilot actions
 *
 * Shows action metadata, rationale, payload, and confirmation controls.
 * Used when autonomy level requires user approval.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Play, X, AlertTriangle, Info, Shield, Undo2,
  Zap, Clock
} from 'lucide-vue-next'
import type { PendingActionPreview } from '@/actions/policyGate'

interface Props {
  preview: PendingActionPreview
}

const props = defineProps<Props>()
const { t } = useI18n()

const emit = defineEmits<{
  approve: [requestId: string]
  reject: [requestId: string]
}>()

const costIcons = {
  low: Zap,
  medium: Clock,
  high: AlertTriangle,
}

function costLabel(cost: keyof typeof costIcons): string {
  if (cost === 'low') return t('copilot.actionPreview.costLow')
  if (cost === 'medium') return t('copilot.actionPreview.costMedium')
  return t('copilot.actionPreview.costHigh')
}

const payloadPreview = computed(() => {
  const payload = (props.preview.action as { payload?: Record<string, unknown> }).payload
  if (!payload) return null

  // Format payload for display
  const entries = Object.entries(payload)
  if (entries.length === 0) return null

  return entries.map(([key, value]) => ({
    key,
    value: typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
  }))
})

function handleApprove() {
  emit('approve', props.preview.requestId)
}

function handleReject() {
  emit('reject', props.preview.requestId)
}
</script>

<template>
  <div class="action-preview">
    <!-- Header -->
    <div class="preview-header">
      <div class="header-icon">
        <Shield class="w-5 h-5" />
      </div>
      <div class="header-content">
        <h3 class="header-title">{{ t('copilot.actionPreview.title') }}</h3>
        <p class="header-subtitle">
          {{ t('copilot.actionPreview.subtitle') }}
        </p>
      </div>
    </div>

    <!-- Action Info -->
    <div class="action-info">
      <div class="action-type">
        <span class="type-label">{{ preview.meta?.label || preview.action.type }}</span>
        <code class="type-code">{{ preview.action.type }}</code>
      </div>

      <!-- Meta badges -->
      <div class="action-badges">
        <span v-if="preview.meta" class="badge" :class="preview.meta.cost">
          <component :is="costIcons[preview.meta.cost]" class="w-3 h-3" />
          {{ costLabel(preview.meta.cost) }}
        </span>
        <span v-if="preview.meta?.reversible" class="badge reversible">
          <Undo2 class="w-3 h-3" />
          {{ t('copilot.actionPreview.reversible') }}
        </span>
        <span v-else-if="preview.meta" class="badge irreversible">
          <AlertTriangle class="w-3 h-3" />
          {{ t('copilot.actionPreview.irreversible') }}
        </span>
      </div>
    </div>

    <!-- Rationale -->
    <div v-if="preview.rationale" class="action-rationale">
      <Info class="w-4 h-4 flex-shrink-0" />
      <p>{{ preview.rationale }}</p>
    </div>

    <!-- Payload Preview -->
    <div v-if="payloadPreview" class="action-payload">
      <h4 class="payload-title">{{ t('copilot.actionPreview.parameters') }}</h4>
      <dl class="payload-list">
        <div v-for="item in payloadPreview" :key="item.key" class="payload-item">
          <dt>{{ item.key }}</dt>
          <dd>{{ item.value }}</dd>
        </div>
      </dl>
    </div>

    <!-- Confirmation reason -->
    <div v-if="preview.confirmationReason" class="confirmation-reason">
      <span>{{ t('copilot.actionPreview.confirmationRequired') }}</span>
      {{ preview.confirmationReason }}
    </div>

    <!-- Actions -->
    <div class="preview-actions">
      <button class="btn-reject" @click="handleReject">
        <X class="w-4 h-4" />
        {{ t('copilot.actionPreview.reject') }}
      </button>
      <button class="btn-approve" @click="handleApprove">
        <Play class="w-4 h-4" />
        {{ t('copilot.actionPreview.run') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.action-preview {
  @apply rounded-xl overflow-hidden;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply shadow-lg;
}

.preview-header {
  @apply flex items-center gap-3 p-4;
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

.header-subtitle {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.action-info {
  @apply px-4 pb-3;
}

.action-type {
  @apply flex items-baseline gap-2 mb-2;
}

.type-label {
  @apply text-base font-medium text-neutral-800 dark:text-neutral-200;
}

.type-code {
  @apply text-xs text-neutral-400 dark:text-neutral-500 font-mono;
}

.action-badges {
  @apply flex flex-wrap gap-2;
}

.badge {
  @apply inline-flex items-center gap-1;
  @apply px-2 py-1 rounded-full;
  @apply text-xs font-medium;
}

.badge.low {
  @apply bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400;
}

.badge.medium {
  @apply bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400;
}

.badge.high {
  @apply bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400;
}

.badge.reversible {
  @apply bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-400;
}

.badge.irreversible {
  @apply bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400;
}

.action-rationale {
  @apply flex gap-2 mx-4 mb-3 p-3 rounded-lg;
  @apply bg-blue-50 dark:bg-blue-900/20;
  @apply text-sm text-blue-700 dark:text-blue-300;
}

.action-payload {
  @apply mx-4 mb-3 p-3 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-700/50;
}

.payload-title {
  @apply text-xs font-semibold text-neutral-500 dark:text-neutral-400 uppercase tracking-wide mb-2;
}

.payload-list {
  @apply space-y-1;
}

.payload-item {
  @apply flex gap-2 text-sm;
}

.payload-item dt {
  @apply font-mono text-neutral-500 dark:text-neutral-400 flex-shrink-0;
}

.payload-item dt::after {
  content: ':';
}

.payload-item dd {
  @apply font-mono text-neutral-800 dark:text-neutral-200 break-all;
}

.confirmation-reason {
  @apply mx-4 mb-3 p-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-700;
  @apply text-xs text-neutral-600 dark:text-neutral-400;
}

.confirmation-reason span {
  @apply font-medium;
}

.preview-actions {
  @apply flex gap-3 p-4;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}

.btn-reject {
  @apply flex-1 inline-flex items-center justify-center gap-2;
  @apply px-4 py-2.5 rounded-lg;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply hover:bg-neutral-300 dark:hover:bg-neutral-600;
  @apply transition-colors;
  @apply text-sm font-medium;
}

.btn-approve {
  @apply flex-1 inline-flex items-center justify-center gap-2;
  @apply px-4 py-2.5 rounded-lg;
  @apply bg-copilot-primary text-white;
  @apply hover:bg-copilot-primary/90;
  @apply transition-colors;
  @apply text-sm font-medium;
}
</style>
