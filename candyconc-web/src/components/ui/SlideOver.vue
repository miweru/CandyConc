<script setup lang="ts">
/**
 * SlideOver - Reusable slide-over panel for Settings, Bookmarks, etc.
 * With focus trap for accessibility
 */
import { ref, watch, onUnmounted, computed } from 'vue'
import { X } from 'lucide-vue-next'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useAnnounce } from '@/composables/useAnnounce'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  modelValue: boolean
  position?: 'right' | 'left'
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'wide'
  title?: string
  closeOnBackdrop?: boolean
  closeOnEscape?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  position: 'right',
  size: 'md',
  closeOnBackdrop: true,
  closeOnEscape: true
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  close: []
}>()

// Unique IDs for ARIA
const panelId = `slideover-${Math.random().toString(36).substr(2, 9)}`
const titleId = computed(() => props.title ? `${panelId}-title` : undefined)

// Focus trap
const panelRef = ref<HTMLElement | null>(null)
const { activate: activateTrap, deactivate: deactivateTrap } = useFocusTrap(panelRef, {
  escapeDeactivates: props.closeOnEscape,
  onEscape: close
})

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

// Lock body scroll and manage focus trap when open
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) {
    document.body.style.overflow = 'hidden'
    // Activate focus trap after DOM update
    setTimeout(() => activateTrap(), 50)
    // Announce to screen readers
    if (props.title) {
      announce(t('common.dialog.panelOpened', { title: props.title }))
    }
  } else {
    document.body.style.overflow = ''
    deactivateTrap()
  }
}, { immediate: true })

onUnmounted(() => {
  deactivateTrap()
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="slide-over">
      <div v-if="modelValue" class="slide-over-container">
        <!-- Backdrop -->
        <div class="backdrop" @click="handleBackdropClick" />

        <!-- Panel -->
        <div
          ref="panelRef"
          class="slide-over-panel"
          :class="[position, size]"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          @click.stop
        >
          <!-- Header -->
          <header v-if="title || $slots.header" class="slide-over-header">
            <slot name="header">
              <h2 :id="titleId" class="slide-over-title">{{ title }}</h2>
            </slot>
            <button
              type="button"
              class="close-btn"
              @click="close"
              :aria-label="t('common.dialog.close')"
            >
              <X class="w-5 h-5" />
            </button>
          </header>

          <!-- Content -->
          <div class="slide-over-content">
            <slot />
          </div>

          <!-- Footer -->
          <footer v-if="$slots.footer" class="slide-over-footer">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
@reference "../../style.css";

.slide-over-container {
  @apply fixed inset-0;
  z-index: var(--z-modal);
}

.backdrop {
  @apply absolute inset-0 bg-black/50;
}

.slide-over-panel {
  @apply absolute top-0 bottom-0;
  @apply bg-white dark:bg-neutral-900;
  @apply flex flex-col;
  @apply shadow-xl;
  max-width: 100vw;
}

/* Position */
.slide-over-panel.right {
  @apply right-0 rounded-l-2xl;
}

.slide-over-panel.left {
  @apply left-0 rounded-r-2xl;
}

/* Sizes */
.slide-over-panel.sm {
  @apply w-80;
}

.slide-over-panel.md {
  @apply w-96;
}

.slide-over-panel.lg {
  @apply w-[32rem];
}

.slide-over-panel.xl {
  @apply w-[40rem];
}

/* A comparison needs two readable text columns, not just a larger settings pane. */
.slide-over-panel.wide {
  width: min(96vw, 84rem);
}

/* Responsive: full width on mobile */
@media (max-width: 640px) {
  .slide-over-panel.sm,
  .slide-over-panel.md,
  .slide-over-panel.lg,
  .slide-over-panel.xl,
  .slide-over-panel.wide {
    @apply w-full rounded-none;
  }

  .slide-over-panel.right,
  .slide-over-panel.left {
    @apply rounded-none;
  }
}

.slide-over-header {
  @apply flex items-center justify-between;
  @apply px-6 py-4;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.slide-over-title {
  @apply text-lg font-semibold text-neutral-900 dark:text-neutral-100;
}

.close-btn {
  @apply p-2 rounded-lg;
  @apply text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors duration-150;
}

.slide-over-content {
  @apply flex-1 overflow-y-auto;
  @apply px-6 py-4;
}

.slide-over-footer {
  @apply px-6 py-4;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}

/* Transitions */
.slide-over-enter-active,
.slide-over-leave-active {
  @apply transition-all duration-300 ease-out;
}

.slide-over-enter-active .backdrop,
.slide-over-leave-active .backdrop {
  @apply transition-opacity duration-300;
}

.slide-over-enter-active .slide-over-panel,
.slide-over-leave-active .slide-over-panel {
  @apply transition-transform duration-300 ease-out;
}

.slide-over-enter-from .backdrop,
.slide-over-leave-to .backdrop {
  @apply opacity-0;
}

/* Right position transitions */
.slide-over-enter-from .slide-over-panel.right,
.slide-over-leave-to .slide-over-panel.right {
  @apply translate-x-full;
}

/* Left position transitions */
.slide-over-enter-from .slide-over-panel.left,
.slide-over-leave-to .slide-over-panel.left {
  @apply -translate-x-full;
}
</style>
