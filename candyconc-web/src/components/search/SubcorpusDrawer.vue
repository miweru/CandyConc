<script setup lang="ts">
/**
 * SubcorpusDrawer - Filter-Builder als Drawer
 */
import SlideOver from '@/components/ui/SlideOver.vue'
import SubcorpusPanel from '@/components/search/SubcorpusPanel.vue'
import { useUiStore } from '@/stores'
import { useI18n } from 'vue-i18n'

const uiStore = useUiStore()
const { t } = useI18n()
</script>

<template>
  <SlideOver v-model="uiStore.subcorpusOpen" size="lg" :title="t('subcorpus.drawer.title')">
    <div class="drawer-body">
      <SubcorpusPanel variant="drawer" />
    </div>
  </SlideOver>
</template>

<style scoped>
@reference "../../style.css";

.drawer-body {
  @apply space-y-4;
}
</style>
