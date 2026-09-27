<script setup lang="ts">
/**
 * SettingsGeneral - General preferences settings
 */
import { computed, onMounted } from 'vue'
import AutonomySlider from '@/components/copilot/AutonomySlider.vue'
import {
  DEFAULT_CORPUS_PREFERENCE,
  SETTINGS_PREFERENCE_OPERATIONS,
  useSettingsStore,
  type UserPreferences,
} from '@/stores/settings'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useOnboardingStore } from '@/stores/onboarding'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useUiStore } from '@/stores/ui'
import type { AppLocale } from '@/i18n'
import { formatNumber } from '@/i18n/format'
import { kwicLoadWindow } from '@/lib/kwicLoadWindow'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const settingsStore = useSettingsStore()
const uiStore = useUiStore()
const onboardingStore = useOnboardingStore()
const prefs = computed(() => settingsStore.preferences)

// Corpus list comes from the shared corpusCapabilities store (single source of
// truth) rather than hardcoded options.
const corpusStore = useCorpusCapabilitiesStore()
const productCapabilities = useProductCapabilitiesStore()
// A corpus literally named like the placeholder is covered by the placeholder option.
const corpusOptions = computed(() =>
  corpusStore.corpora.filter((corpus) => corpus.name !== DEFAULT_CORPUS_PREFERENCE)
)
const preferenceWriteAvailability = computed(() =>
  productCapabilities.productOperationAvailability(SETTINGS_PREFERENCE_OPERATIONS.update)
)
const canUpdatePreferences = computed(() => preferenceWriteAvailability.value.enabled)
const preferenceWriteMessage = computed(() => preferenceWriteAvailability.value.disabledReason)
const observabilityLimits = computed(() =>
  productCapabilities.capabilityFor('admin.security_observability')?.limits ?? []
)

onMounted(() => {
  if (!corpusStore.loaded) {
    void corpusStore.fetchCorpora()
  }
  void productCapabilities.load()
})

function updatePreference<K extends keyof UserPreferences>(
  key: K,
  value: UserPreferences[K]
) {
  if (!canUpdatePreferences.value) {
    uiStore.showToast(preferenceWriteMessage.value ?? t('settings.general.saveNotEnabled'), 'warning')
    return
  }
  settingsStore.savePreference(key, value)
}

// The interface language switches at once and is kept in this browser even
// where the session may not write server preferences.
function changeLanguage(value: string) {
  void settingsStore.setLanguage(value as AppLocale)
}

function restartOnboarding() {
  onboardingStore.reset()
  uiStore.closeSettings()
  window.setTimeout(() => onboardingStore.start(), 100)
}
</script>

<template>
  <div class="settings-section">
    <h3 class="section-title">{{ t('settings.general.title') }}</h3>

    <!--
      Der Autonomiegrad stand ueber jedem Chat, dauerhaft sichtbar, und
      nahm dort Platz und Aufmerksamkeit fuer eine Einstellung, die man
      einmal setzt. Er gehoert dorthin, wo Einstellungen stehen.
    -->
    <div class="setting-row setting-row--block">
      <div class="setting-info">
        <label for="autonomie">{{ t('settings.general.autonomy') }}</label>
        <p class="setting-description">
          {{ t('settings.general.autonomyDescription') }}
        </p>
      </div>
      <AutonomySlider id="autonomie" />
    </div>

    <!-- Language -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="language">{{ t('settings.general.language') }}</label>
        <p class="setting-description">{{ t('settings.general.languageDescription') }}</p>
      </div>
      <select
        id="language"
        :value="prefs.language"
        class="setting-select"
        :title="canUpdatePreferences ? t('settings.general.languageTitle') : t('settings.general.languageLocalTitle')"
        @change="changeLanguage(($event.target as HTMLSelectElement).value)"
      >
        <option value="de">Deutsch</option><!-- i18n-ignore: language names are shown in their own language -->
        <option value="en">English</option>
      </select>
    </div>

    <!-- Default Corpus -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="defaultCorpus">{{ t('settings.general.defaultCorpus') }}</label>
        <p class="setting-description">{{ t('settings.general.defaultCorpusDescription') }}</p>
      </div>
      <select
        id="defaultCorpus"
        :value="prefs.defaultCorpus"
        class="setting-select"
        :disabled="!canUpdatePreferences"
        :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.general.saveDefaultCorpus')"
        @change="updatePreference('defaultCorpus', ($event.target as HTMLSelectElement).value)"
      >
        <option :value="DEFAULT_CORPUS_PREFERENCE">{{ t('settings.general.defaultOption') }}</option>
        <option v-for="corpus in corpusOptions" :key="corpus.name" :value="corpus.name">
          {{ corpus.name }}
        </option>
      </select>
    </div>

    <!-- Results Per Page -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="resultsPerPage">{{ t('settings.general.resultsPerPage') }}</label>
        <p class="setting-description">{{ t('settings.general.resultsPerPageDescription', { lines: formatNumber(kwicLoadWindow(prefs.resultsPerPage)) }) }}</p>
      </div>
      <select
        id="resultsPerPage"
        :value="prefs.resultsPerPage"
        class="setting-select"
        :disabled="!canUpdatePreferences"
        :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.general.saveResultsPerPage')"
        @change="updatePreference('resultsPerPage', parseInt(($event.target as HTMLSelectElement).value))"
      >
        <option :value="50">50</option>
        <option :value="100">100</option>
        <option :value="200">200</option>
        <option :value="500">500</option>
      </select>
    </div>

    <h3 class="section-title mt-8">{{ t('settings.general.behavior') }}</h3>

    <!-- Confirm Delete -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="confirmDelete">{{ t('settings.general.confirmDelete') }}</label>
        <p class="setting-description">{{ t('settings.general.confirmDeleteDescription') }}</p>
      </div>
      <label class="toggle">
        <input
          id="confirmDelete"
          type="checkbox"
          :checked="prefs.confirmDelete"
          :disabled="!canUpdatePreferences"
          :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.general.saveConfirmDelete')"
          @change="updatePreference('confirmDelete', ($event.target as HTMLInputElement).checked)"
        />
        <span class="toggle-slider" />
      </label>
    </div>

    <!-- Enable Shortcuts -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="enableShortcuts">{{ t('settings.general.enableShortcuts') }}</label>
        <p class="setting-description">{{ t('settings.general.enableShortcutsDescription') }}</p>
      </div>
      <label class="toggle">
        <input
          id="enableShortcuts"
          type="checkbox"
          :checked="prefs.enableShortcuts"
          :disabled="!canUpdatePreferences"
          :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.general.saveShortcuts')"
          @change="updatePreference('enableShortcuts', ($event.target as HTMLInputElement).checked)"
        />
        <span class="toggle-slider" />
      </label>
    </div>

    <!-- Background Research -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="backgroundResearch">{{ t('settings.general.backgroundResearch') }}</label>
        <p class="setting-description">
          {{ t('settings.general.backgroundResearchDescription') }}
        </p>
      </div>
      <label class="toggle">
        <input
          id="backgroundResearch"
          type="checkbox"
          :checked="prefs.backgroundResearch"
          :disabled="!canUpdatePreferences"
          :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.general.saveBackgroundResearch')"
          @change="updatePreference('backgroundResearch', ($event.target as HTMLInputElement).checked)"
        />
        <span class="toggle-slider" />
      </label>
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <label>{{ t('settings.general.tour') }}</label>
        <p class="setting-description">
          {{ t('settings.general.tourDescription') }}
        </p>
      </div>
      <button type="button" class="btn-secondary" @click="restartOnboarding">
        {{ t('settings.general.restartTour') }}
      </button>
    </div>

    <h3 class="section-title mt-8">{{ t('settings.general.privacy') }}</h3>

    <div class="setting-row setting-row--stacked">
      <div class="setting-info">
        <label>{{ t('settings.general.localProcessing') }}</label>
        <i18n-t keypath="settings.general.localProcessingDescription" tag="p" class="setting-description" scope="global">
          <template #variable><code>CANDYCONC_ENABLE_LLM_TRACE</code></template>
        </i18n-t>
        <ul v-if="observabilityLimits.length" class="privacy-list">
          <li v-for="limit in observabilityLimits" :key="limit">
            {{ limit }}
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.setting-row--block { flex-direction: column; align-items: stretch; gap: 0.5rem; }
@reference "../../style.css";

.settings-section {
  @apply space-y-4;
}

.section-title {
  @apply text-sm font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply mb-4;
}

.setting-row {
  @apply flex items-center justify-between gap-4;
  @apply py-3;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.setting-row--stacked {
  @apply items-start;
}

.setting-row:last-child {
  @apply border-b-0;
}

.setting-info {
  @apply flex-1;
}

.setting-info label {
  @apply block text-sm font-medium;
  @apply text-neutral-900 dark:text-neutral-100;
}

.setting-description {
  @apply text-xs text-neutral-500 dark:text-neutral-400 mt-0.5;
}

.setting-description code,
.privacy-list code {
  @apply rounded bg-neutral-100 px-1 py-0.5 font-mono text-[11px] text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.privacy-list {
  @apply mt-2 space-y-1 text-xs text-neutral-500 dark:text-neutral-400;
}

.privacy-list li {
  @apply leading-relaxed;
}

.btn-secondary {
  @apply rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium;
  @apply text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200 dark:hover:bg-neutral-800;
}

.setting-select {
  @apply px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm text-neutral-900 dark:text-neutral-100;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

/* Toggle Switch */
.toggle {
  @apply relative inline-block w-11 h-6 cursor-pointer;
}

.toggle input {
  @apply opacity-0 w-0 h-0;
}

.toggle-slider {
  @apply absolute inset-0 rounded-full;
  @apply bg-neutral-300 dark:bg-neutral-600;
  @apply transition-colors duration-200;
}

.toggle-slider::before {
  content: '';
  @apply absolute left-0.5 top-0.5;
  @apply w-5 h-5 rounded-full;
  @apply bg-white;
  @apply transition-transform duration-200;
}

.toggle input:checked + .toggle-slider {
  @apply bg-primary-500;
}

.toggle input:checked + .toggle-slider::before {
  @apply translate-x-5;
}
</style>
