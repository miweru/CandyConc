<script setup lang="ts">
/**
 * ToastContainer - Notification toasts with accessibility support
 * Uses ARIA live regions for screen reader announcements
 */
import { useUiStore, type ToastType } from '@/stores'
import { X, Info, CheckCircle, AlertTriangle, XCircle } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import CodeSpanText from './CodeSpanText.vue'

const { t } = useI18n()

const uiStore = useUiStore()

const icons = {
  info: Info,
  success: CheckCircle,
  warning: AlertTriangle,
  error: XCircle
}

const colors = {
  info: 'bg-primary-500',
  success: 'bg-success-500',
  warning: 'bg-warning-500',
  error: 'bg-error-500'
}

// Determine aria-live value based on toast type
function getAriaLive(type: ToastType): 'polite' | 'assertive' {
  return type === 'error' ? 'assertive' : 'polite'
}

// Determine role based on toast type
function getRole(type: ToastType): 'alert' | 'status' {
  return type === 'error' || type === 'warning' ? 'alert' : 'status'
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-container" :aria-label="t('common.toast.region')">
      <TransitionGroup name="toast">
        <div
          v-for="toast in uiStore.toasts"
          :key="toast.id"
          class="toast"
          :class="colors[toast.type]"
          :role="getRole(toast.type)"
          :aria-live="getAriaLive(toast.type)"
          aria-atomic="true"
        >
          <component :is="icons[toast.type]" class="w-5 h-5 flex-shrink-0" aria-hidden="true" />
          <!-- Action errors name parameters in backticks, shown as code. -->
          <p class="flex-1"><CodeSpanText :text="toast.message" /></p>
          <button
            class="toast-close"
            @click="uiStore.removeToast(toast.id)"
            :aria-label="t('common.toast.close')"
          >
            <X class="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
@reference "../../style.css";

.toast-container {
  @apply fixed bottom-6 left-1/2 -translate-x-1/2;
  @apply flex flex-col gap-2;
  @apply pointer-events-none;
  z-index: var(--z-toast);
}

.toast {
  @apply flex items-center gap-3 px-4 py-3;
  @apply rounded-lg shadow-lg;
  @apply text-white text-sm;
  @apply pointer-events-auto;
  min-width: 300px;
  max-width: 500px;
}

.toast-close {
  @apply p-1 rounded hover:bg-white/20 transition-colors;
}

/* Transition animations */
.toast-enter-active {
  animation: toast-in 0.3s ease-out;
}

.toast-leave-active {
  animation: toast-out 0.3s ease-in;
}

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes toast-out {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateY(-20px) scale(0.95);
  }
}
</style>
