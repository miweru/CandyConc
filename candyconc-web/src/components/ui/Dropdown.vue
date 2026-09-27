<script setup lang="ts">
/**
 * Dropdown - Customizable dropdown menu component
 * With full ARIA support for accessibility
 */
import { ref, computed, watch, onMounted, onUnmounted, provide } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { dropdownKey } from './dropdownKey'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  align?: 'left' | 'right'
  width?: 'auto' | 'trigger' | 'sm' | 'md' | 'lg'
  closeOnSelect?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  align: 'left',
  width: 'auto',
  closeOnSelect: true
})

const isOpen = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)

// Unique IDs for ARIA
const dropdownId = `dropdown-${Math.random().toString(36).substr(2, 9)}`
const triggerId = computed(() => `${dropdownId}-trigger`)
const menuId = computed(() => `${dropdownId}-menu`)

// ARIA *state* for the real (slotted) trigger button. Bound via `v-bind` onto the
// inner <button> instead of a separate role=button wrapper, so the focusable
// control and its expanded/popup state live on one element. The accessible NAME
// stays on the call-site's own button (every trigger sets its own aria-label),
// so we deliberately do NOT emit aria-label here — that would clobber a dynamic
// per-trigger label.
const triggerProps = computed(() => ({
  id: triggerId.value,
  'aria-haspopup': 'menu' as const,
  'aria-expanded': isOpen.value,
  'aria-controls': menuId.value,
}))

function toggle() {
  isOpen.value = !isOpen.value
}

function close() {
  isOpen.value = false
}

// Close on click outside
function handleClickOutside(e: MouseEvent) {
  const target = e.target as Node
  if (
    isOpen.value &&
    triggerRef.value &&
    menuRef.value &&
    !triggerRef.value.contains(target) &&
    !menuRef.value.contains(target)
  ) {
    close()
  }
}

// Get all menu items
function getMenuItems(): HTMLElement[] {
  if (!menuRef.value) return []
  return Array.from(menuRef.value.querySelectorAll('[role="menuitem"]:not([disabled])'))
}

// Handle keyboard navigation
function handleKeydown(e: KeyboardEvent) {
  if (!isOpen.value) return

  // Escape closes the menu
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
    triggerRef.value?.focus()
    return
  }

  const items = getMenuItems()
  if (items.length === 0) return

  const currentIndex = items.findIndex(el => el === document.activeElement)

  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      if (currentIndex === -1 || currentIndex === items.length - 1) {
        items[0]?.focus()
      } else {
        items[currentIndex + 1]?.focus()
      }
      break

    case 'ArrowUp':
      e.preventDefault()
      if (currentIndex === -1 || currentIndex === 0) {
        items[items.length - 1]?.focus()
      } else {
        items[currentIndex - 1]?.focus()
      }
      break

    case 'Home':
      e.preventDefault()
      items[0]?.focus()
      break

    case 'End':
      e.preventDefault()
      items[items.length - 1]?.focus()
      break
  }
}

// Focus first item when menu opens
function onMenuOpen() {
  setTimeout(() => {
    const items = getMenuItems()
    items[0]?.focus()
  }, 50)
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('scroll', menuAusrichten, true)
  window.removeEventListener('resize', menuAusrichten)
})

// The menu hangs in a portal on body, so it computes its position itself.
// The tab bar has overflow-x-auto, and by the CSS specification that turns
// the other axis from visible into auto. The 56-pixel-high bar is then a
// clipping box on BOTH axes and would cut away 83 percent of a 317-pixel-high
// menu (at 1440x900 only 53 of 317 pixels visible). No z-index can fix that,
// because an absolutely positioned box is clipped by every overflow ancestor.
// The portal takes the menu out of every clipping box.
const menuStil = ref<Record<string, string>>({})

function menuAusrichten() {
  const ausloeser = triggerRef.value
  if (!ausloeser) return
  const r = ausloeser.getBoundingClientRect()
  const stil: Record<string, string> = { top: `${r.bottom}px` }
  if (props.width === 'trigger') stil.width = `${r.width}px`
  if (props.align === 'right') {
    stil.left = 'auto'
    stil.right = `${Math.max(0, window.innerWidth - r.right)}px`
  } else {
    stil.left = `${r.left}px`
    stil.right = 'auto'
  }
  menuStil.value = stil
}

// Focus first menu item when opened
watch(isOpen, (open) => {
  if (open) {
    menuAusrichten()
    window.addEventListener('scroll', menuAusrichten, true)
    window.addEventListener('resize', menuAusrichten)
    onMenuOpen()
  } else {
    window.removeEventListener('scroll', menuAusrichten, true)
    window.removeEventListener('resize', menuAusrichten)
  }
})

// Provide close function to children (DropdownItem)
provide(dropdownKey, { close, closeOnSelect: props.closeOnSelect })
</script>

<template>
  <div class="dropdown">
    <!-- Trigger: a non-interactive positioning wrapper. The actual focusable
         control is the slotted <button>, so the wrapper carries no role/tabindex
         (that nested-interactive pairing left the outer element nameless and the
         inner button doubly focusable). Clicks from the inner button bubble here
         to toggle; native buttons turn Enter/Space into clicks already. The
         dropdown ARIA state is bound onto the inner button via `triggerProps`. -->
    <div
      ref="triggerRef"
      class="dropdown-trigger"
      @click="toggle"
    >
      <slot name="trigger" :trigger-props="triggerProps">
        <button
          type="button"
          class="dropdown-default-trigger"
          v-bind="triggerProps"
        >
          <span>{{ t('common.dropdown.trigger') }}</span>
          <ChevronDown class="w-4 h-4 transition-transform" aria-hidden="true" :class="{ 'rotate-180': isOpen }" />
        </button>
      </slot>
    </div>

    <!-- Menu. Im Portal am body, damit kein Overflow-Vorfahre es beschneidet. -->
    <Teleport to="body">
      <Transition name="dropdown">
        <div
          v-if="isOpen"
          ref="menuRef"
          :id="menuId"
          class="dropdown-menu"
          :class="[align, width]"
          :style="menuStil"
          role="menu"
          :aria-labelledby="triggerId"
          @keydown="handleKeydown"
        >
          <slot />
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.dropdown {
  @apply relative inline-block;
}

.dropdown-trigger {
  @apply cursor-pointer;
}

.dropdown-default-trigger {
  @apply inline-flex items-center gap-2;
  @apply px-4 py-2 rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-700;
  @apply transition-colors duration-150;
}

.dropdown-menu {
  @apply fixed mt-2;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply rounded-xl shadow-lg;
  @apply py-1;
  @apply min-w-[12rem];
  z-index: var(--z-dropdown);
}

/* Ausrichtung und Breite kommen als Inline-Stil aus menuAusrichten(), weil
   das Menue im Portal am body haengt und left-0/right-0 sich dort auf den
   Viewport beziehen wuerden statt auf den Ausloeser. */
/* Width */
.dropdown-menu.auto {
  @apply w-auto;
}

.dropdown-menu.sm {
  @apply w-40;
}

.dropdown-menu.md {
  @apply w-56;
}

.dropdown-menu.lg {
  @apply w-72;
}

/* Transitions */
.dropdown-enter-active {
  @apply transition-all duration-150 ease-out;
}

.dropdown-leave-active {
  @apply transition-all duration-100 ease-in;
}

.dropdown-enter-from,
.dropdown-leave-to {
  @apply opacity-0 scale-95;
  transform-origin: top;
}
</style>
