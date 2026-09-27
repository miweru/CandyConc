<script setup lang="ts">
/**
 * DropdownItem - Item component for Dropdown menu
 */
import { inject, type Component } from 'vue'
import { dropdownKey } from './dropdownKey'

interface Props {
  disabled?: boolean
  icon?: Component
  destructive?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  destructive: false
})

const emit = defineEmits<{
  click: [event: MouseEvent | KeyboardEvent]
}>()

// Inject dropdown context
const dropdown = inject(dropdownKey, { close: () => {}, closeOnSelect: true })

function handleClick(e: MouseEvent | KeyboardEvent) {
  if (props.disabled) return

  emit('click', e as MouseEvent)

  if (dropdown.closeOnSelect) {
    dropdown.close()
  }
}
</script>

<template>
  <button
    type="button"
    role="menuitem"
    class="dropdown-item"
    :class="{ disabled, destructive }"
    :disabled="disabled"
    :aria-disabled="disabled"
    :tabindex="disabled ? -1 : 0"
    @click="handleClick"
    @keydown.enter.prevent="handleClick"
    @keydown.space.prevent="handleClick"
  >
    <component v-if="icon" :is="icon" class="item-icon" aria-hidden="true" />
    <span class="item-label">
      <slot />
    </span>
  </button>
</template>

<style scoped>
@reference "../../style.css";

.dropdown-item {
  @apply w-full flex items-center gap-3;
  @apply px-4 py-2.5;
  @apply text-left text-sm;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors duration-100;
}

.dropdown-item.disabled {
  @apply opacity-50 cursor-not-allowed;
  @apply hover:bg-transparent;
}

.dropdown-item.destructive {
  @apply text-error-600 dark:text-error-400;
}

.dropdown-item.destructive:not(.disabled):hover {
  @apply bg-error-50 dark:bg-error-900/30;
}

.item-icon {
  @apply w-4 h-4 flex-shrink-0;
}

.item-label {
  @apply flex-1;
}
</style>
