/**
 * SSE Client - Server-Sent Events for Copilot streaming
 *
 * Handles structured control frames from the LLM:
 * - <<<CC:PLAN {...}>>> - Execution plan
 * - <<<CC:CLARIFY {...}>>> - Clarification question
 * - <<<CC:ACTION {...}>>> - Action request
 */

import type {
  PlanV1,
  ClarifyV1,
  ActionRequestV1,
  ActionMeta,
  ActionCommitPayload,
  ActionResultPayload,
  ToolResultV1,
} from '@/types/copilot-protocol'
import { COPILOT_GROUNDING_OPERATIONS } from '@/lib/copilotGroundingOperations'
import { withAuthHeadersReady } from './auth'
import { t } from '@/i18n'

export { COPILOT_GROUNDING_OPERATIONS }

export interface SSEEvent {
  event: string
  data: string
}

export type SSEHandler = (event: SSEEvent) => void

export interface StreamOptions {
  conversationId?: string
  context?: Record<string, unknown>
  /** UI Context snapshot for the LLM */
  snapshot?: Record<string, unknown>

  // Text streaming
  onContent?: (content: string) => void
  onDone?: (fullMessage: string, meta?: CopilotDoneMeta) => void

  /** Sichtbarer Turn-Fortschritt (`copilot.status`: Werkzeuge/Verifikation/Antwort). */
  onStatus?: (status: CopilotStatusEvent) => void

  /**
   * Ein Werkzeug beginnt oder endet (`start` / `end`). Diese beiden Frames
   * erreichten den Verteiler und wurden stillschweigend verworfen. Sie sind
   * das einzige Signal, mit dem ein Werkzeug ERSCHEINT, waehrend es laeuft:
   * `copilot.tool_result` kommt erst, wenn es fertig ist. Der Kartenrahmen
   * dafuer existiert, `ToolCallResult` kennt den Zustand `running` samt
   * Spinner, der Copilot-Pfad erzeugte ihn nur nie.
   */
  onToolPhase?: (phase: CopilotToolPhaseEvent) => void

  /**
   * Der Server hat den Turn abgebrochen (`copilot.cancelled`), z.B. weil ein
   * neuer Turn desselben Owners ihn ersetzt hat oder der Backstop griff. Ohne
   * diesen Callback endet der Stream terminal-los und die UI bliebe gesperrt.
   */
  onCancelled?: () => void

  // === New Structured Events ===

  /** Copilot sends a structured plan */
  onPlan?: (plan: PlanV1) => void

  /** Copilot asks a structured clarification question */
  onClarifyV1?: (question: ClarifyV1) => void

  /** Copilot requests an action (needs approval based on autonomy) */
  onActionRequest?: (request: ActionRequestV1, meta?: ActionMeta | Record<string, unknown>) => void

  /** Backend acknowledges that an action was committed/executed */
  onActionCommit?: (commit: ActionCommitPayload) => void

  /** Tool result from MCP or backend */
  onToolResultV1?: (result: ToolResultV1) => void

  /** Grounding verdict emitted by the backend verifier. */
  onGrounding?: (grounding: CopilotGroundingEvent) => void

  /**
   * Vorlaeufige Antwort, ausgeliefert BEVOR die Modellverifikation laeuft.
   *
   * Kein Rohtext: derselbe Text, den der Harness ausliefern wuerde, wenn in
   * diesem Moment die Zeit ausginge. Referenzen aufgeloest, Zitate gegen die
   * Evidenzzeilen geprueft, unbelegte Zahlen gestrichen. Die Verifikation
   * laeuft weiter und ersetzt ihn mit `copilot.done`.
   */
  onVorlaeufigeAntwort?: (vorlaeufig: CopilotVorlaeufigeAntwortEvent) => void

  /** Evidence gaps emitted when the backend refuses or limits claims. */
  onEvidenceGap?: (gap: CopilotEvidenceGapEvent) => void

  /** Recovery event emitted when the backend had to fall back/retry. */
  onRecovery?: (recovery: CopilotRecoveryEvent) => void

  /** Background-research progress emitted by the research worker. */
  onResearch?: (research: CopilotResearchEvent) => void

  /** Research-context update (which research tags stay active). */
  onResearchContext?: (context: CopilotResearchContextEvent) => void

  /** The backend blocked a control action (reason included). */
  onActionBlocked?: (blocked: CopilotActionBlockedEvent) => void

  /** Action was executed (result feedback) */
  onActionResult?: (result: ActionResultPayload) => void

  // Error handling
  onError?: (error: Error) => void

  /** Number of retry attempts (default: 0; a POST can already be executing). */
  maxRetries?: number
  /** Base delay between retries in ms (default: 1000) */
  retryDelay?: number
  /** Called when a retry is attempted */
  onRetry?: (attempt: number, maxAttempts: number, error: Error) => void
}

/** Payload of a `copilot.status` event (visible per-stage turn progress). */
/** Beginn oder Ende eines Werkzeugaufrufs. */
export interface CopilotToolPhaseEvent {
  phase: 'start' | 'end'
  tool: string
  /** Sekunden seit Turnbeginn. */
  t_rel?: number
  /** Nur beim Ende: die im Orchestrator bereits gemessene Dauer. */
  duration_ms?: number
}

export interface CopilotStatusEvent {
  stage?: string
  detail?: string
  /**
   * Sekunden seit Turnbeginn. Der Server kann keine DAUER je Stufe liefern,
   * weil er das Ende einer Stufe erst beim naechsten Wechsel kennt. Aus
   * aufeinanderfolgenden Marken bildet das Frontend sie selbst, die letzte
   * schliesst `elapsed_s` aus `copilot.done`.
   */
  t_rel?: number
  /**
   * Aktives Analyse-Rezept des Turns. `null` bedeutet explizit freie Analyse,
   * ein fehlendes Feld bedeutet Alt-Backend ohne Rezept-Transparenz.
   */
  recipe_id?: string | null
  ts?: number
}

/**
 * Aufwandsbilanz des Turns, getragen vom terminalen `copilot.done`-Frame.
 * Alle Felder sind observational und steuern keine Analyse.
 */
export interface CopilotDoneMeta {
  budget_class?: string
  llm_calls_used?: number
  transport_retries_used?: number
  elapsed_s?: number
  /** Timeout-Salvage: die Antwort ist eine ehrlich gekennzeichnete Teilantwort. */
  partial?: boolean
  timeout?: string
  /**
   * The model failure a partial answer follows (`copilot.done.error`, or the
   * `copilot.error` the server sent before this `copilot.done`).
   */
  error?: string
  /** Rezept des Turns (`null` = freie Analyse, fehlend = Alt-Backend). */
  recipe_id?: string | null
  /**
   * Modellzeit des Turns in Sekunden, und ihre Aufteilung je Stufe. Beide
   * Felder liegen seit A2 im `copilot.done`-Frame und wurden hier bislang
   * verworfen. Sie sind der einzige Weg, Modellzeit von Indexzeit zu
   * trennen: am 273M-Korpus lagen in einem Turn 216,3 s Modellzeit gegen
   * 16,9 s Indexzeit in der Werkzeugschleife, in einem anderen 115,7 gegen
   * 146,5. Das Verhaeltnis ist nicht vorhersagbar, es muss gemessen werden.
   */
  llm_seconds?: number
  llm_seconds_je_stufe?: Record<string, number>
}

/**
 * Eine beratende Grounding-Annotation aus `copilot.grounding.annotations`.
 * Beratend, nie blockierend: sie ergaenzt die Antwort, haelt nichts an.
 */
export interface CopilotGroundingAnnotation {
  rule?: string
  note?: string
}

export interface CopilotBelegQuelle {
  id: string
  tool: string
  query: string
  status: string
}

export interface CopilotGroundingEvent {
  analysis_family?: string
  verdict?: string
  rejected_claim_count?: number
  route?: string
  model?: string
  /** Beratende Annotationen ([{rule, note}]); fehlend bei Alt-Backends. */
  annotations?: CopilotGroundingAnnotation[]
  /**
   * Beleg-Map des Deutungspfads ([{id, tool, query, status}]): die Daten,
   * die ein Beleg-Chip-Klick braucht, um DIESE Abfrage im Werkzeug zu
   * oeffnen. Fehlend bei Alt-Backends und im Legacy-Pfad.
   */
  evidence?: CopilotBelegQuelle[]
  ts?: number
}

export interface CopilotVorlaeufigeAntwortEvent {
  /** Der deterministisch gedeckte Antworttext. */
  text?: string
  /** Immer `false`: die Modellverifikation laeuft zu diesem Zeitpunkt noch. */
  geprueft?: boolean
  /** Kurzer Satz fuer die Oberflaeche, vom Backend formuliert. */
  hinweis?: string
}

export interface CopilotEvidenceGapEvent {
  analysis_family?: string
  gaps?: string[]
  route?: string
  model?: string
  ts?: number
}

export interface CopilotRecoveryEvent {
  kind?: string
  message?: string
  route?: string
  model?: string
  retryable?: boolean
  ts?: number
}

/** Payload of a `copilot.research` event (research worker progress). */
export interface CopilotResearchEvent {
  researchId?: string
  phase?: string
  query?: string
  status?: string
  ts?: number
}

/** Payload of a `copilot.research_context` event. */
export interface CopilotResearchContextEvent {
  keep?: string[]
  ts?: number
}

/** Payload of a `copilot.action_blocked` event. */
export interface CopilotActionBlockedEvent {
  request?: {
    requestId?: string
    type?: string
    payload?: Record<string, unknown>
    rationale?: string
  }
  meta?: {
    summary?: string
    status?: string
    reason?: string
    ts?: number
  }
}

// Control frame regex patterns
const CONTROL_FRAME_PATTERNS = {
  PLAN: /<<<CC:PLAN\s+(\{[\s\S]*?\})>>>/g,
  CLARIFY: /<<<CC:CLARIFY\s+(\{[\s\S]*?\})>>>/g,
  ACTION: /<<<CC:ACTION\s+(\{[\s\S]*?\})>>>/g,
} as const

/**
 * Parse control frames from streamed text
 * Returns the text with frames removed and the extracted frames
 */
export function parseControlFrames(text: string): {
  cleanText: string
  plans: PlanV1[]
  clarifications: ClarifyV1[]
  actions: ActionRequestV1[]
} {
  const plans: PlanV1[] = []
  const clarifications: ClarifyV1[] = []
  const actions: ActionRequestV1[] = []

  let cleanText = text

  // Extract PLAN frames
  let match: RegExpExecArray | null
  while ((match = CONTROL_FRAME_PATTERNS.PLAN.exec(text)) !== null) {
    try {
      const jsonStr = match[1]
      if (jsonStr) {
        const plan = JSON.parse(jsonStr) as PlanV1
        plans.push(plan)
        cleanText = cleanText.replace(match[0], '')
      }
    } catch (e) {
      console.warn('[SSE] Failed to parse PLAN frame:', e)
    }
  }
  CONTROL_FRAME_PATTERNS.PLAN.lastIndex = 0

  // Extract CLARIFY frames
  while ((match = CONTROL_FRAME_PATTERNS.CLARIFY.exec(text)) !== null) {
    try {
      const jsonStr = match[1]
      if (jsonStr) {
        const clarify = JSON.parse(jsonStr) as ClarifyV1
        clarifications.push(clarify)
        cleanText = cleanText.replace(match[0], '')
      }
    } catch (e) {
      console.warn('[SSE] Failed to parse CLARIFY frame:', e)
    }
  }
  CONTROL_FRAME_PATTERNS.CLARIFY.lastIndex = 0

  // Extract ACTION frames
  while ((match = CONTROL_FRAME_PATTERNS.ACTION.exec(text)) !== null) {
    try {
      const jsonStr = match[1]
      if (jsonStr) {
        const action = JSON.parse(jsonStr) as ActionRequestV1
        actions.push(action)
        cleanText = cleanText.replace(match[0], '')
      }
    } catch (e) {
      console.warn('[SSE] Failed to parse ACTION frame:', e)
    }
  }
  CONTROL_FRAME_PATTERNS.ACTION.lastIndex = 0

  return { cleanText: cleanText.trim(), plans, clarifications, actions }
}

function unwrapEventPayload(parsed: unknown): Record<string, unknown> {
  if (parsed && typeof parsed === 'object') {
    const record = parsed as Record<string, unknown>
    const isEnvelope = typeof record.event === 'string'
      || typeof record.id === 'string'
      || typeof record.ts === 'number'
    if (isEnvelope && record.payload && typeof record.payload === 'object') {
      return record.payload as Record<string, unknown>
    }
    return record
  }
  return {}
}

function contentFromDeltaPayload(payload: Record<string, unknown>): string {
  const nested = payload.delta && typeof payload.delta === 'object'
    ? payload.delta as Record<string, unknown>
    : {}
  return String(payload.content ?? payload.text ?? nested.content ?? nested.text ?? '')
}

/**
 * Extract the effort metadata from a terminal `copilot.done` payload.
 * Unknown or malformed fields are dropped and an empty result is `undefined`.
 */
function doneMetaFromPayload(payload: Record<string, unknown>): CopilotDoneMeta | undefined {
  const meta: CopilotDoneMeta = {}
  if (typeof payload.budget_class === 'string' && payload.budget_class) {
    meta.budget_class = payload.budget_class
  }
  if (typeof payload.llm_calls_used === 'number' && Number.isFinite(payload.llm_calls_used)) {
    meta.llm_calls_used = payload.llm_calls_used
  }
  if (
    typeof payload.transport_retries_used === 'number'
    && Number.isFinite(payload.transport_retries_used)
  ) {
    meta.transport_retries_used = payload.transport_retries_used
  }
  if (typeof payload.elapsed_s === 'number' && Number.isFinite(payload.elapsed_s)) {
    meta.elapsed_s = payload.elapsed_s
  }
  if (typeof payload.llm_seconds === 'number' && Number.isFinite(payload.llm_seconds)) {
    meta.llm_seconds = payload.llm_seconds
  }
  if (payload.llm_seconds_je_stufe && typeof payload.llm_seconds_je_stufe === 'object') {
    const roh = payload.llm_seconds_je_stufe as Record<string, unknown>
    const je: Record<string, number> = {}
    for (const [stufe, wert] of Object.entries(roh)) {
      if (typeof wert === 'number' && Number.isFinite(wert)) je[stufe] = wert
    }
    if (Object.keys(je).length) meta.llm_seconds_je_stufe = je
  }
  if (payload.partial === true) meta.partial = true
  if (typeof payload.timeout === 'string' && payload.timeout) meta.timeout = payload.timeout
  if (typeof payload.error === 'string' && payload.error) meta.error = payload.error
  // Rezept-Transparenz: `null` ist ein gueltiger Wert (freie Analyse) und
  // bleibt von einem fehlenden Feld (Alt-Backend) unterscheidbar.
  if (typeof payload.recipe_id === 'string' && payload.recipe_id) {
    meta.recipe_id = payload.recipe_id
  } else if (payload.recipe_id === null) {
    meta.recipe_id = null
  }
  return Object.keys(meta).length ? meta : undefined
}

function normalizeActionResultPayload(payload: Record<string, unknown>): ActionResultPayload {
  if (looksLikeActionResultPayload(payload)) {
    return payload as unknown as ActionResultPayload
  }

  const nested = payload.result
  if (looksLikeActionResultPayload(nested)) {
    return nested as unknown as ActionResultPayload
  }

  return payload as unknown as ActionResultPayload
}

function looksLikeActionResultPayload(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return typeof record.requestId === 'string'
    || typeof record.ok === 'boolean'
    || typeof record.runId === 'string'
}

/**
 * Build a human-friendly Error from a non-OK fetch Response.
 *
 * Mirrors the approve/reject helpers below: parse the response body's
 * normalized `detail` (the backend's error envelope) instead of throwing a bare
 * `HTTP <status>`, so a 415/422/400 surfaces the actual backend message and a
 * 429 surfaces a friendly German rate-limit notice. The numeric status is kept
 * in the message so {@link isRetryableError} / the error handler can still
 * classify it.
 */
async function errorFromResponse(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null
  const detail = body?.detail

  if (response.status === 429) {
    // Friendly, actionable rate-limit message (id 21). Keep "HTTP 429" so the
    // error is still classified as retryable downstream.
    return new Error(t('copilot.stream.rateLimited'))
  }

  if (typeof detail === 'string' && detail) {
    return new Error(`${detail} (HTTP ${response.status})`)
  }

  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    const code = typeof record.code === 'string' ? record.code : ''
    const message = typeof record.message === 'string' ? record.message : undefined
    if (code === 'model_not_loaded') {
      return new Error(t('copilot.stream.modelNotLoaded', {
        message: message ?? t('copilot.stream.modelNotLoadedFallback'),
        status: response.status,
      }))
    }
    if (message) {
      return new Error(`${message} (HTTP ${response.status})`)
    }
  }

  return new Error(`HTTP ${response.status}`)
}

/**
 * Check if an error is retryable
 */
function isRetryableError(error: Error): boolean {
  const message = error.message.toLowerCase()

  // Network errors
  if (error.name === 'TypeError' && message.includes('failed to fetch')) {
    return true
  }

  // Specific HTTP status codes that are retryable
  if (
    message.includes('http 429') || // Rate limited
    message.includes('http 500') || // Server error
    message.includes('http 502') || // Bad gateway
    message.includes('http 503') || // Service unavailable
    message.includes('http 504')    // Gateway timeout
  ) {
    return true
  }

  return false
}

// ============================================================================
// Shared SSE event dispatcher
// ============================================================================

interface CopilotStreamState {
  /**
   * Exactly one terminal outcome is allowed. In particular, a server-side
   * `copilot.error` followed by EOF must never overwrite the error bubble
   * with a phantom blank completion.
   */
  terminal: 'active' | 'done' | 'error' | 'aborted'
  fullContent: string
  sessionId: string | null
  /**
   * A server `copilot.error` not yet settled. `copilot.done` is the terminal
   * frame: after a model failure the server still lands the answer from the
   * collected evidence (copilot.grounding partial_on_engine_error, then
   * copilot.done with status partial). The error is terminal only when the
   * stream ends without a copilot.done (`settle`).
   */
  pendingError: Error | null
}

interface CopilotEventDispatcher {
  state: CopilotStreamState
  /** Process one SSE `data:` line for the given `event:` name. */
  handleDataLine: (eventName: string, data: string) => void
  fireDone: (content: string, meta?: CopilotDoneMeta) => void
  fireError: (error: Error) => void
  /** End of stream: a server error without a following copilot.done becomes terminal. Returns whether it did. */
  settle: () => boolean
  /** Reset accumulated content (a retry starts a fresh attempt). */
  resetContent: () => void
}

/**
 * One shared dispatcher for the initial chat stream AND the continue stream.
 * Both streams see the identical backend event set; a single switch prevents
 * handler drift between the two (the continue stream previously dropped
 * `copilot.message` and `copilot.session`).
 */
function createCopilotEventDispatcher(options: StreamOptions): CopilotEventDispatcher {
  const state: CopilotStreamState = {
    terminal: 'active',
    fullContent: '',
    sessionId: null,
    pendingError: null,
  }

  const fireDone = (content: string, meta?: CopilotDoneMeta) => {
    if (state.terminal !== 'active') return
    state.terminal = 'done'
    if (state.pendingError) {
      // The answer follows a model failure: it carries the failure along.
      meta = { ...(meta ?? {}), error: meta?.error ?? state.pendingError.message }
      state.pendingError = null
    }
    // Arity bewahren: ohne Aufwandsbilanz bleibt der Aufruf einargumentig
    // (bestehende Konsumenten/Tests pruefen die exakte Callform).
    if (meta) options.onDone?.(content, meta)
    else options.onDone?.(content)
  }
  const fireError = (error: Error) => {
    if (state.terminal !== 'active') return
    state.terminal = 'error'
    state.pendingError = null
    options.onError?.(error)
  }
  const settle = (): boolean => {
    if (!state.pendingError) return false
    fireError(state.pendingError)
    return true
  }

  function dispatchCopilotEvent(eventName: string, payload: Record<string, unknown>): void {
    switch (eventName) {
      case 'content':
      case 'copilot.delta': {
        if (state.terminal !== 'active') break
        const content = contentFromDeltaPayload(payload)
        state.fullContent += content
        options.onContent?.(content)
        break
      }

      case 'copilot.status':
        if (state.terminal !== 'active') break
        options.onStatus?.((payload.status && typeof payload.status === 'object'
          ? payload.status
          : payload) as CopilotStatusEvent)
        break

      case 'start':
      case 'end':
        if (state.terminal !== 'active') break
        if (typeof payload.tool === 'string' && payload.tool) {
          options.onToolPhase?.({
            phase: eventName === 'start' ? 'start' : 'end',
            tool: payload.tool,
            t_rel: typeof payload.t_rel === 'number' ? payload.t_rel : undefined,
            duration_ms: typeof payload.duration_ms === 'number'
              ? payload.duration_ms
              : undefined,
          })
        }
        break

      case 'copilot.plan':
        if (state.terminal !== 'active') break
        options.onPlan?.((payload.plan || payload) as PlanV1)
        break

      case 'copilot.clarify':
        if (state.terminal !== 'active') break
        options.onClarifyV1?.((payload.question || payload) as ClarifyV1)
        break

      case 'copilot.action_preview':
      case 'copilot.action_request':
        if (state.terminal !== 'active') break
        options.onActionRequest?.(
          (payload.request || payload) as ActionRequestV1,
          payload.meta as ActionMeta | Record<string, unknown> | undefined
        )
        break

      case 'copilot.action_commit':
        if (state.terminal !== 'active') break
        options.onActionCommit?.((payload.commit || payload) as unknown as ActionCommitPayload)
        break

      case 'copilot.action_result':
        if (state.terminal !== 'active') break
        options.onActionResult?.(normalizeActionResultPayload(payload))
        break

      case 'copilot.action_blocked':
        if (state.terminal !== 'active') break
        options.onActionBlocked?.(payload as CopilotActionBlockedEvent)
        break

      case 'copilot.tool_result':
        if (state.terminal !== 'active') break
        options.onToolResultV1?.((payload.toolResult || payload) as ToolResultV1)
        break

      case 'copilot.grounding':
        if (state.terminal !== 'active') break
        options.onGrounding?.((payload.grounding || payload) as CopilotGroundingEvent)
        break

      case 'copilot.vorlaeufige_antwort':
        if (state.terminal !== 'active') break
        // AUCH in fullContent. Der Fehler- und der Abbruchpfad lesen von
        // dort, nicht aus der Nachricht. Ohne diese Zeile ersetzt ein
        // Zeitlimit die bereits gelesene Antwort durch „Fehler: ...".
        //
        // Live gemessen am 2026-08-28 unter Produktivvorgaben: die
        // Vorschau ging nach 71,7 s mit 1423 Zeichen raus, der Backstop
        // schlug bei 135 s zu. Ohne diese Zeile saehe die Nutzerin nach
        // gut zwei Minuten eine Fehlermeldung statt ihrer Antwort.
        if (typeof payload.text === 'string' && payload.text.trim()) {
          state.fullContent = payload.text
        }
        options.onVorlaeufigeAntwort?.(payload as CopilotVorlaeufigeAntwortEvent)
        break

      case 'copilot.evidence_gap':
        if (state.terminal !== 'active') break
        options.onEvidenceGap?.((payload.gap || payload) as CopilotEvidenceGapEvent)
        break

      case 'copilot.recovery':
        if (state.terminal !== 'active') break
        options.onRecovery?.((payload.recovery || payload) as CopilotRecoveryEvent)
        break

      case 'copilot.research':
        if (state.terminal !== 'active') break
        options.onResearch?.(payload as CopilotResearchEvent)
        break

      case 'copilot.research_context':
        if (state.terminal !== 'active') break
        options.onResearchContext?.((payload.context || payload) as CopilotResearchContextEvent)
        break

      case 'copilot.message':
        // Final message with full content
        state.fullContent = String(payload.text ?? state.fullContent)
        break

      case 'copilot.session':
        // Track session ID for action/clarification handling
        if (typeof payload.sessionId === 'string') {
          state.sessionId = payload.sessionId
          currentSessionId = payload.sessionId
        }
        break

      case 'copilot.cancelled':
        // Server-side cancellation is a terminal outcome. Notify exactly once
        // so the UI can re-enable input instead of waiting on a done frame
        // that will never come.
        if (state.terminal === 'active') {
          state.terminal = 'aborted'
          options.onCancelled?.()
        }
        break

      case 'done':
      case 'copilot.done':
        fireDone(String(payload.text ?? state.fullContent), doneMetaFromPayload(payload))
        break

      case 'error':
      case 'copilot.error':
        // Backend copilot.error payloads use the `error` key (e.g.
        // {"error":"TimeoutError"}); fall back to `message` for other
        // shapes (id 2). Held until the stream ends or a copilot.done
        // arrives, see CopilotStreamState.pendingError.
        if (state.terminal !== 'active' || state.pendingError) break
        state.pendingError = new Error(String(payload.error ?? payload.message ?? t('copilot.stream.unknownError')))
        break
    }
  }

  function handleDataLine(eventName: string, data: string): void {
    try {
      const parsed = JSON.parse(data)
      dispatchCopilotEvent(eventName, unwrapEventPayload(parsed))
    } catch {
      // Not JSON, treat as raw content
      if (eventName === 'content' && state.terminal === 'active') {
        state.fullContent += data
        options.onContent?.(data)
      }
    }
  }

  return {
    state,
    handleDataLine,
    fireDone,
    fireError,
    settle,
    resetContent: () => {
      state.fullContent = ''
      state.pendingError = null
    },
  }
}

/**
 * Create a streaming connection to the Copilot API.
 *
 * All events arrive as `copilot.*` SSE frames and are processed by the shared
 * dispatcher above (`copilot.delta`, `copilot.status`, `copilot.plan`,
 * `copilot.clarify`, `copilot.action_*`, `copilot.tool_result`,
 * `copilot.research*`, `copilot.done`, `copilot.cancelled`,
 * `copilot.error`, ...).
 */
export function streamCopilotMessage(
  message: string,
  options: StreamOptions
): () => void {
  const controller = new AbortController()
  // A broken connection after a POST is ambiguous: the backend may still be
  // running tools. Retrying automatically would create a second researcher
  // request with possible duplicate side effects, so retry is opt-in only.
  const maxRetries = options.maxRetries ?? 0
  const retryDelay = options.retryDelay ?? 1000
  let currentAttempt = 0
  let cancelled = false
  const turnId = crypto.randomUUID()
  // ONE dispatcher across retry attempts: the single-terminal-outcome rule and
  // the tracked session id survive a retry; only the accumulated content is
  // reset per attempt.
  const dispatcher = createCopilotEventDispatcher(options)
  const { state } = dispatcher

  // Build the request body
  const messages = [{ role: 'user', content: message }]
  const body = JSON.stringify({
    messages,
    conversation_id: options.conversationId,
    context: options.context,
    ui_context: options.snapshot,  // UI context for autonomy-aware behavior
    turnId,
    stream: true
  })

  async function attemptStream(): Promise<void> {
    if (cancelled) return

    currentAttempt++
    dispatcher.resetContent()

    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: await withAuthHeadersReady({
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        }),
        body,
        signal: controller.signal
      })

      if (!response.ok) {
        // Parse the backend's normalized error detail (id 20) and surface a
        // friendly rate-limit message for 429 (id 21).
        throw await errorFromResponse(response)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error(t('copilot.stream.noResponseBody'))
      }

      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = 'message'

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // Keep incomplete line

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            const data = line.slice(5).replace(/^ /, '')
            dispatcher.handleDataLine(currentEvent, data)
            currentEvent = 'message' // Reset for next event
          }
        }
      }

      if (dispatcher.settle() || state.terminal !== 'active') return

      // Parse any control frames from the accumulated content
      const { cleanText, plans, clarifications, actions } = parseControlFrames(state.fullContent)

      // Dispatch extracted frames
      for (const plan of plans) {
        options.onPlan?.(plan)
      }
      for (const clarify of clarifications) {
        options.onClarifyV1?.(clarify)
      }
      for (const action of actions) {
        options.onActionRequest?.(action)
      }

      dispatcher.fireDone(cleanText)
    } catch (error) {
      if (error instanceof Error) {
        // Don't retry if aborted
        if (error.name === 'AbortError') {
          state.terminal = 'aborted'
          return
        }

        // The server already reported its failure: no new attempt.
        if (dispatcher.settle()) return

        // Check if we should retry
        if (isRetryableError(error) && currentAttempt < maxRetries && !cancelled) {
          // Notify about retry
          options.onRetry?.(currentAttempt, maxRetries, error)

          // Exponential backoff
          const delay = retryDelay * Math.pow(2, currentAttempt - 1)
          await new Promise(resolve => setTimeout(resolve, delay))

          // Retry
          return attemptStream()
        }

        // All retries exhausted or not retryable
        dispatcher.fireError(error)
      }
    }
  }

  // Start the stream
  attemptStream()

  // Return cancel function
  return () => {
    const wasActive = state.terminal === 'active'
    cancelled = true
    state.terminal = 'aborted'
    // The abort only closes the browser reader. Tell the server to make the
    // turn terminal as well, so it cannot dispatch a later tool after a slow
    // LLM request returns.
    if (wasActive) void cancelCopilotTurn({ sessionId: state.sessionId, turnId })
    controller.abort()
  }
}

// ============================================================================
// Copilot Control Frame API Functions
// ============================================================================

export interface CopilotSession {
  sessionId: string
  status: 'started' | 'completed' | 'error'
}

let currentSessionId: string | null = null

/**
 * Get the current session ID (set by streamCopilotMessage)
 */
export function getCurrentSessionId(): string | null {
  return currentSessionId
}

/**
 * Cooperatively stop a server turn. This does not claim to kill an in-flight
 * model HTTP request; it prevents later retries, tool calls and continuations.
 */
export async function cancelCopilotTurn(
  identifiers: { sessionId?: string | null; turnId?: string | null },
): Promise<void> {
  const sessionId = identifiers.sessionId?.trim() || undefined
  const turnId = identifiers.turnId?.trim() || undefined
  if (!sessionId && !turnId) return

  try {
    const response = await fetch('/api/v1/copilot/cancel', {
      method: 'POST',
      headers: await withAuthHeadersReady({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ ...(sessionId ? { sessionId } : {}), ...(turnId ? { turnId } : {}) }),
      // The payload is tiny and should survive the immediate stream abort.
      keepalive: true,
    })
    if (!response.ok && response.status !== 404) {
      throw await errorFromResponse(response)
    }
  } catch (error) {
    // Stopping the local reader remains correct even if the server disappeared;
    // do not turn a user stop into a second visible Copilot error.
    console.warn('[Copilot] Failed to request server-side cancellation:', error)
  }
}

/**
 * Approve a pending action from the Copilot
 */
export async function approveAction(
  actionId: string,
  sessionId?: string
): Promise<{ status: string; actionId: string }> {
  const sid = sessionId || currentSessionId
  if (!sid) {
    throw new Error(t('copilot.stream.noSession'))
  }

  const response = await fetch('/api/v1/copilot/action/approve', {
    method: 'POST',
    headers: await withAuthHeadersReady({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ actionId, sessionId: sid }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: t('copilot.stream.unknownError') }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * Reject a pending action from the Copilot
 */
export async function rejectAction(
  actionId: string,
  reason?: string,
  sessionId?: string
): Promise<{ status: string; actionId: string }> {
  const sid = sessionId || currentSessionId
  if (!sid) {
    throw new Error(t('copilot.stream.noSession'))
  }

  const response = await fetch('/api/v1/copilot/action/reject', {
    method: 'POST',
    headers: await withAuthHeadersReady({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ actionId, sessionId: sid, reason }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: t('copilot.stream.unknownError') }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * Answer a pending clarification question from the Copilot
 */
export async function answerClarification(
  clarificationId: string,
  answer: string | string[],
  sessionId?: string
): Promise<{ status: string; clarificationId: string }> {
  const sid = sessionId || currentSessionId
  if (!sid) {
    throw new Error(t('copilot.stream.noSession'))
  }

  const response = await fetch('/api/v1/copilot/clarify/answer', {
    method: 'POST',
    headers: await withAuthHeadersReady({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ clarificationId, sessionId: sid, answer }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: t('copilot.stream.unknownError') }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * Continue Copilot execution after approval or clarification answer.
 *
 * Call this after approveAction, rejectAction, or answerClarification
 * to resume the orchestrator loop and receive the next events.
 */
export function continueCopilotExecution(
  options: StreamOptions,
  sessionId?: string
): () => void {
  const controller = new AbortController()
  const sid = sessionId || currentSessionId
  // Continuations share the initial stream's dispatcher — identical event
  // handling including `copilot.message` and `copilot.session`.
  const dispatcher = createCopilotEventDispatcher(options)
  const { state } = dispatcher

  if (!sid) {
    options.onError?.(new Error(t('copilot.stream.noSession')))
    return () => {}
  }

  async function startStream(): Promise<void> {
    try {
      const response = await fetch('/api/v1/copilot/continue', {
        method: 'POST',
        headers: await withAuthHeadersReady({
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        }),
        body: JSON.stringify({ sessionId: sid }),
        signal: controller.signal
      })

      if (!response.ok) {
        throw await errorFromResponse(response)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error(t('copilot.stream.noResponseBody'))
      }

      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = 'message'

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            const data = line.slice(5).replace(/^ /, '')
            dispatcher.handleDataLine(currentEvent, data)
            currentEvent = 'message'
          }
        }
      }

      if (!dispatcher.settle() && state.terminal === 'active') dispatcher.fireDone(state.fullContent)
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        state.terminal = 'aborted'
      } else if (error instanceof Error) {
        if (!dispatcher.settle()) dispatcher.fireError(error)
      }
    }
  }

  startStream()

  return () => {
    const wasActive = state.terminal === 'active'
    state.terminal = 'aborted'
    if (wasActive) void cancelCopilotTurn({ sessionId: sid })
    controller.abort()
  }
}

/**
 * Update the UI context for the current Copilot session
 */
export async function updateCopilotContext(
  context: Record<string, unknown>,
  sessionId?: string
): Promise<{ status: string }> {
  const sid = sessionId || currentSessionId
  if (!sid) {
    throw new Error(t('copilot.stream.noSession'))
  }

  const response = await fetch('/api/v1/copilot/context', {
    method: 'POST',
    headers: await withAuthHeadersReady({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ ...context, sessionId: sid }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: t('copilot.stream.unknownError') }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// ============================================================================
// WebSocket Connection
// ============================================================================

/**
 * WebSocket connection for real-time updates (cursor sharing, collaboration)
 */
export class RealtimeConnection {
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private handlers = new Map<string, Set<(data: unknown) => void>>()
  private url: string

  constructor(url: string) {
    this.url = url
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url)
        
        this.ws.onopen = () => {
          this.reconnectAttempts = 0
          resolve()
        }

        this.ws.onmessage = (event) => {
          try {
            const { type, data } = JSON.parse(event.data)
            const typeHandlers = this.handlers.get(type)
            if (typeHandlers) {
              typeHandlers.forEach(handler => handler(data))
            }
          } catch (e) {
            console.error('[WS] Failed to parse message:', e)
          }
        }

        this.ws.onclose = () => {
          this.attemptReconnect()
        }

        this.ws.onerror = (error) => {
          console.error('[WS] Error:', error)
          reject(error)
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  private attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++
      const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)
      setTimeout(() => this.connect(), delay)
    }
  }

  on(type: string, handler: (data: unknown) => void): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set())
    }
    this.handlers.get(type)!.add(handler)
    
    return () => {
      this.handlers.get(type)?.delete(handler)
    }
  }

  send(type: string, data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }))
    }
  }

  disconnect() {
    this.maxReconnectAttempts = 0 // Prevent reconnect
    this.ws?.close()
    this.ws = null
  }
}
