/**
 * useCopilot Composable - Copilot interaction helpers
 *
 * The Copilot is a free-form LLM agent. Tool calls go through policy/MCP
 * gates; rendered prose is treated as interpretation over computed evidence.
 *
 * New in v2: Structured events (Plan, Clarify, ActionRequest)
 */

import { computed, ref, shallowRef } from 'vue'
import { useCopilotStore, useCorpusCapabilitiesStore, useProductCapabilitiesStore, useQueryStore, useUiStore, type ChatMessageStage, type ChatMessageUsage, type ToolCall } from '@/stores'
import { DEFAULT_CLARIFICATION_TIMEOUT_MS, type ChatMessageAnnotation } from '@/stores/copilot'
import { useMcpToolsStore } from '@/stores/mcpTools'
import { useArbeitsspurStore } from '@/stores/arbeitsspur'
import {
  streamCopilotMessage,
  approveAction as apiApproveAction,
  rejectAction as apiRejectAction,
  answerClarification as apiAnswerClarification,
  updateCopilotContext,
  getCurrentSessionId,
  continueCopilotExecution,
  type CopilotDoneMeta,
  type CopilotGroundingEvent,
  type CopilotVorlaeufigeAntwortEvent,
  type CopilotEvidenceGapEvent,
  type CopilotRecoveryEvent,
  type CopilotStatusEvent,
  type CopilotToolPhaseEvent,
  type CopilotResearchEvent,
  type CopilotResearchContextEvent,
  type CopilotActionBlockedEvent,
} from '@/api/sse'
import {
  currentPreview,
  resolvePreview,
  clearPreviews,
  addActionPreview,
  getActionMeta,
  getPolicyDecision,
  actionRequestToAction,
} from '@/actions'
import { useErrorHandler } from './useErrorHandler'
import { useContextSnapshot } from './useContextSnapshot'
import { recordBackendActionResultRun } from '@/services/runRecordService'
import { objectHash, objectDiff } from '@/utils/comparison'
import {
  copilotControlTool,
  copilotToolContractStatus,
  productActionTypeMap,
  type CopilotToolContractStatus,
} from '@/lib/copilotTools'
import { mcpToolRuntimeBlockReason } from '@/lib/copilotToolRuntime'
import { COPILOT_GROUNDING_OPERATIONS, type CopilotGroundingOperationId } from '@/lib/copilotGroundingOperations'
import { routeOperationBlockReasonForAction } from '@/actions/productGate'
import { isCqlfQuery } from '@/lib/cqlDetection'
import {
  hasParallelKwic,
  hasPassageSearch,
  hasWordSimilarity,
  supportsFrequencyGroup,
  unsupportedCqlAttributes,
  type CorpusFrequencyGroup,
} from '@/lib/corpusFeatureOptions'
import { useSettingsStore } from '@/stores/settings'
import { t, te } from '@/i18n'
import type {
  PlanV1,
  ClarifyV1,
  ActionRequestV1,
  ActionMeta,
  ActionCommitPayload,
  ActionResultPayload,
    ToolResultV1,
} from '@/types/copilot-protocol'

/**
 * Localise copilot stream errors for the German UI. A network failure (a fetch
 * TypeError) surfaces as the raw English "Failed to fetch"/"NetworkError" — map
 * it to a clear "Backend nicht erreichbar" hint instead of leaking it (COPILOT-4).
 */
export function localizeCopilotError(error: Error): string {
  const message = error.message ?? ''
  const lowered = message.toLowerCase()
  const isNetworkFailure =
    error.name === 'TypeError' &&
    (lowered.includes('failed to fetch') ||
      lowered.includes('networkerror') ||
      lowered.includes('load failed'))
  if (isNetworkFailure) {
    return t('copilot.session.networkError')
  }
  return message
}

/** One rendered entry of the background-research status timeline. */
export interface CopilotResearchStatusEntry {
  id: string
  kind: 'research' | 'context'
  text: string
  ts: number
}

const RESEARCH_STATUS_LIMIT = 20

export function useCopilot() {
  const copilotStore = useCopilotStore()
  const spurStore = useArbeitsspurStore()
  const queryStore = useQueryStore()
  const uiStore = useUiStore()
  const productCapabilities = useProductCapabilitiesStore()
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const mcpTools = useMcpToolsStore()
  const settingsStore = useSettingsStore()
  const errorHandler = useErrorHandler()
  const { buildSnapshotSync } = useContextSnapshot()

  const cancelStream = ref<(() => void) | null>(null)

  // === Structured Event State ===
  const currentPlan = shallowRef<PlanV1 | null>(null)
  const currentClarification = shallowRef<ClarifyV1 | null>(null)
  /** Background-research status entries (collapsible timeline in the chat). */
  const researchEvents = ref<CopilotResearchStatusEntry[]>([])
  const pendingActionRequests = ref<ActionRequestV1[]>([])
  const actionRequestSessions = new Map<string, string>()
  const actionResultRequests = new Map<string, ActionRequestV1>()
  const blockedActionResultRequestIds = new Set<string>()
  const actionResolutionInFlight = ref<Set<string>>(new Set())
  const knownActionRequestIds = ref<Set<string>>(new Set())
  const committedActionRequestIds = ref<Set<string>>(new Set())
  const committingActionRequestIds = new Set<string>()

  let streamGeneration = 0
  let activeAssistantMessageId: string | null = null

  function beginStream(messageId: string): number {
    streamGeneration += 1
    activeAssistantMessageId = messageId
    return streamGeneration
  }

  function isCurrentStream(generation: number, messageId: string): boolean {
    return generation === streamGeneration && activeAssistantMessageId === messageId
  }

  function stopActiveStream(): void {
    const messageId = activeAssistantMessageId
    // Invalidate callbacks before aborting: a buffered SSE frame can otherwise
    // arrive after a user pressed Stop and resurrect the turn in the UI.
    streamGeneration += 1
    cancelStream.value?.()
    cancelStream.value = null
    activeAssistantMessageId = null
    copilotStore.setStreaming(false)
    currentPlan.value = null
    currentClarification.value = null

    // A stop/supersede also terminates every open clarification on the
    // messages, otherwise the ClarificationCard keeps hanging after the turn
    // is already dead.
    for (const item of copilotStore.messages) {
      if (item.clarification && !item.clarification.answered) {
        copilotStore.updateMessage(item.id, {
          clarification: { ...item.clarification, answered: true, selectedOption: '__stopped__' },
        })
      }
    }

    if (!messageId) return
    const message = copilotStore.messages.find((item) => item.id === messageId)
    if (!message?.isStreaming) return
    const received = message.content.trim()
    copilotStore.updateMessage(messageId, {
      content: received
        ? `${message.content}\n\n${t('copilot.session.stoppedNote')}`
        : t('copilot.session.stopped'),
      isStreaming: false,
      status: undefined,
      error: false,
      retryPrompt: undefined,
    })
  }

  /**
   * Map the `copilot.done` effort report onto the message footer shape.
   * Missing or malformed fields simply produce no footer.
   */
  function usageFromDoneMeta(meta?: CopilotDoneMeta): ChatMessageUsage | undefined {
    if (!meta) return undefined
    const usage: ChatMessageUsage = {}
    if (typeof meta.llm_calls_used === 'number') usage.llmCalls = meta.llm_calls_used
    if (typeof meta.transport_retries_used === 'number') {
      usage.transportRetries = meta.transport_retries_used
    }
    if (typeof meta.elapsed_s === 'number') usage.elapsedS = meta.elapsed_s
    if (typeof meta.budget_class === 'string' && meta.budget_class) {
      usage.budgetClass = meta.budget_class
    }
    if (typeof meta.llm_seconds === 'number') usage.llmSeconds = meta.llm_seconds
    if (meta.llm_seconds_je_stufe) usage.llmSecondsJeStufe = meta.llm_seconds_je_stufe
    if (meta.partial === true) usage.partial = true
    if (typeof meta.timeout === 'string' && meta.timeout) usage.timeout = meta.timeout
    // Rezept-Transparenz: `null` (freie Analyse) ist ein gueltiger Wert und
    // bleibt von einem fehlenden Feld (Alt-Backend) unterscheidbar.
    if (typeof meta.recipe_id === 'string' && meta.recipe_id.trim()) {
      usage.recipeId = meta.recipe_id.trim()
    } else if (meta.recipe_id === null) {
      usage.recipeId = null
    }
    return Object.keys(usage).length ? usage : undefined
  }

  /**
   * `copilot.vorlaeufige_antwort`: der Text steht, die Gegenlesung laeuft.
   *
   * Der Grund ist gemessen: die Modellverifikation kostet ein Vielfaches der
   * Antwort, die sie prueft. Am 2026-08-28 stand ein Turn nach 21 Minuten
   * noch in der zweiten Runde aus Envelope und Verdict, waehrend der
   * fertige, deterministisch gedeckte Text seit Minute zwei bereitlag.
   *
   * Die Nachricht bleibt `isStreaming`, damit die Arbeitsspur weiterlaeuft.
   * `copilot.done` ersetzt den Text und loescht die Marke.
   */
  function applyVorlaeufigeAntwort(
    messageId: string,
    event: CopilotVorlaeufigeAntwortEvent,
  ): void {
    const text = typeof event.text === 'string' ? event.text.trim() : ''
    if (!text) return
    copilotStore.updateMessage(messageId, { content: text, vorlaeufig: true })
  }

  /** `copilot.status`: dezente Stufenanzeige an der laufenden Message. */
  function applyStreamStatus(messageId: string, status: CopilotStatusEvent): void {
    const stage = typeof status.stage === 'string' ? status.stage.trim() : ''
    if (!stage) return
    const detail = typeof status.detail === 'string' ? status.detail.trim() : ''
    // recipe_id tolerant lesen: string oder explizites null werden gespiegelt,
    // jedes andere/fehlende Feld laesst das Verhalten unveraendert.
    const recipeId = typeof status.recipe_id === 'string' && status.recipe_id.trim()
      ? status.recipe_id.trim()
      : status.recipe_id === null ? null : undefined
    // Die Stufenfolge wird GESAMMELT, nicht ueberschrieben. Bisher trug die
    // Nachricht nur die zuletzt gemeldete Stufe, und `onDone` loeschte auch
    // die: nach dem Turn gab es keine Spur mehr davon, wo die Zeit geblieben
    // ist. Am 273M-Korpus sind das bis zu 2530 s Verifikation gegen 233 s
    // Werkzeuge, ein Unterschied, den niemand sehen konnte.
    const msg = copilotStore.messages.find(m => m.id === messageId)
    const bisher: ChatMessageStage[] = msg?.stages ? [...msg.stages] : []
    const tRel = typeof status.t_rel === 'number' && Number.isFinite(status.t_rel)
      ? status.t_rel
      : undefined
    if (tRel !== undefined) {
      const letzte = bisher.length ? bisher[bisher.length - 1] : undefined
      // Aufeinanderfolgende Meldungen derselben Stufe (die Werkzeugschleife
      // meldet je Runde erneut) bilden EINEN Abschnitt, keinen neuen.
      if (!letzte || letzte.stage !== stage) {
        if (letzte && letzte.bis === undefined) letzte.bis = tRel
        bisher.push({ stage, von: tRel })
      }
    }
    copilotStore.updateMessage(messageId, {
      status: {
        stage,
        ...(detail ? { detail } : {}),
        ...(recipeId !== undefined ? { recipeId } : {}),
      },
      ...(tRel !== undefined ? { stages: bisher } : {}),
    })
  }

  /**
   * `start` / `end`: ein Werkzeug erscheint, WAEHREND es laeuft, statt erst
   * wenn sein Ergebnis da ist. Der Kartenrahmen dafuer existiert seit je,
   * `ToolCallResult` kennt den Zustand `running` samt Spinner, der
   * Copilot-Pfad erzeugte ihn nur nie.
   */
  function applyToolPhase(messageId: string, phase: CopilotToolPhaseEvent): void {
    const msg = copilotStore.messages.find(m => m.id === messageId)
    if (!msg) return
    const toolCalls: ToolCall[] = [...(msg.toolCalls || [])]
    if (phase.phase === 'start') {
      // Nur anlegen, wenn nicht schon ein laufender Aufruf desselben
      // Werkzeugs offen ist: sonst entstuenden bei Wiederholungen Karteileichen.
      if (toolCalls.some(tc => tc.name === phase.tool && tc.status === 'running')) return
      toolCalls.push({
        id: `${phase.tool}-${toolCalls.length}-${phase.t_rel ?? 0}`,
        name: phase.tool,
        arguments: {},
        status: 'running',
        ...(phase.t_rel !== undefined ? { von: phase.t_rel } : {}),
      })
      copilotStore.updateMessage(messageId, { toolCalls })
      return
    }
    if (phase.duration_ms === undefined) return
    // Die Dauer an den juengsten Aufruf dieses Werkzeugs haengen, egal ob er
    // noch laeuft oder das Ergebnis schon da war: `copilot.tool_result` und
    // `end` kommen unmittelbar nacheinander, die Reihenfolge ist nicht
    // garantiert.
    for (let i = toolCalls.length - 1; i >= 0; i--) {
      const tc = toolCalls[i]
      if (tc && tc.name === phase.tool && tc.durationMs === undefined) {
        toolCalls[i] = { ...tc, durationMs: phase.duration_ms }
        copilotStore.updateMessage(messageId, { toolCalls })
        return
      }
    }
  }

  /**
   * Die Zeitleiste am Turnende schliessen und die Modellzeit zuordnen.
   *
   * Erst damit steht neben der Dauer, wieviel davon das Modell war und
   * wieviel der Index. Gemessen am 273M-Korpus lagen in einem Turn 216,3 s
   * Modellzeit gegen 16,9 s Indexzeit in der Werkzeugschleife, in einem
   * anderen 115,7 gegen 146,5. Das Verhaeltnis ist nicht vorhersagbar.
   *
   * Steht hier und nicht zweimal im Stream-Aufbau: es gibt zwei davon, den
   * regulaeren und den Fortsetzungspfad, und eine Aenderung an einem von
   * beiden waere eine Verschiebung, kein Fix.
   */
  function zeitleisteAbschliessen(
    messageId: string,
    bilanz: ChatMessageUsage | undefined,
  ): ChatMessageStage[] | undefined {
    const msg = copilotStore.messages.find(m => m.id === messageId)
    if (!msg?.stages?.length) return undefined
    let stages: ChatMessageStage[] = [...msg.stages]
    const letzte = stages[stages.length - 1]
    if (letzte && letzte.bis === undefined && typeof bilanz?.elapsedS === 'number') {
      letzte.bis = bilanz.elapsedS
    }
    const jeStufe = bilanz?.llmSecondsJeStufe
    if (jeStufe) {
      const gesehen: Record<string, number> = {}
      stages = stages.map(a => {
        gesehen[a.stage] = (gesehen[a.stage] ?? 0) + 1
        // Die Buchung ist je Stufe SUMMIERT, nicht je Abschnitt. Sie gehoert
        // deshalb an den ersten Abschnitt einer Stufe, sonst stuende
        // dieselbe Zahl mehrfach da und die Summe waere falsch.
        return gesehen[a.stage] === 1 && jeStufe[a.stage] !== undefined
          ? { ...a, modellSekunden: jeStufe[a.stage] }
          : a
      })
    }
    return stages
  }

  /**
   * `copilot.grounding.annotations`: beratende Hinweise an der laufenden
   * Antwort. Beratend, nie blockierend: fehlerhafte oder leere Eintraege
   * werden verworfen, ein fehlendes Feld aendert nichts (Alt-Backend).
   */
  function sanitizeGroundingAnnotations(event: CopilotGroundingEvent): ChatMessageAnnotation[] {
    if (!Array.isArray(event.annotations)) return []
    const annotations: ChatMessageAnnotation[] = []
    for (const entry of event.annotations) {
      if (!entry || typeof entry !== 'object') continue
      const record = entry as Record<string, unknown>
      // Diagnose-Zeilen sind fuer den Ereignisstrom und die Messung, nicht
      // fuer den Leser der Antwort. Die Zitatwache nennt seit P4 je
      // gestrichener Spanne den Traegersatz und das ungedeckte Zitat,
      // damit eine Messung sieht, WAS gefallen ist. Ohne diesen Filter
      // stuende das gestrichene Fabrikat als "Hinweis" unter derselben
      // Antwort, aus der die Wache es gerade entfernt hat.
      if (record.channel === 'diagnostik') continue
      // Backend-Kontrakt liefert claim_id als Regel-Label (R2), aeltere
      // Staende rule — beide akzeptieren, damit kein Eintrag verloren geht.
      const rawRule =
        typeof record.rule === 'string'
          ? record.rule
          : typeof record.claim_id === 'string'
            ? record.claim_id
            : ''
      const rule = rawRule.trim()
      const note = typeof record.note === 'string' ? record.note.trim() : ''
      if (!rule && !note) continue
      annotations.push({ ...(rule ? { rule } : {}), ...(note ? { note } : {}) })
    }
    return annotations
  }

  function applyGroundingAnnotations(messageId: string, event: CopilotGroundingEvent): void {
    const incoming = sanitizeGroundingAnnotations(event)
    const message = copilotStore.messages.find((item) => item.id === messageId)
    if (!message) return
    if (incoming.length) {
      copilotStore.updateMessage(messageId, {
        annotations: [...(message.annotations ?? []), ...incoming],
      })
    }
    // Beleg-Map des Deutungspfads: klickbare Chips validieren dagegen.
    if (Array.isArray(event.evidence) && event.evidence.length) {
      const belege = event.evidence.filter(
        (e): e is NonNullable<typeof e> =>
          !!e && typeof e === 'object' && typeof (e as { id?: unknown }).id === 'string',
      )
      if (belege.length) copilotStore.updateMessage(messageId, { evidence: belege })
    }
  }

  /**
   * `copilot.cancelled`: the SERVER ended the turn (owner supersede, backstop).
   * Finalize the bubble and release the input immediately, because the stream
   * will not deliver a done frame anymore.
   */
  function finalizeCancelledTurn(messageId: string): void {
    copilotStore.setStreaming(false)
    cancelStream.value = null
    activeAssistantMessageId = null
    currentPlan.value = null
    const message = copilotStore.messages.find((item) => item.id === messageId)
    if (!message?.isStreaming) return
    const received = message.content.trim()
    copilotStore.updateMessage(messageId, {
      content: received
        ? `${message.content}\n\n${t('copilot.session.cancelledNote')}`
        : t('copilot.session.cancelled'),
      isStreaming: false,
      status: undefined,
      // Es liest niemand mehr gegen. Die Marke weiter zu fuehren waere
      // eine Falschaussage ueber einen laufenden Vorgang.
      vorlaeufig: false,
      error: false,
      retryPrompt: undefined,
    })
  }

  // Instance-level context caching
  const lastContextHash = ref('')
  const lastContext = ref<Record<string, unknown>>({})

  function copilotOperationLabel(operationId: CopilotGroundingOperationId): string {
    switch (operationId) {
      case COPILOT_GROUNDING_OPERATIONS.chatStream: return t('copilot.session.opChatStream')
      case COPILOT_GROUNDING_OPERATIONS.actionApprove: return t('copilot.session.opActionApprove')
      case COPILOT_GROUNDING_OPERATIONS.actionReject: return t('copilot.session.opActionReject')
      case COPILOT_GROUNDING_OPERATIONS.clarificationAnswer: return t('copilot.session.opClarificationAnswer')
      case COPILOT_GROUNDING_OPERATIONS.contextUpdate: return t('copilot.session.opContextUpdate')
      case COPILOT_GROUNDING_OPERATIONS.continue: return t('copilot.session.opContinue')
      default: return operationId
    }
  }

  async function assertCopilotOperation(
    operationId: CopilotGroundingOperationId,
    retryPrompt?: string,
  ): Promise<boolean> {
    const label = copilotOperationLabel(operationId)
    try {
      // Every copilot operation here is triggered by an explicit in-app surface
      // interaction (send / approve / reject / answer / continue). Supply that
      // contextual confirmation so a confirmed_contextual_ui operation is
      // satisfied by the in-app gate instead of falling back to a native
      // window.confirm() the German UI never owns.
      await productCapabilities.assertProductOperationAccess(operationId, label, {
        contextualConfirmation: {
          surfaceId: 'copilot.chat',
          interaction: `copilot.${operationId}`,
          source: 'native_surface',
        },
      })
      return true
    } catch (error) {
      const reason = error instanceof Error ? error.message : t('copilot.session.operationNotAllowed', { label })
      // When the operation is recoverable (it carries the original prompt),
      // mark the bubble so the in-app "Erneut versuchen" affordance re-fires the
      // request instead of leaving a dead end.
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.operationBlocked', { label, reason }),
        ...(retryPrompt ? { error: true, retryPrompt } : {}),
      })
      return false
    }
  }

  /**
   * Compute diff between two objects using fast comparison
   */
  function computeDiff(
    prev: Record<string, unknown>,
    curr: Record<string, unknown>
  ): Record<string, unknown> {
    const diff = objectDiff(prev, curr)
    return diff ?? {}
  }

  /**
   * Build context object for Copilot
   * @param full - If true, include full details (selected_rows as array, visible_range)
   * @returns Context object with changed flag and diff
   */
  function buildContext(full = false): {
    changed: boolean
    diff?: Record<string, unknown>
    full?: Record<string, unknown>
  } {
    // Basic context (always sent in minimal form)
    const context: Record<string, unknown> = {
      current_query: queryStore.term || undefined,
      total_results: queryStore.totalKnown ? queryStore.totalHits : undefined,
      selected_count: queryStore.selectedRows.size, // Only count, not all IDs
      active_tab: uiStore.activeTab,
      autonomy_level: copilotStore.autonomyLevel
    }

    // Full context when explicitly requested
    if (full) {
      context.selected_rows = Array.from(queryStore.selectedRows)
    }

    const hash = objectHash(context)

    // Check if context has changed
    if (hash === lastContextHash.value) {
      return { changed: false }
    }

    // Compute diff from last context
    const diff = computeDiff(lastContext.value, context)

    // Update cache
    lastContextHash.value = hash
    lastContext.value = { ...context }

    return {
      changed: true,
      diff: Object.keys(diff).length > 0 ? diff : undefined,
      full: context
    }
  }

  /**
   * Get full context (for first message or when backend requests it)
   */
  function getFullContext(): Record<string, unknown> {
    return {
      current_query: queryStore.term || undefined,
      total_results: queryStore.totalKnown ? queryStore.totalHits : undefined,
      selected_rows: Array.from(queryStore.selectedRows),
      selected_count: queryStore.selectedRows.size,
      active_tab: uiStore.activeTab,
      autonomy_level: copilotStore.autonomyLevel
    }
  }

  function asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {}
  }

  function isNoLocalActionResult(result: unknown): boolean {
    return !!result
      && typeof result === 'object'
      && (result as { status?: unknown }).status === 'no-action'
  }

  /**
   * A backend result that signals failure (so it may overwrite an optimistic
   * local "success"). Recognises both an explicit `status: 'error'` and a
   * truthy `error` field, which is how tool wrappers surface failures.
   */
  function isErrorToolResult(result: unknown): boolean {
    if (!result || typeof result !== 'object') return false
    const record = result as { status?: unknown; error?: unknown; ok?: unknown }
    return record.status === 'error' || record.status === 'not_applicable' || record.ok === false || !!record.error
  }

  function mergeToolResultIntoMessage(
    messageId: string,
    toolName: string,
    result: unknown,
    input?: unknown,
    herkunft?: { reused: boolean; skipped: boolean },
  ): void {
    const msg = copilotStore.messages.find(m => m.id === messageId)
    if (!msg) return

    const incomingIsError = isErrorToolResult(result)

    let matched = false
    const toolCalls = (msg.toolCalls || []).map((tc: ToolCall) => {
      if (tc.name !== toolName) return tc
      // Merge into a still-running call, a placeholder no-action, OR overwrite an
      // optimistic success when the backend reports an error (truth wins).
      const replaceable =
        tc.status === 'running'
        || isNoLocalActionResult(tc.result)
        || (incomingIsError && tc.status === 'success')
      if (!replaceable) return tc
      matched = true
      // Die konkrete Abfrage kommt als `input` mit dem Ergebnis und war
      // bisher verloren: eine Karte, die aus dem `start`-Ereignis stammt,
      // hat `arguments: {}`, und der Merge liess das so. Damit fehlte genau
      // die Angabe, mit der jemand nachvollziehen kann, WONACH gesucht
      // wurde. Vorhandene Argumente werden nicht ueberschrieben.
      const args = (input && typeof input === 'object' && !Array.isArray(input))
        ? { ...(input as Record<string, unknown>) }
        : undefined
      const mitArgs = {
        ...((args && !Object.keys(tc.arguments || {}).length)
          ? { ...tc, arguments: args }
          : tc),
        ...(herkunft?.reused ? { wiederverwendet: true } : {}),
        ...(herkunft?.skipped ? { uebersprungen: true } : {}),
      }
      if (incomingIsError) {
        const errorText =
          (typeof (result as { error?: unknown }).error === 'string'
            ? (result as { error: string }).error
            : undefined)
          ?? t('copilot.session.toolBackendError')
        return { ...mitArgs, status: 'error' as const, error: errorText, result }
      }
      return { ...mitArgs, status: 'success' as const, result }
    })

    if (!matched) {
      const errorText =
        incomingIsError && typeof (result as { error?: unknown }).error === 'string'
          ? (result as { error: string }).error
          : incomingIsError
            ? t('copilot.session.toolBackendError')
            : undefined
      // ``herkunft`` MUSS auch hier gelten, nicht nur im Merge-Zweig.
      //
      // Ein wiederverwendeter oder uebersprungener Aufruf erreicht NUR
      // diesen Zweig: der Orchestrator sendet sein copilot.tool_result in
      // der Filterschleife und macht ``continue``, bevor ``_dispatch``
      // laeuft, und das ``start``-Ereignis entsteht ausschliesslich in
      // ``_dispatch``. Es gibt also keine laufende Karte, in die gemerged
      // werden koennte. Ohne die Flags hier erschien der
      // Zwischenspeicher-Treffer als vollwertige Karte mit Kennzahl, in
      // voller Deckkraft, und wurde als weitere Abfrage gezaehlt: genau
      // die Arbeit, die nicht stattgefunden hat.
      toolCalls.push({
        id: crypto.randomUUID(),
        name: toolName,
        arguments: asRecord(input),
        status: incomingIsError ? 'error' : 'success',
        ...(errorText ? { error: errorText } : {}),
        ...(herkunft?.reused ? { wiederverwendet: true } : {}),
        ...(herkunft?.skipped ? { uebersprungen: true } : {}),
        result,
      })
    }

    copilotStore.updateMessage(messageId, { toolCalls })
  }

  async function loadCorpusSummaryForGate(corpus?: unknown) {
    const requested = typeof corpus === 'string' && corpus.trim()
      ? corpus.trim()
      : queryStore.filters.corpus ?? 'default'
    const cached = corpusCapabilities.corpora.find((entry) => entry.name === requested)
    if (cached) return cached
    return corpusCapabilities.fetchCapabilities(requested)
  }

  async function hiddenCorpusFeatureReasonForCql(term: string, corpus?: unknown): Promise<string | null> {
    if (!isCqlfQuery(term)) return null
    const summary = await loadCorpusSummaryForGate(corpus)
    if (!summary) return t('copilot.session.corpusCheckFailed')
    const missing = unsupportedCqlAttributes(summary, term)
    if (missing.length) {
      return t('copilot.session.cqlAttributesUnsupported', { attributes: missing.join(', ') })
    }
    return null
  }

  async function hiddenCorpusFeatureReasonForTool(
    toolName: string,
    args?: Record<string, unknown>
  ): Promise<string | null> {
    const needsCorpusGate = new Set([
      'run_cqlf_query',
      'parallel_kwic',
      'similar_words',
      'semantic_search',
      'frequency_list',
    ])
    if (!needsCorpusGate.has(toolName)) return null

    const corpus = args?.corpus
    const summary = await loadCorpusSummaryForGate(corpus)
    if (!summary) return t('copilot.session.corpusCheckFailed')

    if (toolName === 'parallel_kwic' && !hasParallelKwic(summary)) {
      return t('copilot.session.noParallel')
    }
    if (toolName === 'similar_words' && !hasWordSimilarity(summary)) {
      return t('copilot.session.noWordEmbeddings')
    }
    if (toolName === 'semantic_search' && !hasPassageSearch(summary)) {
      return t('copilot.session.noPassageEmbeddings')
    }
    if (toolName === 'frequency_list') {
      const groupBy = typeof args?.group_by === 'string' ? args.group_by : undefined
      if (groupBy && groupBy !== 'word' && !supportsFrequencyGroup(summary, groupBy as CorpusFrequencyGroup)) {
        return t('copilot.session.frequencyGroupUnsupported', { group: groupBy })
      }
    }
    if (toolName === 'run_cqlf_query' || toolName === 'parallel_kwic') {
      const term = String(args?.query ?? args?.term ?? '')
      const cqlReason = await hiddenCorpusFeatureReasonForCql(term, corpus)
      if (cqlReason) return cqlReason
    }
    return null
  }

  async function operationBlockReasonForToolStatus(
    toolName: string,
    contractStatus: CopilotToolContractStatus,
    args?: Record<string, unknown>
  ): Promise<string | null> {
    if (contractStatus.status === 'unknown') return null

    const operationIds = contractStatus.operationIds ?? []
    if (!operationIds.length) return null

    const needsCorpusSummary = operationIds.some((operationId) =>
      Boolean(productCapabilities.operationFor(operationId)?.route.requires_corpus_features?.length)
    )
    const summary = needsCorpusSummary
      ? await loadCorpusSummaryForGate(args?.corpus)
      : undefined

    for (const operationId of operationIds) {
      const availability = productCapabilities.productOperationAvailability(
        operationId,
        toolName,
        summary
      )
      if (!availability.enabled) {
        return availability.disabledReason
          ?? t('copilot.session.operationNotEnabled')
      }
    }

    return null
  }

  async function mcpRuntimeBlockReasonForToolStatus(
    toolName: string,
    contractStatus: CopilotToolContractStatus,
  ): Promise<string | null> {
    await mcpTools.load()
    return mcpToolRuntimeBlockReason(
      toolName,
      contractStatus,
      mcpTools.toolStatusesByName.get(toolName),
    )
  }

  async function hiddenCapabilityReasonForTool(
    toolName: string,
    args?: Record<string, unknown>
  ): Promise<string | null> {
    await productCapabilities.ensureAccessContext()
    if (!productCapabilities.contract) {
      return t('copilot.session.functionsNotLoaded')
    }
    // Turn control (e.g. deutung_abgeben) has no product operation and is not
    // evidence. The contract names it, so it is shown as the end of the
    // investigation, not blocked.
    if (copilotControlTool(toolName, productCapabilities.contract)) return null
    const contractStatus = copilotToolContractStatus(toolName, productCapabilities.contract)
    if (contractStatus.status === 'unknown') {
      return t('copilot.session.toolNotInstalled', { tool: toolName })
    }
    const owningCapabilityIds = contractStatus.status === 'product'
      ? contractStatus.capabilityIds
      : contractStatus.canonicalCapabilityIds
    const blockedCapabilityIds = owningCapabilityIds.filter((id) => !productCapabilities.isVisible(id))
    if (blockedCapabilityIds.length) {
      return t('copilot.session.toolNotEnabled', { tool: toolName })
    }
    const operationReason = await operationBlockReasonForToolStatus(toolName, contractStatus, args)
    if (operationReason) return operationReason
    const mcpReason = await mcpRuntimeBlockReasonForToolStatus(toolName, contractStatus)
    if (mcpReason) return mcpReason
    const corpusReason = await hiddenCorpusFeatureReasonForTool(toolName, args)
    if (corpusReason) return corpusReason
    return null
  }

  async function mergeToolResultIntoMessageIfVisible(
    messageId: string,
    toolName: string,
    result: unknown,
    input?: unknown,
    herkunft?: { reused: boolean; skipped: boolean },
  ): Promise<void> {
    const reason = await hiddenCapabilityReasonForTool(toolName, asRecord(input))
    if (reason) {
      mergeToolResultIntoMessage(messageId, toolName, {
        status: 'error',
        error: reason,
        blocked: true,
      }, input)
      return
    }
    mergeToolResultIntoMessage(messageId, toolName, result, input, herkunft)
  }

  async function handleToolResultV1(result: ToolResultV1, messageId: string): Promise<void> {
    const output = asRecord(result.output)
    const backendError = [output.error, output.message]
      .find((value): value is string => typeof value === 'string' && !!value.trim())
    const payload = result.ok
      ? result.output ?? result
      : {
          ok: false,
          status: 'error',
          error: backendError ?? t('copilot.session.toolBackendError'),
          output: result.output,
          ...output,
          citations: result.citations,
        }
    await mergeToolResultIntoMessageIfVisible(
      messageId,
      result.toolName,
      payload,
      result.input,
      { reused: result.reused === true, skipped: result.skipped === true },
    )
    if (result.suggestedActions?.length) {
      await Promise.all(result.suggestedActions.map((request) => handleActionRequest(request)))
    }
  }

  async function handleActionCommit(commit: ActionCommitPayload): Promise<void> {
    const requestId = commit.requestId
    if (!requestId) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.commitMissingId'),
      })
      return
    }
    if (committedActionRequestIds.value.has(requestId)) return
    committingActionRequestIds.add(requestId)

    const hasEmbeddedRequest = !!commit.request
    const knownRequest = knownActionRequestIds.value.has(requestId)
      || pendingActionRequests.value.some(r => r.requestId === requestId)
      || currentPreview.value?.requestId === requestId

    if (hasEmbeddedRequest) {
      knownActionRequestIds.value = new Set(knownActionRequestIds.value).add(requestId)
      actionResultRequests.set(requestId, commit.request!)
    }

    const requestForGate = commit.request
      ?? pendingActionRequests.value.find(r => r.requestId === requestId)
      ?? actionResultRequests.get(requestId)
    if (requestForGate) {
      const action = actionRequestToAction(requestForGate)
      const capabilityReason = await hiddenCapabilityReasonForAction(action)
      if (capabilityReason) {
        blockedActionResultRequestIds.add(requestId)
        actionResultRequests.delete(requestId)
        pendingActionRequests.value = pendingActionRequests.value.filter(
          r => r.requestId !== requestId
        )
        actionRequestSessions.delete(requestId)
        resolvePreview(requestId, false, 'rejected')
        rejectBlockedActionRequest(
          requestForGate,
          buildActionMeta(requestForGate),
          t('copilot.session.commitRecheckBlocked', { reason: capabilityReason }),
        )
        committingActionRequestIds.delete(requestId)
        return
      }
    }

    committedActionRequestIds.value = new Set(committedActionRequestIds.value).add(requestId)

    if (!knownRequest && !hasEmbeddedRequest) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.commitUnknown', { id: requestId }),
      })
      committingActionRequestIds.delete(requestId)
      return
    }

    const stillPending = pendingActionRequests.value.some(r => r.requestId === requestId)
      || currentPreview.value?.requestId === requestId
    if (stillPending) {
      resolvePreview(requestId, true)
      pendingActionRequests.value = pendingActionRequests.value.filter(
        r => r.requestId !== requestId
      )
      actionRequestSessions.delete(requestId)
    }
    const content = stillPending
      ? t('copilot.session.commitReceivedPending', { id: requestId })
      : t('copilot.session.commitRegistered', { id: requestId })

    copilotStore.addMessage({
      role: 'system',
      content,
    })
    committingActionRequestIds.delete(requestId)
  }

  async function handleActionResult(result: ActionResultPayload): Promise<void> {
    if (result.request) {
      actionResultRequests.set(result.requestId, result.request)
      knownActionRequestIds.value = new Set(knownActionRequestIds.value).add(result.requestId)
    }

    if (blockedActionResultRequestIds.has(result.requestId)) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.resultRejectedLocally', { id: result.requestId }),
      })
      return
    }

    const request = result.request ?? actionResultRequests.get(result.requestId)
    if (request) {
      let action: ReturnType<typeof actionRequestToAction>
      try {
        action = actionRequestToAction(request)
      } catch {
        copilotStore.addMessage({
          role: 'system',
          content: t('copilot.session.resultUnknownRequest', { id: result.requestId }),
        })
        return
      }
      const capabilityReason = await hiddenCapabilityReasonForAction(action)
      if (capabilityReason) {
        blockedActionResultRequestIds.add(result.requestId)
        copilotStore.addMessage({
          role: 'system',
          content: t('copilot.session.resultBlocked', { id: result.requestId, reason: capabilityReason }),
        })
        return
      }
    }

    if (!result.ok) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.actionFailed', { detail: result.error ?? result.resultSummary ?? result.requestId }),
      })
      return
    }

    if (!result.runId) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.resultNoRun', { id: result.requestId }),
      })
      return
    }

    if (!request) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.resultNoRequest', { id: result.requestId }),
      })
      return
    }

    const run = recordBackendActionResultRun(result, request)
    if (!run) return

    copilotStore.addMessage({
      role: 'system',
      content: t('copilot.session.runMirrored', { run: run.runId, id: result.requestId, summary: run.summary }),
    })
  }

  function readableGroundingVerdict(verdict?: string): string {
    switch (verdict) {
      case 'accepted':
      case 'grounded':
      case 'pass':
        return t('copilot.session.verdictAccepted')
      case 'conservative_only':
        return t('copilot.session.verdictConservative')
      case 'retry':
        return t('copilot.session.verdictRetry')
      case 'rejected':
        return t('copilot.session.verdictRejected')
      case 'verifier_skipped_time_budget':
        return t('copilot.session.verdictSkippedTime')
      default:
        return verdict || t('copilot.session.unknown')
    }
  }

  function compactEventPart(label: string, value?: unknown): string | null {
    if (value === undefined || value === null || value === '') return null
    return `${label}: ${String(value)}`
  }

  /** The analysis family in words, the code itself when it has no label. */
  function readableAnalysisFamily(family?: string): string | undefined {
    if (!family) return undefined
    const key = `copilot.session.family.${family}`
    return te(key) ? t(key) : family
  }

  function showGroundingEvent(event: CopilotGroundingEvent): void {
    const rejected = Number(event.rejected_claim_count ?? 0)
    const family = compactEventPart(t('copilot.session.partAnalysis'), readableAnalysisFamily(event.analysis_family))
    let parts: Array<string | null>
    if (event.verdict === 'deutungs_synthese') {
      // The evidence map of the interpretation path. It arrives before the
      // answer is written, it is no verdict on an answer.
      const count = Array.isArray(event.evidence) ? event.evidence.length : 0
      parts = [t('copilot.session.evidenceForAnswer', { count }, count)]
    } else if (event.verdict === 'partial_on_engine_error') {
      // The landing after a model failure. copilot.done names the failure
      // (showAnswerAfterFailure), the error text stands in the annotations.
      return
    } else if (event.verdict === 'completed_on_collected_evidence') {
      parts = [t('copilot.session.answerFromCollectedEvidence')]
    } else if (event.verdict === 'final_polish') {
      // The notes of the last step before the answer is delivered.
      const notes = Array.isArray(event.annotations) ? event.annotations.length : 0
      parts = [
        t('copilot.session.answerFinished'),
        family,
        notes > 0 ? t('copilot.session.answerNotes', { count: notes }, notes) : null,
      ]
    } else {
      parts = [
        t('copilot.session.groundingChecked', { verdict: readableGroundingVerdict(event.verdict) }),
        family,
        compactEventPart(t('copilot.session.partRoute'), event.route),
        compactEventPart(t('copilot.session.partModel'), event.model),
        rejected > 0 ? t('copilot.session.claimsRejected', { count: rejected }, rejected) : null,
      ]
    }
    copilotStore.addMessage({
      role: 'system',
      content: parts.filter(Boolean).join(' · '),
    })
  }

  function showEvidenceGapEvent(event: CopilotEvidenceGapEvent): void {
    const gaps = Array.isArray(event.gaps)
      ? event.gaps.map((gap) => String(gap).trim()).filter(Boolean)
      : []
    const summary = gaps.length ? gaps.slice(0, 3).join('; ') : t('copilot.session.evidenceGapFallback')
    copilotStore.addMessage({
      role: 'system',
      content: [
        t('copilot.session.evidenceGap', { summary }),
        compactEventPart(t('copilot.session.partAnalysis'), event.analysis_family),
        compactEventPart(t('copilot.session.partModel'), event.model),
      ].filter(Boolean).join(' · '),
    })
  }

  /**
   * A model failure the answer follows: the server lands the answer from the
   * collected evidence and names the failure in `copilot.done` (or it sent
   * `copilot.error` before that frame, see the stream dispatcher).
   */
  function showAnswerAfterFailure(meta?: CopilotDoneMeta): void {
    if (!meta?.error) return
    copilotStore.addMessage({
      role: 'system',
      content: t('copilot.session.answerAfterFailure', { error: localizeCopilotError(new Error(meta.error)) }),
    })
  }

  function showRecoveryEvent(event: CopilotRecoveryEvent): void {
    // The kind in words. A kind without a label is not shown as a code: the
    // message of the event says what happened.
    const kindKey = event.kind ? `copilot.session.recoveryKind.${event.kind}` : ''
    const heading = kindKey && te(kindKey)
      ? t('copilot.session.recovery', { kind: t(kindKey) })
      : t('copilot.session.recoveryGeneric')
    copilotStore.addMessage({
      role: 'system',
      content: [
        heading,
        event.message,
        compactEventPart(t('copilot.session.partRoute'), event.route),
        compactEventPart(t('copilot.session.partModel'), event.model),
        event.retryable ? t('copilot.session.retryPossible') : null,
      ].filter(Boolean).join(' · '),
    })
  }

  function pushResearchStatus(kind: 'research' | 'context', text: string, ts?: number): void {
    researchEvents.value = [
      ...researchEvents.value,
      {
        id: crypto.randomUUID(),
        kind,
        text,
        ts: typeof ts === 'number' ? ts : Date.now(),
      },
    ].slice(-RESEARCH_STATUS_LIMIT)
  }

  /** `copilot.research`: progress of the background research worker. */
  function showResearchEvent(event: CopilotResearchEvent): void {
    const parts = [
      t('copilot.session.researchPhase', { phase: event.phase || t('copilot.session.unknown') }),
      compactEventPart(t('copilot.session.partQuery'), event.query),
      compactEventPart(t('copilot.session.partStatus'), event.status),
    ].filter(Boolean)
    pushResearchStatus('research', parts.join(' · '), event.ts)
  }

  /** `copilot.research_context`: which research tags stay active. */
  function showResearchContextEvent(event: CopilotResearchContextEvent): void {
    const keep = Array.isArray(event.keep)
      ? event.keep.map((tag) => String(tag).trim()).filter(Boolean)
      : []
    const text = keep.length
      ? t('copilot.session.researchContextUpdated', { tags: keep.join(', ') })
      : t('copilot.session.researchContextCleared')
    pushResearchStatus('context', text, event.ts)
  }

  /**
   * `copilot.action_blocked`: the backend refused a control action. Rendered
   * as a visible system message including the backend reason.
   */
  function showActionBlockedEvent(event: CopilotActionBlockedEvent): void {
    const type = event.request?.type ? ` "${event.request.type}"` : ''
    const reason = event.meta?.reason || t('copilot.session.actionBlockedNoReason')
    copilotStore.addMessage({
      role: 'system',
      content: [
        t('copilot.session.actionBlockedByServer', { type, reason }),
        compactEventPart(t('copilot.session.partSummary'), event.meta?.summary),
      ].filter(Boolean).join(' · '),
    })
  }

  /**
   * Send a message to the Copilot with streaming.
   * The LLM backend proposes tool/action use, but execution still goes
   * through backend policy and local action gates.
   */
  async function sendMessage(message: string): Promise<void> {
    // A new request supersedes the old turn visibly and makes late SSE frames inert.
    stopActiveStream()

    // Add user message
    copilotStore.addMessage({
      role: 'user',
      content: message
    })

    if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.chatStream, message)) {
      return
    }

    // Start streaming
    copilotStore.setStreaming(true)

    const assistantMessageId = copilotStore.addMessage({
      role: 'assistant',
      content: '',
      isStreaming: true,
      toolCalls: []
    })
    // Die Arbeitsspur faehrt von selbst ein, sobald gearbeitet wird. Wer
    // sie im laufenden Turn von Hand schliesst, bei dem bleibt sie zu: eine
    // Ansicht, die sich gegen den erklaerten Willen erneut oeffnet, ist eine
    // Zumutung.
    spurStore.turnBeginnt(assistantMessageId)
    const generation = beginStream(assistantMessageId)
    const isCurrent = () => isCurrentStream(generation, assistantMessageId)

    let fullContent = ''

    // Build context (use full context for first message in conversation)
    const contextResult = buildContext(true)
    const context = contextResult.full || getFullContext()

    // Build UI snapshot for the LLM. buildSnapshotSync() reads
    // copilotStore.autonomyLevel live, so the value is never stale. The
    // snapshot nests autonomy under session.autonomy; we additionally surface a
    // top-level autonomy_level so the backend's plan-gate reads it from
    // ui_context.autonomy_level at send time (id 1). The background-research
    // preference travels as ui_context.disable_background_research, which the
    // orchestrator reads in _should_run_research_worker.
    const snapshot = {
      ...(buildSnapshotSync() as unknown as Record<string, unknown>),
      autonomy_level: copilotStore.autonomyLevel,
      ...(settingsStore.preferences.backgroundResearch === false
        ? { disable_background_research: true }
        : {}),
    }

    const streamCancel = streamCopilotMessage(message, {
      conversationId: copilotStore.conversationId ?? undefined,
      context,
      snapshot,

      onContent: (content) => {
        if (!isCurrent()) return
        fullContent += content
        copilotStore.appendStreamingContent(content)
        copilotStore.updateMessage(assistantMessageId, {
          content: fullContent,
          isStreaming: true
        })
      },

      onToolPhase: (phase) => {
        if (!isCurrent()) return
        applyToolPhase(assistantMessageId, phase)
      },

      onStatus: (status) => {
        if (!isCurrent()) return
        applyStreamStatus(assistantMessageId, status)
      },

      onCancelled: () => {
        if (!isCurrent()) return
        finalizeCancelledTurn(assistantMessageId)
      },

      onToolResultV1: (result) => {
        if (!isCurrent()) return
        void handleToolResultV1(result, assistantMessageId)
      },

      // === New Structured Event Handlers ===

      onPlan: (plan) => {
        if (!isCurrent()) return
        const normalized = normalizePlan(plan)
        currentPlan.value = normalized
        // Add a system message showing the plan
        copilotStore.addMessage({
          role: 'assistant',
          content: `**Plan: ${normalized.goal}**\n\n${normalized.steps.map((s, i) => `${i + 1}. ${s.title}`).join('\n')}`
        })
      },

      onClarifyV1: (question) => {
        if (!isCurrent()) return
        const normalized = normalizeClarify(question)
        currentClarification.value = normalized
        // Convert to legacy format for existing UI
        copilotStore.updateMessage(assistantMessageId, {
          clarification: {
            id: normalized.questionId,
            explanation: normalized.prompt,
            options: normalized.options.map(o => ({
              id: o.id,
              label: o.label,
              value: o.value
            })),
            answered: false,
            timeout: normalized.blocking ? DEFAULT_CLARIFICATION_TIMEOUT_MS : undefined,
            fallbackOptionId: normalized.options.find(o => o.isDefault)?.id
          }
        })
      },

      onActionRequest: (request, meta) => {
        if (!isCurrent()) return
        void handleActionRequest(request, meta)
      },

      onActionCommit: (commit) => {
        if (!isCurrent()) return
        void handleActionCommit(commit)
      },

      onActionResult: (result) => {
        if (!isCurrent()) return
        void handleActionResult(result)
      },

      onGrounding: (event) => {
        if (!isCurrent()) return
        applyGroundingAnnotations(assistantMessageId, event)
        showGroundingEvent(event)
      },

      onVorlaeufigeAntwort: (event) => {
        if (!isCurrent()) return
        applyVorlaeufigeAntwort(assistantMessageId, event)
      },

      onEvidenceGap: (event) => {
        if (!isCurrent()) return
        showEvidenceGapEvent(event)
      },

      onRecovery: (event) => {
        if (!isCurrent()) return
        showRecoveryEvent(event)
      },

      onResearch: (event) => {
        if (!isCurrent()) return
        showResearchEvent(event)
      },

      onResearchContext: (event) => {
        if (!isCurrent()) return
        showResearchContextEvent(event)
      },

      onActionBlocked: (event) => {
        if (!isCurrent()) return
        showActionBlockedEvent(event)
      },

      onDone: (finalContent, meta) => {
        if (!isCurrent()) return
        copilotStore.setStreaming(false)
        const bilanz = usageFromDoneMeta(meta)
        const stages = zeitleisteAbschliessen(assistantMessageId, bilanz)
        copilotStore.updateMessage(assistantMessageId, {
          content: finalContent,
          isStreaming: false,
          status: undefined,
          // Die Gegenlesung ist durch: die Marke muss weg, sonst behauptet
          // eine fertige Antwort weiter, sie sei vorlaeufig.
          vorlaeufig: false,
          ...(stages?.length ? { stages } : {}),
          usage: bilanz
        })
        showAnswerAfterFailure(meta)
        cancelStream.value = null
        activeAssistantMessageId = null
        // Clear plan after completion
        currentPlan.value = null
      },

      onError: (error) => {
        if (!isCurrent()) return
        copilotStore.setStreaming(false)

        // A single streamed whitespace delta makes `fullContent` truthy, which
        // previously suppressed the "Fehler: …" fallback and left a blank
        // bubble (id 3). Treat whitespace-only content as empty. When real
        // content WAS received before the failure, keep it and append the error
        // notice rather than discarding it (id 0) — any tool results already on
        // the message (e.g. keyness rows) stay intact via the existing
        // toolCalls.
        const received = fullContent.trim()
        const errorNotice = t('copilot.session.errorNotice', { message: localizeCopilotError(error) })
        const content = received
          ? `${fullContent}\n\n${errorNotice}`
          : errorNotice

        copilotStore.updateMessage(assistantMessageId, {
          content,
          isStreaming: false,
          status: undefined,
          // Die Gegenlesung ist nicht mehr unterwegs, sie ist gescheitert.
          vorlaeufig: false,
          error: true,
          retryPrompt: message
        })

        // Use error handler for proper error management
        errorHandler.handleError(error, {
          action: { type: 'copilot/sendMessage', payload: { message } },
          component: 'CopilotChat',
          operation: 'sendMessage'
        })

        cancelStream.value = null
        activeAssistantMessageId = null
        currentPlan.value = null
      }
    })
    if (isCurrent()) {
      cancelStream.value = streamCancel
    } else {
      streamCancel()
    }
  }

  /**
   * Retry a failed assistant turn (id 0).
   *
   * Clears the error/retry markers on the failed bubble so its retry affordance
   * disappears, then re-sends the original user prompt. Already-received tool
   * results live on their own (preserved) message and are unaffected.
   */
  async function retryMessage(messageId: string) {
    const failed = copilotStore.messages.find(m => m.id === messageId)
    const prompt = failed?.retryPrompt
    if (!prompt) return

    copilotStore.updateMessage(messageId, { error: false, retryPrompt: undefined })
    await sendMessage(prompt)
  }

  /**
   * Answer a clarification question from the LLM
   */
  async function answerClarification(questionId: string, optionId: string) {
    copilotStore.answerClarification(questionId, optionId)

    // Send the selected answer as a follow-up message to the LLM
    const question = copilotStore.messages.find(m => m.clarification?.id === questionId)
    const option = question?.clarification?.options.find(o => o.id === optionId)

    if (option) {
      await sendMessage(`${option.label}`)
    }
  }

  async function hiddenCorpusFeatureReasonForAction(
    action: ReturnType<typeof actionRequestToAction>
  ): Promise<string | null> {
    const typedAction = action as { type: string; payload?: Record<string, unknown> }
    const payload = typedAction.payload ?? {}

    if (typedAction.type === 'query/execute') {
      const filters = payload.filters as Record<string, unknown> | undefined
      return hiddenCorpusFeatureReasonForCql(String(payload.term ?? ''), filters?.corpus)
    }
    if (typedAction.type === 'query/loadMore') {
      return hiddenCorpusFeatureReasonForCql(queryStore.term, queryStore.filters.corpus)
    }
    if (typedAction.type === 'analysis/frequency') {
      const groupBy = typeof payload.groupBy === 'string' ? payload.groupBy : undefined
      if (!groupBy || groupBy === 'word') return null
      const summary = await loadCorpusSummaryForGate(queryStore.filters.corpus)
      if (!summary) return t('copilot.session.corpusCheckFailed')
      if (!supportsFrequencyGroup(summary, groupBy as CorpusFrequencyGroup)) {
        return t('copilot.session.frequencyGroupUnsupported', { group: groupBy })
      }
    }
    if (typedAction.type === 'analysis/semantic') {
      const summary = await loadCorpusSummaryForGate(queryStore.filters.corpus)
      if (!summary) return t('copilot.session.corpusCheckFailed')
      const mode = payload.mode === 'thesaurus' ? 'thesaurus' : 'passage'
      if (mode === 'thesaurus' && !hasWordSimilarity(summary)) {
        return t('copilot.session.noWordEmbeddings')
      }
      if (mode === 'passage' && !hasPassageSearch(summary)) {
        return t('copilot.session.noPassageEmbeddings')
      }
    }
    return null
  }

  async function hiddenCapabilityReasonForAction(action: ReturnType<typeof actionRequestToAction>): Promise<string | null> {
    await productCapabilities.ensureAccessContext()
    if (!productCapabilities.contract) {
      return t('copilot.session.capabilityCatalogFailed')
    }

    if (
      (action.type === 'query/execute' || action.type === 'query/loadMore' || action.type === 'query/setFilters')
      && !productCapabilities.isVisible('query.kwic')
    ) {
      return t('copilot.session.kwicNotEnabled')
    }

    const actionCapabilityIds = action.type.startsWith('query/')
      ? undefined
      : productActionTypeMap(productCapabilities.contract).get(action.type)
    if (actionCapabilityIds?.length) {
      const blockedCapabilityIds = actionCapabilityIds.filter((id) => !productCapabilities.isVisible(id))
      if (blockedCapabilityIds.length) {
        return t('copilot.session.actionHidden', { action: action.type, capabilities: blockedCapabilityIds.join(', ') })
      }
    } else if (action.type.startsWith('query/')) {
      // Query actions share the KWIC/CQLF executor; handled explicitly above and below.
      // Do not require a one-to-one action map entry for the CQLF overlay capability.
    } else if (action.type === 'nav/switchTab') {
      if (!productCapabilities.isAnalysisTabVisible(action.payload.tab)) {
        return t('copilot.session.tabNotEnabled', { tab: action.payload.tab })
      }
    } else if (action.type.startsWith('kwic/')) {
      if (!productCapabilities.isVisible('query.kwic')) {
        return t('copilot.session.kwicActionsNotEnabled')
      }
    } else if (action.type.startsWith('copilot/')) {
      if (!productCapabilities.isVisible('research.copilot_grounding')) {
        return t('copilot.session.copilotActionsNotEnabled')
      }
    } else if (action.type === 'ui/toast' || action.type === 'ui/setLoading') {
      return null
    } else {
      return t('copilot.session.actionNotRegistered', { action: action.type })
    }

    if (action.type === 'query/execute' && isCqlfQuery(action.payload.term)) {
      if (!productCapabilities.isVisible('query.cqlf')) {
        return t('copilot.session.cqlfNotEnabled')
      }
    }
    if (action.type === 'query/loadMore' && isCqlfQuery(queryStore.term)) {
      if (!productCapabilities.isVisible('query.cqlf')) {
        return t('copilot.session.cqlfPagingNotEnabled')
      }
    }
    const routeReason = routeOperationBlockReasonForAction(action)
    if (routeReason) return routeReason

    const actionRecord = action as { type: string; payload?: Record<string, unknown> }
    const payload = actionRecord.payload ?? {}
    const needsCorpusFeatureGate =
      (actionRecord.type === 'query/execute' && isCqlfQuery(String(payload.term ?? ''))) ||
      (actionRecord.type === 'query/loadMore' && isCqlfQuery(queryStore.term)) ||
      actionRecord.type === 'analysis/frequency' ||
      actionRecord.type === 'analysis/semantic'
    if (needsCorpusFeatureGate) {
      const corpusFeatureReason = await hiddenCorpusFeatureReasonForAction(action)
      if (corpusFeatureReason) return corpusFeatureReason
    }
    return null
  }

  async function handleActionRequest(
    request: ActionRequestV1,
    meta?: ActionMeta | Record<string, unknown>
  ): Promise<void> {
    if (
      committedActionRequestIds.value.has(request.requestId)
      || committingActionRequestIds.has(request.requestId)
    ) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.requestIgnored', { id: request.requestId }),
      })
      return
    }
    if (
      pendingActionRequests.value.some(r => r.requestId === request.requestId)
      || currentPreview.value?.requestId === request.requestId
      || knownActionRequestIds.value.has(request.requestId)
    ) {
      return
    }

    knownActionRequestIds.value = new Set(knownActionRequestIds.value).add(request.requestId)
    actionResultRequests.set(request.requestId, request)
    const action = actionRequestToAction(request)
    const previewMeta = buildActionMeta(request, meta)
    const capabilityReason = await hiddenCapabilityReasonForAction(action)
    if (capabilityReason) {
      actionResultRequests.delete(request.requestId)
      blockedActionResultRequestIds.add(request.requestId)
      rejectBlockedActionRequest(request, previewMeta, capabilityReason)
      return
    }
    const decision = getPolicyDecision(action, copilotStore.autonomyLevel, 'copilot')
    const sessionId = getCurrentSessionId()

    if (decision === 'block') {
      actionResultRequests.delete(request.requestId)
      blockedActionResultRequestIds.add(request.requestId)
      rejectBlockedActionRequest(request, previewMeta)
      return
    }

    if (!sessionId) {
      actionResultRequests.delete(request.requestId)
      blockedActionResultRequestIds.add(request.requestId)
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.noSession', { label: previewMeta.label }),
      })
      return
    }

    if (!requiresFrontendApproval(meta)) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.notPending', { label: previewMeta.label }),
      })
      return
    }

    actionRequestSessions.set(request.requestId, sessionId)
    pendingActionRequests.value.push(request)
    addActionPreview(action, previewMeta, 'preview', request.rationale, request.requestId)
  }

  function rejectBlockedActionRequest(request: ActionRequestV1, meta: ActionMeta, detail?: string) {
    const reason = detail
      ? t('copilot.session.policyBlockedDetail', { label: meta.label, type: request.type, detail })
      : t('copilot.session.policyBlocked', { label: meta.label, type: request.type })
    copilotStore.addMessage({
      role: 'system',
      content: reason,
    })

    const sessionId = getCurrentSessionId()
    if (!sessionId) return

    void (async () => {
      if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.actionReject)) return
      await apiRejectAction(request.requestId, reason, sessionId)
      await continueCopilotAfterActionResolution(sessionId)
    })()
        .catch((error) => {
          console.warn('[Copilot] Failed to notify backend of blocked action:', error)
        })
  }

  function requiresFrontendApproval(meta?: ActionMeta | Record<string, unknown>): boolean {
    if (!meta || typeof meta !== 'object') return true
    const record = meta as Record<string, unknown>
    if (record.requiresApproval === false) return false
    if (record.status === 'auto_approved') return false
    return true
  }

  /**
   * Cancel ongoing stream
   */
  function cancel() {
    stopActiveStream()
  }

  /**
   * Quick actions
   */
  function open(mode?: 'floating' | 'docked') {
    copilotStore.open(mode)
  }

  function close() {
    cancel()
    copilotStore.close()
  }

  function toggle() {
    copilotStore.toggle()
  }

  function setAutonomy(level: number) {
    copilotStore.setAutonomyLevel(level)
  }

  // === Plan and Action Management ===

  /**
   * Clear current plan
   */
  function clearPlan() {
    currentPlan.value = null
  }

  /**
   * Approve a pending action preview and continue orchestration
   */
  async function approveAction(requestId: string) {
    if (committedActionRequestIds.value.has(requestId)) {
      resolveCommittedPreview(requestId)
      return
    }
    if (!startActionResolution(requestId)) return

    const sessionId = actionRequestSessions.get(requestId)
    if (sessionId) {
      try {
        if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.actionApprove)) {
          finishActionResolution(requestId)
          return
        }
        await apiApproveAction(requestId, sessionId)
      } catch (error) {
        console.warn('[Copilot] Failed to notify backend of action approval:', error)
        finishActionResolution(requestId)
        return
      }
    } else if (hasPendingBackendAction(requestId)) {
      console.warn('[Copilot] Refusing to approve backend action without active request session:', requestId)
      finishActionResolution(requestId)
      return
    }

    try {
      resolvePreview(requestId, true)
      knownActionRequestIds.value = new Set(knownActionRequestIds.value).add(requestId)
      pendingActionRequests.value = pendingActionRequests.value.filter(
        r => r.requestId !== requestId
      )
      actionRequestSessions.delete(requestId)

      if (sessionId) {
        await continueCopilotAfterActionResolution(sessionId)
      }
    } finally {
      finishActionResolution(requestId)
    }
  }

  function startActionResolution(requestId: string): boolean {
    if (actionResolutionInFlight.value.has(requestId)) {
      return false
    }
    actionResolutionInFlight.value = new Set(actionResolutionInFlight.value).add(requestId)
    return true
  }

  function finishActionResolution(requestId: string): void {
    const next = new Set(actionResolutionInFlight.value)
    next.delete(requestId)
    actionResolutionInFlight.value = next
  }

  function hasPendingBackendAction(requestId: string): boolean {
    return pendingActionRequests.value.some(r => r.requestId === requestId)
  }

  /**
   * Reject a pending action preview
   */
  async function rejectAction(requestId: string, reason?: string) {
    if (committedActionRequestIds.value.has(requestId)) {
      resolveCommittedPreview(requestId)
      return
    }
    if (!startActionResolution(requestId)) return

    const sessionId = actionRequestSessions.get(requestId)
    if (sessionId) {
      try {
        if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.actionReject)) {
          finishActionResolution(requestId)
          return
        }
        await apiRejectAction(requestId, reason, sessionId)
      } catch (error) {
        console.warn('[Copilot] Failed to notify backend of action rejection:', error)
        finishActionResolution(requestId)
        return
      }
    } else if (hasPendingBackendAction(requestId)) {
      console.warn('[Copilot] Refusing to reject backend action without active request session:', requestId)
      finishActionResolution(requestId)
      return
    }

    try {
      resolvePreview(requestId, false)
      pendingActionRequests.value = pendingActionRequests.value.filter(
        r => r.requestId !== requestId
      )
      actionRequestSessions.delete(requestId)
      actionResultRequests.delete(requestId)
      blockedActionResultRequestIds.add(requestId)
      if (sessionId) {
        await continueCopilotAfterActionResolution(sessionId)
      }
    } finally {
      finishActionResolution(requestId)
    }
  }

  function resolveCommittedPreview(requestId: string): void {
    resolvePreview(requestId, true)
    pendingActionRequests.value = pendingActionRequests.value.filter(
      r => r.requestId !== requestId
    )
    actionRequestSessions.delete(requestId)
    knownActionRequestIds.value = new Set(knownActionRequestIds.value).add(requestId)
    copilotStore.addMessage({
      role: 'system',
      content: t('copilot.session.alreadyCommitted', { id: requestId }),
    })
  }

  /**
   * Continue orchestration after approval, rejection or clarification
   */
  async function continueCopilotAfterActionResolution(sessionId: string) {
    if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.continue)) {
      return
    }

    // An approved/rejected action starts the next explicit turn. Do not let a
    // buffered frame from the preceding turn mutate this continuation.
    stopActiveStream()

    const assistantMessageId = copilotStore.addMessage({
      role: 'assistant',
      content: '',
      isStreaming: true
    })
    // Die Arbeitsspur faehrt von selbst ein, sobald gearbeitet wird. Wer
    // sie im laufenden Turn von Hand schliesst, bei dem bleibt sie zu: eine
    // Ansicht, die sich gegen den erklaerten Willen erneut oeffnet, ist eine
    // Zumutung.
    spurStore.turnBeginnt(assistantMessageId)
    const generation = beginStream(assistantMessageId)
    const isCurrent = () => isCurrentStream(generation, assistantMessageId)
    let fullContent = ''
    copilotStore.setStreaming(true)

    const streamCancel = continueCopilotExecution({
      onContent: (content) => {
        if (!isCurrent()) return
        fullContent += content
        copilotStore.updateMessage(assistantMessageId, {
          content: fullContent,
          isStreaming: true
        })
      },

      onToolPhase: (phase) => {
        if (!isCurrent()) return
        applyToolPhase(assistantMessageId, phase)
      },

      onStatus: (status) => {
        if (!isCurrent()) return
        applyStreamStatus(assistantMessageId, status)
      },

      onCancelled: () => {
        if (!isCurrent()) return
        finalizeCancelledTurn(assistantMessageId)
      },

      onPlan: (plan) => {
        if (!isCurrent()) return
        currentPlan.value = normalizePlan(plan)
      },

      onClarifyV1: (question) => {
        if (!isCurrent()) return
        currentClarification.value = normalizeClarify(question)
      },

      onActionRequest: (request, meta) => {
        if (!isCurrent()) return
        void handleActionRequest(request, meta)
      },

      onActionCommit: (commit) => {
        if (!isCurrent()) return
        void handleActionCommit(commit)
      },

      onActionResult: (result) => {
        if (!isCurrent()) return
        void handleActionResult(result)
      },

      onToolResultV1: (result) => {
        if (!isCurrent()) return
        void handleToolResultV1(result, assistantMessageId)
      },

      onGrounding: (event) => {
        if (!isCurrent()) return
        applyGroundingAnnotations(assistantMessageId, event)
        showGroundingEvent(event)
      },

      onVorlaeufigeAntwort: (event) => {
        if (!isCurrent()) return
        applyVorlaeufigeAntwort(assistantMessageId, event)
      },

      onEvidenceGap: (event) => {
        if (!isCurrent()) return
        showEvidenceGapEvent(event)
      },

      onRecovery: (event) => {
        if (!isCurrent()) return
        showRecoveryEvent(event)
      },

      onResearch: (event) => {
        if (!isCurrent()) return
        showResearchEvent(event)
      },

      onResearchContext: (event) => {
        if (!isCurrent()) return
        showResearchContextEvent(event)
      },

      onActionBlocked: (event) => {
        if (!isCurrent()) return
        showActionBlockedEvent(event)
      },

      onDone: (finalContent, meta) => {
        if (!isCurrent()) return
        copilotStore.setStreaming(false)
        const bilanz = usageFromDoneMeta(meta)
        const stages = zeitleisteAbschliessen(assistantMessageId, bilanz)
        copilotStore.updateMessage(assistantMessageId, {
          content: finalContent,
          isStreaming: false,
          status: undefined,
          // Die Gegenlesung ist durch: die Marke muss weg, sonst behauptet
          // eine fertige Antwort weiter, sie sei vorlaeufig.
          vorlaeufig: false,
          ...(stages?.length ? { stages } : {}),
          usage: bilanz
        })
        showAnswerAfterFailure(meta)
        cancelStream.value = null
        activeAssistantMessageId = null
        currentPlan.value = null
      },

      onError: (error) => {
        if (!isCurrent()) return
        copilotStore.setStreaming(false)
        // Same whitespace-only guard as sendMessage (id 3): a stray blank delta
        // must not suppress the error notice.
        const received = fullContent.trim()
        const errorNotice = t('copilot.session.errorNotice', { message: localizeCopilotError(error) })
        copilotStore.updateMessage(assistantMessageId, {
          content: received ? `${fullContent}\n\n${errorNotice}` : errorNotice,
          isStreaming: false,
          status: undefined,
          error: true
        })
        errorHandler.handleError(error, {
          action: { type: 'copilot/continue', payload: { sessionId } },
          component: 'CopilotChat',
          operation: 'continueAfterActionResolution'
        })
        cancelStream.value = null
        activeAssistantMessageId = null
      }
    }, sessionId)
    if (isCurrent()) {
      cancelStream.value = streamCancel
    } else {
      streamCancel()
    }
  }

  /**
   * Clear all pending action previews
   */
  function clearAllPreviews() {
    clearPreviews()
  }

  /**
   * Answer a V1 clarification question and continue orchestration
   */
  async function answerClarificationV1(questionId: string, optionId: string, _value: unknown) {
    if (currentClarification.value?.questionId !== questionId) return

    // Notify backend (if we have a session)
    const sessionId = getCurrentSessionId()
    if (!sessionId) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.clarificationNoSession'),
      })
      return
    }

    try {
      if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.clarificationAnswer)) {
        return
      }
      await apiAnswerClarification(questionId, optionId, sessionId)
      if (currentClarification.value?.questionId === questionId) {
        currentClarification.value = null
      }
      // Also mark the message-level clarification as answered — otherwise the
      // ClarificationCard (degraded V1 path) keeps hanging after the answer.
      copilotStore.answerClarification(questionId, optionId)

      // Continue the orchestration loop with the acknowledged answer.
      await continueCopilotAfterActionResolution(sessionId)
    } catch (error) {
      console.warn('[Copilot] Failed to notify backend of clarification answer:', error)
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.clarificationSendFailed', { error: localizeCopilotError(error instanceof Error ? error : new Error(String(error))) }),
      })
    }
  }

  /**
   * Answer with free text input and continue orchestration
   */
  async function answerClarificationFreeText(questionId: string | null, text: string) {
    if (!questionId || currentClarification.value?.questionId !== questionId) return

    // Notify backend (if we have a session)
    const sessionId = getCurrentSessionId()
    if (!sessionId) {
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.clarificationNoSession'),
      })
      return
    }

    try {
      if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.clarificationAnswer)) {
        return
      }
      await apiAnswerClarification(questionId, text, sessionId)
      if (currentClarification.value?.questionId === questionId) {
        currentClarification.value = null
      }
      // Same hang-guard as answerClarificationV1: close the message-level
      // clarification once the free-text answer is acknowledged.
      copilotStore.answerClarification(questionId, text)

      // Continue the orchestration loop with the acknowledged answer.
      await continueCopilotAfterActionResolution(sessionId)
    } catch (error) {
      console.warn('[Copilot] Failed to notify backend of free-text clarification:', error)
      copilotStore.addMessage({
        role: 'system',
        content: t('copilot.session.clarificationSendFailed', { error: localizeCopilotError(error instanceof Error ? error : new Error(String(error))) }),
      })
    }
  }

  /**
   * A clarification timeout is not an answer. Keep the backend from receiving
   * fabricated input and make the abandoned turn visibly terminal instead.
   */
  function expireClarification(questionId: string | null): void {
    if (!questionId || currentClarification.value?.questionId !== questionId) return
    stopActiveStream()
    copilotStore.addMessage({
      role: 'system',
      content: t('copilot.session.clarificationExpired'),
    })
  }

  /**
   * Sync UI context with backend
   */
  async function syncContext() {
    const sessionId = getCurrentSessionId()
    if (!sessionId) return

    const context = getFullContext()
    try {
      if (!await assertCopilotOperation(COPILOT_GROUNDING_OPERATIONS.contextUpdate)) {
        return
      }
      await updateCopilotContext(context, sessionId)
    } catch (error) {
      console.warn('[Copilot] Failed to sync context:', error)
    }
  }

  return {
    // State (readonly)
    isOpen: computed(() => copilotStore.isOpen),
    isThinking: computed(() => copilotStore.isThinking),
    messages: computed(() => copilotStore.messages),
    autonomyLevel: computed(() => copilotStore.autonomyLevel),
    autonomyDescription: computed(() => copilotStore.autonomyDescription),
    pendingClarification: computed(() => copilotStore.pendingClarification),
    mode: computed(() => copilotStore.mode),

    // === New Structured State ===
    currentPlan,
    currentClarification,
    researchEvents: computed(() => researchEvents.value),
    pendingActionRequests: computed(() => pendingActionRequests.value),
    currentActionPreview: currentPreview,

    // Actions
    sendMessage,
    retryMessage,
    answerClarification,
    cancel,
    open,
    close,
    toggle,
    setAutonomy,

    // === Plan and Action Management ===
    clearPlan,
    approveAction,
    rejectAction,
    clearAllPreviews,
    answerClarificationV1,
    answerClarificationFreeText,
    expireClarification,
    continueCopilotAfterActionResolution,

    // Context
    buildContext,
    getFullContext,
    syncContext,

    // Error handler
    errorHandler
  }
}
  function normalizePlan(raw: PlanV1 | Record<string, unknown>): PlanV1 {
    if (!raw || typeof raw !== 'object') {
      return { goal: '', steps: [] }
    }
    const plan = raw as Partial<PlanV1> & {
      steps?: Array<Record<string, unknown>>
    }
    const steps = (plan.steps || []).map((step, idx) => {
      const stepId = String(step.stepId ?? step.id ?? idx + 1)
      const title = String(step.title ?? step.description ?? step.tool ?? t('copilot.session.planStepFallback', { n: idx + 1 }))
      const expectedOutput = String(step.expectedOutput ?? step.rationale ?? plan.expectedOutcome ?? '')
      return {
        stepId,
        title,
        expectedOutput,
      }
    })
    return {
      goal: String(plan.goal ?? ''),
      steps,
      ...(plan.expectedOutcome !== undefined ? { expectedOutcome: String(plan.expectedOutcome) } : {}),
      ...(plan.status !== undefined ? { status: String(plan.status) } : {}),
    }
  }

  function normalizeClarify(raw: ClarifyV1 | Record<string, unknown>): ClarifyV1 {
    const question = raw as ClarifyV1 & { defaultOption?: string }
    const options = (question.options || []).map((opt) => {
      const isDefault = opt.isDefault ?? (question.defaultOption ? opt.id === question.defaultOption : false)
      return {
        ...opt,
        value: opt.value ?? opt.id ?? opt.label,
        isDefault,
      }
    })
    return {
      questionId: question.questionId,
      prompt: question.prompt,
      blocking: question.blocking ?? true,
      options,
      freeInput: question.freeInput,
      rationale: question.rationale,
    }
  }

  function buildActionMeta(
    request: ActionRequestV1,
    meta?: ActionMeta | Record<string, unknown>
  ): ActionMeta {
    const registryMeta = getActionMeta(request.type)
    const summary = typeof meta === 'object' && meta ? (meta as { summary?: string }).summary : undefined
    const reversible = typeof meta === 'object' && meta ? (meta as { reversible?: boolean }).reversible : undefined
    return {
      type: request.type,
      label: summary || registryMeta?.label || request.type,
      reversible: reversible ?? registryMeta?.reversible ?? true,
      userVisible: registryMeta?.userVisible ?? true,
      cost: registryMeta?.cost ?? 'medium',
      scientificRisk: registryMeta?.scientificRisk ?? ['none'],
      requiresConfirmationAtOrBelowAutonomy: registryMeta?.requiresConfirmationAtOrBelowAutonomy ?? 5,
      preconditions: registryMeta?.preconditions,
    }
  }
