<script setup lang="ts">
/**
 * ChatMessage - Single message in the chat
 */
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatMessage as ChatMessageType } from '@/stores'
import { copilotRecipeLabel } from '@/stores/copilot'
import { User, Sparkles, Loader2, Info } from 'lucide-vue-next'
import ToolCallResult from './ToolCallResult.vue'
import { renderMarkdown } from '@/utils/markdown'
import { belegChipsEinsetzen, type BelegQuelle } from '@/utils/belege'
import { evidenceOpensKwic, evidenceSearch, evidenceToolCallId } from '@/utils/evidenceTarget'
import {
  toolCallHasComputedEvidenceCandidate,
  toolResultHasSyntaxDiagnostic,
} from '@/lib/copilotToolRuntime'
import { formatNumber, formatTime } from '@/i18n/format'
import { copilotStageLabel } from '@/lib/copilotKlartext'

interface Props {
  message: ChatMessageType
}

const props = defineProps<Props>()
const { t } = useI18n()

const isUser = computed(() => props.message.role === 'user')
const isAssistant = computed(() => props.message.role === 'assistant')
const isSystem = computed(() => props.message.role === 'system')
const isAssistantError = computed(() => isAssistant.value && props.message.error === true)
const hasToolEvidence = computed(() =>
  (props.message.toolCalls ?? []).some(toolCallHasComputedEvidenceCandidate)
)
const hasSyntaxDiagnostic = computed(() =>
  (props.message.toolCalls ?? []).some(toolCall => toolResultHasSyntaxDiagnostic(toolCall.result))
)
const hasCorpusToolEvidence = computed(() =>
  (props.message.toolCalls ?? []).some(toolCall =>
    toolCallHasComputedEvidenceCandidate(toolCall)
    && !toolResultHasSyntaxDiagnostic(toolCall.result)
  )
)
const toolEvidenceLabel = computed(() => {
  if (hasCorpusToolEvidence.value) return t('copilot.chatMessage.evidenceComputed')
  if (hasSyntaxDiagnostic.value) return t('copilot.chatMessage.evidenceSyntax')
  return t('copilot.chatMessage.evidenceNone')
})
const toolEvidenceAria = computed(() => toolEvidenceLabel.value)
const toolEvidenceNote = computed(() => {
  if (hasCorpusToolEvidence.value) return t('copilot.chatMessage.evidenceNoteComputed')
  if (hasSyntaxDiagnostic.value) {
    return t('copilot.chatMessage.evidenceNoteSyntax')
  }
  return t('copilot.chatMessage.evidenceNoteNone')
})
const assistantClaimLabel = computed(() => isAssistantError.value
  ? t('copilot.chatMessage.claimError')
  : t('copilot.chatMessage.claimInterpretation'))
const assistantClaimAria = computed(() => isAssistantError.value
  ? t('copilot.chatMessage.claimError')
  : t('copilot.chatMessage.claimOutput'))
const assistantClaimNote = computed(() => {
  if (isAssistantError.value) {
    return t('copilot.chatMessage.claimNoteError')
  }
  if (hasSyntaxDiagnostic.value && !hasCorpusToolEvidence.value) {
    return t('copilot.chatMessage.claimNoteSyntax')
  }
  return hasToolEvidence.value
    ? t('copilot.chatMessage.claimNoteTools')
    : t('copilot.chatMessage.claimNoteFree')
})

const formattedTime = computed(() => {
  const date = new Date(props.message.timestamp)
  return formatTime(date, { hour: '2-digit', minute: '2-digit' })
})

// Dezente Stufenanzeige (`copilot.status`) nur an der laufenden Message.
const streamStatus = computed(() => {
  if (!props.message.isStreaming) return null
  const status = props.message.status
  return status?.stage ? status : null
})
// Rezept-Transparenz: traegt der Status ein recipe_id-Feld, wird der
// humanisierte Rezeptname vorangestellt ('Rezept: Kontrast · Werkzeuge').
// Ohne das Feld (Alt-Backend) bleibt die reine Stufenanzeige unveraendert.
const streamStatusLabel = computed(() => {
  const status = streamStatus.value
  if (!status) return ''
  const stagePart = `${copilotStageLabel(status.stage)}…`
  if (status.recipeId === undefined) return stagePart
  return t('copilot.chatMessage.recipeStatus', {
    recipe: copilotRecipeLabel(status.recipeId),
    stage: stagePart,
  })
})

// Fortschrittsbalken (ANFORDERUNG vom 2026-09-01: "und er hat dann auch so
// ne progressbar"). Das Backend traegt den Anteil im copilot.status-Ereignis
// mit, also braucht es keine zweite Abfrage.
//
// Faellt das Feld weg (aelteres Backend), gibt es KEINEN Balken statt eines
// falschen: ein Balken, der raet, ist schlimmer als eine Textzeile.
const streamFortschritt = computed(() => {
  const status = streamStatus.value as { fortschritt?: { schritt?: number; von?: number; anteil?: number } } | null
  const f = status?.fortschritt
  if (!f || typeof f.anteil !== 'number' || !Number.isFinite(f.anteil)) return null
  const anteil = Math.min(1, Math.max(0, f.anteil))
  return {
    anteil,
    prozent: Math.round(anteil * 100),
    schritt: Number(f.schritt ?? 0),
    von: Number(f.von ?? 0),
  }
})

function formatSeconds(value: number): string {
  return formatNumber(value, { maximumFractionDigits: 1 })
}

// Aufwands-Fusszeile aus `copilot.done` (z.B. "Kontrast · 3 LLM-Aufrufe · 24 s").
// Der Rezeptname steht vor der Call-Bilanz, sofern das Backend ihn meldet.
const usageLabel = computed(() => {
  const usage = props.message.usage
  if (!usage) return ''
  const parts: string[] = []
  if (usage.recipeId !== undefined) {
    parts.push(copilotRecipeLabel(usage.recipeId))
  }
  if (typeof usage.llmCalls === 'number') {
    parts.push(t('copilot.chatMessage.llmCalls', { count: formatNumber(usage.llmCalls) }, usage.llmCalls))
  }
  if (typeof usage.elapsedS === 'number') {
    parts.push(`${formatSeconds(usage.elapsedS)} s`)
  }
  if (typeof usage.llmSeconds === 'number') {
    parts.push(t('copilot.chatMessage.modelSeconds', { seconds: formatSeconds(usage.llmSeconds) }))
  }
  if (usage.partial) parts.push(t('copilot.chatMessage.partialAnswer'))
  return parts.join(' · ')
})

// Detailwerte als Tooltip, damit die Fusszeile unaufdringlich bleibt.
const usageTitle = computed(() => {
  const usage = props.message.usage
  if (!usage) return ''
  const parts: string[] = []
  if (typeof usage.transportRetries === 'number') {
    parts.push(t('copilot.chatMessage.transportRetries', { retries: formatNumber(usage.transportRetries) }))
  }
  if (usage.budgetClass) parts.push(t('copilot.chatMessage.budgetClass', { budget: usage.budgetClass }))
  if (usage.partial && usage.timeout) parts.push(t('copilot.chatMessage.timeLimit', { limit: usage.timeout }))
  return parts.join(' · ')
})

// Die Antwort wurde bisher roh interpoliert, ohne pre-wrap. Der
// Methodensteckbrief, den das Backend deterministisch an jede Landung
// haengt, kollabierte damit zu Fliesstext mit sichtbaren Rautenzeichen.
// renderMarkdown escaped zuerst alles; die Chip-Marken [[beleg:ID]] sind
// davon unberuehrt und werden NUR gegen die servergelieferte Beleg-Map
// validiert in klickbare Chips umgesetzt. Ohne Map-Treffer: [Beleg fehlt].
const renderedContent = computed(() =>
  belegChipsEinsetzen(renderMarkdown(props.message.content), props.message.evidence),
)

// Tool card the last chip click pointed at (methoden C2).
const citedToolCallId = ref<string | null>(null)
const toolCallsEl = ref<HTMLElement | null>(null)

/** Chip-Klick. Ein Chip eines Such- oder Konkordanzwerkzeugs oeffnet dessen
 * Abfrage im KWIC, im Korpus und Docset des Aufrufs. Jeder andere Chip zeigt
 * die zitierte Werkzeugkarte dieser Nachricht, zugeordnet ueber Werkzeugname
 * und Argumente. Stores werden erst im Handler geholt, die Komponente bleibt
 * ohne Pinia mountbar (Zeitleisten-Tests). */
async function onContentClick(event: MouseEvent): Promise<void> {
  const ziel = (event.target as HTMLElement).closest?.('.ev-chip') as HTMLElement | null
  if (!ziel) return
  const id = ziel.dataset.ev ?? ''
  const quelle: BelegQuelle | undefined = props.message.evidence?.find((e) => e.id === id)
  if (!quelle) return
  const { useProductCapabilitiesStore } = await import('@/stores/productCapabilities')
  const contract = useProductCapabilitiesStore().contract
  const suche = evidenceOpensKwic(quelle.tool, contract) ? evidenceSearch(quelle) : null
  if (suche) {
    const { useQueryStore } = await import('@/stores')
    const { useUiStore } = await import('@/stores/ui')
    const { useDispatch } = await import('@/composables/useActions')
    const queryStore = useQueryStore()
    const uiStore = useUiStore()
    const { dispatch } = useDispatch()
    const result = await dispatch({
      type: 'query/execute',
      payload: {
        term: suche.term,
        contextSize: queryStore.contextSize,
        ...(suche.corpus ? { filters: { ...queryStore.filters, corpus: suche.corpus } } : {}),
        ...(suche.docsetId ? { docsetId: suche.docsetId } : {}),
      },
    })
    if (result.success) uiStore.setActiveTab('kwic')
    return
  }
  const toolCallId = evidenceToolCallId(quelle, props.message.toolCalls ?? [])
  if (!toolCallId) return
  citedToolCallId.value = toolCallId
  await nextTick()
  const cards = Array.from(toolCallsEl.value?.querySelectorAll<HTMLElement>('[data-tool-call-id]') ?? [])
  const card = cards.find((el) => el.dataset.toolCallId === toolCallId)
  card?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
}

/**
 * Die Zeitleiste des Turns. Sie beantwortet die Frage, die die Fusszeile
 * bisher offen liess: wo ist die Zeit geblieben.
 *
 * Am 273M-Korpus gemessen liegen in einem Turn 2530 s Verifikation gegen
 * 233 s Werkzeuge, und der Anteil Modellzeit an der Werkzeugschleife
 * schwankt zwischen 7 und 56 Prozent. Beides war unsichtbar.
 */
const zeitleiste = computed(() => {
  const stages = props.message.stages
  if (!stages?.length) return []
  const schluss = props.message.usage?.elapsedS
  const ende = stages[stages.length - 1]?.bis ?? schluss
  // Bezugsgroesse fuer die Balkenbreite: die laengste GESCHLOSSENE Stufe,
  // solange das Turnende fehlt. Sonst waere der Nenner waehrend des Laufs
  // eine Zahl, die sich mit jedem Frame aendert.
  const geschlossen = stages
    .map(a => (a.bis ?? (a === stages[stages.length - 1] ? ende : undefined)))
    .map((bis, i) => (bis === undefined ? undefined : bis - (stages[i]?.von ?? 0)))
  const bezug = Math.max(
    ...geschlossen.filter((d): d is number => d !== undefined),
    0.001,
  )
  return stages.map((a, i) => {
    const dauer = geschlossen[i]
    const modell = a.modellSekunden
    return {
      stufe: a.stage,
      // `undefined` heisst LAEUFT NOCH. Eine Null waere hier eine
      // Falschaussage: die Stufe laeuft, ihr Ende ist nur unbekannt.
      dauer,
      anteil: dauer === undefined ? undefined : Math.max((dauer / bezug) * 100, 2),
      modell,
    }
  })
})

/** Summe der abgeschlossenen Stufen. Offene zaehlen nicht mit. */
const zeitleisteGesamt = computed(
  () => zeitleiste.value.reduce((s, a) => s + (a.dauer ?? 0), 0),
)

/** Laeuft noch mindestens eine Stufe? Dann ist die Summe eine Untergrenze. */
const zeitleisteOffen = computed(
  () => zeitleiste.value.some(a => a.dauer === undefined),
)

/**
 * Eine offene Stufe an einer NICHT mehr laufenden Nachricht.
 *
 * Der Fall ist echt: ein Turn, der in den Backstop laeuft oder abgebrochen
 * wird, schickt kein `copilot.done` mit `elapsed_s`. Die letzte Stufe
 * bekommt dann nie ein Ende. "laeuft" waere dort falsch, sie laeuft ja
 * gerade nicht mehr, und eine Dauer waere erfunden.
 */
const zeitleisteAbgebrochen = computed(
  () => !props.message.isStreaming && zeitleisteOffen.value,
)

/** Total of the timeline, a lower bound while a stage is open. */
const zeitleisteGesamtText = computed(() => {
  const seconds = formatSeconds(zeitleisteGesamt.value)
  const total = zeitleisteOffen.value
    ? t('copilot.chatMessage.timelineTotalOpen', { seconds })
    : t('copilot.chatMessage.timelineTotal', { seconds })
  return zeitleisteAbgebrochen.value ? t('copilot.chatMessage.timelineIncomplete', { total }) : total
})

// Beratende Hinweise (`copilot.grounding.annotations`): einklappbarer Block
// unter der Antwort. Neutral und klein, Info-Optik, kein Modal, blockiert nichts.
const annotations = computed(() => props.message.annotations ?? [])
</script>

<template>
  <div
    class="chat-message"
    :class="{
      'is-user': isUser,
      'is-assistant': isAssistant,
      'is-system': isSystem,
      'is-streaming': message.isStreaming
    }"
  >
    <!-- Avatar -->
    <div class="message-avatar">
      <User v-if="isUser" class="w-4 h-4" />
      <Info v-else-if="isSystem" class="w-4 h-4" />
      <Sparkles v-else class="w-4 h-4" />
    </div>

    <!-- Content -->
    <div class="message-content">
      <div v-if="isAssistant" class="message-claim-label" :aria-label="assistantClaimAria">
        <span
          class="claim-pill"
          :class="isAssistantError ? 'claim-pill-error' : 'claim-pill-interpretation'"
        >
          {{ assistantClaimLabel }}
        </span>
        <span class="claim-note">
          {{ assistantClaimNote }}
        </span>
      </div>

      <!-- Text. renderMarkdown escaped zuerst alles, danach ueberlebt kein
           rohes HTML aus der Modellausgabe. -->
      <div class="message-text">
        <div v-html="renderedContent" @click="onContentClick"></div>
        <span v-if="message.isStreaming" class="streaming-cursor">|</span>
      </div>

      <!-- Der Text steht, die Gegenlesung laeuft noch. Eine Zeile, kein
           Banner: die Antwort ist brauchbar, nur noch nicht gegengelesen.
           Sie ist NICHT roh, sondern durch die deterministischen Wachen
           gelaufen. Verschwindet mit copilot.done. -->
      <div v-if="message.vorlaeufig" class="vorlaeufig">
        <Loader2 class="w-3 h-3 shrink-0 animate-spin" aria-hidden="true" />
        <span>{{ t('copilot.chatMessage.provisional') }}</span>
      </div>

      <!-- Turn-Fortschritt (copilot.status): klein, neutral, verschwindet bei done -->
      <div
        v-if="streamStatus"
        class="stream-status"
        role="status"
        :title="streamStatus.detail || undefined"
      >
        {{ streamStatusLabel }}
      </div>

      <!-- Fortschrittsbalken. Nur wenn das Backend einen Anteil meldet:
           ein ratender Balken ist schlimmer als eine Textzeile. -->
      <div
        v-if="streamFortschritt"
        class="turn-fortschritt"
        role="progressbar"
        :aria-valuenow="streamFortschritt.prozent"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="t('copilot.chatMessage.progressAria', { step: streamFortschritt.schritt, total: streamFortschritt.von })"
      >
        <div class="turn-fortschritt-balken" :style="{ width: streamFortschritt.prozent + '%' }" />
        <span class="turn-fortschritt-text">
          {{ t('copilot.chatMessage.progressText', { step: streamFortschritt.schritt, total: streamFortschritt.von }) }}
        </span>
      </div>

      <!-- Tool Calls -->
      <div v-if="message.toolCalls?.length" ref="toolCallsEl" class="tool-calls">
        <div class="tool-calls-label" :aria-label="toolEvidenceAria">
          <span class="claim-pill" :class="hasToolEvidence ? 'claim-pill-evidence' : 'claim-pill-no-evidence'">
            {{ toolEvidenceLabel }}
          </span>
          <span class="claim-note">
            {{ toolEvidenceNote }}
          </span>
        </div>
        <div
          v-for="tool in message.toolCalls"
          :key="tool.id"
          :data-tool-call-id="tool.id"
          :class="{ 'tool-call-cited': citedToolCallId === tool.id }"
        >
          <ToolCallResult :tool-call="tool" />
        </div>
      </div>

      <!-- Beratende Hinweise (copilot.grounding.annotations): einklappbar,
           neutral, Info-Optik. Beratend, nie blockierend. -->
      <details v-if="annotations.length" class="grounding-annotations">
        <summary class="grounding-annotations-summary">
          <Info class="annotation-icon" aria-hidden="true" />
          {{ t('copilot.chatMessage.annotations', { count: annotations.length }) }}
        </summary>
        <ul class="grounding-annotations-list">
          <li v-for="(annotation, index) in annotations" :key="index">
            <span>{{ annotation.note || annotation.rule }}</span>
            <span
              v-if="annotation.note && annotation.rule"
              class="annotation-rule"
            >({{ annotation.rule }})</span>
          </li>
        </ul>
      </details>

      <!-- Zeitleiste des Turns: wo die Zeit geblieben ist -->
      <details v-if="zeitleiste.length" class="zeitleiste">
        <summary>
          {{ t('copilot.chatMessage.timeline') }}
          <span class="zeitleiste-gesamt">{{ zeitleisteGesamtText }}</span>
        </summary>
        <ul>
          <li v-for="(a, i) in zeitleiste" :key="`${a.stufe}-${i}`">
            <div class="zeitleiste-kopf">
              <span class="zeitleiste-name">{{ copilotStageLabel(a.stufe) }}</span>
              <span class="zeitleiste-dauer">
                <template v-if="a.dauer === undefined">
                  {{ message.isStreaming ? t('copilot.chatMessage.stageRunning') : t('copilot.chatMessage.stageNoEnd') }}
                </template>
                <template v-else>
                  {{ formatSeconds(a.dauer) }} s<template
                    v-if="a.modell !== undefined"
                  > · {{ t('copilot.chatMessage.modelSeconds', { seconds: formatSeconds(a.modell) }) }}</template>
                </template>
              </span>
            </div>
            <div
              class="zeitleiste-spur"
              :class="{ 'ist-offen': a.dauer === undefined && message.isStreaming }"
            >
              <span
                v-if="a.anteil !== undefined"
                class="zeitleiste-balken"
                :style="{ width: `${a.anteil}%` }"
              >
                <span
                  v-if="a.modell !== undefined && (a.dauer ?? 0) > 0"
                  class="zeitleiste-modell"
                  :style="{ width: `${Math.min((a.modell / (a.dauer ?? 1)) * 100, 100)}%` }"
                ></span>
              </span>
            </div>
          </li>
        </ul>
      </details>

      <!-- Timestamp + Aufwands-Fusszeile (copilot.done) -->
      <div class="message-time">
        {{ formattedTime }}
        <span
          v-if="usageLabel"
          class="usage-footer"
          :title="usageTitle || undefined"
        >· {{ usageLabel }}</span>
        <Loader2 v-if="message.isStreaming" class="w-3 h-3 ml-1 animate-spin" />
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.chat-message {
  @apply flex gap-3;
}

.chat-message.is-user {
  @apply flex-row-reverse;
}

.message-avatar {
  @apply w-8 h-8 rounded-full flex-shrink-0;
  @apply flex items-center justify-center;
}

.is-user .message-avatar {
  @apply bg-neutral-200 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300;
}

.is-assistant .message-avatar {
  @apply bg-copilot-bg text-copilot-primary;
}

.is-system .message-avatar {
  @apply bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400;
}

.message-content {
  @apply flex-1 min-w-0;
}

.is-user .message-content {
  @apply text-right;
}

.message-text {
  @apply inline-block px-4 py-2 rounded-2xl;
  @apply text-sm leading-relaxed;
  max-width: 85%;
}

/* Beleg-Chips (Deutungspfad): klickbare Referenzen auf Werkzeug-Evidenz.
   Der Chip ist ein <button>, der Klick laeuft die EXAKTE Abfrage im
   KWIC-Tool. Optisch zurueckhaltend, aber klar als Interaktion lesbar.
   The chips come from v-html and carry no scope attribute, so the rules
   reach them through :deep() below the message text. */
.message-text :deep(.ev-chip) {
  @apply inline-block align-baseline cursor-pointer;
  @apply px-2 mx-0.5 text-xs font-medium rounded-full;
  @apply border border-violet-300 dark:border-violet-600;
  @apply bg-violet-50 dark:bg-violet-900/40 text-violet-700 dark:text-violet-200;
}

.message-text :deep(.ev-chip:hover) {
  @apply bg-violet-100 dark:bg-violet-900/70;
}

.message-text :deep(.ev-chip:focus-visible) {
  @apply outline-none ring-2 ring-violet-400 ring-offset-1;
}

.message-claim-label {
  @apply mb-1 flex flex-wrap items-center gap-1.5;
}

.claim-pill {
  @apply inline-flex items-center rounded-full px-2 py-0.5;
  @apply text-[0.65rem] font-semibold uppercase tracking-wide;
}

.claim-pill-interpretation {
  @apply bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200;
}

.claim-pill-error {
  @apply bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200;
}

.claim-pill-evidence {
  @apply bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200;
}

.claim-pill-no-evidence {
  @apply bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300;
}

.claim-note {
  @apply text-[0.68rem] text-neutral-500 dark:text-neutral-400;
}

.is-user .message-text {
  @apply bg-primary-500 text-white;
  @apply rounded-tr-sm;
}

.is-assistant .message-text {
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply rounded-tl-sm;
}

/* System notices (backend commit/run/error mirrors): muted, full-width, not a
 * conversational bubble — visually distinct from user/assistant turns. */
.is-system .message-text {
  @apply block max-w-full;
  @apply bg-transparent border border-dashed;
  @apply border-neutral-300 dark:border-neutral-600;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply text-xs italic rounded-md;
}

/* Markdown der Antwort. Kein `prose`-Plugin im Projekt, deshalb knappe
   eigene Regeln: der Text steht in einer Blase und darf die
   Ueberschriftenhierarchie der Seite nicht uebernehmen. */
.message-text :deep(h3),
.message-text :deep(h4),
.message-text :deep(h5),
.message-text :deep(h6) {
  @apply font-semibold mt-3 mb-1 first:mt-0;
  @apply text-neutral-800 dark:text-neutral-100;
}
.message-text :deep(h3) { @apply text-sm; }
.message-text :deep(h4),
.message-text :deep(h5),
.message-text :deep(h6) { @apply text-xs uppercase tracking-wide opacity-70; }
.message-text :deep(p) { @apply mb-2 last:mb-0; }
.message-text :deep(ul) { @apply list-disc pl-5 mb-2 last:mb-0 space-y-0.5; }
.message-text :deep(ol) { @apply list-decimal pl-5 mb-2 last:mb-0 space-y-0.5; }
.message-text :deep(strong) { @apply font-semibold; }
.message-text :deep(code) {
  @apply px-1 py-0.5 rounded text-[0.85em];
  @apply bg-neutral-200/70 dark:bg-neutral-700/70;
  @apply font-mono;
}
.message-text :deep(pre) {
  @apply mb-2 p-2 rounded overflow-x-auto;
  @apply bg-neutral-200/70 dark:bg-neutral-800/70;
}
.message-text :deep(pre code) { @apply bg-transparent p-0; }
/* Breite Tabellen scrollen in sich, nie die Blase. */
.message-text :deep(.md-table-scroll) { @apply overflow-x-auto mb-2 last:mb-0; }
.message-text :deep(table) { @apply text-xs border-collapse; }
.message-text :deep(th),
.message-text :deep(td) {
  @apply border px-2 py-1 text-left align-top whitespace-nowrap;
  @apply border-neutral-300 dark:border-neutral-600;
}
.message-text :deep(th) { @apply font-semibold bg-neutral-200/50 dark:bg-neutral-700/50; }

/* Zeitleiste: wo die Zeit geblieben ist. Eingeklappt, damit sie den Chat
   nicht dominiert, aber vorhanden statt nur im Log. */
.zeitleiste {
  @apply mt-2 text-[0.68rem];
  @apply text-neutral-500 dark:text-neutral-400;
}
.zeitleiste > summary {
  @apply cursor-pointer select-none opacity-80 hover:opacity-100;
}
.zeitleiste-gesamt { @apply ml-1 tabular-nums opacity-70; }
.zeitleiste ul { @apply mt-1 space-y-1.5; }
/* Zweizeilig: im Copilot-Panel ist kein Platz fuer Name, Balken und Dauer
   nebeneinander, die Dauer brach dort ueber drei Zeilen um. */
.zeitleiste li { @apply block; }
.zeitleiste-kopf { @apply flex items-baseline justify-between gap-2; }
.zeitleiste-name { @apply truncate; }
.zeitleiste-spur {
  @apply mt-0.5 h-1.5 w-full rounded-sm overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
}
.zeitleiste-balken {
  @apply block h-full rounded-sm relative;
  @apply bg-neutral-300 dark:bg-neutral-600;
  min-width: 2px;
}
/* Der dunklere Teil ist Modellzeit, der Rest Index und Vorbereitung. */
.zeitleiste-modell {
  @apply absolute left-0 top-0 h-full rounded-sm;
  @apply bg-neutral-500 dark:bg-neutral-300;
}
.zeitleiste-dauer { @apply tabular-nums opacity-80; }
/* Eine laufende Stufe bekommt keinen Balken, sondern eine wandernde Spur:
   ihre Dauer ist unbekannt, und eine Breite waere eine Behauptung. */
.zeitleiste-spur.ist-offen {
  background-image: linear-gradient(
    90deg,
    transparent 0%, rgb(148 163 184 / 0.7) 50%, transparent 100%
  );
  background-size: 40% 100%;
  background-repeat: no-repeat;
  animation: zeitleiste-wandern 1.4s ease-in-out infinite;
}
@keyframes zeitleiste-wandern {
  from { background-position: -40% 0; }
  to { background-position: 140% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .zeitleiste-spur.ist-offen { animation: none; }
}

.streaming-cursor {
  @apply text-copilot-primary;
  animation: blink 1s step-end infinite;
}

.turn-fortschritt {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.25rem;
}
.turn-fortschritt-balken {
  height: 3px;
  border-radius: 2px;
  background: currentColor;
  opacity: 0.45;
  transition: width 0.35s ease;
  min-width: 2px;
  flex: 0 0 auto;
}
.turn-fortschritt::before {
  content: '';
  position: absolute;
}
.turn-fortschritt-text {
  font-variant-numeric: tabular-nums;
  opacity: 0.7;
  font-size: 0.72rem;
  white-space: nowrap;
}

/* Turn-Fortschritt (copilot.status): dezente Stufenanzeige unter der laufenden
 * Message. Kein Modal, kein Layout-Sprung. */
.stream-status {
  @apply mt-1 text-[0.68rem] text-neutral-400 dark:text-neutral-500;
}

/* Vorlaeufig: eine Zeile in derselben Tonlage wie die Stufenanzeige. Kein
 * Warnbanner, denn der Text ist deterministisch gedeckt und brauchbar, ihm
 * fehlt nur die Gegenlesung. Hell 500 und dunkel 400 wegen der 4,5:1 von
 * WCAG AA, dieselbe Wahl wie in der Arbeitsspur. */
.vorlaeufig {
  @apply mt-1.5 flex items-center gap-1.5 text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}

/* Aufwands-Fusszeile (copilot.done): gleiche Tonalitaet wie der Zeitstempel,
 * Details nur im Tooltip. */
.usage-footer {
  @apply ml-1 text-neutral-400 dark:text-neutral-500;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.tool-calls {
  @apply mt-2 space-y-2;
}

/* The tool card a chip cites. */
.tool-call-cited {
  @apply rounded-md ring-2 ring-primary-400 dark:ring-primary-500;
}

/* Beratende Hinweise (copilot.grounding.annotations): neutrale Info-Optik,
 * bewusst OHNE Warnfarben. Einklappbar, klein, unter der Antwort. */
.grounding-annotations {
  @apply mt-2 px-3 py-2 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800/40;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.grounding-annotations-summary {
  @apply cursor-pointer select-none font-medium;
}

.annotation-icon {
  @apply inline-block w-3 h-3 mr-1 align-text-bottom;
}

.grounding-annotations-list {
  @apply mt-2 space-y-1 list-disc pl-4;
}

.annotation-rule {
  @apply ml-1 text-neutral-400 dark:text-neutral-500;
}

.tool-calls-label {
  @apply flex flex-wrap items-center gap-1.5;
}

.message-time {
  @apply mt-1 text-xs text-neutral-400 flex items-center;
}

.is-user .message-time {
  @apply justify-end;
}
</style>
