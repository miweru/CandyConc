<script setup lang="ts">
/**
 * ClusterRenderer - Generic renderer for clustering-related tool results
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Share2 } from 'lucide-vue-next'

interface ClusterPayload {
  status?: string
  clusters?: unknown[]
  plan?: Record<string, unknown>
  url?: string
}

interface Props {
  data: ClusterPayload
}

const props = defineProps<Props>()
const { t } = useI18n()

const clusterCount = computed(() => props.data.clusters?.length ?? 0)
const hasPlan = computed(() => !!props.data.plan && Object.keys(props.data.plan).length > 0)
</script>

<template>
  <div class="cluster-renderer">
    <div class="renderer-header">
      <Share2 class="w-4 h-4 text-primary-500" />
      <span class="font-medium">{{ t('copilot.renderers.clusterTitle') }}</span>
    </div>

    <div class="cluster-body">
      <p v-if="clusterCount > 0" class="cluster-line">
        {{ t('copilot.renderers.clustersCreated', { count: clusterCount }, clusterCount) }}
      </p>
      <p v-else-if="hasPlan" class="cluster-line">
        {{ t('copilot.renderers.reclusterPlan') }}
      </p>
      <p v-else class="cluster-line">
        {{ t('copilot.renderers.clusterDone') }}
      </p>

      <p v-if="props.data.status" class="cluster-meta">
        {{ t('copilot.renderers.clusterStatus', { status: props.data.status }) }}
      </p>
      <p v-if="props.data.url" class="cluster-meta">
        {{ t('copilot.renderers.clusterExport') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.cluster-renderer {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-hidden;
}

.renderer-header {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800;
}

.cluster-body {
  @apply px-3 py-4 space-y-1;
}

.cluster-line {
  @apply text-sm font-medium text-neutral-900 dark:text-neutral-100;
}

.cluster-meta {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}
</style>
