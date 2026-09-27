<script setup lang="ts">
/**
 * Die schmale Leiste am unteren Rand.
 *
 * Sie faehrt beim Turnstart von selbst ein und zeigt nur, WAS gerade
 * laeuft. Sie verdeckt die Arbeitsflaeche nicht und laesst sich mit einem
 * Klick zur ganzen Spur aufziehen.
 *
 * KEIN ANTEILSBALKEN WAEHREND DER ARBEIT. Die Zahl der Schritte steht nicht
 * vorher fest: der Copilot entscheidet waehrend des Turns, was er noch
 * braucht. Ein Balken, der bei 60 Prozent steht, waere eine Erfindung, und
 * eine, die man an der Wanduhr messen kann. Waehrend der Arbeit laeuft
 * deshalb eine unbestimmte Spur, ein Anteil erscheint erst danach.
 */
import { computed, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2, X, Loader2 } from 'lucide-vue-next'
import { useCopilotStore, type ChatMessage } from '@/stores/copilot'
import { useArbeitsspurStore } from '@/stores/arbeitsspur'
import { useArbeitsspur } from '@/composables/useArbeitsspur'
import { formatNumber } from '@/i18n/format'

const { t } = useI18n()
const copilotStore = useCopilotStore()
const spurStore = useArbeitsspurStore()

const nachricht = computed<ChatMessage | undefined>(() => {
  const id = spurStore.verfolgteNachricht
  const alle = copilotStore.messages.filter(m => m.role === 'assistant')
  if (id) return alle.find(m => m.id === id) ?? alle[alle.length - 1]
  return alle[alle.length - 1]
})

const spur = useArbeitsspur(toRef(nachricht, 'value') as never)
const { laufenderSchritt, werkzeuge, laeuft } = spur

/** Wieviele Abfragen bisher gelaufen sind. Eine Zahl, keine Quote. */
const gelaufen = computed(
  () => werkzeuge.value.filter(w => w.status !== 'running').length,
)
</script>

<template>
  <div class="leiste" role="status" aria-live="polite">
    <button
      type="button"
      class="leiste-flaeche"
      :title="t('copilot.traceBar.open')"
      @click="spurStore.vergroessern()"
    >
      <Loader2 v-if="laeuft" class="w-3.5 h-3.5 animate-spin shrink-0" aria-hidden="true" />
      <span class="leiste-text">
        <template v-if="laeuft">{{ laufenderSchritt || t('copilot.traceBar.working') }}</template>
        <template v-else>{{ t('copilot.traceBar.title') }}</template>
      </span>
      <span v-if="gelaufen" class="leiste-zahl">
        {{ t('copilot.traceBar.queries', { count: formatNumber(gelaufen) }, gelaufen) }}
      </span>
      <span v-if="laeuft" class="leiste-spur" aria-hidden="true"></span>
    </button>
    <button
      type="button"
      class="leiste-knopf"
      :title="t('copilot.traceBar.open')"
      @click="spurStore.vergroessern()"
    >
      <Maximize2 class="w-3.5 h-3.5" aria-hidden="true" />
      <span class="sr-only">{{ t('copilot.traceBar.open') }}</span>
    </button>
    <button
      type="button"
      class="leiste-knopf"
      :title="t('common.dialog.close')"
      @click="spurStore.schliessen()"
    >
      <X class="w-3.5 h-3.5" aria-hidden="true" />
      <span class="sr-only">{{ t('common.dialog.close') }}</span>
    </button>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.leiste {
  @apply flex items-center gap-1 pl-3 pr-1.5 py-1.5 shrink-0;
  @apply border-t border-neutral-200 dark:border-neutral-800;
  @apply bg-white/85 dark:bg-neutral-900/85 backdrop-blur;
}
.leiste-flaeche {
  @apply relative flex items-center gap-2 flex-1 min-w-0 text-left;
  @apply px-1 py-0.5 rounded transition-colors;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}
.leiste-text {
  @apply text-xs truncate;
  @apply text-neutral-700 dark:text-neutral-200;
}
.leiste-zahl {
  /* hell 500, dunkel 400: umgekehrt waren es 2,42 und 3,78 gegen die
     4,5:1 von WCAG AA. */
  @apply text-xs tabular-nums shrink-0;
  @apply text-neutral-500 dark:text-neutral-400;
}
/* Unbestimmte Spur: sie zeigt Leben, behauptet aber keinen Anteil. */
.leiste-spur {
  @apply absolute left-0 right-0 -bottom-1.5 h-px overflow-hidden;
  background-image: linear-gradient(
    90deg,
    transparent 0%,
    var(--color-primary-400) 50%,
    transparent 100%
  );
  background-size: 35% 100%;
  background-repeat: no-repeat;
  animation: leiste-wandern 1.6s ease-in-out infinite;
}
@keyframes leiste-wandern {
  from { background-position: -35% 0; }
  to { background-position: 135% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .leiste-spur { animation: none; opacity: 0.5; background-position: 50% 0; }
}
.leiste-knopf {
  @apply p-1.5 rounded transition-colors shrink-0;
  @apply text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100;
  @apply dark:text-neutral-400 dark:hover:text-neutral-50 dark:hover:bg-neutral-800;
}
</style>
