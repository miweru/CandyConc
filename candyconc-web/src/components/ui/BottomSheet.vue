<script setup lang="ts">
/**
 * BottomSheet - Draggable bottom sheet for mobile
 */
import { ref, watch } from 'vue'

interface Props {
  modelValue?: boolean
  initialHeight?: number
  minHeight?: number
  maxHeight?: number
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: true,
  initialHeight: 60,
  minHeight: 30,
  maxHeight: 90
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  close: []
}>()

const sheetHeight = ref(props.initialHeight)
const startY = ref(0)
const startHeight = ref(0)
const isDragging = ref(false)

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function onTouchStart(e: TouchEvent) {
  const touch = e.touches[0]
  if (!touch) return

  isDragging.value = true
  startY.value = touch.clientY
  startHeight.value = sheetHeight.value
}

function onTouchMove(e: TouchEvent) {
  if (!isDragging.value) return

  const touch = e.touches[0]
  if (!touch) return

  const deltaY = startY.value - touch.clientY
  const deltaPercent = (deltaY / window.innerHeight) * 100
  const newHeight = startHeight.value + deltaPercent

  sheetHeight.value = Math.min(props.maxHeight, Math.max(props.minHeight, newHeight))
}

function onTouchEnd() {
  isDragging.value = false

  // Snap to nearest position (30%, 60%, 90%) or close if below threshold
  if (sheetHeight.value < 20) {
    close()
  } else if (sheetHeight.value < 45) {
    sheetHeight.value = props.minHeight
  } else if (sheetHeight.value < 75) {
    sheetHeight.value = 60
  } else {
    sheetHeight.value = props.maxHeight
  }
}

// Reset height when opened
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) {
    sheetHeight.value = props.initialHeight
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="modelValue" class="bottom-sheet-container">
        <!-- Backdrop -->
        <div class="backdrop" @click="close" />

        <!-- Sheet -->
        <div
          class="bottom-sheet"
          :class="{ 'is-dragging': isDragging }"
          :style="{ height: `${sheetHeight}vh` }"
        >
          <!-- Drag Handle -->
          <div
            class="drag-handle"
            @touchstart="onTouchStart"
            @touchmove="onTouchMove"
            @touchend="onTouchEnd"
          >
            <div class="handle-bar" />
          </div>

          <!-- Content -->
          <div class="sheet-content">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
@reference "../../style.css";

.bottom-sheet-container {
  @apply fixed inset-0;
  z-index: var(--z-modal);
}

.backdrop {
  @apply absolute inset-0 bg-black/50;
}

.bottom-sheet {
  @apply absolute bottom-0 inset-x-0;
  @apply bg-white dark:bg-neutral-900;
  @apply rounded-t-2xl;
  @apply flex flex-col;
  @apply transition-[height] duration-200 ease-out;
  padding-bottom: var(--spacing-safe-bottom);
}

.bottom-sheet.is-dragging {
  @apply transition-none;
}

.drag-handle {
  @apply flex justify-center py-3 cursor-grab;
  @apply touch-none;
}

.drag-handle:active {
  @apply cursor-grabbing;
}

.handle-bar {
  @apply w-10 h-1 rounded-full;
  @apply bg-neutral-300 dark:bg-neutral-600;
}

.sheet-content {
  @apply flex-1 overflow-y-auto overflow-x-hidden;
  @apply px-4;
}

/* Transitions */
.sheet-enter-active,
.sheet-leave-active {
  @apply transition-all duration-300 ease-out;
}

.sheet-enter-active .backdrop,
.sheet-leave-active .backdrop {
  @apply transition-opacity duration-300;
}

.sheet-enter-active .bottom-sheet,
.sheet-leave-active .bottom-sheet {
  @apply transition-transform duration-300 ease-out;
}

.sheet-enter-from .backdrop,
.sheet-leave-to .backdrop {
  @apply opacity-0;
}

.sheet-enter-from .bottom-sheet,
.sheet-leave-to .bottom-sheet {
  @apply translate-y-full;
}
</style>
