<script setup lang="ts">
/**
 * SettingsPanel - Main settings container with tabs
 */
import { computed, onMounted, watch } from 'vue'
import SlideOver from '@/components/ui/SlideOver.vue'
import SettingsGeneral from './SettingsGeneral.vue'
import SettingsAppearance from './SettingsAppearance.vue'
import EmbeddingsManager from './EmbeddingsManager.vue'
import SettingsModelRoute from './SettingsModelRoute.vue'
import SystemInfo from './SystemInfo.vue'
import CorpusManagerContent from '@/components/corpus/CorpusManagerContent.vue'
import {
  EMBEDDING_MANAGEMENT_OPERATIONS,
  SETTINGS_PREFERENCE_OPERATIONS,
  SYSTEM_OPERATION_OPERATIONS,
  useSettingsStore,
} from '@/stores/settings'
import { useUiStore, type SettingsTab } from '@/stores/ui'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { Settings, Palette, Brain, Server, Database, Cpu } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  modelValue: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const settingsStore = useSettingsStore()
const uiStore = useUiStore()
const productCapabilities = useProductCapabilitiesStore()

interface SettingsTabDef {
  id: SettingsTab
  label: string
  icon: typeof Settings
  visible: boolean
  enabled: boolean
  disabledReason: string | null
}

const activeTab = computed<SettingsTab>({
  get: () => uiStore.settingsTab,
  set: (tab) => uiStore.setSettingsTab(tab),
})
const panelTitle = computed(() =>
  activeTab.value === 'corpora' ? t('settings.panel.corpusManager') : t('settings.panel.title')
)

// Tab labels are catalog keys, resolved when the tab list is computed.
function staticTab(id: SettingsTab, labelKey: string, icon: typeof Settings): SettingsTabDef {
  return { id, label: t(labelKey), icon, visible: true, enabled: true, disabledReason: null }
}

function capabilityTab(
  id: SettingsTab,
  labelKey: string,
  icon: typeof Settings,
  capabilityIds: string[],
): SettingsTabDef {
  const decisions = capabilityIds.map((capabilityId) =>
    productCapabilities.surfaceAvailability(capabilityId),
  )
  const visible = decisions.some((decision) => decision.visible)
  const enabled = decisions.some((decision) => decision.enabled)
  return {
    id,
    label: t(labelKey),
    icon,
    visible,
    enabled,
    disabledReason: enabled ? null : decisions.find((decision) => decision.disabledReason)?.disabledReason ?? null,
  }
}

const tabs = computed<SettingsTabDef[]>(() => [
  staticTab('general', 'settings.panel.tabGeneral', Settings),
  staticTab('appearance', 'settings.panel.tabAppearance', Palette),
  capabilityTab('corpora', 'settings.panel.tabCorpora', Database, ['corpus.catalogue', 'corpus.import']),
  capabilityTab('embeddings', 'settings.panel.tabEmbeddings', Brain, ['settings.embedding_management']),
  capabilityTab('modelroute', 'settings.panel.tabModelRoute', Cpu, ['settings.model_route']),
  capabilityTab('system', 'settings.panel.tabSystem', Server, ['admin.system_operations']),
].filter((tab) => tab.visible))

const enabledTabs = computed(() => tabs.value.filter((tab) => tab.enabled))
const canUseEmbeddings = computed(() =>
  productCapabilities.productOperationAvailability(EMBEDDING_MANAGEMENT_OPERATIONS.list, t('settings.panel.loadEmbeddings')).enabled
)
const canLoadPreferences = computed(() =>
  productCapabilities.productOperationAvailability(SETTINGS_PREFERENCE_OPERATIONS.read, t('settings.panel.loadPreferences')).enabled
)
const canUseSystemInfo = computed(() =>
  productCapabilities.productOperationAvailability(SYSTEM_OPERATION_OPERATIONS.info).enabled
)
const preferenceResetAvailability = computed(() =>
  productCapabilities.productOperationAvailability(SETTINGS_PREFERENCE_OPERATIONS.update)
)
const canResetPreferences = computed(() => preferenceResetAvailability.value.enabled)
const preferenceResetMessage = computed(() => preferenceResetAvailability.value.disabledReason)
onMounted(async () => {
  await productCapabilities.ensureAccessContext()
  settingsStore.init({
    loadPreferences: canLoadPreferences.value,
    loadEmbeddings: canUseEmbeddings.value,
    loadSystemInfo: canUseSystemInfo.value,
  })
})

watch(
  () => uiStore.corpusManagerOpen,
  (isOpen) => {
    if (isOpen && tabs.value.some((tab) => tab.id === 'corpora' && tab.enabled)) activeTab.value = 'corpora'
  },
  { immediate: true }
)

watch(tabs, (nextTabs) => {
  const current = nextTabs.find((tab) => tab.id === activeTab.value)
  if (!current?.enabled) {
    activeTab.value = enabledTabs.value[0]?.id ?? 'general'
  }
})

watch(canUseEmbeddings, (visible) => {
  if (visible) {
    void settingsStore.loadEmbeddings()
  }
})

watch(canUseSystemInfo, (visible) => {
  if (visible) {
    void settingsStore.loadSystemInfo()
  }
})

function updateOpen(value: boolean) {
  emit('update:modelValue', value)
  if (!value) uiStore.closeCorpusManager()
}

function selectTab(tab: SettingsTabDef) {
  if (!tab.enabled) {
    if (tab.disabledReason) uiStore.showToast(tab.disabledReason, 'warning')
    return
  }
  activeTab.value = tab.id
}

function resetPreferences() {
  if (!canResetPreferences.value) {
    uiStore.showToast(preferenceResetMessage.value ?? t('settings.panel.resetNotEnabled'), 'warning')
    return
  }
  void settingsStore.resetPreferences()
}
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    @update:model-value="updateOpen"
    :title="panelTitle"
    size="lg"
  >
    <!-- Tab Navigation -->
    <nav class="settings-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        class="settings-tab"
        :class="{ active: activeTab === tab.id, disabled: !tab.enabled }"
        :aria-disabled="!tab.enabled"
        :title="tab.disabledReason ?? tab.label"
        @click="selectTab(tab)"
      >
        <component :is="tab.icon" class="w-4 h-4" />
        <span>{{ tab.label }}</span>
        <span v-if="tab.disabledReason" class="tab-reason">{{ t('settings.panel.locked') }}</span>
      </button>
    </nav>

    <!-- Tab Content -->
    <div class="settings-content">
      <SettingsGeneral v-if="activeTab === 'general'" />
      <SettingsAppearance v-else-if="activeTab === 'appearance'" />
      <CorpusManagerContent v-else-if="activeTab === 'corpora'" />
      <EmbeddingsManager v-else-if="activeTab === 'embeddings'" />
      <SettingsModelRoute v-else-if="activeTab === 'modelroute'" />
      <SystemInfo v-else-if="activeTab === 'system'" />
    </div>

    <template v-if="activeTab !== 'corpora'" #footer>
      <div class="settings-footer">
        <button
          type="button"
          class="btn-reset"
          :disabled="!canResetPreferences"
          :title="!canResetPreferences ? preferenceResetMessage ?? t('settings.panel.notEnabled') : t('settings.panel.reset')"
          @click="resetPreferences"
        >
          {{ t('settings.panel.reset') }}
        </button>
      </div>
    </template>
  </SlideOver>
</template>

<style scoped>
@reference "../../style.css";

.settings-tabs {
  /* The tabs wrap onto a second row instead of scrolling sideways: in the
     512 px panel a scrolling row hid "Model connection" and "System". */
  @apply flex flex-wrap gap-x-1 mb-6;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply -mx-6 px-6;
}

.settings-tab {
  @apply flex flex-none items-center gap-2;
  @apply px-4 py-2.5;
  @apply text-sm font-medium;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply border-b-2 border-transparent;
  @apply transition-colors;
}

.settings-tab:hover {
  @apply text-neutral-900 dark:text-neutral-100;
}

.settings-tab.active {
  @apply text-primary-600 dark:text-primary-400;
  @apply border-primary-500;
}

.settings-tab.disabled {
  @apply opacity-50 cursor-not-allowed;
}

.tab-reason {
  @apply rounded-full bg-warning-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-700 dark:bg-warning-900/30 dark:text-warning-200;
}

.settings-content {
  @apply min-h-[400px];
}

.settings-footer {
  @apply flex justify-end;
}

.btn-reset {
  @apply px-4 py-2 text-sm font-medium;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply hover:text-error-600 dark:hover:text-error-400;
  @apply transition-colors;
}
</style>
