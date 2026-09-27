<script setup lang="ts">
/**
 * EmptyState - Placeholder for empty content areas
 */
import { type Component } from 'vue'
import { Search } from 'lucide-vue-next'
import Button from './Button.vue'
import CodeSpanText from './CodeSpanText.vue'

interface Props {
  icon?: Component
  title: string
  description?: string
  actionLabel?: string
  secondaryActionLabel?: string
  secondaryActionVariant?: 'secondary' | 'ghost' | 'danger' | 'success'
  size?: 'sm' | 'md' | 'lg'
}

const props = withDefaults(defineProps<Props>(), {
  icon: () => Search,
  size: 'md'
})

const emit = defineEmits<{
  action: []
  secondaryAction: []
}>()
</script>

<template>
  <div class="empty-state" :class="size">
    <!-- Icon -->
    <div class="icon-container">
      <component :is="icon" class="empty-icon" />
    </div>

    <!-- Content -->
    <h3 class="empty-title">{{ title }}</h3>
    <p v-if="description" class="empty-description"><CodeSpanText :text="description" /></p>

    <!-- Actions -->
    <div v-if="actionLabel || secondaryActionLabel" class="action-row">
      <Button
        v-if="actionLabel"
        variant="primary"
        @click="emit('action')"
      >
        {{ actionLabel }}
      </Button>
      <Button
        v-if="secondaryActionLabel"
        :variant="secondaryActionVariant || 'ghost'"
        @click="emit('secondaryAction')"
      >
        {{ secondaryActionLabel }}
      </Button>
    </div>

    <!-- Slot for custom content -->
    <slot />
  </div>
</template>

<style scoped>
@reference "../../style.css";

.empty-state {
  @apply flex flex-col items-center justify-center;
  @apply text-center;
}

/* Sizes */
.empty-state.sm {
  @apply py-8;
}

.empty-state.md {
  @apply py-16;
}

.empty-state.lg {
  @apply py-24;
}

.icon-container {
  @apply mb-4;
}

.empty-icon {
  @apply text-neutral-300 dark:text-neutral-600;
}

.empty-state.sm .empty-icon {
  @apply w-10 h-10;
}

.empty-state.md .empty-icon {
  @apply w-16 h-16;
}

.empty-state.lg .empty-icon {
  @apply w-20 h-20;
}

.empty-title {
  @apply font-semibold text-neutral-900 dark:text-neutral-100;
}

.empty-state.sm .empty-title {
  @apply text-base;
}

.empty-state.md .empty-title {
  @apply text-lg;
}

.empty-state.lg .empty-title {
  @apply text-xl;
}

.empty-description {
  @apply mt-2 max-w-md;
  @apply text-neutral-500 dark:text-neutral-400;
}

.empty-state.sm .empty-description {
  @apply text-sm;
}

.empty-state.md .empty-description {
  @apply text-base;
}

.action-row {
  @apply mt-4 flex flex-wrap items-center justify-center gap-2;
}
</style>
