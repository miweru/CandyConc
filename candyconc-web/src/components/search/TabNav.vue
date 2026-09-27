<script setup lang="ts">
/**
 * TabNav - Analysis tabs navigation with overflow dropdown
 */
import { computed, type Component } from 'vue'
import { asSwitchTabId, useCorpusCapabilitiesStore, useUiStore, type ActiveTab } from '@/stores'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useDispatch } from '@/composables'
import { MoreHorizontal } from 'lucide-vue-next'
import { iconComponentForSurfaceIconName } from '@/lib/productSurfaceIcons'
import {
  iconNameForAnalysisTab,
} from '@/lib/productSurfaceRegistry'
import Dropdown from '@/components/ui/Dropdown.vue'
import DropdownItem from '@/components/ui/DropdownItem.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const uiStore = useUiStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const { dispatch } = useDispatch()

interface TabDef {
  id: ActiveTab
  label: string
  icon: Component
  shortcut: string
  primary?: boolean
  disabledReason?: string | null
  partialReason?: string | null
}

const allTabs = computed<TabDef[]>(() =>
  productCapabilities.discoverableAnalysisTabs.map((surface) => {
    const availability = productCapabilities.surfaceAvailability(
      surface.capabilityId,
      corpusCapabilities.activeSummary,
    )
    return {
      id: surface.tab,
      label: surface.label,
      icon: iconComponentForSurfaceIconName(iconNameForAnalysisTab(surface.tab)),
      shortcut: surface.shortcut,
      primary: surface.primary,
      disabledReason: availability.disabledReason,
      partialReason: availability.partialReason,
    }
  })
)

const primaryTabs = computed(() => allTabs.value.filter(t => t.primary))
const moreTabs = computed(() => allTabs.value.filter(t => !t.primary))

const activeMoreTab = computed(() => {
  return moreTabs.value.find(t => t.id === uiStore.activeTab)
})

function selectTab(tab: TabDef) {
  if (tab.disabledReason) {
    uiStore.showToast(tab.disabledReason, 'warning')
    return
  }
  dispatch({ type: 'nav/switchTab', payload: { tab: asSwitchTabId(tab.id) } })
}

// Keyboard navigation for tabs
function selectNextTab() {
  const selectable = primaryTabs.value.filter(t => !t.disabledReason)
  const currentIndex = selectable.findIndex(t => t.id === uiStore.activeTab)
  if (currentIndex < selectable.length - 1) {
    selectTab(selectable[currentIndex + 1]!)
  }
}

function selectPrevTab() {
  const selectable = primaryTabs.value.filter(t => !t.disabledReason)
  const currentIndex = selectable.findIndex(t => t.id === uiStore.activeTab)
  if (currentIndex > 0) {
    selectTab(selectable[currentIndex - 1]!)
  }
}
</script>

<template>
  <nav class="tab-nav" role="tablist" :aria-label="t('search.tabNav.ariaLabel')">
    <!-- Primary tabs -->
    <button
      v-for="tab in primaryTabs"
      :key="tab.id"
      class="tab-btn"
      :class="{ 'is-active': uiStore.activeTab === tab.id, 'is-disabled': tab.disabledReason, 'is-partial': tab.partialReason }"
      :title="tab.disabledReason ?? tab.partialReason ?? `${tab.label} (${tab.shortcut})`"
      :aria-label="`${tab.label} (${tab.shortcut})`"
      role="tab"
      :aria-selected="uiStore.activeTab === tab.id"
      :aria-disabled="Boolean(tab.disabledReason)"
      :aria-controls="`tabpanel-${tab.id}`"
      :tabindex="uiStore.activeTab === tab.id ? 0 : -1"
      @click="selectTab(tab)"
      @keydown.arrow-right.prevent="selectNextTab"
      @keydown.arrow-left.prevent="selectPrevTab"
    >
      <component :is="tab.icon" class="w-4 h-4" aria-hidden="true" />
      <span class="tab-label">{{ tab.label }}</span>
      <span v-if="tab.partialReason && !tab.disabledReason" class="tab-status">{{ t('search.tabNav.partial') }}</span>
    </button>

    <!-- More tabs dropdown -->
    <Dropdown placement="bottom-end">
      <template #trigger="{ triggerProps }">
        <button
          class="tab-btn more-btn"
          :class="{ 'is-active': activeMoreTab }"
          :title="activeMoreTab?.disabledReason ?? activeMoreTab?.partialReason ?? t('search.tabNav.moreTabs')"
          :aria-label="activeMoreTab ? t('search.tabNav.moreTabsActive', { label: activeMoreTab.label }) : t('search.tabNav.moreTabs')"
          v-bind="triggerProps"
        >
          <component
            :is="activeMoreTab?.icon ?? MoreHorizontal"
            class="w-4 h-4"
            aria-hidden="true"
          />
          <span class="tab-label">{{ activeMoreTab?.label ?? t('search.tabNav.more') }}</span>
          <MoreHorizontal v-if="activeMoreTab" class="w-3.5 h-3.5 ml-1 opacity-50" aria-hidden="true" />
        </button>
      </template>

      <DropdownItem
        v-for="tab in moreTabs"
        :key="tab.id"
        :icon="tab.icon"
        :disabled="Boolean(tab.disabledReason)"
        role="menuitem"
        @click="selectTab(tab)"
      >
        <div class="dropdown-tab-content">
          <div class="flex items-center justify-between w-full">
            <span>{{ tab.label }}</span>
            <kbd class="dropdown-shortcut" :aria-label="t('search.tabNav.shortcut')">{{ tab.shortcut }}</kbd>
          </div>
          <span v-if="tab.disabledReason" class="dropdown-reason">{{ tab.disabledReason }}</span>
          <span v-else-if="tab.partialReason" class="dropdown-reason">{{ tab.partialReason }}</span>
        </div>
      </DropdownItem>
    </Dropdown>
  </nav>
</template>

<style scoped>
@reference "../../style.css";

.tab-nav {
  @apply hidden md:flex items-center gap-1 px-4 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-x-auto;
  /* The width of the main area, not of the window, decides how much room the
     tabs have: a docked copilot takes 320 to 384 px of the window. */
  container-type: inline-size;
}

.tab-btn {
  @apply flex items-center gap-2 px-4 py-2;
  @apply text-sm font-medium rounded-lg;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply hover:text-neutral-900 dark:hover:text-neutral-100;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors whitespace-nowrap;
  /* The global button min-width lets flex shrink a tab below its label, the
     labels then overlap. A row that does not fit scrolls instead. */
  flex-shrink: 0;
}

.tab-btn > svg {
  flex-shrink: 0;
}

/* Narrower main area: tighter tabs, the partial badge moves into the title. */
@container (max-width: 1000px) {
  .tab-btn {
    @apply px-2.5;
  }
  .tab-status {
    display: none !important;
  }
}

/* Too narrow for all labels: inactive tabs show their icon, the active tab
   keeps its label. Name and shortcut stay in aria-label and title. */
@container (max-width: 850px) {
  .tab-btn:not(.is-active) .tab-label {
    display: none;
  }
}

.tab-btn.is-active {
  @apply text-primary-600 dark:text-primary-400;
  @apply bg-primary-50 dark:bg-primary-900/20;
}

.tab-btn.is-disabled {
  @apply opacity-50 cursor-not-allowed;
}

.tab-btn.is-partial:not(.is-disabled) {
  @apply ring-1 ring-warning-200 dark:ring-warning-900/50;
}

.tab-label {
  @apply hidden sm:inline;
}

.tab-status {
  @apply hidden rounded-full bg-warning-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-700 dark:bg-warning-900/30 dark:text-warning-200 lg:inline;
}

.more-btn {
  @apply ml-auto;
}

.dropdown-shortcut {
  @apply ml-4 px-1.5 py-0.5 rounded;
  @apply bg-neutral-100 dark:bg-neutral-700;
  @apply text-xs font-mono text-neutral-500;
}

.dropdown-tab-content {
  @apply flex flex-col gap-1 w-full;
}

.dropdown-reason {
  @apply text-xs text-warning-600 dark:text-warning-400;
}
</style>
