<script setup lang="ts">
/**
 * StatusBar - Footer bar with corpus info and status
 */
import { computed } from 'vue'
import { Database, Wifi, WifiOff, Command, RefreshCw, Clock } from 'lucide-vue-next'
import { useQueryStore } from '@/stores/query'
import { useSettingsStore } from '@/stores/settings'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useGlobalOnlineStatus } from '@/composables/useOnlineStatus'
import { formatNumber, formatTime } from '@/i18n/format'
import { useI18n } from 'vue-i18n'
import { corpusDisplayName } from '@/lib/corpusDisplayName'

const { t } = useI18n()

const queryStore = useQueryStore()
const settingsStore = useSettingsStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const { isOnline, isBackendReady, backendReadiness, copilotAvailable, isChecking, lastCheckTimestamp, forceCheck } =
  useGlobalOnlineStatus()

const corpusInfo = computed(() => settingsStore.systemInfo)
const corpusInfoIsFresh = computed(() => settingsStore.systemInfoIsFresh)
const corpusInfoProvenance = computed(() => settingsStore.systemInfoProvenance)
const activeCorpusSummary = computed(() => corpusCapabilities.activeSummary)
const displayedCorpusInfo = computed(() => {
  const summary = activeCorpusSummary.value
  if (summary) {
    return {
      verified: true,
      corpusName: corpusDisplayName(summary),
      tokenCount: corpusCapabilities.activeCorpusTokenCount,
      title: t('layout.statusBar.activeFromCatalogue'),
    }
  }
  if (corpusInfoIsFresh.value) {
    return {
      verified: true,
      corpusName: corpusInfo.value.corpusName,
      tokenCount: corpusInfo.value.tokenCount,
      title: t('layout.statusBar.freshSystemInfo'),
    }
  }
  return null
})
// First start without a corpus: no corpus is the state, not missing information.
const noCorpus = computed(() => corpusCapabilities.catalogEmpty)
const corpusInfoFallbackLabel = computed(() => {
  if (noCorpus.value) return t('layout.statusBar.noCorpus')
  if (corpusInfoProvenance.value.freshness === 'stale_cache') return t('layout.statusBar.systemInfoCached')
  if (corpusInfoProvenance.value.freshness === 'degraded') return t('layout.statusBar.systemInfoDegraded')
  return t('layout.statusBar.systemInfoMissing')
})
const lastCheckLabel = computed(() => {
  if (!lastCheckTimestamp.value) return t('layout.statusBar.never')
  return formatTime(lastCheckTimestamp.value, {
    hour: '2-digit',
    minute: '2-digit',
  })
})
const resultsLabel = computed(() => {
  if (!queryStore.hasResults && !queryStore.totalKnown && !queryStore.totalPartial) return ''
  if (queryStore.countIsLowerBound) {
    return t('layout.statusBar.hitsAtLeast', { count: formatNumber(queryStore.totalHits) }, queryStore.totalHits)
  }
  if (!queryStore.totalKnown) {
    return t('layout.statusBar.counting')
  }
  if (queryStore.rowsIncomplete) {
    return t(
      'layout.statusBar.hitsLoaded',
      { count: formatNumber(queryStore.totalHits), loaded: formatNumber(queryStore.results.length) },
      queryStore.totalHits,
    )
  }
  return t('layout.statusBar.hits', { count: formatNumber(queryStore.totalHits) }, queryStore.totalHits)
})
const backendStateLabel = computed(() => {
  if (!isOnline.value) return t('layout.statusBar.offline')
  if (backendReadiness.value === 'ready') return t('layout.statusBar.ready')
  if (backendReadiness.value === 'checking') return t('layout.statusBar.checking')
  if (backendReadiness.value === 'auth_required') return t('layout.statusBar.authRequired')
  if (backendReadiness.value === 'contract_unavailable') return t('layout.statusBar.notReady')
  return t('layout.statusBar.offline')
})
</script>

<template>
  <footer class="status-bar">
    <div class="status-left">
      <span
        class="corpus-info"
        :class="{ 'corpus-info--unverified': !displayedCorpusInfo?.verified && !noCorpus }"
        :title="displayedCorpusInfo?.title ?? (noCorpus ? undefined : corpusInfoProvenance.message)"
      >
        <Database class="w-3.5 h-3.5" />
        <template v-if="displayedCorpusInfo">
          <span>{{ displayedCorpusInfo.corpusName }}</span>
          <span class="separator">|</span>
          <span>{{ t('layout.statusBar.tokens', { count: formatNumber(displayedCorpusInfo.tokenCount) }) }}</span>
        </template>
        <span v-else>{{ corpusInfoFallbackLabel }}</span>
      </span>
    </div>

    <div class="status-center">
      <span v-if="resultsLabel" class="results-info">
        {{ resultsLabel }}
        <template v-if="queryStore.selectedCount > 0">
          <span class="separator">|</span>
          {{ t('layout.statusBar.selected', { count: queryStore.selectedCount }) }}
        </template>
      </span>
    </div>

    <div class="status-right">
      <span class="shortcut-hint">
        <Command class="w-3.5 h-3.5" />
        <span>{{ t('layout.statusBar.commandsHint') }}</span>
      </span>
      <span class="separator shortcut-separator">|</span>
      <span class="backend-status" :class="{ offline: !isBackendReady }">
        <span class="backend-label">{{ t('layout.statusBar.server') }}</span>
        <span class="backend-state">
          {{ backendStateLabel }}
        </span>
        <span class="backend-check">
          <Clock class="w-3.5 h-3.5" />
          <span>{{ lastCheckLabel }}</span>
        </span>
        <button class="backend-refresh" type="button" :disabled="isChecking" @click="forceCheck" :aria-label="t('layout.statusBar.recheck')">
          <RefreshCw class="w-3.5 h-3.5" :class="{ spinning: isChecking }" />
        </button>
      </span>
      <span class="separator">|</span>
      <span class="online-status" :class="{ offline: !isOnline }">
        <Wifi v-if="copilotAvailable" class="w-3.5 h-3.5" />
        <WifiOff v-else class="w-3.5 h-3.5" />
        <span v-if="!copilotAvailable" class="offline-label">{{ t('layout.statusBar.offline') }}</span>
      </span>
    </div>
  </footer>
</template>

<style scoped>
@reference "../../style.css";

.status-bar {
  /* Wrap at narrow widths so the right-hand status cluster never forces a
     page-level horizontal scroll at 375px (DESIGN-A11Y-01). */
  @apply flex flex-wrap items-center justify-between gap-x-3 gap-y-1;
  @apply px-4 py-2;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border-t border-neutral-200 dark:border-neutral-700;
  @apply text-xs text-neutral-600 dark:text-neutral-400;
}

.status-left,
.status-center,
.status-right {
  /* min-w-0 lets the groups shrink; flex-wrap keeps long status chips on-screen. */
  @apply flex flex-wrap items-center gap-2 min-w-0;
}

.corpus-info {
  @apply flex items-center gap-1.5;
}

.corpus-info--unverified {
  @apply text-warning-700 dark:text-warning-300;
}

.results-info {
  @apply font-medium text-neutral-700 dark:text-neutral-300;
}

.operation-summary {
  @apply rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 font-semibold text-blue-700;
  @apply hover:bg-blue-100 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300 dark:hover:bg-blue-900/50;
}

.operation-summary.has-error {
  @apply border-error-200 bg-error-50 text-error-700 dark:border-error-900 dark:bg-error-900/40 dark:text-error-300;
}

.separator {
  @apply text-neutral-400 dark:text-neutral-600;
}

/* A phone has no keyboard shortcut. Without the hint the bar keeps two rows. */
.shortcut-hint {
  @apply hidden md:flex items-center gap-1;
}

.shortcut-separator {
  @apply hidden md:inline;
}

.online-status {
  @apply flex items-center gap-1;
  @apply text-success-600 dark:text-success-400;
}

.online-status.offline {
  @apply text-error-600 dark:text-error-400;
}

.offline-label {
  @apply text-error-600 dark:text-error-400;
}

.backend-status {
  @apply inline-flex items-center gap-2 text-xs;
  @apply text-neutral-600 dark:text-neutral-300;
}

.backend-status.offline {
  @apply text-error-600 dark:text-error-400;
}

.backend-label {
  @apply font-medium;
}

.backend-state {
  @apply text-[11px] uppercase tracking-wide;
}

.backend-check {
  @apply inline-flex items-center gap-1 text-[11px];
}

.backend-refresh {
  @apply p-1 rounded-md;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
}

.spinning {
  @apply animate-spin;
}
</style>
