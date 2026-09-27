"""Characterization tests for Phase 3 of the ``run_async`` decomposition:
the tool-specs-provider seam and the lifted LLM-invocation web.

Pinned seams (all lifted verbatim from former closures):

* ``_ra_active_tool_specs(state)`` -- the provider: ``forced_next_tools``
  wins over ``active_allowed_tools`` (both now live on ``_RunTurnState``).
* ``_ra_invoke_llm(state, ...)`` -- message/tool/kwarg assembly for one LLM
  call, reading the per-turn invocation config from the state object.
* ``_ra_call_llm_with_recovery(state, copilot_event_bus, invoker=None)`` -- retry and
  typed-error recovery, budgets on the state object.
* ``_ra_run_structured_step(state, copilot_event_bus, *, doc, payload, schema)`` --
  the schema side-channel; ``run_async`` binds it with ``functools.partial``
  and injects that binding into ``GroundingVerifier`` (kw-only call
  convention pinned here).
* ``_ra_run_tool_batches(state, copilot_event_bus, calls, ...)`` -- filter plumbing
  from state + safe/unsafe dispatch ordering.

No live LLM; fakes only. Real modules via ``tests.ai._real_copilot``.
"""

import asyncio
import functools
import types
import unittest

from tests.ai._real_copilot import make_orchestrator, orchestrator as orch_module

_RunTurnState = orch_module._RunTurnState
LLMErrorKind = orch_module.LLMErrorKind
LLMRequestError = orch_module.LLMRequestError


def _spec(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


def _capture_copilot_event_bus(events):
    return types.SimpleNamespace(
        publish=lambda event, session_id=None: events.append(event)
    )


def _turn_state(**overrides):
    """A _RunTurnState with the per-turn config run_async would assign."""
    state = _RunTurnState()
    state.question = "Wie oft kommt Zeit vor?"
    state.normalized_question = "Wie oft kommt Zeit vor?"
    state.role = "user"
    state.stream = False
    state.system_prompt = "SYSTEM-PROMPT"
    state.accepts_stream = False
    state.accepts_json_schema = False
    state.accepts_tool_choice = False
    state.llm_is_async = True
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


class _RecordingLLM:
    """Async call_llm fake recording (messages, tools, kwargs) per call.

    ``script`` is a list of results; Exception instances are raised instead
    of returned. The last entry repeats once the script is exhausted.
    """

    def __init__(self, script=None):
        self.calls = []
        self.script = list(script or [{"choices": [{"message": {"content": "ok"}}]}])

    async def __call__(self, messages, tools, **kwargs):
        self.calls.append(
            {"messages": list(messages), "tools": list(tools), "kwargs": dict(kwargs)}
        )
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def _make_orch(tools, call_llm=None):
    async def _no_dispatch(tool_call, _token=None):  # pragma: no cover
        raise AssertionError("dispatch must not be called in these tests")

    async def _no_llm(messages, tools_arg, **kwargs):  # pragma: no cover
        raise AssertionError("LLM must not be called in this test")

    return make_orchestrator(tools, call_llm or _no_llm, _no_dispatch)


class ActiveToolSpecsProviderTests(unittest.TestCase):
    """The provider seam: forced tools win over the allowed bundle."""

    def setUp(self):
        self.tools = [_spec("frequency_list"), _spec("run_cqlf_query"), _spec("keyness")]
        self.orch = _make_orch(self.tools)

    def _names(self, state):
        return [
            s["function"]["name"] for s in self.orch._ra_active_tool_specs(state)
        ]

    def test_both_none_exposes_full_registry(self):
        state = _turn_state()
        self.assertEqual(self.orch._ra_active_tool_specs(state), self.tools)

    def test_allowed_bundle_filters_when_no_forced_tools(self):
        state = _turn_state(active_allowed_tools=["keyness", "frequency_list"])
        self.assertEqual(self._names(state), ["frequency_list", "keyness"])

    def test_forced_tools_win_over_allowed_bundle(self):
        state = _turn_state(
            active_allowed_tools=["keyness", "frequency_list"],
            forced_next_tools=["run_cqlf_query"],
        )
        self.assertEqual(self._names(state), ["run_cqlf_query"])

    def test_empty_forced_list_exposes_no_tools(self):
        state = _turn_state(
            active_allowed_tools=["keyness"], forced_next_tools=[]
        )
        self.assertEqual(self._names(state), [])

    def test_resetting_forced_tools_restores_allowed_bundle(self):
        # mirrors the main-loop reassignment formerly done via ``nonlocal``
        state = _turn_state(
            active_allowed_tools=["keyness"], forced_next_tools=["run_cqlf_query"]
        )
        self.assertEqual(self._names(state), ["run_cqlf_query"])
        state.forced_next_tools = None
        self.assertEqual(self._names(state), ["keyness"])


class RequiredEvidenceRecoveryTests(unittest.TestCase):
    def test_not_applicable_metric_does_not_force_unrelated_metric_tool(self):
        tools = [
            _spec("compare_collocates"),
            _spec("keyness"),
            _spec("metadata_values"),
        ]
        orch = _make_orch(tools)
        orch._turn_evidence_items = [
            orch_module.EvidenceItem(
                id="e_compare",
                tool="compare_collocates",
                tool_call_id="call_compare",
                query='{"term": "Mensch"}',
                status="not_applicable",
                truncated=False,
                raw_surface={
                    "status": "not_applicable",
                    "message": "Korpus ist nicht gepaart.",
                },
            ).to_dict()
        ]
        contract = orch_module.AnalysisContract(
            mode="tool_analysis",
            track="comparative_analysis",
            analysis_family="contrast_keyness",
            deliverable_kind="contrast_report",
            allowed_tools=[
                "compare_collocates",
                "keyness",
                "metadata_values",
            ],
            required_evidence=["metric_rows", "metadata_rows"],
        )

        pending, missing = orch._ra_pending_required_evidence_tools(
            contract,
            contract.allowed_tools,
        )

        self.assertEqual(pending, ["metadata_values"])
        self.assertEqual(missing, ["metadata_rows"])
        self.assertNotIn("keyness", pending)


class InvokeLlmTests(unittest.TestCase):
    def test_default_messages_tools_and_kwargs_from_state(self):
        llm = _RecordingLLM()
        orch = _make_orch([_spec("frequency_list")], llm)
        orch.session.append({"role": "user", "content": "Wie oft kommt Zeit vor?"})
        state = _turn_state(active_allowed_tools=["frequency_list"])

        result = asyncio.run(orch._ra_invoke_llm(state))

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        call = llm.calls[0]
        # R2 KV-split: the state's system prompt is the byte-stable message
        # prefix; the per-call runtime guard is a turn variable and is
        # APPENDED at the end of the message list.
        self.assertEqual(call["messages"][0]["content"], "SYSTEM-PROMPT")
        self.assertEqual(call["messages"][0]["role"], "system")
        self.assertIn("RUNTIME-TOOL-SPACE:", call["messages"][-1]["content"])
        # Waechter-Rollen-Aenderung (a038abb3e1): der Guard reist als
        # USER-Nachricht mit [System note:]-Wrapper.
        self.assertEqual(call["messages"][-1]["role"], "user")
        self.assertEqual(
            call["messages"][-2]["content"], "Wie oft kommt Zeit vor?"
        )
        self.assertEqual(
            [t["function"]["name"] for t in call["tools"]], ["frequency_list"]
        )
        self.assertEqual(call["kwargs"]["user"], "user")
        self.assertIs(call["kwargs"]["policy"], orch.policy)
        # accepts_stream / accepts_json_schema are False -> neither forwarded
        self.assertNotIn("stream", call["kwargs"])
        self.assertNotIn("json_schema", call["kwargs"])

    def test_forced_tools_narrow_the_exposed_tool_space(self):
        llm = _RecordingLLM()
        orch = _make_orch([_spec("frequency_list"), _spec("keyness")], llm)
        state = _turn_state(
            active_allowed_tools=["frequency_list", "keyness"],
            forced_next_tools=["keyness"],
        )
        asyncio.run(orch._ra_invoke_llm(state))
        self.assertEqual(
            [t["function"]["name"] for t in llm.calls[0]["tools"]], ["keyness"]
        )

    def test_forced_evidence_tools_require_a_tool_call_when_supported(self):
        llm = _RecordingLLM()
        orch = _make_orch([_spec("frequency_list"), _spec("keyness")], llm)
        state = _turn_state(
            active_allowed_tools=["frequency_list", "keyness"],
            forced_next_tools=["frequency_list"],
            accepts_tool_choice=True,
        )

        asyncio.run(orch._ra_invoke_llm(state))

        self.assertEqual(
            llm.calls[0]["kwargs"]["tool_choice"],
            "required",
        )

    def test_tools_override_suppresses_provider_but_declares_empty_tool_space(self):
        llm = _RecordingLLM()
        orch = _make_orch([_spec("frequency_list")], llm)
        state = _turn_state(active_allowed_tools=["frequency_list"])
        request_messages = [{"role": "user", "content": "STRUCT"}]

        asyncio.run(
            orch._ra_invoke_llm(
                state, request_messages=request_messages, tools_override=[]
            )
        )

        call = llm.calls[0]
        self.assertEqual(call["tools"], [])
        # R2 KV-split: the guard is appended AFTER the request messages.
        self.assertIn("keine Tools verfügbar", call["messages"][-1]["content"])
        self.assertEqual(call["messages"][:-1], request_messages)

    def test_stream_kwarg_follows_state_and_use_stream_override(self):
        llm = _RecordingLLM()
        orch = _make_orch([], llm)
        state = _turn_state(accepts_stream=True, stream=True)
        asyncio.run(orch._ra_invoke_llm(state))
        self.assertIs(llm.calls[0]["kwargs"]["stream"], True)
        asyncio.run(orch._ra_invoke_llm(state, use_stream=False))
        self.assertIs(llm.calls[1]["kwargs"]["stream"], False)

    def test_json_schema_forwarded_only_when_path_accepts_it(self):
        llm = _RecordingLLM()
        orch = _make_orch([], llm)
        schema = {"name": "s", "schema": {"type": "object"}}

        state = _turn_state(accepts_json_schema=False)
        asyncio.run(orch._ra_invoke_llm(state, json_schema=schema))
        self.assertNotIn("json_schema", llm.calls[0]["kwargs"])

        state = _turn_state(accepts_json_schema=True)
        asyncio.run(orch._ra_invoke_llm(state, json_schema=schema))
        self.assertIs(llm.calls[1]["kwargs"]["json_schema"], schema)

    def test_sync_call_llm_goes_through_to_thread(self):
        calls = []

        def sync_llm(messages, tools, **kwargs):
            calls.append(kwargs)
            return {"choices": [{"message": {"content": "sync"}}]}

        orch = _make_orch([], sync_llm)
        state = _turn_state(llm_is_async=False)
        result = asyncio.run(orch._ra_invoke_llm(state))
        self.assertEqual(result["choices"][0]["message"]["content"], "sync")
        self.assertEqual(len(calls), 1)

    def test_unbounded_async_llm_call_observes_out_of_band_cancellation(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def hanging_llm(_messages, _tools, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        orch = _make_orch([], hanging_llm)

        async def scenario():
            task = asyncio.create_task(orch._ra_invoke_llm(_turn_state()))
            await started.wait()
            orch.request_cancel()
            await task

        with self.assertRaises(orch_module.CopilotTurnCancelled):
            asyncio.run(scenario())
        self.assertTrue(cancelled.is_set())

    def test_route_and_model_recorded_from_result(self):
        llm = _RecordingLLM(
            [
                {
                    "choices": [{"message": {"content": "ok"}}],
                    "_cc_route": "primary:chat",
                    "_cc_model": "test-model",
                }
            ]
        )
        orch = _make_orch([], llm)
        asyncio.run(orch._ra_invoke_llm(_turn_state()))
        self.assertEqual(orch._last_llm_route, "primary:chat")
        self.assertEqual(orch._last_llm_model, "test-model")


class CallLlmWithRecoveryTests(unittest.TestCase):
    def test_default_invoker_is_plain_invoke_llm(self):
        llm = _RecordingLLM([{"choices": [{"message": {"content": "direct"}}]}])
        orch = _make_orch([_spec("frequency_list")], llm)
        state = _turn_state(active_allowed_tools=["frequency_list"])
        result = asyncio.run(
            orch._ra_call_llm_with_recovery(state, _capture_copilot_event_bus([]))
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "direct")
        # the default invoker exposed the state-resolved tool space
        self.assertEqual(
            [t["function"]["name"] for t in llm.calls[0]["tools"]],
            ["frequency_list"],
        )

    def test_max_output_tokens_recovery_bumps_state_counter_and_retries(self):
        error = LLMRequestError(
            kind=LLMErrorKind.MAX_OUTPUT_TOKENS, message="output limit"
        )
        llm = _RecordingLLM(
            [error, {"choices": [{"message": {"content": "second"}}]}]
        )
        orch = _make_orch([], llm)
        orch.llm_retries = 1  # recovery only re-calls within the attempt budget
        events = []
        state = _turn_state()

        result = asyncio.run(
            orch._ra_call_llm_with_recovery(state, _capture_copilot_event_bus(events))
        )

        self.assertEqual(result["choices"][0]["message"]["content"], "second")
        self.assertEqual(state.output_resume_count, 1)
        self.assertEqual(len(llm.calls), 2)
        recovery_kinds = [
            e["recovery"]["kind"] for e in events if e.get("event") == "copilot.recovery"
        ]
        self.assertIn("max_output_tokens", recovery_kinds)
        # the shortening system note was appended for the retried call
        history = orch.session.get_history()
        self.assertTrue(
            any("Ausgabelimit" in str(m.get("content", "")) for m in history)
        )

    def test_recovery_on_last_attempt_still_reinvokes_llm(self):
        """Corrected contract (the historical ``for attempt in range(...)``
        boundary swallowed this re-call and returned ``None`` — a wasted
        recovery): a typed-error recovery that SUCCEEDS always earns one more
        LLM invoke, even with the default ``llm_retries=0`` budget."""
        error = LLMRequestError(
            kind=LLMErrorKind.MAX_OUTPUT_TOKENS, message="output limit"
        )
        llm = _RecordingLLM(
            [error, {"choices": [{"message": {"content": "after recovery"}}]}]
        )
        orch = _make_orch([], llm)
        self.assertEqual(orch.llm_retries, 0)
        state = _turn_state()
        result = asyncio.run(
            orch._ra_call_llm_with_recovery(state, _capture_copilot_event_bus([]))
        )
        self.assertEqual(
            result["choices"][0]["message"]["content"], "after recovery"
        )
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(state.output_resume_count, 1)

    def test_unrecoverable_typed_error_is_reraised_without_budget_use(self):
        error = LLMRequestError(
            kind=LLMErrorKind.AUTH_FAILED, message="bad key", retryable=False
        )
        llm = _RecordingLLM([error, error])
        orch = _make_orch([], llm)
        state = _turn_state()
        with self.assertRaises(LLMRequestError):
            asyncio.run(
                orch._ra_call_llm_with_recovery(state, _capture_copilot_event_bus([]))
            )
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(state.output_resume_count, 0)
        self.assertEqual(state.context_recovery_count, 0)
        self.assertEqual(state.microcompact_count, 0)

    def test_generic_error_uses_plain_retry_budget_and_emits_recovery(self):
        llm = _RecordingLLM(
            [ValueError("boom"), {"choices": [{"message": {"content": "again"}}]}]
        )
        orch = _make_orch([], llm)
        orch.llm_retries = 1
        events = []
        result = asyncio.run(
            orch._ra_call_llm_with_recovery(_turn_state(), _capture_copilot_event_bus(events))
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "again")
        self.assertEqual(len(llm.calls), 2)
        recovery_kinds = [
            e["recovery"]["kind"] for e in events if e.get("event") == "copilot.recovery"
        ]
        self.assertEqual(recovery_kinds, ["llm_retry"])

    def test_generic_error_without_budget_is_reraised(self):
        llm = _RecordingLLM([ValueError("boom")])
        orch = _make_orch([], llm)
        with self.assertRaises(ValueError):
            asyncio.run(
                orch._ra_call_llm_with_recovery(_turn_state(), _capture_copilot_event_bus([]))
            )

    def test_explicit_invoker_bypasses_default_invoke_llm(self):
        orch = _make_orch([])  # call_llm asserts if reached

        async def invoker():
            return {"choices": [{"message": {"content": "custom"}}]}

        result = asyncio.run(
            orch._ra_call_llm_with_recovery(
                _turn_state(), _capture_copilot_event_bus([]), invoker
            )
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "custom")

    def test_stream_consumer_engine_failure_stays_inside_recovery_boundary(self):
        orch = _make_orch([])
        state = _turn_state()
        calls = 0

        async def invoker():
            nonlocal calls
            calls += 1
            return calls

        async def consume(value):
            if value == 1:
                raise LLMRequestError(
                    kind=LLMErrorKind.ENGINE_UNAVAILABLE,
                    message="engine interrupted during iteration",
                    retryable=True,
                )
            return {"choices": [{"message": {"content": "complete"}}]}

        original_delays = orch_module._ENGINE_RETRY_DELAYS
        orch_module._ENGINE_RETRY_DELAYS = (0.0,)
        try:
            result = asyncio.run(
                orch._ra_call_llm_with_recovery(
                    state,
                    _capture_copilot_event_bus([]),
                    invoker=invoker,
                    consume=consume,
                )
            )
        finally:
            orch_module._ENGINE_RETRY_DELAYS = original_delays

        self.assertEqual(result["choices"][0]["message"]["content"], "complete")
        self.assertEqual(calls, 2)
        self.assertEqual(state.engine_retry_count, 0)

    def test_started_stream_engine_failure_is_replayed_after_waiting(self):
        # Runde 5, 2026-09-13: ein Modellwechsel mitten im Strom toetete den
        # Turn, obwohl kein Werkzeug gelaufen war. Werkzeuge laufen erst nach
        # dem vollstaendigen Strom, ein Replay erzeugt kein Duplikat. Die
        # Teilausgabe wird als stream_replay verworfen, dann wartet der Turn
        # auf dasselbe Modell und wiederholt den Aufruf.
        events = []
        error = LLMRequestError(
            kind=LLMErrorKind.ENGINE_UNAVAILABLE,
            message="engine interrupted after output",
            retryable=True,
            response_started=True,
        )
        llm = _RecordingLLM(
            [error, {"choices": [{"message": {"content": "nach dem Warten"}}]}]
        )
        orch = _make_orch([], llm)
        gewartet = []

        async def _warte(turn_state):
            gewartet.append(1)
            return True

        orch._ra_warte_auf_modell = _warte
        original = orch_module._ENGINE_RETRY_DELAYS
        orch_module._ENGINE_RETRY_DELAYS = (0.0,)
        try:
            result = asyncio.run(
                orch._ra_call_llm_with_recovery(
                    _turn_state(),
                    _capture_copilot_event_bus(events),
                )
            )
        finally:
            orch_module._ENGINE_RETRY_DELAYS = original

        self.assertEqual(result["choices"][0]["message"]["content"], "nach dem Warten")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(gewartet, [1])
        kinds = [
            (e.get("recovery") or {}).get("kind")
            for e in events
            if e.get("event") == "copilot.recovery"
        ]
        self.assertEqual(kinds, ["stream_replay", "engine_wait"])

    def test_started_stream_is_not_replayed_after_unexplained_abort(self):
        # Der Verzicht auf Replay bleibt fuer den unerklaerten Abbruch nach
        # sichtbarem Text (kein Modellwechsel, nicht wiederholbar): der
        # Abbruch landet als stream_abort, damit der Client weiss, warum
        # der Strom endete, und es gibt genau einen Aufruf.
        events = []
        error = LLMRequestError(
            kind=LLMErrorKind.TRANSPORT,
            message="stream aborted after output",
            retryable=False,
            response_started=True,
        )
        llm = _RecordingLLM(
            [error, {"choices": [{"message": {"content": "duplicate"}}]}]
        )
        orch = _make_orch([], llm)

        with self.assertRaises(LLMRequestError):
            asyncio.run(
                orch._ra_call_llm_with_recovery(
                    _turn_state(),
                    _capture_copilot_event_bus(events),
                )
            )

        self.assertEqual(len(llm.calls), 1)
        recoveries = [e["recovery"] for e in events if e.get("event") == "copilot.recovery"]
        self.assertEqual([e["kind"] for e in recoveries], ["stream_abort"])
        self.assertIn("nicht automatisch wiederholt", recoveries[0]["message"])

    def test_recovery_wait_observes_out_of_band_cancellation(self):
        orch = _make_orch([])

        async def scenario():
            task = asyncio.create_task(orch._ra_wait_with_cancellation(10.0))
            await asyncio.sleep(0)
            orch.request_cancel()
            await task

        with self.assertRaises(orch_module.CopilotTurnCancelled):
            asyncio.run(scenario())


class RunStructuredStepTests(unittest.TestCase):
    def test_returns_none_without_json_schema_support(self):
        orch = _make_orch([])  # call_llm asserts if reached
        state = _turn_state(accepts_json_schema=False)
        result = asyncio.run(
            orch._ra_run_structured_step(
                state,
                _capture_copilot_event_bus([]),
                doc="DOC",
                payload={"q": 1},
                schema={"name": "s"},
            )
        )
        self.assertIsNone(result)

    def test_structured_call_pins_schema_empty_tools_and_parses_payload(self):
        llm = _RecordingLLM(
            [{"choices": [{"message": {"content": '{"mode": "tool_analysis"}'}}]}]
        )
        orch = _make_orch([_spec("frequency_list")], llm)
        state = _turn_state(
            accepts_json_schema=True,
            active_allowed_tools=["frequency_list"],
        )
        schema = {"name": "contract", "schema": {"type": "object"}}

        result = asyncio.run(
            orch._ra_run_structured_step(
                state,
                _capture_copilot_event_bus([]),
                doc="CONTRACT-DOC",
                payload={"question": "Wie oft kommt Zeit vor?"},
                schema=schema,
            )
        )

        self.assertEqual(result, {"mode": "tool_analysis"})
        call = llm.calls[0]
        # Structured side-channel: no provider tools, explicit empty-space
        # guard, and the schema pinned to the call.
        self.assertEqual(call["tools"], [])
        self.assertIs(call["kwargs"]["json_schema"], schema)
        # R2 KV-split: doc + payload first, empty-space guard appended last.
        self.assertEqual(
            [m["role"] for m in call["messages"]],
            ["system", "user", "user"],
        )
        self.assertTrue(call["messages"][0]["content"].startswith("CONTRACT-DOC"))
        self.assertIn("Wie oft kommt Zeit vor?", call["messages"][1]["content"])
        self.assertIn("keine Tools verfügbar", call["messages"][2]["content"])

    def test_use_stream_is_forced_off_for_structured_steps(self):
        llm = _RecordingLLM([{"choices": [{"message": {"content": "[]"}}]}])
        orch = _make_orch([], llm)
        state = _turn_state(
            accepts_json_schema=True, accepts_stream=True, stream=True
        )
        asyncio.run(
            orch._ra_run_structured_step(
                state, _capture_copilot_event_bus([]), doc="D", payload={}, schema={"name": "s"}
            )
        )
        self.assertIs(llm.calls[0]["kwargs"]["stream"], False)

    def test_partial_binding_matches_verifier_call_convention(self):
        """run_async injects ``functools.partial(_ra_run_structured_step,
        turn_state, copilot_event_bus)`` into GroundingVerifier, which calls it with
        kw-only ``doc=/payload=/schema=`` -- pin that convention."""
        llm = _RecordingLLM(
            [{"choices": [{"message": {"content": '{"claims": []}'}}]}]
        )
        orch = _make_orch([], llm)
        state = _turn_state(accepts_json_schema=True)
        bound = functools.partial(
            orch._ra_run_structured_step, state, _capture_copilot_event_bus([])
        )
        result = asyncio.run(
            bound(doc="ENVELOPE-DOC", payload={"facts": []}, schema={"name": "env"})
        )
        self.assertEqual(result, {"claims": []})

    def test_recovery_wraps_the_structured_invoker(self):
        error = LLMRequestError(
            kind=LLMErrorKind.MAX_OUTPUT_TOKENS, message="output limit"
        )
        llm = _RecordingLLM(
            [error, {"choices": [{"message": {"content": '{"ok": true}'}}]}]
        )
        orch = _make_orch([], llm)
        orch.llm_retries = 1  # recovery only re-calls within the attempt budget
        state = _turn_state(accepts_json_schema=True)
        result = asyncio.run(
            orch._ra_run_structured_step(
                state, _capture_copilot_event_bus([]), doc="D", payload={}, schema={"name": "s"}
            )
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(state.output_resume_count, 1)
        # the retried call is still the structured invoker (schema + no tools)
        self.assertEqual(llm.calls[1]["tools"], [])
        self.assertIn("json_schema", llm.calls[1]["kwargs"])


class RunToolBatchesTests(unittest.TestCase):
    def _orch_with_filter_capture(self, allowed_result):
        orch = _make_orch([_spec("frequency_list")])
        captured = {}

        def fake_filter(candidate_calls, **kwargs):
            captured["candidate_calls"] = candidate_calls
            captured.update(kwargs)
            return allowed_result

        orch._ra_filter_tool_calls = fake_filter
        return orch, captured

    @staticmethod
    def _tc(call_id, name="frequency_list"):
        return {"id": call_id, "function": {"name": name, "arguments": "{}"}}

    def test_filter_receives_state_plumbing_and_blocks_dispatch(self):
        orch, captured = self._orch_with_filter_capture([])
        state = _turn_state(
            active_allowed_tools=["frequency_list"],
            forced_next_tools=["keyness"],
        )
        dispatched = []

        async def dispatch(tc, tokens):  # pragma: no cover - must not run
            dispatched.append((tc, tokens))

        copilot_event_bus = _capture_copilot_event_bus([])
        asyncio.run(
            orch._ra_run_tool_batches(
                state,
                copilot_event_bus,
                [self._tc("c1")],
                active_contract=None,
                dispatch=dispatch,
            )
        )

        self.assertEqual(dispatched, [])
        self.assertEqual(captured["question"], state.normalized_question)
        self.assertEqual(captured["principal"], state.principal)
        self.assertEqual(captured["active_allowed_tools"], ["frequency_list"])
        self.assertEqual(captured["forced_next_tools"], ["keyness"])
        self.assertIsNone(captured["active_contract"])
        self.assertIs(captured["copilot_event_bus"], copilot_event_bus)
        self.assertEqual(captured["candidate_calls"], [self._tc("c1")])

    def test_allowed_calls_are_dispatched_with_their_token_counts(self):
        tc1, tc2 = self._tc("c1"), self._tc("c2", "keyness")
        orch, _ = self._orch_with_filter_capture([(tc1, 5), (tc2, 7)])
        orch._partition_tool_calls = lambda calls: [(False, list(calls))]
        order = []

        async def dispatch(tc, tokens):
            order.append((tc["id"], tokens))

        asyncio.run(
            orch._ra_run_tool_batches(
                _turn_state(),
                _capture_copilot_event_bus([]),
                [tc1, tc2],
                active_contract=None,
                dispatch=dispatch,
            )
        )
        # unsafe batch: strictly sequential, original order, token map intact
        self.assertEqual(order, [("c1", 5), ("c2", 7)])

    def test_safe_batches_run_concurrently_via_gather(self):
        tc1, tc2 = self._tc("c1"), self._tc("c2")
        orch, _ = self._orch_with_filter_capture([(tc1, 1), (tc2, 2)])
        orch._partition_tool_calls = lambda calls: [(True, list(calls))]
        in_flight = {"now": 0, "max": 0}

        async def dispatch(tc, tokens):
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
            await asyncio.sleep(0.01)
            in_flight["now"] -= 1

        asyncio.run(
            orch._ra_run_tool_batches(
                _turn_state(),
                _capture_copilot_event_bus([]),
                [tc1, tc2],
                active_contract=None,
                dispatch=dispatch,
            )
        )
        self.assertEqual(in_flight["max"], 2)


if __name__ == "__main__":
    unittest.main()
