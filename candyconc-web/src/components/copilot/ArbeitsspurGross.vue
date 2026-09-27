<script setup lang="ts">
/**
 * Die Arbeitsspur in voller Breite.
 *
 * Sie erklaert einer fachlich nicht vertrauten Person, WAS der Copilot
 * getan hat, und zwar waehrend er es tut. Sie ist ausdruecklich KEINE
 * Debug-Ansicht und ausdruecklich kein Guetesiegel.
 *
 * DER PRUEFSTEIN fuer jede Angabe hier: stuende sie genauso da, wenn die
 * Antwort falsch waere? Wenn nein, gehoert sie nicht hierher. Eine
 * Selbstnote erscheint auch dann gruen, wenn die Antwort falsch ist, und
 * ist damit genau dort wertlos, wo sie gebraucht wuerde.
 *
 * WAS DESHALB FEHLT, obwohl es technisch moeglich waere:
 *
 * - Keine Verknuepfung zwischen einer Zahl der Antwort und einem Schritt.
 *   `citations` ist ein Phantomfeld: das Frontend liest es, kein Emitter im
 *   Orchestrator setzt es je. Schritte unter eine Ueberschrift "woher die
 *   Zahlen kommen" zu stellen liesse den Leser eine Verbindung schliessen,
 *   die es nicht gibt.
 * - Keine Zahl verworfener Aussagen. `rejected_claim_count` ist auf drei
 *   von vier Emissionspfaden die Literalzahl 0, und zwar genau auf denen,
 *   wo gar nicht geprueft wurde. "0 verworfen" hiesse dort "nichts
 *   gefunden" und bedeutete "nicht gesucht".
 * - Kein "geprueft", kein Haekchen, kein Prozentwert.
 *
 * Was bleibt, ist die Arbeit selbst: welche Abfragen liefen, mit welchen
 * Worten, mit welchem Ergebnis, und was die deterministischen Wachen aus
 * der Antwort entfernt haben.
 */
import { computed, onMounted, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Minimize2, X, Circle, Loader2, AlertTriangle, ChevronRight } from 'lucide-vue-next'
import { useCopilotStore, copilotRecipeLabel, type ChatMessage } from '@/stores/copilot'
import { useArbeitsspurStore } from '@/stores/arbeitsspur'
import { useArbeitsspur, type SpurWerkzeug } from '@/composables/useArbeitsspur'
import { useCopilotRezepteStore } from '@/stores/copilotRezepte'
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

const frage = computed(() => {
  const alle = copilotStore.messages
  const i = alle.findIndex(m => m.id === nachricht.value?.id)
  for (let k = i - 1; k >= 0; k--) {
    if (alle[k]?.role === 'user') return alle[k]?.content ?? ''
  }
  return ''
})

const spur = useArbeitsspur(toRef(nachricht, 'value') as never)
const { stufen, laufenderSchritt, steckbrief, wachen, laeuft, abgebrochen } = spur

const rezepteStore = useCopilotRezepteStore()
onMounted(() => { void rezepteStore.laden() })

const rezept = computed(() => {
  const id = nachricht.value?.usage?.recipeId
  return id === undefined ? '' : copilotRecipeLabel(id)
})

/**
 * Das gewaehlte Verfahren, wie das Backend es beschreibt.
 *
 * Ohne Verzeichnis (Alt-Backend, oder die Route ist nicht erreichbar)
 * bleibt es leer, und die Stufe sagt weiterhin nur, DASS eingeordnet
 * wurde. Eine erfundene Beschreibung waere schlimmer als eine knappe.
 */
const verfahren = computed(() => {
  const id = nachricht.value?.usage?.recipeId
  return id ? rezepteStore.rezept(id) : undefined
})

const teilantwort = computed(() => nachricht.value?.usage?.partial === true)
const zeitlimit = computed(() => nachricht.value?.usage?.timeout ?? '')

const entfernt = computed(() => wachen.value.filter(w => w.entfernung))
const hinweise = computed(() => wachen.value.filter(w => !w.entfernung))

function zahl(n: number): string {
  return formatNumber(n, { maximumFractionDigits: 1 })
}

function dauerText(sekunden: number | undefined): string {
  if (sekunden === undefined) return ''
  if (sekunden < 90) return `${zahl(sekunden)} s`
  return `${zahl(sekunden / 60)} min`
}

function werkzeugZustand(w: SpurWerkzeug): string {
  if (w.uebersprungen) return t('copilot.researchTrace.stateSkipped')
  if (w.wiederverwendet) return t('copilot.researchTrace.stateCached')
  if (w.status === 'running') return t('copilot.researchTrace.stateRunning')
  if (w.status === 'error') return t('copilot.researchTrace.stateFailed')
  return ''
}
</script>

<template>
  <section class="spur" :aria-label="t('copilot.researchTrace.aria')">
    <header class="spur-kopf">
      <div class="spur-kopf-text">
        <p class="spur-frage">{{ frage || t('copilot.researchTrace.questionFallback') }}</p>
        <p class="spur-lage">
          <template v-if="laeuft">
            <Loader2 class="w-3.5 h-3.5 animate-spin shrink-0" aria-hidden="true" />
            <span>{{ laufenderSchritt || t('copilot.researchTrace.working') }}</span>
          </template>
          <template v-else-if="abgebrochen">{{ t('copilot.researchTrace.notFinished') }}</template>
          <template v-else-if="teilantwort">
            {{ t('copilot.researchTrace.partialAnswer') }}<template v-if="zeitlimit"> · {{ t('copilot.researchTrace.timeLimit', { limit: zeitlimit }) }}</template>
          </template>
          <template v-else>{{ t('copilot.researchTrace.completed') }}</template>
          <template v-if="rezept"> · {{ rezept }}</template>
        </p>
      </div>
      <div class="spur-knoepfe">
        <button type="button" class="spur-knopf" :title="t('copilot.researchTrace.minimize')" @click="spurStore.verkleinern()">
          <Minimize2 class="w-4 h-4" aria-hidden="true" />
          <span class="sr-only">{{ t('copilot.researchTrace.minimize') }}</span>
        </button>
        <button type="button" class="spur-knopf" :title="t('common.dialog.close')" @click="spurStore.schliessen()">
          <X class="w-4 h-4" aria-hidden="true" />
          <span class="sr-only">{{ t('common.dialog.close') }}</span>
        </button>
      </div>
    </header>

    <div class="spur-koerper">
      <!-- Die Schritte -->
      <ol v-if="stufen.length" class="stufen">
        <li v-for="(s, i) in stufen" :key="`${s.stufe}-${i}`" class="stufe">
          <span class="stufe-schiene" aria-hidden="true">
            <Loader2
              v-if="laeuft && s.dauer === undefined"
              class="stufe-knoten stufe-knoten-laeuft animate-spin"
            />
            <Circle v-else class="stufe-knoten" />
          </span>
          <div class="stufe-inhalt">
            <div class="stufe-kopf">
              <h3 class="stufe-titel">{{ s.titel }}</h3>
              <span class="stufe-dauer">
                <template v-if="s.dauer !== undefined">{{ dauerText(s.dauer) }}</template>
                <template v-else-if="laeuft">{{ t('copilot.researchTrace.stageRunning') }}</template>
                <template v-else>{{ t('copilot.researchTrace.stageNoEnd') }}</template>
              </span>
            </div>
            <p v-if="s.was" class="stufe-was">{{ s.was }}</p>

            <!-- Was der Copilot verstanden hat, wenn das Verzeichnis es sagt -->
            <div v-if="s.stufe === 'Vorlauf' && verfahren" class="verfahren">
              <p class="verfahren-name">{{ verfahren.name }}</p>
              <p class="verfahren-einsatz">{{ verfahren.einsatz }}</p>
              <ol v-if="verfahren.schritte.length" class="verfahren-schritte">
                <li v-for="(z, k) in verfahren.schritte" :key="k">{{ z }}</li>
              </ol>
            </div>

            <!-- Die einzelnen Abfragen dieser Stufe -->
            <ul v-if="s.werkzeuge.length" class="schritte">
              <li
                v-for="w in s.werkzeuge"
                :key="w.id"
                class="schritt"
                :class="{
                  'ist-blass': w.wiederverwendet || w.uebersprungen,
                  'ist-fehler': w.status === 'error',
                }"
              >
                <details>
                  <summary class="schritt-kopf">
                    <ChevronRight class="schritt-pfeil" aria-hidden="true" />
                    <span class="schritt-name">{{ w.schritt }}</span>
                    <code v-if="w.abfrage" class="schritt-abfrage">{{ w.abfrage }}</code>
                    <span v-if="w.kennzahl" class="schritt-zahl">
                      {{ formatNumber(w.kennzahl.wert) }}
                      <span class="schritt-einheit">{{ w.kennzahl.einheit }}</span>
                    </span>
                    <span v-if="werkzeugZustand(w)" class="schritt-zustand">
                      {{ werkzeugZustand(w) }}
                    </span>
                  </summary>
                  <div class="schritt-detail">
                    <p class="schritt-erklaerung">{{ w.erklaerung }}</p>
                    <p v-if="w.wiederverwendet" class="schritt-warnung">
                      {{ t('copilot.researchTrace.cachedNote') }}
                    </p>
                    <p v-if="w.uebersprungen" class="schritt-warnung">
                      {{ t('copilot.researchTrace.skippedNote') }}
                    </p>
                    <p v-if="w.fehler" class="schritt-warnung">{{ w.fehler }}</p>
                    <dl v-if="Object.keys(w.argumente).length" class="schritt-args">
                      <template v-for="(wert, feld) in w.argumente" :key="feld">
                        <dt>{{ feld }}</dt>
                        <dd><code>{{ typeof wert === 'string' ? wert : JSON.stringify(wert) }}</code></dd>
                      </template>
                    </dl>
                    <p class="schritt-technisch">
                      {{ t('copilot.researchTrace.tool') }} <code>{{ w.technisch }}</code><template
                        v-if="w.dauerMs !== undefined"
                      > · {{ zahl(w.dauerMs / 1000) }} s</template>
                    </p>
                  </div>
                </details>
              </li>
            </ul>
          </div>
        </li>
      </ol>

      <p v-else class="spur-leer">
        {{ t('copilot.researchTrace.empty') }}
      </p>

      <!-- Methodensteckbrief, woertlich wie das Backend ihn gebaut hat -->
      <section v-if="steckbrief.length" class="block">
        <h3 class="block-titel">{{ t('copilot.researchTrace.methodTitle') }}</h3>
        <p class="block-was">
          {{ t('copilot.researchTrace.methodText') }}
        </p>
        <dl class="steckbrief">
          <template v-for="z in steckbrief" :key="z.bezeichnung">
            <dt>{{ z.bezeichnung }}</dt>
            <dd>
              <span v-for="(a, i) in z.angaben" :key="i" class="angabe">{{ a }}</span>
            </dd>
          </template>
        </dl>
      </section>

      <!-- Was die Wachen entfernt haben -->
      <section v-if="entfernt.length" class="block">
        <h3 class="block-titel">{{ t('copilot.researchTrace.removedTitle') }}</h3>
        <p class="block-was">
          {{ t('copilot.researchTrace.removedText') }}
        </p>
        <ul class="wachen">
          <li v-for="(w, i) in entfernt" :key="i">{{ w.text }}</li>
        </ul>
      </section>

      <section v-if="hinweise.length" class="block">
        <h3 class="block-titel">{{ t('copilot.researchTrace.systemNotes') }}</h3>
        <ul class="wachen wachen-leise">
          <li v-for="(w, i) in hinweise" :key="i">{{ w.text }}</li>
        </ul>
      </section>

      <section v-if="teilantwort" class="block block-grenze">
        <h3 class="block-titel">
          <AlertTriangle class="w-4 h-4 shrink-0" aria-hidden="true" />
          {{ t('copilot.researchTrace.unfinishedTitle') }}
        </h3>
        <p class="block-was">
          {{ t('copilot.researchTrace.unfinishedText') }}
        </p>
      </section>
    </div>
  </section>
</template>

<style scoped>
@reference "../../style.css";

.spur {
  @apply h-full flex flex-col overflow-hidden;
  @apply bg-neutral-50 dark:bg-neutral-900;
}

.spur-kopf {
  @apply flex items-start justify-between gap-4 px-6 py-4 shrink-0;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-white/70 dark:bg-neutral-900/70 backdrop-blur;
}
.spur-kopf-text { @apply min-w-0; }
.spur-frage {
  @apply text-sm font-medium truncate;
  @apply text-neutral-900 dark:text-neutral-100;
}
.spur-lage {
  @apply mt-1 flex items-center gap-1.5 text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}
.spur-knoepfe { @apply flex items-center gap-1 shrink-0; }
.spur-knopf {
  @apply p-1.5 rounded-md transition-colors;
  @apply text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100;
  @apply dark:text-neutral-400 dark:hover:text-neutral-100 dark:hover:bg-neutral-800;
}

.spur-koerper { @apply flex-1 overflow-y-auto px-6 py-5 space-y-6; }

/* --- Die Stufen als Schiene ------------------------------------------- */
.stufen { @apply space-y-0; }
.stufe { @apply flex gap-4; }
.stufe-schiene {
  @apply relative flex justify-center w-4 shrink-0;
}
/* Die durchgehende Linie zwischen den Knoten. */
.stufe:not(:last-child) .stufe-schiene::after {
  content: '';
  @apply absolute top-5 bottom-0 w-px;
  @apply bg-neutral-200 dark:bg-neutral-700;
}
.stufe-knoten {
  @apply w-3.5 h-3.5 mt-1.5 shrink-0 relative z-10;
  @apply text-neutral-300 dark:text-neutral-600;
  fill: currentColor;
}
.stufe-knoten-laeuft {
  @apply text-primary-500 dark:text-primary-400;
  fill: none;
}
.stufe-inhalt { @apply flex-1 min-w-0 pb-6; }
.stufe-kopf { @apply flex items-baseline justify-between gap-3; }
.stufe-titel {
  @apply text-sm font-semibold;
  @apply text-neutral-900 dark:text-neutral-100;
}
.stufe-dauer {
  /* hell 500 (4,54:1), dunkel 400 (7,11:1). Umgekehrt waren es 2,42 und
     3,78, beides unter den 4,5:1 von WCAG AA. */
  @apply text-xs tabular-nums shrink-0;
  @apply text-neutral-500 dark:text-neutral-400;
}
.stufe-was {
  @apply mt-0.5 text-xs max-w-prose;
  @apply text-neutral-500 dark:text-neutral-400;
}
/* Das gewaehlte Verfahren: was der Copilot verstanden hat, und wonach er
   deshalb vorgeht. */
.verfahren {
  @apply mt-2 rounded-lg border px-3 py-2 max-w-prose;
  @apply border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-800/40;
}
.verfahren-name {
  @apply text-xs font-medium;
  @apply text-neutral-900 dark:text-neutral-100;
}
.verfahren-einsatz {
  @apply mt-0.5 text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}
.verfahren-schritte {
  @apply mt-2 space-y-0.5 text-xs list-decimal pl-4;
  @apply text-neutral-600 dark:text-neutral-300;
}

/* --- Die einzelnen Abfragen -------------------------------------------- */
.schritte { @apply mt-3 space-y-1.5; }
.schritt {
  @apply rounded-lg border transition-colors;
  @apply border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-800/40;
}
.schritt:hover { @apply border-neutral-300 dark:border-neutral-700; }
/* Zwischenspeicher und uebersprungen werden abgesetzt: sie sind keine
   Arbeit. NICHT ueber Deckkraft, die macht den Text unlesbar und traegt
   die Aussage ohnehin nicht. Sie steht im Wortlaut daneben. */
.schritt.ist-blass {
  @apply border-dashed;
  @apply bg-neutral-100 dark:bg-neutral-800/70;
}
.schritt.ist-blass .schritt-name {
  @apply font-normal text-neutral-600 dark:text-neutral-300;
}
.schritt.ist-fehler { @apply border-amber-300 dark:border-amber-800; }

.schritt-kopf {
  @apply flex flex-wrap items-baseline gap-x-2.5 gap-y-1 px-3 py-2;
  @apply cursor-pointer select-none list-none;
}
.schritt-kopf::-webkit-details-marker { display: none; }
/* Ohne Andeutung erkennt niemand, dass die Zeile mehr traegt. */
.schritt-pfeil {
  @apply w-3.5 h-3.5 shrink-0 transition-transform;
  @apply text-neutral-500 dark:text-neutral-400;
}
details[open] > .schritt-kopf .schritt-pfeil { @apply rotate-90; }
@media (prefers-reduced-motion: reduce) {
  .schritt-pfeil { transition: none; }
}
.schritt-name {
  @apply text-xs font-medium;
  @apply text-neutral-800 dark:text-neutral-100;
}
.schritt-abfrage {
  @apply px-1.5 py-0.5 rounded text-xs font-mono truncate max-w-[18rem];
  @apply bg-neutral-100 dark:bg-neutral-700/60;
  @apply text-neutral-700 dark:text-neutral-200;
}
.schritt-zahl {
  @apply ml-auto text-xs font-semibold tabular-nums shrink-0;
  @apply text-neutral-900 dark:text-neutral-50;
}
.schritt-einheit {
  /* Die Einheit tritt hinter die Zahl zurueck, aber ueber eine Farbe,
     nicht ueber Deckkraft: 60 Prozent auf neutral-900 ergeben rund 3:1.
     Die Einheit sagt, WAS gezaehlt wurde, sie ist nicht Beiwerk. */
  @apply font-normal text-neutral-500 dark:text-neutral-400;
}
.schritt-zustand {
  @apply text-xs shrink-0;
  @apply text-neutral-600 dark:text-neutral-300;
}

.schritt-detail {
  @apply px-3 pb-3 pt-1 space-y-2 text-xs;
  @apply border-t border-neutral-100 dark:border-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
}
.schritt-erklaerung { @apply max-w-prose; }
.schritt-warnung {
  @apply px-2 py-1.5 rounded max-w-prose;
  @apply bg-amber-50 dark:bg-amber-950/40;
  @apply text-amber-900 dark:text-amber-200;
}
.schritt-args { @apply grid grid-cols-[auto_1fr] gap-x-3 gap-y-1; }
.schritt-args dt {
  @apply font-mono text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}
.schritt-args dd { @apply min-w-0; }
.schritt-args code {
  @apply font-mono text-[0.7rem] break-all;
}
.schritt-technisch {
  /* Keine Deckkraft: sie halbiert den Kontrast. Der technische Name soll
     zurueckhaltend sein, nicht unlesbar. Das eigene Versprechen lautet
     "nichts wird versteckt". */
  @apply text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}
.schritt-technisch code { @apply font-mono; }

/* --- Bloecke ----------------------------------------------------------- */
.block {
  @apply rounded-xl border p-4;
  @apply border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-800/40;
}
.block-grenze { @apply border-amber-300 dark:border-amber-800/70; }
.block-titel {
  @apply flex items-center gap-2 text-sm font-semibold;
  @apply text-neutral-900 dark:text-neutral-100;
}
.block-was {
  @apply mt-1 mb-3 text-xs max-w-prose;
  @apply text-neutral-500 dark:text-neutral-400;
}
.steckbrief {
  @apply grid gap-x-6 gap-y-1.5 text-xs;
  grid-template-columns: minmax(8rem, auto) 1fr;
}
.steckbrief dt {
  @apply text-neutral-500 dark:text-neutral-400;
}
.steckbrief dd { @apply flex flex-wrap gap-1.5; }
.angabe {
  @apply px-1.5 py-0.5 rounded text-xs tabular-nums;
  @apply bg-neutral-100 dark:bg-neutral-700/60;
  @apply text-neutral-800 dark:text-neutral-100;
}
.wachen { @apply space-y-1 text-xs list-disc pl-4; }
.wachen li { @apply text-neutral-700 dark:text-neutral-200; }
.wachen-leise li { @apply text-neutral-500 dark:text-neutral-400; }

.spur-leer {
  @apply text-xs italic;
  @apply text-neutral-500 dark:text-neutral-400;
}
</style>
