"""Qualitätstests für den Copilot.

KEINE MOCKS - Testet echte LLM-Faehigkeiten:
- Kann das LLM Tools korrekt aufrufen?
- Generiert es valide Control Frames?
- Beantwortet es Korpuslinguistik-Fragen korrekt?
- Versteht es den UI-Context?
"""

import pytest
import asyncio
import httpx
import json
import re
import os

from candyconc.config import APP_CONFIG


def lm_studio_available() -> bool:
    """Prüft ob LM Studio erreichbar ist."""
    endpoint = APP_CONFIG.COPILOT_ENDPOINT
    if not endpoint:
        return False
    try:
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

# Längerer Timeout für grosse Modelle (120B braucht Zeit)
LLM_TIMEOUT = 300  # 5 Minuten


def get_realistic_ui_context(
    query: str = "",
    total_results: int = 0,
    kwic_preview: list = None,
    autonomy_level: int = 5,
    active_tab: str = "kwic",
) -> dict:
    """Erstellt einen realistischen UI-Context wie ihn das Frontend senden würde."""
    context = {
        "session": {
            "autonomy": autonomy_level,
            "locale": "de",
        },
        "view": {
            "activeTab": active_tab,
        },
        "corpus": {
            "corpusId": "demo",
            "subcorpus": {
                "size": {"tokens": 15000000, "docs": 12000},
                "filters": [],
            },
        },
        "query": {
            "mode": "cqlf" if "[" in query else "term",
            "term": query if "[" not in query else None,
            "cqlf": query if "[" in query else None,
            "context": {"left": 5, "right": 5},
        },
        "kwic": {
            "resultSet": {"rows": total_results},
            "selection": {"rowIds": []},
            "preview": kwic_preview or [],
        },
        "history": {
            "recentActions": [],
        },
    }
    return context


# Standard KWIC-Preview für Tests
SAMPLE_KWIC_PREVIEW = [
    {
        "rowId": "row-0",
        "left": "Die Diskussion über",
        "match": "Klimawandel",
        "right": "ist wichtig für die Zukunft",
        "docId": "news_001",
    },
    {
        "rowId": "row-1",
        "left": "Experten warnen vor dem",
        "match": "Klimawandel",
        "right": "und seinen Folgen",
        "docId": "wiki_042",
    },
    {
        "rowId": "row-2",
        "left": "Der menschengemachte",
        "match": "Klimawandel",
        "right": "verändert unsere Welt",
        "docId": "news_123",
    },
]


class TestUIContextUnderstanding:
    """Testet ob das LLM den UI-Context versteht."""

    def test_llm_uses_visible_kwic_for_analysis(self):
        """LLM sollte die sichtbaren KWIC-Zeilen für Analysen nutzen."""
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
        from candyconc.candyconc_copilot.session_manager import SessionManager
        from candyconc.candyconc_copilot.dispatcher import dispatch
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        ui_context = get_realistic_ui_context(
            query="Klimawandel",
            total_results=4523,
            kwic_preview=SAMPLE_KWIC_PREVIEW,
            autonomy_level=7,
        )

        async def _run():
            session = SessionManager()
            tools = get_tools()

            orch = ReActOrchestrator(
                tools=tools,
                call_llm=call_llm_async,
                dispatch=dispatch,
                session=session,
                ui_context=ui_context,
            )

            # Frage die sich auf sichtbare Daten bezieht
            return await orch.run_async(
                "Was faellt dir an den Suchergebnissen auf?"
            )

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        response = asyncio.run(_run())

        print(f"\nAntwort: {response[:600]}...")

        # Antwort sollte auf die Daten eingehen
        assert len(response) > 50, "Antwort zu kurz"

        # Sollte irgendwas über die Ergebnisse sagen
        relevant_terms = [
            "klimawandel", "treffer", "ergebnis", "kontext",
            "experten", "zukunft", "folgen", "menschengemacht"
        ]
        has_relevant = any(term in response.lower() for term in relevant_terms)
        assert has_relevant, f"Antwort bezieht sich nicht auf die Daten: {response[:200]}"

    def test_llm_understands_analysiere_das_with_context(self):
        """'Analysiere das' sollte mit UI-Context funktionieren."""
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
        from candyconc.candyconc_copilot.session_manager import SessionManager
        from candyconc.candyconc_copilot.dispatcher import dispatch
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        ui_context = get_realistic_ui_context(
            query="[lemma=\"gehen\"]",
            total_results=8234,
            kwic_preview=[
                {"rowId": "row-0", "left": "er wollte nicht", "match": "gehen", "right": "aber musste", "docId": "d1"},
                {"rowId": "row-1", "left": "sie ließ ihn", "match": "gehen", "right": "ohne Widerspruch", "docId": "d2"},
                {"rowId": "row-2", "left": "wir werden", "match": "gehen", "right": "wenn es Zeit ist", "docId": "d3"},
            ],
            autonomy_level=5,
        )

        async def _run():
            session = SessionManager()
            tools = get_tools()

            orch = ReActOrchestrator(
                tools=tools,
                call_llm=call_llm_async,
                dispatch=dispatch,
                session=session,
                ui_context=ui_context,
            )

            return await orch.run_async("Analysiere das.")

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        response = asyncio.run(_run())

        print(f"\nAntwort auf 'Analysiere das': {response[:600]}...")

        # Mit richtigem Context sollte es verstehen dass 'das' = aktuelle Query
        assert len(response) > 100, "Antwort zu kurz"

        # Sollte nicht nach Klaerung fragen wenn Context klar ist
        # (aber CLARIFY Frame ist auch akzeptabel wenn Autonomie niedrig)
        confused_indicators = ["was genau", "was soll", "was moechten"]
        is_confused = all(ind in response.lower() for ind in confused_indicators)
        assert not is_confused, "LLM sollte 'das' aus dem Context verstehen"


class TestCorpusLinguisticsKnowledge:
    """Testet das Fachwissen des LLM zu Korpuslinguistik."""

    def test_llm_explains_cqp_syntax(self):
        """LLM sollte CQLF-Syntax korrekt erklären können."""
        from candyconc.candyconc_copilot import chat

        async def _run():
            messages = [
                {"role": "user", "content": "Erkläre die CQLF-Syntax für eine Suche nach Adjektiven gefolgt von Nomen."},
            ]
            return await chat(messages)

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        result = asyncio.run(_run())

        content = result["content"]
        print(f"\nAntwort: {content[:800]}...")

        # Antwort sollte CQLF-Elemente enthalten
        cqp_indicators = ["pos=", "ADJ", "NN", "["]

        found = [ind for ind in cqp_indicators if ind.lower() in content.lower()]
        print(f"Gefundene CQLF-Indikatoren: {found}")

        # Mindestens 2 CQLF-relevante Elemente sollten erklärt werden
        assert len(found) >= 2, f"Zu wenig CQLF-Wissen: nur {found}"

    def test_llm_knows_collocation_metrics(self):
        """LLM sollte Kollokations-Metriken kennen."""
        from candyconc.candyconc_copilot import chat

        async def _run():
            messages = [
                {"role": "user", "content": "Was ist der Unterschied zwischen t-score und MI bei Kollokationen?"},
            ]
            return await chat(messages)

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        result = asyncio.run(_run())

        content = result["content"]
        print(f"\nAntwort: {content[:800]}...")

        # Sollte beide Metriken erwähnen (verschiedene Schreibweisen beruecksichtigen)
        # t-score kann als t-score, t‑score (en-dash), t_score, tscore geschrieben sein
        content_normalized = content.lower().replace("‑", "-").replace("–", "-")
        has_tscore = "t-score" in content_normalized or "t score" in content_normalized or "tscore" in content_normalized
        has_mi = "mi" in content.lower() or "mutual information" in content.lower()

        assert has_tscore, f"Erwähnt t-score nicht in: {content[:300]}"
        assert has_mi, f"Erwähnt MI nicht in: {content[:300]}"


class TestResponseQuality:
    """Testet die Qualität der LLM-Antworten."""

    def test_response_is_in_german(self):
        """Antworten sollten auf Deutsch sein."""
        from candyconc.candyconc_copilot import chat

        async def _run():
            messages = [
                {"role": "user", "content": "Erkläre mir Kollokationen."},
            ]
            return await chat(messages)

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        result = asyncio.run(_run())

        content = result["content"]
        print(f"\nAntwort: {content[:500]}...")

        # Deutsche Wörter
        german_indicators = [
            "ist", "sind", "eine", "der", "die", "das", "und", "oder",
            "werden", "kann", "beispiel", "wörter", "text"
        ]

        german_count = sum(1 for ind in german_indicators if ind in content.lower())
        print(f"Deutsche Wörter gefunden: {german_count}")

        assert german_count >= 5, f"Antwort nicht auf Deutsch: nur {german_count} Indikatoren"

    def test_response_contains_substance(self):
        """Antworten sollten substantiell sein."""
        from candyconc.candyconc_copilot import chat

        async def _run():
            messages = [
                {"role": "user", "content": "Was ist der Unterschied zwischen Type und Token?"},
            ]
            return await chat(messages)

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        result = asyncio.run(_run())

        content = result["content"]
        print(f"\nAntwort: {content[:600]}...")

        # Keine Fehlermeldungen
        error_indicators = ["error", "exception", "traceback"]
        has_error = any(ind in content.lower() for ind in error_indicators)
        assert not has_error, f"Antwort enthält Fehler"

        # Substantielle Länge
        assert len(content) > 100, f"Antwort zu kurz: {len(content)} Zeichen"

        # Sollte Type und Token erwähnen
        has_type = "type" in content.lower() or "typ" in content.lower()
        has_token = "token" in content.lower()
        assert has_type and has_token, "Erwähnt Type/Token nicht"


class TestMultiTurnConversation:
    """Testet Konversationen über mehrere Nachrichten."""

    def test_llm_remembers_previous_context(self):
        """LLM sollte vorherige Nachrichten beruecksichtigen."""
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
        from candyconc.candyconc_copilot.session_manager import SessionManager
        from candyconc.candyconc_copilot.dispatcher import dispatch
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        ui_context = get_realistic_ui_context(autonomy_level=7)

        async def _run():
            session = SessionManager()
            tools = get_tools()

            orch = ReActOrchestrator(
                tools=tools,
                call_llm=call_llm_async,
                dispatch=dispatch,
                session=session,
                ui_context=ui_context,
            )

            # Erste Nachricht
            r1 = await orch.run_async("Ich interessiere mich für das Wort 'Nachhaltigkeit'.")

            # Folgenachricht
            r2 = await orch.run_async("Welche Kollokationen würden mich da interessieren?")

            return r1, r2, session.get_history()

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        r1, r2, history = asyncio.run(_run())

        print(f"\nAntwort 1: {r1[:300]}...")
        print(f"\nAntwort 2: {r2[:300]}...")

        # Zweite Antwort sollte auf 'Nachhaltigkeit' Bezug nehmen
        # (auch ohne dass es nochmal explizit erwähnt wird)
        assert len(r2) > 50, "Zweite Antwort zu kurz"

        # Entweder erwähnt Nachhaltigkeit direkt oder gibt sinnvolle Kollokations-Tipps
        sustainability_mentioned = "nachhaltigkeit" in r2.lower() or "nachhaltig" in r2.lower()
        collocation_tips = any(
            word in r2.lower()
            for word in ["kollokation", "umwelt", "entwicklung", "ressource", "wirtschaft"]
        )
        assert sustainability_mentioned or collocation_tips, \
            "Zweite Antwort ignoriert den Kontext aus Nachricht 1"


class TestControlFrameBehavior:
    """Testet Control Frame Verhalten basierend auf Autonomie."""

    def test_low_autonomy_gives_response(self):
        """Bei niedriger Autonomie sollte LLM trotzdem antworten."""
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
        from candyconc.candyconc_copilot.session_manager import SessionManager
        from candyconc.candyconc_copilot.dispatcher import dispatch
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools
        from candyconc.candyconc_copilot.prompts import extract_all_control_frames

        ui_context = get_realistic_ui_context(
            query="Politik",
            total_results=1000,
            autonomy_level=2,  # Niedrig
        )

        async def _run():
            session = SessionManager()
            tools = get_tools()

            orch = ReActOrchestrator(
                tools=tools,
                call_llm=call_llm_async,
                dispatch=dispatch,
                session=session,
                ui_context=ui_context,
            )

            response = await orch.run_async("Zeige mir die Kollokationen.")
            return response, session.get_history()

        os.environ["COPILOT_TIMEOUT"] = str(LLM_TIMEOUT)
        response, history = asyncio.run(_run())

        print(f"\nAntwort bei Autonomie 2: {response[:600] if response else 'LEER'}...")

        # Prüfe ob eine Antwort kam (Control Frames werden intern verarbeitet)
        all_content = " ".join(m.get("content", "") for m in history if m.get("role") == "assistant")

        frames = extract_all_control_frames(all_content)
        frame_types = [f[0] for f in frames]
        print(f"Control Frames in History: {frame_types}")
        print(f"Gesamte Assistant Content Länge: {len(all_content)}")

        # Das LLM sollte entweder:
        # 1. Control Frames generiert haben (die werden verarbeitet und pausieren)
        # 2. Oder eine Antwort gegeben haben
        # 3. Oder Tool Calls gemacht haben (sichtbar in History)
        has_any_response = len(all_content) > 0 or len(frames) > 0

        # Prüfe auch ob Tool Calls in der History sind
        tool_calls_in_history = any(
            m.get("tool_calls") for m in history if m.get("role") == "assistant"
        )

        print(f"Tool Calls in History: {tool_calls_in_history}")

        assert has_any_response or tool_calls_in_history, \
            "LLM sollte irgendeine Form von Antwort geben"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-k", "", "-s"])
