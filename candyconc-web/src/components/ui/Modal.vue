<script setup lang="ts">
/**
 * Modal - Reusable modal dialog component
 * With focus trap for accessibility
 */
import { ref, watch, onUnmounted, computed, useSlots } from 'vue'
import { X } from 'lucide-vue-next'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useAnnounce } from '@/composables/useAnnounce'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  modelValue: boolean
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full'
  title?: string
  description?: string
  closeOnBackdrop?: boolean
  closeOnEscape?: boolean
  showClose?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  closeOnBackdrop: true,
  closeOnEscape: true,
  showClose: true
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  close: []
}>()

// Unique IDs for ARIA
const slots = useSlots()
const modalId = `modal-${Math.random().toString(36).substr(2, 9)}`
// The default <h2 id=titleId> only renders when `title` is set AND no custom
// #header slot replaces it. A custom header slot would leave aria-labelledby
// dangling (no element with that id) → the dialog has NO accessible name
// (DESIGN-A11Y-05). So only point aria-labelledby at it when it actually exists,
// and otherwise fall back to aria-label from the title.
const hasDefaultTitle = computed(() => !!props.title && !slots.header)
const titleId = computed(() => (hasDefaultTitle.value ? `${modalId}-title` : undefined))
const ariaLabel = computed(() => (hasDefaultTitle.value ? undefined : props.title))
const descId = computed(() => props.description ? `${modalId}-desc` : undefined)

// Focus trap
const panelRef = ref<HTMLElement | null>(null)
const { activate: activateTrap, deactivate: deactivateTrap } = useFocusTrap(panelRef, {
  escapeDeactivates: props.closeOnEscape,
  onEscape: close
})
let activateTrapTimer: ReturnType<typeof setTimeout> | null = null

// Screen reader announcements
const { announce } = useAnnounce()

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function handleBackdropClick() {
  if (props.closeOnBackdrop) {
    close()
  }
}

function clearActivateTrapTimer() {
  if (activateTrapTimer !== null) {
    clearTimeout(activateTrapTimer)
    activateTrapTimer = null
  }
}

// Lock body scroll and manage focus trap when open
watch(() => props.modelValue, (isOpen) => {
  if (typeof document === 'undefined') return

  if (isOpen) {
    document.body.style.overflow = 'hidden'
    // Activate focus trap after DOM update
    clearActivateTrapTimer()
    activateTrapTimer = setTimeout(() => {
      activateTrapTimer = null
      activateTrap()
    }, 50)
    // Announce to screen readers
    if (props.title) {
      announce(t('common.dialog.opened', { title: props.title }))
    }
  } else {
    clearActivateTrapTimer()
    document.body.style.overflow = ''
    deactivateTrap()
  }
}, { immediate: true })

onUnmounted(() => {
  clearActivateTrapTimer()
  deactivateTrap()
  if (typeof document !== 'undefined') {
    document.body.style.overflow = ''
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="modelValue" class="modal-container" @click="handleBackdropClick">
        <!-- Panel -->
        <div
          ref="panelRef"
          class="modal-panel"
          :class="size"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          :aria-label="ariaLabel"
          :aria-describedby="descId"
          @click.stop
        >
          <!-- Header -->
          <header v-if="title || $slots.header || showClose" class="modal-header">
            <div>
              <slot name="header">
                <h2 v-if="title" :id="titleId" class="modal-title">{{ title }}</h2>
                <p v-if="description" :id="descId" class="modal-description">{{ description }}</p>
              </slot>
            </div>
            <button
              v-if="showClose"
              type="button"
              class="close-btn"
              @click="close"
              :aria-label="t('common.dialog.close')"
            >
              <X class="w-5 h-5" />
            </button>
          </header>

          <!-- Content -->
          <div class="modal-content">
            <slot />
          </div>

          <!-- Footer -->
          <footer v-if="$slots.footer" class="modal-footer">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
@reference "../../style.css";

.modal-container {
  @apply fixed inset-0;
  @apply flex items-center justify-center;
  @apply bg-black/50;
  @apply p-4;
  z-index: var(--z-modal);
}

.modal-panel {
  @apply bg-white dark:bg-neutral-900;
  @apply rounded-2xl shadow-2xl;
  @apply flex flex-col;
  @apply max-h-[90vh];
  @apply overflow-hidden;
}

/* Sizes */
.modal-panel.sm {
  @apply w-full max-w-sm;
}

.modal-panel.md {
  @apply w-full max-w-md;
}

.modal-panel.lg {
  @apply w-full max-w-lg;
}

.modal-panel.xl {
  @apply w-full max-w-xl;
}

.modal-panel.full {
  @apply w-full max-w-4xl;
}

.modal-header {
  @apply flex items-start justify-between gap-4;
  @apply px-6 py-4;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.modal-title {
  @apply text-lg font-semibold text-neutral-900 dark:text-neutral-100;
}

.modal-description {
  @apply mt-1 text-sm text-neutral-500 dark:text-neutral-400;
}

.close-btn {
  @apply p-2 rounded-lg -mr-2 -mt-1;
  @apply text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors duration-150;
}

.modal-content {
  @apply flex-1 overflow-y-auto;
  @apply px-6 py-4;
}

.modal-footer {
  @apply flex items-center justify-end gap-3;
  @apply px-6 py-4;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}

/* Transitions */
.modal-enter-active {
  @apply transition-all duration-200 ease-out;
}

.modal-leave-active {
  @apply transition-all duration-150 ease-in;
}

.modal-enter-from,
.modal-leave-to {
  @apply opacity-0;
}

.modal-enter-from .modal-panel,
.modal-leave-to .modal-panel {
  @apply scale-95 opacity-0;
}
</style>
