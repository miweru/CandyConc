"""Chat and copilot HTTP routes.

Resolve shared sessions, model calls and server-owned helpers at call
time. The session busy lock prevents concurrent drivers of one
orchestrator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import json
import re
import time
import uuid
from typing import Annotated, Any, Dict

from fastapi import Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.answer_language import answer_language_scope
from candyconc.i18n import current_language, localize, lt

from .. import copilot_sessions as _sessions
from candyconc.services.backend.pii_filter import mask_free_text_pii
from candyconc.utils.text_normalize import strip_llm_protocol_tail

from .. import auth

router = CandyAPIRouter()

_TURN_ID_RE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


def _clean_assistant_output(value: object) -> str:
    """Sanitise only final assistant prose, never tool or corpus payloads."""

    return strip_llm_protocol_tail(str(value or ""))


def _copilot_terminal_events(
    *,
    session_id: str,
    reply: str | None,
    salvage_text: str | None,
    timed_out: bool,
    error_text: str | None,
    usage_report: Dict[str, Any],
    extra_annotations: list[Dict[str, str]] | None = None,
) -> list[tuple[str, Dict[str, Any]]]:
    """Plan terminal SSE frames from the completed work and termination reason.

A model reply completes normally. A grounded fallback after the wall-clock
backstop is delivered with its explanatory grounding annotation. An engine
failure with a fallback remains partial and includes the error. Without a
reply or fallback, report the timeout or terminal error. Append polishing
annotations to copilot.grounding rather than the visible answer."""
    events: list[tuple[str, Dict[str, Any]]] = []
    # Deterministic emergency composition after an engine failure during
    # finalization: the orchestrator delivers text AND copilot.error. The
    # emergency composition lands as partial_on_engine_error, not as a clean
    # completed (a failure is not a result).
    if reply is not None and error_text is not None and not timed_out:
        annotations = [
            {"rule": "engine_error", "note": error_text},
            *(extra_annotations or []),
        ]
        events.append(
            (
                "copilot.grounding",
                {
                    "sessionId": session_id,
                    "grounding": {
                        "verdict": "partial_on_engine_error",
                        "annotations": annotations,
                    },
                },
            )
        )
        events.append(
            (
                "copilot.done",
                {
                    "sessionId": session_id,
                    "status": "partial",
                    "partial": True,
                    "error": error_text,
                    "text": reply,
                    **usage_report,
                },
            )
        )
        events.append(
            ("copilot.session", {"sessionId": session_id, "status": "completed"})
        )
        return events
    if reply is not None:
        events.append(
            (
                "copilot.done",
                {
                    "sessionId": session_id,
                    "status": "completed",
                    "text": reply,
                    **usage_report,
                },
            )
        )
        events.append(
            ("copilot.session", {"sessionId": session_id, "status": "completed"})
        )
        return events
    if salvage_text is not None:
        if not timed_out and error_text is not None:
            # When an engine fails after evidence was collected, deliver the
            # available answer with partial status.
            annotations = [
                {
                    "rule": "engine_error",
                    "note": lt(
                        "Engine-Ausfall vor der vollständigen Antwort. "
                        "Berichtet wird nur die bereits gesicherte Evidenz.",
                        "Engine failure before the complete answer. "
                        "Only the evidence already secured is reported.",
                    ),
                }
            ]
            annotations.extend(extra_annotations or [])
            events.append(
                (
                    "copilot.grounding",
                    {
                        "sessionId": session_id,
                        "grounding": {
                            "verdict": "partial_on_engine_error",
                            "annotations": annotations,
                        },
                    },
                )
            )
            events.append(
                (
                    "copilot.done",
                    {
                        "sessionId": session_id,
                        "status": "partial",
                        "partial": True,
                        "error": error_text,
                        "text": salvage_text,
                        **usage_report,
                    },
                )
            )
            events.append(
                (
                    "copilot.session",
                    {"sessionId": session_id, "status": "completed"},
                )
            )
            return events
        note = (
            lt(
                "Zeitbudget erreicht — Antwort aus der bis dahin gesammelten "
                "Evidenz; weitere Vertiefung wurde nicht ausgeführt.",
                "Time budget reached. Answer from the evidence collected so "
                "far. No further analysis was carried out.",
            )
            if timed_out
            else lt(
                "Turn vor der vollständigen Vertiefung beendet — Antwort aus "
                "der bis dahin gesammelten Evidenz.",
                "Turn ended before the complete analysis. Answer from the "
                "evidence collected so far.",
            )
        )
        annotations: list[Dict[str, str]] = [
            {
                "rule": "time_budget" if timed_out else "early_stop",
                "note": note,
            }
        ]
        annotations.extend(extra_annotations or [])
        events.append(
            (
                "copilot.grounding",
                {
                    "sessionId": session_id,
                    "grounding": {
                        "verdict": "completed_on_collected_evidence",
                        "annotations": annotations,
                    },
                },
            )
        )
        events.append(
            (
                "copilot.done",
                {
                    "sessionId": session_id,
                    "status": "completed",
                    "text": salvage_text,
                    **usage_report,
                },
            )
        )
        events.append(
            ("copilot.session", {"sessionId": session_id, "status": "completed"})
        )
        return events
    if timed_out:
        # Wall backstop with no salvageable evidence: honestly a partial timeout.
        events.append(
            (
                "copilot.done",
                {
                    "sessionId": session_id,
                    "status": "timeout",
                    "partial": True,
                    "timeout": error_text,
                    "text": lt(
                        "⚠️ Zeitlimit erreicht, bevor verwertbare Evidenz "
                        "gesammelt werden konnte.",
                        "⚠️ Time limit reached before usable evidence "
                        "could be collected.",
                    ),
                    **usage_report,
                },
            )
        )
        events.append(
            ("copilot.session", {"sessionId": session_id, "status": "error"})
        )
        return events
    if error_text is not None:
        events.append(
            ("copilot.error", {"sessionId": session_id, "error": error_text})
        )
        events.append(
            ("copilot.session", {"sessionId": session_id, "status": "error"})
        )
        return events
    # Defensive: nothing terminal to report (should not occur in practice).
    events.append(
        ("copilot.session", {"sessionId": session_id, "status": "completed"})
    )
    return events


def _validated_turn_id(value: object) -> str:
    """Accept an opaque client correlation id without making it a session id."""
    if value is None:
        # Non-browser API clients may not know about client-side cancellation.
        # Keep the streaming contract compatible; they can still cancel by the
        # server-generated sessionId once the initial SSE frame arrives.
        return uuid.uuid4().hex
    if not isinstance(value, str) or not _TURN_ID_RE.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="turnId must be an opaque identifier of 16-128 letters, digits, '_' or '-'",
        )
    return value


def _mask_llm_bound_messages(
    history: list[dict[str, Any]],
    question: str,
) -> tuple[list[dict[str, Any]], str]:
    """Apply configured free-text PII masking before prompts reach an LLM."""
    masked_history: list[dict[str, Any]] = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            msg = {**msg, "content": mask_free_text_pii(content)}
        masked_history.append(msg)
    return masked_history, mask_free_text_pii(question)


#: UI context fields that hold search expressions (the current query, the
#: filters of the active subcorpus), exempt from free-text masking.
_UI_CONTEXT_SEARCH_PATHS = frozenset({
    ("current_query",),
    ("query", "term"),
    ("query", "cqlf"),
    ("corpus", "subcorpus", "filters"),
})


def _mask_llm_bound_ui_context(ui_context: dict[str, Any]) -> dict[str, Any]:
    """Copy and redact UI state before an LLM or a resumed session can see it.

    A KWIC preview contains literal corpus text. Regex redaction is useful for
    free user input but cannot reliably detect every named entity in arbitrary
    corpus text, so previews stay server-local until an entity-aligned export
    path is available. Structural context (scope, counts, selected row IDs) is
    retained for tool selection and grounding.

    Query strings and subcorpus filter values stay as written: they are search
    expressions over the corpus, not free text. The corpus text they select
    reaches the model in the tool results either way, and a masked query is a
    different query than the one the interface ran.
    """
    def redact(value: Any, path: tuple[str, ...] = ()) -> Any:
        if path in _UI_CONTEXT_SEARCH_PATHS:
            return value
        if isinstance(value, str):
            return mask_free_text_pii(value)
        if isinstance(value, list):
            return [redact(item, path) for item in value]
        if isinstance(value, dict):
            return {str(key): redact(item, (*path, str(key))) for key, item in value.items()}
        return value

    masked = redact(ui_context)
    if not isinstance(masked, dict):  # Defensive for direct route callers.
        return {}
    kwic = masked.get("kwic")
    if isinstance(kwic, dict) and isinstance(kwic.get("preview"), list):
        preview_count = len(kwic["preview"])
        masked["kwic"] = {
            **kwic,
            "preview": [],
            "preview_omitted_for_privacy": preview_count,
        }
    return masked


@router.post(
    "/chat",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"role": "assistant", "content": "Here is a summary ..."}
                }
            }
        }
    },
)
async def chat_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Chat",
                "value": {"messages": [{"role": "user", "content": "Show the collocations of freedom"}]},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Return a chat reply for the given conversation."""
    from .. import server as _server
    user_token = token or payload.get("token")
    project = payload.get("project", "default")
    _server._user_key(user_token, project)
    username = auth.username_for_token(user_token) or "anon"
    _server._validate_chat_messages(payload)
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be list")
    messages = [m for m in messages if isinstance(m, dict)]
    history = messages[:-1]
    question = str(messages[-1].get("content", "")) if messages else ""
    # Payload abuse ceilings (DoS finding B): bound message count / question
    # length / history size before the (LLM-cost-bearing) turn runs.
    _server._enforce_copilot_payload_caps(messages, question)

    policy = _server._resolve_chat_policy(payload, username=username, project=project, user_token=user_token)

    if policy.get(username, "jailbreak_cleaning", True):
        question = _server.clean_prompt(question)
    if _server.moderate(question, username, policy) == "block":
        raise HTTPException(status_code=422, detail="unsafe content")
    history, question = _mask_llm_bound_messages(history, question)
    # Abuse ceiling: clamp the loop budget regardless of the client request.
    # The default is the ceiling itself. A fixed default of 20 would lie below
    # the recipe limit of 200 rounds and become the binding limit for models
    # that make one call per round. Clients that send no max_steps get the
    # ceiling.
    max_steps = _server._clamp_copilot_max_steps(
        payload.get("max_steps", _server._copilot_max_steps_ceiling()))
    max_time = _server._copilot_max_time_sec()

    ui_context = payload.get("ui_context", {})
    if not isinstance(ui_context, dict):
        ui_context = {}
    ui_context = _mask_llm_bound_ui_context(ui_context)
    ui_context = _server._clamp_autonomy_level(ui_context)
    contract = _server.response_contract_for_prompt(question, ui_context=ui_context)
    if contract:
        ui_context = {**ui_context, **contract}

    session = _server.SessionManager()
    for msg in history:
        session.append(msg)

    selected_tools = _server._select_chat_tools_for_principal(
        question,
        ui_context=ui_context,
        username=username,
    )
    llm_messages = [*history, {"role": "user", "content": question}]
    try:
        await _server.ensure_copilot_runtime_available(llm_messages, selected_tools)
    except _server.LLMRequestError as exc:
        _server._raise_llm_http_error(exc)

    orch = _server.ReActOrchestrator(
        selected_tools,
        _server.call_llm,
        _server._dispatch_with_record,
        session=session,
        policy=policy,
        observability=_server._OBSERVABILITY,
        token=user_token,
        ui_context=ui_context,
    )
    # Fallback for the answer language when the question does not show its
    # own (answer_language.resolve_answer_language): the request language.
    with contextlib.suppress(Exception):
        orch.interface_language = current_language()
    # Two-tier time budget (r9 DT-SERVER + DT-ORCH-GROUND):
    #  1. Cooperative: pass max_time to orch.run so the orchestrator stops its
    #     ReAct loop at a step boundary near max_time and returns a grounded
    #     partial answer (a useful 200) instead of running to max_steps.
    #  2. Backstop: bound the whole turn with asyncio.wait_for at
    #     max_time + grace so a single wedged step (LLM/tool blocked past the
    #     cooperative check) still cannot pin the request forever. The grace
    #     margin lets the cooperative path win the race in the common case.
    #  An abandoned to_thread future does not interrupt the worker thread, so the
    #  cooperative kwarg is what actually shortens real work; the backstop only
    #  releases THIS request.
    # Ohne Zeitbudget gibt es keinen Backstop: wait_for(timeout=None)
    # wartet, bis die Arbeit fertig ist.
    backstop = (
        None if max_time is None
        else max_time + _server._copilot_backstop_grace_sec()
    )
    try:
        reply = await asyncio.wait_for(
            asyncio.to_thread(
                orch.run,
                question,
                role="user",
                principal=username,
                max_steps=max_steps,
                max_time=max_time,
            ),
            timeout=backstop,
        )
    except asyncio.TimeoutError as exc:
        # K1: kooperatives Cancel-Flag setzen, damit die verlassene
        # Worker-Kette (LLM-Retries, Tool-Dispatches) nicht als Zombie
        # weiterbrennt, sondern an der naechsten Schranke stoppt.
        orch.request_cancel()
        raise ApiError(
            504,
            "copilot.time_limit_exceeded",
            lt("Copilot-Zeitlimit ({seconds:.0f}s) überschritten", "Copilot time limit ({seconds:.0f}s) exceeded"),
            seconds=backstop,
        ) from exc
    except _server.LLMRequestError as exc:
        _server._raise_llm_http_error(exc)
    return {"role": "assistant", "content": _clean_assistant_output(reply)}


@router.post(
    "/chat/stream",
    responses={200: {"content": {"text/event-stream": {"example": ""}}}},
)
async def chat_stream_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Chat Stream",
                "value": {"messages": [{"role": "user", "content": "How often does freedom occur per million tokens?"}]},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> StreamingResponse:
    """Stream a chat reply using Server-Sent Events."""
    from .. import server as _server
    user_token = token or payload.get("token")
    project = payload.get("project", "default")
    _server._user_key(user_token, project)
    username = auth.username_for_token(user_token) or "anon"
    # Finding 22: validate the message shape BEFORE opening the SSE stream so a
    # missing/empty 'messages' array (or a stray singular 'message') fails with a
    # clear 422 instead of silently dropping the question or dangling a stream.
    _server._validate_chat_messages(payload)
    turn_id = _validated_turn_id(payload.get("turnId"))
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be list")
    messages = [m for m in messages if isinstance(m, dict)]
    history = messages[:-1]
    question = str(messages[-1].get("content", "")) if messages else ""
    # Payload abuse ceilings (DoS finding B): same caps as the non-streaming
    # endpoint so the streaming surface cannot bypass them.
    _server._enforce_copilot_payload_caps(messages, question)

    policy = _server._resolve_chat_policy(payload, username=username, project=project, user_token=user_token)

    if policy.get(username, "jailbreak_cleaning", True):
        question = _server.clean_prompt(question)
    if _server.moderate(question, username, policy) == "block":
        raise HTTPException(status_code=422, detail="unsafe content")
    history, question = _mask_llm_bound_messages(history, question)
    # Abuse ceiling: clamp the loop budget regardless of the client request.
    # The default is the ceiling itself. A fixed default of 20 would lie below
    # the recipe limit of 200 rounds and become the binding limit for models
    # that make one call per round. Clients that send no max_steps get the
    # ceiling.
    max_steps = _server._clamp_copilot_max_steps(
        payload.get("max_steps", _server._copilot_max_steps_ceiling()))
    max_time = _server._copilot_max_time_sec()

    # Extract UI context for autonomy-aware behavior
    ui_context = payload.get("ui_context", {})
    if not isinstance(ui_context, dict):
        ui_context = {}
    ui_context = _mask_llm_bound_ui_context(ui_context)
    ui_context = _server._clamp_autonomy_level(ui_context)
    contract = _server.response_contract_for_prompt(question, ui_context=ui_context)
    if contract:
        ui_context = {**ui_context, **contract}

    session = _server.SessionManager()
    for msg in history:
        session.append(msg)

    # Session IDs are server-generated to prevent fixation/overwrite by clients.
    session_id = getattr(session, "session_id", None) or uuid.uuid4().hex
    with contextlib.suppress(Exception):
        session.session_id = session_id

    selected_tools = _server._select_chat_tools_for_principal(
        question,
        ui_context=ui_context,
        username=username,
    )
    llm_messages = [*history, {"role": "user", "content": question}]
    try:
        await _server.ensure_copilot_runtime_available(llm_messages, selected_tools)
    except _server.LLMRequestError as exc:
        _server._raise_llm_http_error(exc)

    orch = _server.ReActOrchestrator(
        selected_tools,
        _server.call_llm,
        _server._dispatch_with_record,
        session=session,
        policy=policy,
        observability=_server._OBSERVABILITY,
        token=user_token,
        ui_context=ui_context,
    )
    # Fallback for the answer language when the question does not show its
    # own (answer_language.resolve_answer_language): the request language.
    with contextlib.suppress(Exception):
        orch.interface_language = current_language()

    # K1: Ein neuer Turn desselben Owners cancelt noch aktiv laufende alte
    # Turns kooperativ (der alte darf nicht weiterbrennen). Sessions, die nur
    # auf Approval/Clarification warten, bleiben unberuehrt.
    _server._cancel_running_turns_for_owner(username)
    # Register orchestrator for action/clarification handling
    active_session = _server._register_active_orchestrator(
        session_id,
        orch,
        username,
        turn_id=turn_id,
    )
    # Hold the busy lock during the initial run so a concurrent continuation
    # cannot drive the orchestrator from another event loop. Reject a race
    # between session registration and lock acquisition.
    if not active_session.run_lock.acquire(blocking=False):  # pragma: no cover - register/acquire race
        raise ApiError(409, "copilot.session_busy", lt("Session läuft bereits", "Session is already running"))
    # Idempotent release shared by the generator ``finally`` (normal end) and
    # the response background hook (mid-stream client disconnect, where the
    # suspended sync generator is only finalized by GC — see _make_once_releaser).
    release_run_lock = _server._make_once_releaser(active_session.run_lock)

    def gen() -> Any:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Bind the queue to THIS worker-thread loop so cross-thread emits from the
        # orchestrator (running via asyncio.to_thread on a different thread) wake
        # this loop via call_soon_threadsafe (D7 cross-thread delivery fix).
        queue = _server.copilot_event_bus.subscribe(session_id, loop=loop)

        # Emit session info at start for client tracking
        yield "event: copilot.session\n"
        yield f"data: {json.dumps({'sessionId': session_id, 'status': 'started'})}\n\n"

        # The cooperative turn budget allows a partial answer before the
        # wall-clock backstop. Keep the worker on the session so a disconnected
        # SSE loop does not lose its result. GET /copilot/lauf retrieves it.
        _sessions.lauf_abgekoppelt_starten(
            active_session,
            orch.run,
            question,
            role="user",
            principal=username,
            max_steps=max_steps,
            max_time=max_time,
        )

        async def _auf_lauf_warten() -> Any:
            await asyncio.to_thread(active_session.fertig.wait)
            ergebnis = dict(active_session.ergebnis or {})
            if ergebnis.get("status") == "fehler":
                raise RuntimeError(
                    str(ergebnis.get("fehler") or "Lauf fehlgeschlagen")
                )
            return ergebnis.get("antwort")

        task = loop.create_task(_auf_lauf_warten())
        # Hard wall-clock abuse ceiling (D8 #8): if the orchestrator exceeds the
        # backstop we stop waiting and end the stream with an error frame.
        # Ohne Zeitbudget liegt die Frist im Unendlichen: die
        # Wartefenster bleiben 0,25s, und der Vergleich unten wird nie wahr.
        stream_deadline = (
            float("inf") if max_time is None
            else time.monotonic() + max_time + _server._copilot_backstop_grace_sec()
        )
        next_item = loop.create_task(queue.get())
        reply: str | None = None
        error_text: str | None = None
        timed_out = False
        cancelled = False
        # Finding 14: track already-computed work so a wall-clock backstop does
        # not throw it away. ``partial_text`` accumulates streamed assistant
        # deltas; ``last_tool_result`` keeps the most recent tool result frame so
        # we can ground a partial answer if the LLM summary never lands.
        partial_text: str = ""
        last_tool_result: dict[str, Any] | None = None
        #: Wie viele Werkzeuge schon gelaufen sind. Speist den Balken.
        _werkzeugschritte = 0
        # Die vorlaeufige Antwort ist der beste Bergungskandidat, den es
        # gibt: eine VOLLSTAENDIGE, durch den Politur-Chokepoint gelaufene
        # Antwort (Referenzen aufgeloest, Zitate gegen die Evidenzzeilen
        # geprueft, unbelegte Zahlen gestrichen). ``partial_text`` dagegen
        # sind rohe Deltas eines Aufrufs, der gerade gestorben ist.
        #
        # Under production defaults two turns ended like this:
        #   preview 1423 characters at 71.7 s -> final answer 0 characters
        #   preview 1384 characters at 56.5 s -> final answer 0 characters
        # In both cases the answer was complete and the cross-check killed
        # it. The route saw the event pass by and has to keep it.
        vorlaeufiger_text: str = ""
        try:
            while True:
                if active_session.cancel_requested.is_set():
                    cancelled = True
                    break
                # ``task`` becomes None once finished — never pass None into
                # asyncio.wait (TypeError that killed the stream mid-drain).
                # A timeout makes the wait wake periodically so the wall-clock
                # abuse ceiling can be enforced even while the orchestrator is
                # still running (no event yet). None timeout once the task is done
                # so the post-task drain blocks on queued events as before.
                wait_timeout = None
                if task is not None:
                    # Poll a cancellation request without waiting for a blocked
                    # LLM transport to emit another SSE frame.
                    wait_timeout = min(0.25, max(0.0, stream_deadline - time.monotonic()))
                done, _ = loop.run_until_complete(
                    asyncio.wait(
                        {t for t in (task, next_item) if t is not None},
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=wait_timeout,
                    )
                )
                if next_item in done:
                    item = next_item.result()
                    # Salvage bookkeeping for the timeout fallback (finding 14).
                    if isinstance(item, dict):
                        delta = item.get("delta")
                        if isinstance(delta, dict):
                            chunk = delta.get("content")
                            if isinstance(chunk, str):
                                partial_text += chunk
                        if item.get("event") == "copilot.tool_result":
                            tr = item.get("toolResult")
                            if isinstance(tr, dict):
                                last_tool_result = tr
                            # FORTSCHRITT FUER DEN BALKEN.
                            #
                            # Der Auftraggeber hat ihn ausdruecklich
                            # verlangt. Ein Werkzeugergebnis ist der
                            # einzige Takt, den ein Turn wirklich hat:
                            # Modelldeltas kommen unregelmaessig, Schritte
                            # sind gezaehlt. Er wandert an die SITZUNG,
                            # damit ihn auch ein zurueckkehrender Client
                            # ueber GET /copilot/lauf abholen kann.
                            _werkzeugschritte += 1
                            with contextlib.suppress(Exception):
                                _sessions.fortschritt_setzen(
                                    active_session,
                                    schritt=_werkzeugschritte,
                                    von=max_steps,
                                    text=str(
                                        (tr or {}).get("tool")
                                        or item.get("tool")
                                        or ""
                                    ),
                                )
                        if item.get("event") == "copilot.vorlaeufige_antwort":
                            vorschau = item.get("text")
                            if isinstance(vorschau, str) and vorschau.strip():
                                vorlaeufiger_text = vorschau
                        # The orchestrator reports an engine failure during
                        # finalization as copilot.error, and the terminal
                        # classification then lands the emergency
                        # composition as partial.
                        if item.get("event") == "copilot.error":
                            error_text = str(item.get("error") or error_text)
                    yield _server._copilot_sse_frame(item)
                    next_item = loop.create_task(queue.get())
                if task is not None and task in done:
                    try:
                        reply = task.result()
                    except Exception as exc:
                        # An orchestrator failure must not abort the SSE stream
                        # without terminal events — surface it and end cleanly.
                        error_text = str(exc) or exc.__class__.__name__
                        _server.logger.exception("chat stream orchestrator failed")
                    task = None
                if task is not None and time.monotonic() >= stream_deadline:
                    # Hard wall-clock backstop hit while still running: stop
                    # waiting, surface a timeout error, and let the finally-block
                    # cancel the in-flight task (the worker thread is abandoned but
                    # bounded). The cooperative max_time on orch.run should have
                    # fired first; reaching here means a single step wedged.
                    backstop_sec = (max_time or 0.0) + _server._copilot_backstop_grace_sec()
                    error_text = lt(
                        "Copilot-Zeitlimit ({seconds:.0f}s) überschritten",
                        "Copilot time limit ({seconds:.0f}s) exceeded",
                    ).format(seconds=backstop_sec)
                    timed_out = True
                    _server.logger.warning(
                        "chat stream exceeded backstop=%.0fs (max_time=%.0fs)",
                        backstop_sec,
                        max_time or -1.0,
                    )
                    break
                if task is None:
                    if next_item.done():
                        continue
                    if queue.empty():
                        break
        finally:
            if task is not None:
                # K1 (Zombie-Kette): Der Turn laeuft noch (Backstop, Cancel
                # oder Client-Disconnect). task.cancel() unterbricht den
                # to_thread-Worker nicht. Das kooperative Cancel-Flag stoppt
                # jede weitere LLM-/Tool-Schranke im Worker.
                with contextlib.suppress(Exception):
                    orch.request_cancel()
                task.cancel()
            next_item.cancel()
            with contextlib.suppress(BaseException):
                if task is not None:
                    loop.run_until_complete(task)
            with contextlib.suppress(BaseException):
                loop.run_until_complete(next_item)
            _server.copilot_event_bus.unsubscribe(queue)
            loop.close()
            # Release the initial-run lock so a continuation can drive the
            # orchestrator again.
            release_run_lock()
            # Clean up orchestrator after a delay to allow late action/clarification handling
            # In production, this would use a TTL-based cleanup
            # For now, keep it registered for follow-up interactions
        if cancelled:
            yield "event: copilot.cancelled\n"
            yield f"data: {json.dumps({'sessionId': session_id, 'status': 'cancelled'})}\n\n"
            yield "event: copilot.session\n"
            yield f"data: {json.dumps({'sessionId': session_id, 'status': 'cancelled'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Finding 14 / Härtung r3: on a wall-clock TIMEOUT or a non-time terminal
        # error, do not discard already-computed work. If a partial reply was
        # streamed or a tool result is in hand, salvage it. The terminal planner
        # (_copilot_terminal_events) then lands an evidence-backed answer as a
        # clean ``completed`` with one honest copilot.grounding annotation —
        # never ``partial``. Only genuine total data loss (a wall backstop with
        # NO salvageable evidence) stays an honest ``timeout``; any other
        # error-without-evidence stays copilot.error. We never wait past the
        # hard ceiling.
        salvage_text: str | None = None
        # Finding 14 (extended): salvage on ANY terminal error with computed work,
        # not just the wall-clock backstop. An LLM-call TimeoutError raised by the
        # orchestrator surfaces as an exception (error_text) without timed_out, and
        # previously produced only copilot.error -> a blank bubble in the UI even
        # though e.g. a keyness tool result was already in hand. Deliver it.
        if reply is None and (timed_out or error_text is not None):
            # Härtung r3, Fix 1/2: ``annotate=False`` — the salvage text carries
            # NO in-band banner. The landing planner decides the terminal shape
            # (evidence-backed -> clean completed + one copilot.grounding
            # annotation; no evidence -> honest timeout/error). ``partial`` and
            # the timeout status are reserved for genuine total data loss.
            with answer_language_scope(getattr(orch, "_answer_language", None)):
                salvage_text = _server._copilot_timeout_salvage_text(
                    # Die Vorschau schlaegt die rohen Deltas: sie ist fertig und
                    # bereits gewacht, die Deltas sind es per Konstruktion nicht.
                    _clean_assistant_output(vorlaeufiger_text or partial_text),
                    last_tool_result,
                    orch,
                    timed_out=timed_out,
                    annotate=False,
                    # The engine-failure answer already includes its failure reason.
                    engine_error=(not timed_out and error_text is not None),
                    # Der Grund gehoert benannt, nicht geraten: ein
                    # Modell-Timeout ist kein Engine-Fehler.
                    error_text=error_text,
                )
        if reply is not None:
            reply = _clean_assistant_output(reply)
        polish_annotations: list[Dict[str, str]] = []
        if salvage_text is not None:
            salvage_text = _clean_assistant_output(salvage_text)
            # Run the fallback answer through final polish and quote verification.
            # Send polish annotations through copilot.grounding rather than adding
            # them to the visible answer.
            with contextlib.suppress(Exception):
                from candyconc.candyconc_copilot.recipe_runtime import (
                    politur_mit_zitatwache as _politur,
                )

                with answer_language_scope(getattr(orch, "_answer_language", None)):
                    salvage_text, polish_annotations = _politur(
                        salvage_text,
                        list(getattr(orch, "_turn_evidence_items", None) or ()),
                        frage=question,
                    )
        # Observational usage data must never control analytical depth.
        usage_report = {}
        with contextlib.suppress(Exception):
            report = getattr(orch, "turn_usage_report", None)
            if callable(report):
                usage_report = report() or {}
        for event_name, payload in _copilot_terminal_events(
            session_id=session_id,
            reply=reply,
            salvage_text=salvage_text,
            timed_out=timed_out,
            error_text=error_text,
            usage_report=usage_report,
            extra_annotations=polish_annotations,
        ):
            yield f"event: {event_name}\n"
            yield "data: " + json.dumps(localize(payload)) + "\n\n"
        yield "data: [DONE]\n\n"

    # ``background`` runs after the response — Starlette executes it even when
    # the client disconnected mid-stream, guaranteeing busy-lock release.
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        background=BackgroundTask(release_run_lock),
    )


@router.post(
    "/copilot/cancel",
    responses={
        200: {"content": {"application/json": {"example": {"status": "cancellation_requested"}}}},
        404: {"content": {"application/json": {"example": {"detail": "Session not found"}}}},
    },
)
async def cancel_copilot_turn(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "by_turn": {
                "summary": "Cancel a running Copilot turn",
                "value": {"turnId": "vW0X7F5m1aXQb1kR6aPq3Tz9"},
            },
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Request cooperative stop: no future LLM retry, tool or continuation."""
    from .. import server as _server

    session_id = payload.get("sessionId")
    if session_id is not None and not isinstance(session_id, str):
        raise HTTPException(status_code=422, detail="sessionId must be string")
    turn_id = payload.get("turnId")
    if turn_id is not None:
        turn_id = _validated_turn_id(turn_id)
    active_session = _server._cancel_active_session(session_id, turn_id, token)
    return {
        "status": "cancellation_requested",
        "sessionId": str(getattr(active_session.orchestrator.session, "session_id", "")),
    }


@router.get(
    "/copilot/status",
    responses={
        200: {"content": {"application/json": {"example": {
            "configured": False, "model": None}}}},
    },
)
async def copilot_status(
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Whether a language model is configured for the copilot.

    Everything else in CandyConc works without one. The interface reads this
    before a question is sent, so that an unconfigured copilot does not look
    ready and the way to the model settings is visible. The value is read at
    call time and follows a change of the model route without a restart. No
    request goes to the model server.
    """
    from candyconc.config import get as get_config

    endpoint = (get_config("COPILOT_ENDPOINT") or "").strip()
    model = (get_config("COPILOT_MODEL") or "").strip()
    return {"configured": bool(endpoint), "model": model or None}


@router.get(
    "/copilot/lauf",
    responses={
        200: {"content": {"application/json": {"example": {
            "status": "laeuft", "fortschritt": {
                "schritt": 3, "von": 8, "anteil": 0.375,
                "text": "Counting collocates",
            },
        }}}},
        404: {"content": {"application/json": {"example": {
            "detail": "Session not found"}}}},
    },
)
async def copilot_lauf(
    sessionId: str | None = None,
    turnId: str | None = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """State and result of a copilot run that outlived its connection.

    ``status`` is ``laeuft`` (running, with the progress), ``fertig`` (done, with
    the answer) or ``fehler`` (failed).

    """
    from .. import server as _server

    sitzung, _ = _server._lookup_active_session(sessionId, turnId)
    if sitzung.fertig.is_set() and sitzung.ergebnis:
        return {"sessionId": sessionId, **dict(sitzung.ergebnis)}
    return {
        "sessionId": sessionId,
        "status": "laeuft",
        "fortschritt": dict(sitzung.fortschritt or {}),
    }


@router.post(
    "/copilot/action/approve",
    responses={
        200: {"content": {"application/json": {"example": {"status": "approved", "actionId": "abc123"}}}},
        404: {"content": {"application/json": {"example": {"detail": "Action not found"}}}},
    },
)
async def approve_action(
    payload: Dict[str, str] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Approve action",
                "value": {"actionId": "abc123", "sessionId": "session-xyz"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Approve a pending action proposed by the Copilot."""
    from .. import server as _server
    action_id = payload.get("actionId")
    session_id = payload.get("sessionId")

    if not action_id:
        raise HTTPException(status_code=400, detail="actionId required")

    orch = _server._get_active_orchestrator(session_id, token)

    if orch.approve_action(action_id):
        return {"status": "approved", "actionId": action_id}
    else:
        raise HTTPException(status_code=404, detail="Action not found or already processed")


@router.post(
    "/copilot/action/reject",
    responses={
        200: {"content": {"application/json": {"example": {"status": "rejected", "actionId": "abc123"}}}},
        404: {"content": {"application/json": {"example": {"detail": "Action not found"}}}},
    },
)
async def reject_action(
    payload: Dict[str, str] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Reject action",
                "value": {"actionId": "abc123", "sessionId": "session-xyz", "reason": "Too risky"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Reject a pending action proposed by the Copilot."""
    from .. import server as _server
    action_id = payload.get("actionId")
    session_id = payload.get("sessionId")
    reason = payload.get("reason", "")

    if not action_id:
        raise HTTPException(status_code=400, detail="actionId required")

    orch = _server._get_active_orchestrator(session_id, token)

    if orch.reject_action(action_id, reason):
        return {"status": "rejected", "actionId": action_id}
    else:
        raise HTTPException(status_code=404, detail="Action not found or already processed")


@router.post(
    "/copilot/clarify/answer",
    responses={
        200: {"content": {"application/json": {"example": {"status": "answered", "clarificationId": "abc123"}}}},
        404: {"content": {"application/json": {"example": {"detail": "Clarification not found"}}}},
    },
)
async def answer_clarification(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Answer clarification",
                "value": {
                    "clarificationId": "abc123",
                    "sessionId": "session-xyz",
                    "answer": "opt_1",
                },
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Answer a pending clarification question from the Copilot."""
    from .. import server as _server
    clarification_id = payload.get("clarificationId")
    session_id = payload.get("sessionId")
    answer = payload.get("answer")  # Can be string or list of strings

    if not clarification_id:
        raise HTTPException(status_code=400, detail="clarificationId required")
    if answer is None:
        raise HTTPException(status_code=400, detail="answer required")

    orch = _server._get_active_orchestrator(session_id, token)

    if orch.answer_clarification(clarification_id, answer):
        return {"status": "answered", "clarificationId": clarification_id}
    else:
        raise HTTPException(status_code=404, detail="Clarification not found or already answered")


@router.post(
    "/copilot/context",
    responses={
        200: {"content": {"application/json": {"example": {"status": "updated"}}}},
    },
)
async def update_copilot_context(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Update UI context",
                "value": {
                    "sessionId": "session-xyz",
                    "autonomy_level": 5,
                    "current_query": "freedom",
                    "total_results": 1234,
                },
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Update the UI context for an active Copilot session."""
    from .. import server as _server
    session_id = payload.get("sessionId")
    orch = _server._get_active_orchestrator(session_id, token)

    # Extract context fields
    context = _mask_llm_bound_ui_context(
        {k: v for k, v in payload.items() if k != "sessionId"}
    )
    set_ui_context = getattr(orch, "set_ui_context", None)
    if callable(set_ui_context):
        set_ui_context(context)
    else:
        current = getattr(orch, "ui_context", {})
        if not isinstance(current, dict):
            current = {}
        with contextlib.suppress(Exception):
            orch.ui_context = {**current, **context}

    return {"status": "updated"}


@router.post(
    "/copilot/continue",
    responses={
        200: {"content": {"text/event-stream": {"example": "event: copilot.delta\ndata: {...}"}}},
        404: {"content": {"application/json": {"example": {"detail": "Session not found"}}}},
        409: {"content": {"application/json": {"example": {"detail": "Orchestrator not ready to continue"}}}},
    },
)
async def continue_copilot_execution(
    payload: Dict[str, str] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Continue after approval/clarification",
                "value": {"sessionId": "session-xyz"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> StreamingResponse:
    """Continue Copilot execution after approval or clarification answer.

    Call this endpoint after approve_action, reject_action, or answer_clarification
    to resume the orchestrator loop and receive the next SSE events.
    """
    from .. import server as _server
    from candyconc.candyconc_copilot.orchestrator import State

    session_id = payload.get("sessionId")
    active_session = _server._get_active_session(session_id, token)
    orch = active_session.orchestrator

    # Acquire the busy lock before reading state to prevent concurrent
    # continuations from driving the orchestrator on separate event loops.
    if not active_session.run_lock.acquire(blocking=False):
        raise ApiError(409, "copilot.session_busy", lt("Session läuft bereits", "Session is already running"))

    try:
        # Check if orchestrator is in a continuable state
        if orch.state not in (State.WAITING_LLM, State.EXECUTING_TOOL):
            state_label = getattr(orch.state, "value", orch.state)
            raise HTTPException(
                status_code=409,
                detail=f"Orchestrator in state {state_label}, cannot continue"
            )
    except BaseException:
        active_session.run_lock.release()
        raise

    # Idempotent release shared by the generator ``finally`` (normal end) and
    # the response background hook (mid-stream client disconnect, where the
    # suspended sync generator is only finalized by GC — see _make_once_releaser).
    release_run_lock = _server._make_once_releaser(active_session.run_lock)

    # C-server-degrade-1: the continue endpoint previously dropped max_time and
    # had no wall-clock backstop, so a wedged resumed step could hang the stream
    # indefinitely. Forward the cooperative max_time to the producer and arm the
    # same grace-margin wall-clock backstop the chat-stream endpoint uses.
    max_time = _server._copilot_max_time_sec()

    def gen() -> Any:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Bind the queue to THIS worker-thread loop so cross-thread emits from the
        # orchestrator (running via asyncio.to_thread on a different thread) wake
        # this loop via call_soon_threadsafe (D7 cross-thread delivery fix).
        queue = _server.copilot_event_bus.subscribe(session_id, loop=loop)

        # Determine continuation method based on state. Forward max_time so the
        # resumed run_async loop honours the same cooperative timeout as the
        # initial run instead of resetting to its default budget.
        # Auch die Fortsetzung wird abgekoppelt. Sie sind Koroutinen und
        # liefen bisher IN diesem Loop, sterben also mit ihm. Eine
        # Reparatur an einer von zwei Naehten waere eine Verschiebung.
        #
        # ``orch.run`` legt in seinem Thread ohnehin einen eigenen Loop an
        # (orchestrator.py: asyncio.run), diese Fassung tut dasselbe.
        active_session.fertig.clear()
        active_session.ergebnis = None
        if orch.state == State.EXECUTING_TOOL:
            _fortsetzen = orch.continue_after_approval
        else:
            _fortsetzen = orch.continue_after_clarification
        _sessions.lauf_abgekoppelt_starten(
            active_session,
            lambda: asyncio.run(_fortsetzen(max_time=max_time)),
        )

        async def _auf_fortsetzung_warten() -> Any:
            await asyncio.to_thread(active_session.fertig.wait)
            ergebnis = dict(active_session.ergebnis or {})
            if ergebnis.get("status") == "fehler":
                raise RuntimeError(
                    str(ergebnis.get("fehler") or "Fortsetzung fehlgeschlagen")
                )
            return ergebnis.get("antwort")

        task = loop.create_task(_auf_fortsetzung_warten())

        # Hard wall-clock abuse ceiling: if the resumed orchestrator exceeds the
        # backstop we stop waiting and end the stream with a terminal error frame.
        # Ohne Zeitbudget liegt die Frist im Unendlichen: die
        # Wartefenster bleiben 0,25s, und der Vergleich unten wird nie wahr.
        stream_deadline = (
            float("inf") if max_time is None
            else time.monotonic() + max_time + _server._copilot_backstop_grace_sec()
        )
        next_item = loop.create_task(queue.get())
        reply: str | None = None
        error_text: str | None = None
        cancelled = False
        # Wie in ``chat_stream``: eine fertige, gewachte Antwort darf der
        # Backstop nicht wegwerfen. Diese Route hatte gar keine Bergung, sie
        # lieferte ``reply or ""``. Derselbe Defekt eine Route weiter.
        vorlaeufiger_text: str = ""

        try:
            while True:
                if active_session.cancel_requested.is_set():
                    cancelled = True
                    break
                # ``task`` becomes None once finished — never pass None into
                # asyncio.wait (TypeError that killed the stream mid-drain).
                # While the task is still running, wake periodically so the
                # wall-clock backstop is enforced even with no pending event.
                wait_timeout = None
                if task is not None:
                    wait_timeout = min(0.25, max(0.0, stream_deadline - time.monotonic()))
                done, _ = loop.run_until_complete(
                    asyncio.wait(
                        {t for t in (task, next_item) if t is not None},
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=wait_timeout,
                    )
                )
                if next_item in done:
                    item = next_item.result()
                    if isinstance(item, dict) and (
                        item.get("event") == "copilot.vorlaeufige_antwort"
                    ):
                        vorschau = item.get("text")
                        if isinstance(vorschau, str) and vorschau.strip():
                            vorlaeufiger_text = vorschau
                    yield _server._copilot_sse_frame(item)
                    next_item = loop.create_task(queue.get())
                if task is not None and task in done:
                    try:
                        reply = task.result()
                    except Exception as exc:
                        # A continuation failure must not abort the SSE stream
                        # without terminal events — surface it and end cleanly.
                        error_text = str(exc) or exc.__class__.__name__
                        _server.logger.exception("copilot continue failed")
                    task = None
                if task is not None and time.monotonic() >= stream_deadline:
                    # Hard wall-clock backstop hit while still running: stop
                    # waiting, surface a timeout error and let the finally-block
                    # cancel the in-flight task. The cooperative max_time on the
                    # resumed run should have fired first; reaching here means a
                    # single step wedged.
                    backstop_sec = (max_time or 0.0) + _server._copilot_backstop_grace_sec()
                    error_text = lt(
                        "Copilot-Zeitlimit ({seconds:.0f}s) überschritten",
                        "Copilot time limit ({seconds:.0f}s) exceeded",
                    ).format(seconds=backstop_sec)
                    _server.logger.warning(
                        "copilot continue exceeded backstop=%.0fs (max_time=%.0fs)",
                        backstop_sec,
                        max_time or -1.0,
                    )
                    break
                if task is None:
                    if next_item.done():
                        continue
                    if queue.empty():
                        break
        finally:
            if task is not None and not task.done():
                # K1 (Zombie-Kette): siehe chat_stream. Kooperatives Cancel,
                # damit der abgebrochene Continue-Worker nicht weiterbrennt.
                with contextlib.suppress(Exception):
                    orch.request_cancel()
                task.cancel()
            if next_item and not next_item.done():
                next_item.cancel()
            with contextlib.suppress(BaseException):
                if task is not None:
                    loop.run_until_complete(task)
            with contextlib.suppress(BaseException):
                loop.run_until_complete(next_item)
            _server.copilot_event_bus.unsubscribe(queue)
            loop.close()
            # Release the continuation lock so the next continuation can run.
            release_run_lock()

        if cancelled:
            yield "event: copilot.cancelled\n"
            yield f"data: {json.dumps({'sessionId': session_id, 'status': 'cancelled'})}\n\n"
            return
        if error_text is not None:
            yield "event: copilot.error\n"
            yield f"data: {json.dumps(localize({'sessionId': session_id, 'error': error_text}))}\n\n"
        # Emit completion
        end_status = "completed" if error_text is None else "error"
        reply = _clean_assistant_output(reply)
        if not (reply or "").strip() and vorlaeufiger_text.strip():
            # Der Turn ist gestorben, die Antwort war fertig. Sie geht durch
            # denselben Chokepoint wie jede andere Landung: keine Ausgabe
            # umgeht die Zitatwache, auch keine geborgene.
            geborgen = _clean_assistant_output(vorlaeufiger_text)
            with contextlib.suppress(Exception):
                from candyconc.candyconc_copilot.recipe_runtime import (
                    politur_mit_zitatwache as _politur,
                )

                with answer_language_scope(getattr(orch, "_answer_language", None)):
                    geborgen, _ = _politur(
                        geborgen,
                        list(getattr(orch, "_turn_evidence_items", None) or ()),
                        # ``_turn_frage``, not ``question``: the attribute
                        # ``question`` lives on ``_RunTurnState``, not on
                        # ``ReActOrchestrator``. getattr would ALWAYS return
                        # the empty string here, and
                        # ``spanne_ist_fragenbezug`` stops at once for an
                        # empty question. The question-reference exception
                        # would then be dead on the salvage path, while the
                        # sibling call above passes the question correctly,
                        # and a salvage would judge differently from the
                        # landing.
                        frage=str(getattr(orch, "_turn_frage", "") or ""),
                    )
            if geborgen.strip():
                reply = geborgen
        usage_report = {}
        with contextlib.suppress(Exception):
            report = getattr(orch, "turn_usage_report", None)
            if callable(report):
                usage_report = report() or {}
        yield "event: copilot.done\n"
        yield (
            "data: "
            + json.dumps(
                {
                    "sessionId": session_id,
                    "status": end_status,
                    "text": reply or "",
                    **usage_report,
                }
            )
            + "\n\n"
        )

    # ``background`` runs after the response — Starlette executes it even when
    # the client disconnected mid-stream, guaranteeing busy-lock release.
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        background=BackgroundTask(release_run_lock),
    )


# ---------------------------------------------------------------------------
# Rezept-Verzeichnis: was der Copilot verstanden hat, in Alltagssprache
# ---------------------------------------------------------------------------

#: Die Felder eines Rezepts, die eine fachlich nicht vertraute Person lesen
#: soll. Bewusst NICHT dabei: ``briefing``, ``trigger``,
#: ``router_paraphrasen``, ``leitplanken``, ``vorplan``, ``slots``,
#: ``precondition*``, ``abbruch_kriterium``, ``max_tool_runden``. Das ist
#: Innenleben des Harness. Wer es sieht, lernt nichts ueber die eigene
#: Frage, und die Routing-Stichworte laden ausserdem dazu ein, die naechste
#: Frage danach zu formulieren, statt sie zu stellen.
_REZEPT_FELDER_OEFFENTLICH = ("id", "name", "einsatz", "beispiel_frage")


def _rezept_oeffentlich(
    rezept: dict[str, Any], englisch: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Ein Rezept auf die nach aussen sichtbaren Felder reduzieren.

    ``schritte`` wird auf das ``ziel`` je Schritt eingedampft. Der
    ``tool_hinweis`` daneben nennt Werkzeugnamen und Parameter und gehoert
    in den Prompt, nicht in eine Erklaerung.

    ``englisch`` holds the English interface texts of the recipe
    (``recipes_data.RECIPES_UI_EN``). Each shown text becomes a German and
    English pair, resolved to the request language when the response is
    rendered. The id is never translated.
    """
    englisch = englisch or {}
    aus: dict[str, Any] = {
        feld: rezept.get(feld, "") for feld in _REZEPT_FELDER_OEFFENTLICH
    }
    for feld in ("name", "einsatz", "beispiel_frage"):
        text_en = str(englisch.get(feld) or "").strip()
        if text_en:
            aus[feld] = lt(str(aus.get(feld) or ""), text_en)
    ziele_en = list(englisch.get("schritte") or ())
    ziele: list[str] = []
    for position, schritt in enumerate(rezept.get("schritte") or ()):
        if not isinstance(schritt, dict):
            continue
        ziel = str(schritt.get("ziel") or "").strip()
        if not ziel:
            continue
        ziel_en = str(ziele_en[position]).strip() if position < len(ziele_en) else ""
        ziele.append(lt(ziel, ziel_en) if ziel_en else ziel)
    aus["schritte"] = ziele
    return aus


@router.get(
    "/copilot/recipes",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "recipes": [
                            {
                                "id": "frequenz",
                                "name": "Frequenz und Verteilung",
                                "einsatz": (
                                    "Wie oft kommt X vor und wie ist es "
                                    "verteilt (absolut, pro Million, im "
                                    "Vergleich)?"
                                ),
                                "beispiel_frage": (
                                    "Wie häufig kommt 'Klimawandel' im "
                                    "Korpus vor, pro Million Tokens?"
                                ),
                                "schritte": [
                                    "Exakte Trefferzahl und Rate bestimmen",
                                ],
                            }
                        ]
                    }
                }
            }
        }
    },
)
async def copilot_recipes(corpus: str | None = None) -> dict[str, Any]:
    """The analysis procedures (recipes) of the copilot.

    Each recipe has a name, its purpose, an example question and the goals of its
    steps. With a loaded corpus the example question is built from the metadata
    of that corpus, and ``beispiel_frage_quelle`` names where the shown question
    comes from.

    """
    from candyconc.candyconc_copilot.recipes_data import (
        RECIPES_DATA,
        RECIPES_UI_EN,
    )
    from candyconc.services.backend import start_suggestions as sv

    aus_dem_korpus: dict[str, str] = {}
    zeitachse = True
    if corpus is not None:
        try:
            from candyconc.services.backend import server as _server

            idx = _server.get_corpus(corpus)
            aus_dem_korpus = sv.vorschlaege(idx)
            zeitachse = sv.zeitachse_vorhanden(idx)
        except Exception:
            # Ein Korpus, das sich nicht oeffnen laesst, kostet keine
            # Rezeptliste. Der Nutzer bekommt die statischen Fragen.
            logging.getLogger(__name__).debug(
                "Startvorschlaege nicht ermittelbar", exc_info=True
            )

    rezepte: list[dict[str, Any]] = []
    for roh in RECIPES_DATA:
        eintrag = _rezept_oeffentlich(roh, RECIPES_UI_EN.get(str(roh.get("id") or "")))
        kennung = str(eintrag.get("id") or "")
        # Ein Verlauf ohne Zeitachse ist nicht beantwortbar. Ihn trotzdem
        # anzubieten waere derselbe Fehler wie das Teilkorpus 'news'.
        eintrag["im_korpus_beantwortbar"] = not (
            kennung == "verlauf" and corpus is not None and not zeitachse
        )
        frage = aus_dem_korpus.get(kennung)
        eintrag["beispiel_frage_quelle"] = "korpus" if frage else "statisch"
        if frage:
            eintrag["beispiel_frage"] = frage
        rezepte.append(eintrag)
    return {"recipes": rezepte}
