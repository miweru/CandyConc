"""Integration tests for the Copilot orchestrator flow.

NO MOCKS - Tests the real components.
"""

import pytest
from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator, State
from candyconc.candyconc_copilot.session_manager import SessionManager
from candyconc.candyconc_copilot.prompts import (
    parse_control_frame,
    extract_all_control_frames,
    remove_control_frames,
    TOOLS_DOC,
)

pytestmark = pytest.mark.integration


class TestControlFrameParsing:
    """Test control frame parsing from LLM responses."""

    def test_parse_plan_frame(self):
        text = '''Ich erstelle einen Analyseplan.

<<<CC:PLAN {"goal": "Frequenzanalyse", "steps": [{"id": 1, "description": "Suche", "tool": "run_cqlf_query"}], "expectedOutcome": "Frequenzdaten"}>>>

Das war der Plan.'''

        result = parse_control_frame(text)
        assert result is not None
        frame_type, data = result
        assert frame_type == "PLAN"
        assert data["goal"] == "Frequenzanalyse"
        assert len(data["steps"]) == 1

    def test_parse_clarify_frame(self):
        text = '''Ich brauche mehr Information.

<<<CC:CLARIFY {"question": "Welches Korpus?", "reason": "Mehrere verfügbar", "options": [{"id": "news", "label": "Nachrichten"}, {"id": "wiki", "label": "Wikipedia"}], "timeout": 60}>>>'''

        result = parse_control_frame(text)
        assert result is not None
        frame_type, data = result
        assert frame_type == "CLARIFY"
        assert data["question"] == "Welches Korpus?"
        assert len(data["options"]) == 2

    def test_parse_action_frame(self):
        text = '''Ich führe die Suche aus.

<<<CC:ACTION {"actionType": "run_cqlf_query", "summary": "Suche nach Politik", "payload": {"query": "Politik", "ctx": 5}, "impact": "Durchsucht Korpus", "reversible": true, "requiresApproval": true}>>>'''

        result = parse_control_frame(text)
        assert result is not None
        frame_type, data = result
        assert frame_type == "ACTION"
        assert data["actionType"] == "run_cqlf_query"
        assert data["requiresApproval"] is True

    def test_extract_multiple_frames(self):
        text = '''Plan und Aktion:

<<<CC:PLAN {"goal": "Test", "steps": [], "expectedOutcome": "Ergebnis"}>>>

Und jetzt die Aktion:

<<<CC:ACTION {"actionType": "test", "summary": "Test", "payload": {}, "impact": "Keine", "reversible": true, "requiresApproval": false}>>>'''

        frames = extract_all_control_frames(text)
        assert len(frames) == 2
        assert frames[0][0] == "PLAN"
        assert frames[1][0] == "ACTION"

    def test_remove_control_frames(self):
        text = '''Vorher <<<CC:PLAN {"goal": "Test", "steps": [], "expectedOutcome": "X"}>>> Nachher'''
        cleaned = remove_control_frames(text)
        assert "<<<CC:PLAN" not in cleaned
        assert "Vorher" in cleaned
        assert "Nachher" in cleaned

    # The build_* frame helpers were deleted (frames are emitted by the LLM as
    # text; only the parser side is runtime code). The former roundtrip tests
    # keep their payload coverage with literal frame strings.

    def test_plan_frame_literal_roundtrip(self):
        frame = (
            '<<<CC:PLAN {"goal": "Frequenzanalyse von Politik", '
            '"steps": [{"id": 1, "description": "CQLF Query", '
            '"tool": "run_cqlf_query"}], '
            '"expectedOutcome": "Frequenztabelle"}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        frame_type, data = result
        assert frame_type == "PLAN"
        assert data["goal"] == "Frequenzanalyse von Politik"

    def test_clarify_frame_literal_roundtrip(self):
        frame = (
            '<<<CC:CLARIFY {"question": "Welches Register?", '
            '"reason": "Mehrere verfügbar", '
            '"options": [{"id": "news", "label": "News"}], '
            '"timeout": 30, "defaultOption": "news"}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        frame_type, data = result
        assert frame_type == "CLARIFY"
        assert data["question"] == "Welches Register?"

    def test_action_frame_literal_roundtrip(self):
        frame = (
            '<<<CC:ACTION {"actionType": "collocate_stats", '
            '"summary": "Kollokationen für Politik", '
            '"payload": {"term": "Politik", "window": 5}, '
            '"impact": "Berechnet Kollokationen", '
            '"reversible": true, "requiresApproval": false}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        frame_type, data = result
        assert frame_type == "ACTION"
        assert data["actionType"] == "collocate_stats"


class TestSessionManager:
    """Test SessionManager without mocks."""

    def test_session_append_and_history(self):
        session = SessionManager(max_messages=100, max_tokens=10000)

        session.append({"role": "user", "content": "Hello"})
        session.append({"role": "assistant", "content": "Hi there!"})

        history = session.get_history()
        assert len(history) >= 2
        # Last two should be our messages
        assert history[-2]["content"] == "Hello"
        assert history[-1]["content"] == "Hi there!"

    def test_session_id_generated(self):
        session1 = SessionManager()
        session2 = SessionManager()

        assert session1.session_id is not None
        assert session2.session_id is not None
        assert session1.session_id != session2.session_id

    def test_session_with_custom_id(self):
        session = SessionManager(session_id="test-123")
        assert session.session_id == "test-123"

    def test_token_count_basic(self):
        messages = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi there"},
        ]
        count = SessionManager._token_count(messages)
        assert count > 0
        assert count < 100  # Should be reasonable


class TestOrchestratorStateManagement:
    """Test orchestrator state transitions without running LLM."""

    def test_initial_state(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )
        assert orch.state == State.WAITING_LLM

    def test_approve_action_with_pending(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        # Simulate pending action
        orch._pending_action = {"requestId": "abc-123", "type": "test", "payload": {}}
        orch.state = State.WAITING_APPROVAL

        result = orch.approve_action("abc-123")
        assert result is True
        assert orch.state == State.EXECUTING_TOOL

    def test_approve_action_wrong_id(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        orch._pending_action = {"requestId": "abc-123", "type": "test", "payload": {}}
        orch.state = State.WAITING_APPROVAL

        result = orch.approve_action("wrong-id")
        assert result is False
        assert orch.state == State.WAITING_APPROVAL

    def test_reject_action(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        orch._pending_action = {"requestId": "abc-123", "type": "test", "payload": {}}
        orch.state = State.WAITING_APPROVAL

        result = orch.reject_action("abc-123", "Too risky")
        assert result is True
        assert orch.state == State.WAITING_LLM
        assert orch._pending_action is None

    def test_answer_clarification(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        orch._pending_clarification = {
            "questionId": "q-456",
            "prompt": "Welches Korpus?",
            "options": []
        }
        orch.state = State.WAITING_CLARIFICATION
        initial_history_len = len(session.history)

        result = orch.answer_clarification("q-456", "news")
        assert result is True
        assert orch.state == State.WAITING_LLM
        assert orch._pending_clarification is None
        # Answer should be added to session
        assert len(session.history) == initial_history_len + 1

    def test_answer_clarification_wrong_id(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        orch._pending_clarification = {"questionId": "q-456", "prompt": "Test?", "options": []}
        orch.state = State.WAITING_CLARIFICATION

        result = orch.answer_clarification("wrong-id", "answer")
        assert result is False
        assert orch.state == State.WAITING_CLARIFICATION

    def test_set_ui_context(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        orch.set_ui_context({"autonomy_level": 8, "current_query": "Politik"})
        assert orch.ui_context["autonomy_level"] == 8
        assert orch.ui_context["current_query"] == "Politik"


class TestAutonomyLevelBehavior:
    """Test autonomy level affects approval requirements."""

    def test_low_autonomy_requires_approval(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
            ui_context={"autonomy_level": 1}
        )

        # Low autonomy should require approval for most actions
        data = {"reversible": True}
        assert orch._should_require_approval(data) is True

    def test_high_autonomy_skips_approval_for_reversible(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
            ui_context={"autonomy_level": 8}
        )

        # High autonomy should not require approval for reversible actions
        data = {"reversible": True}
        assert orch._should_require_approval(data) is False

    def test_max_autonomy_skips_all_approval(self):
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
            ui_context={"autonomy_level": 10}
        )

        # Max autonomy should skip approval even for irreversible
        data = {"reversible": False}
        assert orch._should_require_approval(data) is False


class TestToolDocumentation:
    """Test tool documentation completeness."""

    def test_all_semantic_tools_documented(self):
        expected_tools = [
            "semantic_cluster_words",
            "refine_cluster_label",
            "semantic_recluster",
            "cluster_save",
            "cluster_export_md",
            "documentation_search",
        ]

        for tool in expected_tools:
            assert tool in TOOLS_DOC, f"Tool {tool} not documented in TOOLS_DOC"

    def test_translate_query_removed(self):
        assert "translate_query" not in TOOLS_DOC

        from candyconc.candyconc_copilot import __all__
        assert "translate_query_tool" not in __all__
        assert "TRANSLATE_QUERY_TOOL" not in __all__

    def test_core_tools_documented(self):
        core_tools = [
            "run_cqlf_query",
            "collocate_stats",
            "frequency_list",
            "dispersion_offsets",
            "keyness",
            "semantic_search",
        ]

        for tool in core_tools:
            assert tool in TOOLS_DOC, f"Core tool {tool} not documented"

    def test_tools_have_output_descriptions(self):
        """Each tool should have OUTPUT description."""
        assert "OUTPUT:" in TOOLS_DOC or "output:" in TOOLS_DOC.lower()


class TestControlFrameEventStructure:
    """Test that emitted events have correct structure."""

    def test_emit_action_event_structure(self):
        """Action events should have requestId in request object."""
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
            ui_context={"autonomy_level": 2}
        )

        captured = []
        class FakeCopilotEventBus:
            def publish(self, event, session_id=None):
                captured.append(event)

        action_data = {
            "actionType": "run_cqlf_query",
            "summary": "Test",
            "payload": {"query": "test"},
            "impact": "None",
            "reversible": True,
            "requiresApproval": True
        }

        orch._emit_control_frame_event("ACTION", action_data, FakeCopilotEventBus())

        action_events = [e for e in captured if e.get("event") == "copilot.action_request"]
        assert len(action_events) == 1

        event = action_events[0]
        assert "request" in event
        assert "requestId" in event["request"]
        assert "type" in event["request"]
        assert "meta" in event

    def test_emit_clarify_event_structure(self):
        """Clarify events should have questionId in question object."""
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        captured = []
        class FakeCopilotEventBus:
            def publish(self, event, session_id=None):
                captured.append(event)

        clarify_data = {
            "question": "Welches Korpus?",
            "reason": "Mehrere verfügbar",
            "options": [{"id": "news", "label": "News"}],
            "timeout": 60
        }

        orch._emit_control_frame_event("CLARIFY", clarify_data, FakeCopilotEventBus())

        clarify_events = [e for e in captured if e.get("event") == "copilot.clarify"]
        assert len(clarify_events) == 1

        event = clarify_events[0]
        assert "question" in event
        assert "questionId" in event["question"]
        assert "prompt" in event["question"]

    def test_emit_plan_event_structure(self):
        """Plan events should have proper structure."""
        session = SessionManager()
        orch = ReActOrchestrator(
            tools=[],
            call_llm=lambda m, t, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            dispatch=lambda tc, token: {"status": "ok"},
            session=session,
        )

        captured = []
        class FakeCopilotEventBus:
            def publish(self, event, session_id=None):
                captured.append(event)

        plan_data = {
            "goal": "Analyse durchführen",
            "steps": [{"id": 1, "description": "Schritt 1", "tool": "run_cqlf_query"}],
            "expectedOutcome": "Ergebnis"
        }

        orch._emit_control_frame_event("PLAN", plan_data, FakeCopilotEventBus())

        plan_events = [e for e in captured if e.get("event") == "copilot.plan"]
        assert len(plan_events) == 1

        event = plan_events[0]
        assert "plan" in event
        assert "goal" in event["plan"]
        assert "steps" in event["plan"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
