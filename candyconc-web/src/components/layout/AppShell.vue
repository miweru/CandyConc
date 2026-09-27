<script setup lang="ts">
/**
 * AppShell - Main application layout (responsive)
 */
import { ref, computed, nextTick, onMounted, onUnmounted, watch, defineAsyncComponent } from 'vue'
import { useUiStore, useCopilotStore, useProductCapabilitiesStore } from '@/stores'
import { useKeyboard } from '@/composables'
import { useGlobalOnlineStatus } from '@/composables/useOnlineStatus'
import CopilotTrigger from '@/components/copilot/CopilotTrigger.vue'
import ToastContainer from '@/components/ui/ToastContainer.vue'
import MobileNav from '@/components/layout/MobileNav.vue'
import BottomSheet from '@/components/ui/BottomSheet.vue'
import ArbeitsspurLeiste from '@/components/copilot/ArbeitsspurLeiste.vue'
import { useArbeitsspurStore } from '@/stores/arbeitsspur'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// Die grosse Spur ist schwer und wird nur gebraucht, wenn jemand sie
// aufzieht. Wie CopilotPanel nachgeladen.
const ArbeitsspurGross = defineAsyncComponent({
  loader: () => import('@/components/copilot/ArbeitsspurGross.vue'),
  delay: 100,
})

// Lazy load CopilotPanel (heavy component with many sub-components)
const CopilotPanel = defineAsyncComponent({
  loader: () => import('@/components/copilot/CopilotPanel.vue'),
  delay: 100
})

const uiStore = useUiStore()
const copilotStore = useCopilotStore()
const spurStore = useArbeitsspurStore()

/**
 * Der Fokus wandert in die Spur, wenn sie sich oeffnet, und zurueck auf
 * die Arbeitsflaeche, wenn sie schliesst.
 *
 * Ohne das faellt der Fokus bei jedem Moduswechsel auf ``document.body``:
 * die Tastatur landet im Nichts, Escape geht an den Copilot statt an die
 * Spur, und ein Screenreader liest nach dem Oeffnen nichts vor.
 */
const spurRahmen = ref<HTMLElement | null>(null)
watch(() => spurStore.istGross, async (gross) => {
  await nextTick()
  if (gross) {
    spurRahmen.value?.focus()
    return
  }
  document.getElementById('main-content')?.focus()
})
const productCapabilities = useProductCapabilitiesStore()
const { copilotAvailable } = useGlobalOnlineStatus()
const canUseCopilot = computed(() => productCapabilities.isVisible('research.copilot_grounding'))

// Mobile detection
const windowWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1024)
const MOBILE_BREAKPOINT = 768

const isMobile = computed(() => windowWidth.value < MOBILE_BREAKPOINT)

function handleResize() {
  windowWidth.value = window.innerWidth
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})

// Copilot open state for bottom sheet
const copilotSheetOpen = computed({
  get: () => copilotStore.isOpen && isMobile.value,
  set: (value: boolean) => {
    if (!value) {
      copilotStore.close()
    }
  }
})

// Initialize keyboard shortcuts
useKeyboard()

// Initialize theme on mount
uiStore.init()

</script>

<template>
  <div class="app-shell" :class="{ 'has-mobile-nav': isMobile }">
    <!-- Skip-to-content link: first focusable element, visible only on focus
         (DESIGN-A11Y-07) so keyboard users can bypass the header chrome. -->
    <a href="#main-content" class="skip-link">{{ t('layout.appShell.skipToContent') }}</a>

    <!-- Main Content Row -->
    <div class="content-row">
      <!-- Main Content Area -->
      <div
        class="main-area"
        :class="{
          'with-sidebar': !isMobile && canUseCopilot && copilotStore.isDocked && copilotStore.isOpen
        }"
      >
        <!-- Header -->
        <header class="app-header">
          <slot name="header">
            <div class="flex items-center gap-4">
              <h1 class="text-lg md:text-xl font-semibold text-neutral-900 dark:text-neutral-100">
                CandyConc
              </h1>
            </div>
          </slot>
        </header>

        <!-- Main Content. Die Arbeitsspur UEBERLAGERT sie, sie ersetzt sie
             nicht: wer minimiert, findet Konkordanz, Frequenzliste oder
             Kontrast unveraendert vor, samt Bildlaufstand und Auswahl.
             Die Ueberlagerung liegt NEBEN dem Scrollcontainer, nicht darin:
             absolut positioniert in einem scrollenden Kasten wandert sie
             mit dem Inhalt aus dem Bild, und eine klebende Registerleiste
             liegt darueber und verschluckt die Bedienknoepfe. -->
        <div class="inhalt-und-spur">
          <main
            id="main-content"
            class="app-content"
            tabindex="-1"
            :aria-hidden="spurStore.istGross ? 'true' : undefined"
            :inert="spurStore.istGross"
          >
            <slot />
          </main>
          <div
            v-if="spurStore.istGross"
            ref="spurRahmen"
            class="spur-ueberlagerung"
            tabindex="-1"
            @keydown.esc.stop.prevent="spurStore.verkleinern()"
          >
            <ArbeitsspurGross />
          </div>
        </div>

        <!-- Schmale Laufleiste am unteren Rand der Arbeitsflaeche -->
        <ArbeitsspurLeiste v-if="spurStore.modus === 'leiste'" />
      </div>

      <!-- Desktop: Docked Copilot Sidebar -->
      <aside
        v-if="!isMobile && canUseCopilot && copilotStore.isDocked && copilotStore.isOpen"
        class="copilot-sidebar"
      >
        <CopilotPanel mode="docked" />
      </aside>
    </div>

    <!-- The copilot button takes the left end of the footer, beside the
         status bar. As a floating button it covered the first column of
         every table and the lowest lines of every view. -->
    <footer class="app-footer">
      <div
        v-if="!isMobile && canUseCopilot && copilotStore.isMinimized"
        class="app-footer-copilot"
      >
        <CopilotTrigger :disabled="!copilotAvailable" />
      </div>
      <div class="app-footer-bar">
        <slot name="footer" />
      </div>
    </footer>

    <!-- Desktop: Floating Copilot -->
    <CopilotPanel
      v-if="!isMobile && canUseCopilot && copilotStore.isFloating && copilotStore.isOpen"
      mode="floating"
    />

    <!-- Mobile: Bottom Sheet Copilot -->
    <BottomSheet v-if="isMobile && canUseCopilot" v-model="copilotSheetOpen" :initial-height="70">
      <CopilotPanel mode="sheet" />
    </BottomSheet>

    <!-- Mobile: Bottom Navigation -->
    <MobileNav v-if="isMobile" />

    <!-- Toast Notifications -->
    <ToastContainer />
  </div>
</template>

<style scoped>
/* Der Bezugsrahmen ist der NICHT scrollende Kasten um main herum. Der
   Inhalt darunter bleibt montiert und behaelt Bildlaufstand und Auswahl. */
.inhalt-und-spur {
  @apply relative flex-1 min-h-0 flex flex-col;
}
.spur-ueberlagerung {
  /* z-30 liegt ueber der klebenden Registerleiste der Analyseflaeche. */
  @apply absolute inset-0 z-30 outline-none;
  @apply bg-neutral-50 dark:bg-neutral-900;
}

@reference "../../style.css";

.app-shell {
  @apply min-h-screen h-screen flex flex-col bg-neutral-50 dark:bg-neutral-950 overflow-hidden;
}

/* Off-screen until focused, then pinned to the top-left (DESIGN-A11Y-07). */
.skip-link {
  @apply sr-only;
}
.skip-link:focus {
  @apply not-sr-only fixed left-3 top-3 z-50 rounded-md px-3 py-2;
  @apply bg-primary-600 text-white shadow-lg outline-none ring-2 ring-primary-300;
}

.app-shell.has-mobile-nav {
  /* Space for mobile bottom nav */
  padding-bottom: calc(4rem + var(--spacing-safe-bottom));
}

.content-row {
  @apply flex-1 flex min-h-0;
}

.main-area {
  @apply flex-1 flex flex-col min-w-0 min-h-0 transition-all duration-300;
}

.app-header {
  @apply px-3 md:px-4 py-2 md:py-3 flex flex-col gap-2;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
}

.app-content {
  @apply flex-1 overflow-auto min-h-0;
}

.app-footer {
  @apply flex-shrink-0 flex items-stretch;
}

.app-footer-bar {
  @apply flex-1 min-w-0;
}

/* Same surface as the status bar next to it. */
.app-footer-copilot {
  @apply flex items-center pl-3 md:pl-4;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}

/* Desktop: Copilot Sidebar */
.copilot-sidebar {
  @apply hidden md:flex;
  @apply w-80 lg:w-96 flex-shrink-0;
  @apply border-l border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
}
</style>
