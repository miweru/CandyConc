<script setup lang="ts">
/**
 * SettingsAppearance - Theme and display settings
 */
import { computed } from 'vue'
import {
  SETTINGS_PREFERENCE_OPERATIONS,
  useSettingsStore,
  type UserPreferences,
} from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { Sun, Moon, Monitor, Palette } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const settingsStore = useSettingsStore()
const uiStore = useUiStore()
const productCapabilities = useProductCapabilitiesStore()
const prefs = computed(() => settingsStore.preferences)
const preferenceWriteAvailability = computed(() =>
  productCapabilities.productOperationAvailability(SETTINGS_PREFERENCE_OPERATIONS.update)
)
const canUpdatePreferences = computed(() => preferenceWriteAvailability.value.enabled)
const preferenceWriteMessage = computed(() => preferenceWriteAvailability.value.disabledReason)

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

const themeOptions = computed(() => [
  { value: 'light', label: t('settings.appearance.themeLight'), icon: Sun },
  { value: 'dark', label: t('settings.appearance.themeDark'), icon: Moon },
  { value: 'system', label: t('settings.appearance.themeSystem'), icon: Monitor },
  { value: 'pink', label: t('settings.appearance.themePink'), icon: Palette },
] as const)

const highlightColors = computed(() => [
  { value: 'yellow', label: t('settings.appearance.colorYellow'), class: 'bg-yellow-400' },
  { value: 'blue', label: t('settings.appearance.colorBlue'), class: 'bg-blue-400' },
  { value: 'green', label: t('settings.appearance.colorGreen'), class: 'bg-green-400' },
  { value: 'purple', label: t('settings.appearance.colorPurple'), class: 'bg-purple-400' },
] as const)
</script>

<template>
  <div class="settings-section">
    <h3 class="section-title">{{ t('settings.appearance.design') }}</h3>

    <!-- Theme -->
    <div class="setting-row">
      <div class="setting-info">
        <label>{{ t('settings.appearance.colorScheme') }}</label>
        <p class="setting-description">{{ t('settings.appearance.colorSchemeDescription') }}</p>
      </div>
      <div class="theme-buttons">
        <button
          v-for="option in themeOptions"
          :key="option.value"
          type="button"
          class="theme-btn"
          :class="{ active: uiStore.theme === option.value }"
          :aria-pressed="uiStore.theme === option.value"
          @click="uiStore.setTheme(option.value)"
        >
          <component :is="option.icon" class="w-4 h-4" />
          <span>{{ option.label }}</span>
        </button>
      </div>
    </div>

    <!-- Highlight Color -->
    <div class="setting-row">
      <div class="setting-info">
        <label>{{ t('settings.appearance.highlightColor') }}</label>
        <p class="setting-description">{{ t('settings.appearance.highlightColorDescription') }}</p>
      </div>
      <div class="color-buttons">
        <button
          v-for="color in highlightColors"
          :key="color.value"
          type="button"
          class="color-btn"
          :class="[color.class, { active: prefs.highlightColor === color.value }]"
          :disabled="!canUpdatePreferences"
          :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : color.label"
          @click="updatePreference('highlightColor', color.value)"
        />
      </div>
    </div>

    <h3 class="section-title mt-8">{{ t('settings.appearance.font') }}</h3>

    <!-- Font Family -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="fontFamily">{{ t('settings.appearance.fontFamily') }}</label>
        <p class="setting-description">{{ t('settings.appearance.fontFamilyDescription') }}</p>
      </div>
      <select
        id="fontFamily"
        :value="prefs.fontFamily"
        class="setting-select"
        :disabled="!canUpdatePreferences"
        :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.appearance.saveFontFamily')"
        @change="updatePreference('fontFamily', ($event.target as HTMLSelectElement).value as UserPreferences['fontFamily'])"
      >
        <option value="system">{{ t('settings.appearance.fontSystem') }}</option>
        <option value="mono">Monospace</option><!-- i18n-ignore: typeface name -->
      </select>
    </div>

    <!-- Font Size -->
    <div class="setting-row">
      <div class="setting-info">
        <label for="fontSize">{{ t('settings.appearance.fontSize') }}</label>
        <p class="setting-description">{{ t('settings.appearance.fontSizeDescription') }}</p>
      </div>
      <div class="size-buttons">
        <button
          type="button"
          class="size-btn"
          :class="{ active: prefs.fontSize === 'small' }"
          :disabled="!canUpdatePreferences"
          :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.appearance.saveSmall')"
          @click="updatePreference('fontSize', 'small')"
        >
          <span class="text-xs">A</span>
        </button>
        <button
          type="button"
          class="size-btn"
          :class="{ active: prefs.fontSize === 'medium' }"
          :disabled="!canUpdatePreferences"
          :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.appearance.saveMedium')"
          @click="updatePreference('fontSize', 'medium')"
        >
          <span class="text-sm">A</span>
        </button>
        <button
          type="button"
          class="size-btn"
          :class="{ active: prefs.fontSize === 'large' }"
          :disabled="!canUpdatePreferences"
          :title="!canUpdatePreferences ? preferenceWriteMessage ?? t('settings.general.notEnabled') : t('settings.appearance.saveLarge')"
          @click="updatePreference('fontSize', 'large')"
        >
          <span class="text-base">A</span>
        </button>
      </div>
    </div>

    <!-- Preview -->
    <div class="preview-section mt-8">
      <h3 class="section-title">{{ t('settings.appearance.preview') }}</h3>
      <div class="preview-box">
        <div class="preview-row">
          <span class="preview-left">{{ t('settings.appearance.preview1Left') }}</span>
          <span
            class="preview-match kwic-match"
          >{{ t('settings.appearance.previewMatch') }}</span>
          <span class="preview-right">{{ t('settings.appearance.preview1Right') }}</span>
        </div>
        <div class="preview-row">
          <span class="preview-left">{{ t('settings.appearance.preview2Left') }}</span>
          <span
            class="preview-match kwic-match"
          >{{ t('settings.appearance.previewMatch') }}</span>
          <span class="preview-right">{{ t('settings.appearance.preview2Right') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
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

.setting-select {
  @apply px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm text-neutral-900 dark:text-neutral-100;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

/* Theme Buttons */
.theme-buttons {
  @apply flex flex-wrap justify-end gap-1;
}

.theme-btn {
  @apply flex items-center gap-2;
  @apply px-3 py-2 rounded-lg;
  @apply text-sm font-medium;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply border border-transparent;
  @apply transition-all;
}

.theme-btn:hover {
  @apply text-neutral-900 dark:text-neutral-100;
}

.theme-btn.active {
  @apply bg-primary-50 dark:bg-primary-900/30;
  @apply text-primary-600 dark:text-primary-400;
  @apply border-primary-300 dark:border-primary-700;
}

/* Color Buttons */
.color-buttons {
  @apply flex gap-2;
}

.color-btn {
  @apply w-8 h-8 rounded-full;
  @apply border-2 border-transparent;
  @apply transition-all;
}

.color-btn:hover {
  @apply scale-110;
}

.color-btn.active {
  @apply ring-2 ring-offset-2 ring-primary-500;
}

/* Size Buttons */
.size-buttons {
  @apply flex;
  @apply border border-neutral-200 dark:border-neutral-700 rounded-lg overflow-hidden;
}

.size-btn {
  @apply px-4 py-2;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply border-r border-neutral-200 dark:border-neutral-700;
  @apply transition-colors;
}

.size-btn:last-child {
  @apply border-r-0;
}

.size-btn:hover {
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.size-btn.active {
  @apply bg-primary-100 dark:bg-primary-900/30;
  @apply text-primary-600 dark:text-primary-400;
}

/* Preview Section */
.preview-section {
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.preview-box {
  /* Typeface and size follow the preferences like the rest of the interface. */
  @apply space-y-2 mt-3;
  @apply text-sm;
}

.preview-row {
  @apply flex items-center gap-2;
}

.preview-left,
.preview-right {
  @apply text-neutral-500 dark:text-neutral-400;
}

.preview-match {
  @apply px-1;
}

</style>
