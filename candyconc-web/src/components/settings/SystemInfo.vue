<script setup lang="ts">
/**
 * SystemInfo - System status and admin tools
 */
import { computed, onMounted, ref } from 'vue'
import {
  SYSTEM_OPERATION_OPERATIONS,
  useSettingsStore,
} from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { corpusDisplayName } from '@/lib/corpusDisplayName'
import {
  Server,
  Database,
  HardDrive,
  Trash2,
  Clock,
  Cpu,
  AlertCircle,
  CheckCircle2,
  Loader2
} from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const settingsStore = useSettingsStore()
const uiStore = useUiStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()

const sysInfo = computed(() => settingsStore.systemInfo)
const systemInfoProvenance = computed(() => settingsStore.systemInfoProvenance)
const systemInfoIsFresh = computed(() => settingsStore.systemInfoIsFresh)
const systemInfoTrustMessage = computed(() =>
  systemInfoProvenance.value.freshness === 'fresh'
    ? null
    : systemInfoProvenance.value.message
)
const systemInfoAvailability = computed(() =>
  productCapabilities.productOperationAvailability(SYSTEM_OPERATION_OPERATIONS.info)
)
const clearCacheAvailability = computed(() =>
  productCapabilities.productOperationAvailability(SYSTEM_OPERATION_OPERATIONS.clearCache)
)
const canViewSystemInfo = computed(() => systemInfoAvailability.value.enabled)
const canClearCache = computed(() =>
  clearCacheAvailability.value.enabled && systemInfoIsFresh.value
)
const systemAccessMessage = computed(() => systemInfoAvailability.value.disabledReason)
const clearCacheAccessMessage = computed(() =>
  !systemInfoIsFresh.value
    ? t('settings.system.notFresh')
    : clearCacheAvailability.value.disabledReason
)

/**
 * The corpus card names the corpus the interface works with. The server
 * reports the active entry of its catalog, which a corpus chosen in the
 * interface does not change. That one appears as its own line when it
 * differs, and stands alone only while the catalog of the interface is not
 * loaded.
 */
const workingCorpus = computed(() => corpusCapabilities.activeSummary)
const workingCorpusName = computed(() => corpusDisplayName(workingCorpus.value, corpusCapabilities.activeCorpus))
const serverCatalogCorpus = computed(() => {
  const name = sysInfo.value.corpusName?.trim() ?? ''
  if (!name || !workingCorpus.value) return ''
  return name === workingCorpus.value.name ? '' : name
})

// A source checkout reports the version "unknown", which read as "vunknown".
const serverVersion = computed(() => {
  const version = sysInfo.value.backendVersion?.trim() ?? ''
  return /^\d/.test(version) ? `v${version}` : version
})

const isClearing = ref(false)

const faissStatusConfig = computed(() => {
  switch (sysInfo.value.faissStatus) {
    case 'ready':
      return { icon: CheckCircle2, class: 'text-success-500', label: t('settings.system.faissReady') }
    case 'building':
      return { icon: Loader2, class: 'text-warning-500 animate-spin', label: t('settings.system.faissBuilding') }
    case 'error':
      return { icon: AlertCircle, class: 'text-error-500', label: t('settings.system.faissError') }
    default:
      return { icon: AlertCircle, class: 'text-neutral-400', label: t('settings.system.faissUnavailable') }
  }
})

async function handleClearCache() {
  if (!canClearCache.value) {
    uiStore.showToast(clearCacheAccessMessage.value ?? t('settings.system.clearNotEnabled'), 'warning')
    return
  }
  isClearing.value = true
  const success = await settingsStore.clearCache()
  isClearing.value = false

  if (success) {
    uiStore.showToast(t('settings.system.cleared'), 'success')
  } else {
    uiStore.showToast(t('settings.system.clearFailed'), 'error')
  }
}

onMounted(() => {
  if (canViewSystemInfo.value) {
    void settingsStore.loadSystemInfo()
  }
})
</script>

<template>
  <div class="system-info">
    <div class="section-header">
      <Server class="w-5 h-5 text-primary-500" />
      <div>
        <h3 class="section-title">{{ t('settings.system.title') }}</h3>
        <p class="section-description">
          {{ t('settings.system.description') }}
        </p>
      </div>
    </div>

    <div v-if="systemAccessMessage" class="warning-box">
      <AlertCircle class="w-5 h-5 flex-shrink-0" />
      <p>{{ systemAccessMessage }}</p>
    </div>

    <div
      v-if="canViewSystemInfo && systemInfoTrustMessage"
      class="warning-box"
      data-testid="system-info-provenance"
    >
      <AlertCircle class="w-5 h-5 flex-shrink-0" />
      <p>{{ systemInfoTrustMessage }}</p>
    </div>

    <div v-if="canViewSystemInfo && !systemInfoIsFresh" class="empty-box">
      {{ t('settings.system.waitingForServer') }}
    </div>

    <!-- Info Cards -->
    <div v-if="canViewSystemInfo && systemInfoIsFresh" class="info-grid">
      <!-- Backend -->
      <div class="info-card">
        <div class="card-icon">
          <Cpu class="w-5 h-5" />
        </div>
        <div class="card-content">
          <h4>{{ t('settings.system.server') }}</h4>
          <p class="card-value">{{ serverVersion }}</p>
          <p class="card-meta">
            <Clock class="w-3.5 h-3.5" />
            {{ t('settings.system.uptime', { uptime: sysInfo.uptime }) }}
          </p>
        </div>
      </div>

      <!-- FAISS Index -->
      <div class="info-card">
        <div class="card-icon">
          <Database class="w-5 h-5" />
        </div>
        <div class="card-content">
          <h4>{{ t('settings.system.faissIndex') }}</h4>
          <p class="card-status">
            <component
              :is="faissStatusConfig.icon"
              class="w-4 h-4"
              :class="faissStatusConfig.class"
            />
            {{ faissStatusConfig.label }}
          </p>
          <p class="card-meta">{{ t('settings.system.vectors', { count: formatNumber(sysInfo.vectorCount) }) }}</p>
          <p v-if="sysInfo.faissDetail" class="card-meta text-error-500">
            {{ sysInfo.faissDetail }}
          </p>
        </div>
      </div>

      <!-- Corpus -->
      <div class="info-card">
        <div class="card-icon">
          <Database class="w-5 h-5" />
        </div>
        <div class="card-content">
          <template v-if="workingCorpus">
            <h4>{{ t('settings.system.workingCorpus') }}</h4>
            <p class="card-value">{{ workingCorpusName }}</p>
            <p class="card-meta">{{ t('settings.system.tokens', { count: formatNumber(workingCorpus.token_count) }) }}</p>
            <p v-if="serverCatalogCorpus" class="card-meta">{{ t('settings.system.serverCatalogActive', { name: serverCatalogCorpus }) }}</p>
          </template>
          <template v-else>
            <h4>{{ t('settings.system.serverCatalogCorpus') }}</h4>
            <p class="card-value">{{ sysInfo.corpusName }}</p>
            <p class="card-meta">{{ t('settings.system.tokens', { count: formatNumber(sysInfo.tokenCount) }) }}</p>
          </template>
        </div>
      </div>

      <!-- Cache -->
      <div class="info-card">
        <div class="card-icon">
          <HardDrive class="w-5 h-5" />
        </div>
        <div class="card-content">
          <h4>{{ t('settings.system.cache') }}</h4>
          <p class="card-value">{{ sysInfo.cacheSize }}</p>
          <p class="card-meta">{{ t('settings.system.temporaryData') }}</p>
        </div>
      </div>
    </div>

    <!-- Admin Actions -->
    <div v-if="canViewSystemInfo && systemInfoIsFresh" class="admin-section">
      <h4 class="admin-title">{{ t('settings.system.administration') }}</h4>

      <div class="admin-actions">
        <div class="action-item">
          <div class="action-info">
            <h5>{{ t('settings.system.clearCache') }}</h5>
            <p>{{ t('settings.system.clearCacheDescription') }}</p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            :icon="Trash2"
            :loading="isClearing"
            :disabled="!canClearCache"
            :title="!canClearCache ? clearCacheAccessMessage ?? t('settings.general.notEnabled') : t('settings.system.clearCache')"
            @click="handleClearCache"
          >
            {{ t('settings.system.clear') }}
          </Button>
        </div>

      </div>
    </div>

  </div>
</template>

<style scoped>
@reference "../../style.css";

.system-info {
  @apply space-y-6;
}

.section-header {
  @apply flex items-start gap-3;
  @apply pb-4 border-b border-neutral-200 dark:border-neutral-700;
}

.section-title {
  @apply text-base font-semibold;
  @apply text-neutral-900 dark:text-neutral-100;
}

.section-description {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

/* Info Grid */
.info-grid {
  @apply grid grid-cols-2 gap-3;
}

.info-card {
  @apply flex items-start gap-3;
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.card-icon {
  @apply p-2 rounded-lg;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply text-neutral-600 dark:text-neutral-300;
}

.card-content h4 {
  @apply text-xs font-medium uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
}

.card-value {
  @apply text-sm font-semibold;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply mt-0.5;
}

.card-status {
  @apply flex items-center gap-1.5;
  @apply text-sm font-medium;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply mt-0.5;
}

.card-meta {
  @apply flex items-center gap-1;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  @apply mt-1;
}

/* Admin Section */
.admin-section {
  @apply pt-4 border-t border-neutral-200 dark:border-neutral-700;
}

.admin-title {
  @apply text-xs font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply mb-3;
}

.admin-actions {
  @apply space-y-3;
}

.action-item {
  @apply flex items-center justify-between gap-4;
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.action-info h5 {
  @apply text-sm font-medium;
  @apply text-neutral-900 dark:text-neutral-100;
}

.action-info p {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  @apply mt-0.5;
}

/* Warning Box */
.warning-box {
  @apply flex items-start gap-3;
  @apply p-4 rounded-xl;
  @apply bg-warning-50 dark:bg-warning-900/20;
  @apply border border-warning-200 dark:border-warning-800;
  @apply text-warning-700 dark:text-warning-400;
  @apply text-sm;
}
</style>
