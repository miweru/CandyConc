<script setup lang="ts">
/**
 * Button - Styled button with loading state and press effects
 */
import { computed, type Component } from 'vue'
import LoadingSpinner from './LoadingSpinner.vue'

interface Props {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
  size?: 'xs' | 'sm' | 'md' | 'lg'
  loading?: boolean
  disabled?: boolean
  icon?: Component
  iconPosition?: 'left' | 'right'
  fullWidth?: boolean
  type?: 'button' | 'submit' | 'reset'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'primary',
  size: 'md',
  loading: false,
  disabled: false,
  iconPosition: 'left',
  fullWidth: false,
  type: 'button'
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()

const isDisabled = computed(() => props.disabled || props.loading)

const variantClasses = computed(() => {
  switch (props.variant) {
    case 'secondary':
      return 'btn-secondary'
    case 'ghost':
      return 'btn-ghost'
    case 'danger':
      return 'btn-danger'
    case 'success':
      return 'btn-success'
    default:
      return 'btn-primary'
  }
})

const sizeClasses = computed(() => {
  switch (props.size) {
    case 'xs':
      return 'btn-xs'
    case 'sm':
      return 'btn-sm'
    case 'lg':
      return 'btn-lg'
    default:
      return 'btn-md'
  }
})

const spinnerColor = computed(() => {
  if (props.variant === 'primary' || props.variant === 'danger' || props.variant === 'success') {
    return 'white'
  }
  return 'primary'
})

function handleClick(e: MouseEvent) {
  if (!isDisabled.value) {
    emit('click', e)
  }
}
</script>

<template>
  <button
    :type="type"
    class="btn"
    :class="[
      variantClasses,
      sizeClasses,
      {
        'w-full': fullWidth,
        loading: loading,
        'opacity-50 cursor-not-allowed': isDisabled && !loading
      }
    ]"
    :disabled="isDisabled"
    @click="handleClick"
  >
    <!-- Loading State -->
    <div v-if="loading" class="btn-loader">
      <LoadingSpinner variant="spinner" size="sm" :color="spinnerColor" />
    </div>

    <!-- Content -->
    <span class="btn-content" :class="{ 'opacity-0': loading }">
      <!-- Left Icon -->
      <component
        v-if="icon && iconPosition === 'left'"
        :is="icon"
        class="btn-icon"
        :class="{ '-ml-0.5': size !== 'xs' }"
      />

      <!-- Label -->
      <span v-if="$slots.default" class="btn-label">
        <slot />
      </span>

      <!-- Right Icon -->
      <component
        v-if="icon && iconPosition === 'right'"
        :is="icon"
        class="btn-icon"
        :class="{ '-mr-0.5': size !== 'xs' }"
      />
    </span>
  </button>
</template>

<style scoped>
@reference "../../style.css";

.btn {
  @apply relative inline-flex items-center justify-center;
  @apply font-medium rounded-lg;
  @apply transition-all duration-150;
  @apply focus-visible:outline-2 focus-visible:outline-offset-2;
}

/* Active state */
.btn:not(:disabled):active {
  @apply scale-[0.97];
}

/* Hover lift */
.btn:not(:disabled):hover {
  @apply -translate-y-0.5;
}

.btn:not(:disabled):active {
  @apply translate-y-0;
}

/* Variants */
.btn-primary {
  @apply bg-primary-600 text-white;
  @apply hover:bg-primary-700;
  @apply focus-visible:outline-primary-500;
  @apply shadow-sm hover:shadow-md;
}

.btn-secondary {
  @apply bg-white dark:bg-neutral-800 text-neutral-700 dark:text-neutral-200;
  @apply border border-neutral-300 dark:border-neutral-600;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-700;
  @apply focus-visible:outline-primary-500;
}

.btn-ghost {
  @apply bg-transparent text-neutral-700 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply focus-visible:outline-primary-500;
}

.btn-danger {
  @apply bg-error-600 text-white;
  @apply hover:bg-error-700;
  @apply focus-visible:outline-error-500;
  @apply shadow-sm hover:shadow-md;
}

.btn-success {
  @apply bg-success-600 text-white;
  @apply hover:bg-success-700;
  @apply focus-visible:outline-success-500;
  @apply shadow-sm hover:shadow-md;
}

/* Sizes */
.btn-xs {
  @apply px-2 py-1 text-xs gap-1;
}

.btn-sm {
  @apply px-3 py-1.5 text-sm gap-1.5;
}

.btn-md {
  @apply px-4 py-2 text-sm gap-2;
}

.btn-lg {
  @apply px-6 py-3 text-base gap-2;
}

/* Content */
.btn-content {
  @apply inline-flex items-center justify-center;
  @apply transition-opacity duration-100;
}

.btn-icon {
  @apply w-4 h-4 flex-shrink-0;
}

.btn-lg .btn-icon {
  @apply w-5 h-5;
}

/* Loading */
.btn-loader {
  @apply absolute inset-0 flex items-center justify-center;
}

/* Ripple Effect (pseudo) */
.btn::after {
  content: '';
  @apply absolute inset-0 rounded-lg;
  @apply bg-white/20;
  @apply scale-0 opacity-0;
  transition: transform 0.3s ease, opacity 0.3s ease;
}

.btn:active::after {
  @apply scale-100 opacity-100;
  transition: transform 0s, opacity 0s;
}
</style>
