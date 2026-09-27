"""End-to-End integration tests for the Copilot.

KEINE MOCKS - Echte LLM-Aufrufe, echte Tools.
Tests werden übersprungen wenn LM Studio nicht läuft.
"""

import pytest
import asyncio
import httpx
import os

from candyconc.config import APP_CONFIG


def lm_studio_available() -> bool:
    """Prüft ob LM Studio erreichbar ist."""
    endpoint = APP_CONFIG.COPILOT_ENDPOINT
    if not endpoint:
        return False
    try:
        # Prüfe /v1/models Endpoint
        base = endpoint.rsplit("/v1/", 1)[0] + "/v1/models"
        resp = httpx.get(base, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CANDYCONC_RUN_LM_INTEGRATION") != "1",
        reason="Set CANDYCONC_RUN_LM_INTEGRATION=1 to run live LLM integration tests",
    ),
]


@pytest.fixture(autouse=True)
def _require_lm_studio_runtime():
    if not lm_studio_available():
        pytest.skip("LM Studio nicht erreichbar")


class TestRealLLMConnection:
    """Teste echte LLM-Verbindung."""

    def test_call_llm_async_returns_response(self):
        """Echter LLM-Aufruf gibt Antwort zurück."""
        from candyconc.services.llm_client import call_llm_async

        async def _run():
            messages = [{"role": "user", "content": "Antworte nur mit 'OK'."}]
            return await call_llm_async(messages, tools=[])

        result = asyncio.run(_run())

        assert "choices" in result
        assert len(result["choices"]) > 0
        assert "message" in result["choices"][0]
        content = result["choices"][0]["message"].get("content", "")
        assert len(content) > 0
        print(f"\nLLM Antwort: {content[:100]}...")

    def test_call_llm_async_with_tools(self):
        """LLM kann Tool-Calls generieren."""
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        async def _run():
            tools = get_tools()
            messages = [
                {"role": "system", "content": "Du bist ein Korpuslinguistik-Assistent."},
                {"role": "user", "content": "Führe eine CQLF-Suche nach 'Politik' aus."},
            ]
            return await call_llm_async(messages, tools)

        result = asyncio.run(_run())

        assert "choices" in result
        choice = result["choices"][0]
        # LLM sollte entweder Content oder Tool-Call zurückgeben
        message = choice.get("message", {})
        has_content = bool(message.get("content"))
        has_tool_calls = bool(message.get("tool_calls"))
        print(f"\nHat Content: {has_content}, Hat Tool-Calls: {has_tool_calls}")
        if has_content:
            print(f"Content: {message['content'][:200]}...")
        if has_tool_calls:
            print(f"Tool-Calls: {message['tool_calls']}")
        assert has_content or has_tool_calls


class TestRealOrchestrator:
    """Teste echten ReAct-Orchestrator mit LLM."""

    def test_orchestrator_simple_question(self):
        """Orchestrator beantwortet einfache Frage."""
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
        from candyconc.candyconc_copilot.session_manager import SessionManager
        from candyconc.candyconc_copilot.dispatcher import dispatch
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        async def _run():
            session = SessionManager()
            tools = get_tools()

            orch = ReActOrchestrator(
                tools=tools,
                call_llm=call_llm_async,
                dispatch=dispatch,
                session=session,
            )

            # Einfache Frage ohne Tool-Nutzung
            return await orch.run_async("Was ist CQLF? Antworte kurz in einem Satz.")

        response = asyncio.run(_run())

        assert response is not None
        assert len(response) > 0
        assert isinstance(response, str)
        print(f"\nOrchestrator Antwort: {response[:300]}...")

    def test_orchestrator_with_control_frame(self):
        """Orchestrator kann Control Frames parsen."""
        from candyconc.candyconc_copilot.prompts import parse_control_frame

        # Simuliere was passiert wenn das LLM einen Control Frame als Text
        # zurückgibt (die build_*-Helfer wurden gelöscht — Frames entstehen
        # im Betrieb ausschliesslich als LLM-Text).
        frame = (
            '<<<CC:ACTION {"actionType": "run_cqlf_query", '
            '"summary": "Suche nach Politik", '
            '"payload": {"query": "Politik", "ctx": 5}, '
            '"impact": "Durchsucht Korpus", '
            '"reversible": true, "requiresApproval": true}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        frame_type, data = result
        assert frame_type == "ACTION"
        assert data["actionType"] == "run_cqlf_query"


class TestRealSessionManager:
    """Teste echten SessionManager."""

    def test_session_creates_unique_ids(self):
        """Jede Session bekommt eindeutige ID."""
        from candyconc.candyconc_copilot.session_manager import SessionManager

        s1 = SessionManager()
        s2 = SessionManager()

        assert s1.session_id != s2.session_id

    def test_session_maintains_history(self):
        """Session speichert Konversationsverlauf."""
        from candyconc.candyconc_copilot.session_manager import SessionManager

        session = SessionManager()
        session.append({"role": "user", "content": "Hallo"})
        session.append({"role": "assistant", "content": "Hi!"})

        history = session.get_history()
        assert len(history) >= 2

        # Letzte Nachrichten prüfen
        user_msgs = [m for m in history if m["role"] == "user"]
        asst_msgs = [m for m in history if m["role"] == "assistant"]

        assert any("Hallo" in m["content"] for m in user_msgs)
        assert any("Hi!" in m["content"] for m in asst_msgs)


class TestRealDispatcher:
    """Teste echten Tool-Dispatcher."""

    def test_dispatch_validates_arguments(self):
        """Dispatcher validiert Tool-Argumente."""
        from candyconc.candyconc_copilot.dispatcher import dispatch

        async def _run():
            # Ungültiges Tool-Schema sollte ValidationError werfen
            invalid_call = {
                "function": {
                    "name": "run_cqlf_query",
                    "arguments": '{"invalid_key": "value"}',
                }
            }
            return await dispatch(invalid_call)

        with pytest.raises((ValueError, KeyError)):
            asyncio.run(_run())


class TestRealChat:
    """Teste echte Chat-Funktion."""

    def test_chat_returns_assistant_response(self):
        """Chat gibt Assistenten-Antwort zurück."""
        from candyconc.candyconc_copilot import chat

        async def _run():
            messages = [
                {"role": "user", "content": "Sage nur 'Test bestanden'."},
            ]
            return await chat(messages)

        result = asyncio.run(_run())

        assert result["role"] == "assistant"
        assert len(result["content"]) > 0
        print(f"\nChat Antwort: {result['content'][:100]}...")


class TestOrchestratorStateTransitions:
    """Teste Orchestrator-Zustandsübergaenge mit echtem LLM."""

    def test_orchestrator_state_after_init(self):
        """Orchestrator startet in WAITING_LLM."""
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator, State
        from candyconc.candyconc_copilot.session_manager import SessionManager
        from candyconc.candyconc_copilot.dispatcher import dispatch
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        session = SessionManager()
        tools = get_tools()

        orch = ReActOrchestrator(
            tools=tools,
            call_llm=call_llm_async,
            dispatch=dispatch,
            session=session,
        )

        assert orch.state == State.WAITING_LLM

    def test_autonomy_level_affects_approval(self):
        """Autonomy Level beeinflusst Approval-Anforderung."""
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
        from candyconc.candyconc_copilot.session_manager import SessionManager
        from candyconc.candyconc_copilot.dispatcher import dispatch
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        session = SessionManager()
        tools = get_tools()

        # Niedriges Autonomy-Level
        orch_low = ReActOrchestrator(
            tools=tools,
            call_llm=call_llm_async,
            dispatch=dispatch,
            session=session,
            ui_context={"autonomy_level": 1},
        )
        assert orch_low._should_require_approval({"reversible": True}) is True

        # Hohes Autonomy-Level
        orch_high = ReActOrchestrator(
            tools=tools,
            call_llm=call_llm_async,
            dispatch=dispatch,
            session=SessionManager(),
            ui_context={"autonomy_level": 8},
        )
        assert orch_high._should_require_approval({"reversible": True}) is False

        # Max Autonomy-Level
        orch_max = ReActOrchestrator(
            tools=tools,
            call_llm=call_llm_async,
            dispatch=dispatch,
            session=SessionManager(),
            ui_context={"autonomy_level": 10},
        )
        assert orch_max._should_require_approval({"reversible": False}) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-k", "", "-s"])
