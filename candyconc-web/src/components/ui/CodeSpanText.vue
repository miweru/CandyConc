<script setup lang="ts">
/**
 * An explanation text whose backtick spans render as code. The text is
 * rendered as text nodes and code elements, never as HTML.
 */
import { computed } from 'vue'
import { splitCodeSpans } from '@/lib/codeSpans'

const props = defineProps<{ text: string }>()
const segments = computed(() => splitCodeSpans(props.text))
</script>

<template>
  <template v-for="(segment, index) in segments" :key="index"><code v-if="segment.code" class="explanation-code">{{ segment.text }}</code><template v-else>{{ segment.text }}</template></template>
</template>

<style scoped>
.explanation-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
  padding: 0.05rem 0.3rem;
  border-radius: 0.25rem;
  background: rgba(115, 115, 115, 0.12);
  overflow-wrap: anywhere;
}
</style>
