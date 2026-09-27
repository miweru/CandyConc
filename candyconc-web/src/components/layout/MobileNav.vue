<script setup lang="ts">
/**
 * MobileNav - Bottom navigation for mobile devices
 */
import { computed } from 'vue'
import type { Component } from 'vue'
import { asSwitchTabId, useCorpusCapabilitiesStore, useUiStore, useCopilotStore, useProductCapabilitiesStore } from '@/stores'
import { Sparkles } from 'lucide-vue-next'
import type { ActiveTab } from '@/stores'
import { actionBus } from '@/actions'
import { iconComponentForSurfaceIconName } from '@/lib/productSurfaceIcons'
import {
  iconNameForAnalysisTab,
} from '@/lib/productSurfaceRegistry'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const uiStore = useUiStore()
const copilotStore = useCopilotStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const canUseCopilot = computed(() => productCapabilities.isVisible('research.copilot_grounding'))

interface NavTab {
  id: ActiveTab
  label: string
  icon: Component
  disabledReason?: string | null
  partialReason?: string | null
}

const tabs = computed<NavTab[]>(() => productCapabilities.discoverableAnalysisTabs
  .map((surface) => {
    const availability = productCapabilities.surfaceAvailability(
      surface.capabilityId,
      corpusCapabilities.activeSummary,
    )
    return {
      id: surface.tab,
      label: surface.label,
      icon: iconComponentForSurfaceIconName(iconNameForAnalysisTab(surface.tab)),
      disabledReason: availability.disabledReason,
      partialReason: availability.partialReason,
    }
  }))

const activeTab = computed(() => uiStore.activeTab)

function switchTab(tab: NavTab) {
  if (tab.disabledReason) {
    uiStore.showToast(tab.disabledReason, 'warning')
    return
  }
  void actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: asSwitchTabId(tab.id) } })
}

function toggleCopilot() {
  if (!canUseCopilot.value) return
  copilotStore.toggle()
}
</script>

<template>
  <nav class="mobile-nav" :aria-label="t('layout.mobileNav.ariaLabel')">
    <div class="nav-scroll" role="list">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        role="listitem"
        :class="['nav-item', { active: activeTab === tab.id, disabled: tab.disabledReason, partial: tab.partialReason }]"
        :aria-disabled="Boolean(tab.disabledReason)"
        :title="tab.disabledReason ?? tab.partialReason ?? tab.label"
        @click="switchTab(tab)"
      >
        <component :is="tab.icon" class="nav-icon" aria-hidden="true" />
        <span class="nav-label">{{ tab.label }}</span>
        <span v-if="tab.partialReason && !tab.disabledReason" class="nav-note">{{ t('layout.mobileNav.partial') }}</span>
      </button>
    </div>

    <!-- Copilot FAB -->
    <button
      v-if="canUseCopilot"
      class="copilot-fab"
      :class="{ 'is-thinking': copilotStore.isThinking }"
      @click="toggleCopilot"
      :aria-label="t('layout.mobileNav.openCopilot')"
    >
      <Sparkles class="w-6 h-6" aria-hidden="true" />
    </button>
  </nav>
</template>

<style scoped>
@reference "../../style.css";

.mobile-nav {
  @apply fixed bottom-0 inset-x-0;
  @apply flex items-center;
  @apply h-16 bg-white dark:bg-neutral-900;
  @apply border-t border-neutral-200 dark:border-neutral-800;
  padding-bottom: var(--spacing-safe-bottom);
  z-index: var(--z-sticky);
}

.nav-scroll {
  @apply flex items-center gap-1 overflow-x-auto;
  @apply flex-1 min-w-0 h-full px-2;
  scrollbar-width: none;
}

.nav-scroll::-webkit-scrollbar {
  display: none;
}

.nav-item {
  @apply flex flex-col items-center justify-center gap-0.5;
  @apply flex-none h-full;
  min-width: 4.75rem;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply transition-colors;
}

.nav-item.active {
  @apply text-primary-600 dark:text-primary-400;
}

.nav-item.disabled {
  @apply opacity-50 cursor-not-allowed;
}

.nav-item.partial:not(.disabled) {
  @apply text-warning-700 dark:text-warning-300;
}

.nav-icon {
  @apply w-5 h-5;
}

.nav-label {
  @apply text-[10px] font-medium;
}

.nav-note {
  @apply text-[9px] font-semibold uppercase tracking-wide leading-none;
}

/* Part of the bar, at its right end. Raised half above the bar it covered
   the status bar and the last tab of the scrolling list. */
.copilot-fab {
  @apply flex-none mx-2;
  @apply w-11 h-11 rounded-full;
  @apply flex items-center justify-center;
  @apply bg-copilot-primary text-white;
  @apply shadow-lg;
  @apply transition-transform;
  @apply active:scale-95;
}

.copilot-fab:hover {
  box-shadow: var(--shadow-copilot);
}

.copilot-fab.is-thinking {
  @apply animate-pulse;
}
</style>
