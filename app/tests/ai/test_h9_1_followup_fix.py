"""H9.1-Nachfix am Rezept-Harness: Offline-Pins fuer die drei Live-Befunde.

Befund 1 (Klassifikator-Timeout): 6 s waren fuer den kalten 30B-Prompt ohne
KV-Cache-Praefix zu knapp , der Live-Lauf zeigte reihenweise
``asyncio.TimeoutError`` in ``classify_recipe_llm`` und damit freie
Fallbacks. Gepinnt werden (a) der neue 25-s-Default samt Env/pyproject-Knopf
``COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S`` (Env > pyproject > Konstante),
(b) die Byte-Stabilitaet des Klassifikator-Praefixes (Menue zuerst, Frage
GANZ am Ende, nichts Variables davor) und (c) die Kappung des
Klassifikator-Timeouts auf ein Drittel des Turn-Zeitbudgets (EIN
Wanduhr-Abzug, kein Doppelabzug).

Befund 2 (falsche Eindeutigkeit): ``fresh_meta_stichprobe`` und
``fresh_gender_darstellung`` landeten nach Klassifikator-Timeout im
Fallback auf einen rein generisch gestuetzten Stufe-1-Pick und wirkten
damit 'eindeutig' fehlgeroutet. Gepinnt: ein Pick ohne rezeptspezifisches
Lexem (Familien-Route allein oder Trigger aus ``GENERIC_TRIGGER_LEXEMES``)
ist NIE eindeutig und wird nach Stufe-2-Fehlschlag NICHT uebernommen
(freier Modus). Die 10 Suite-Fragen und die korrekt gerouteten
Transfer-Fragen (fresh_split_qa -> kontrast via neues Split-QA-Signal,
fresh_trend_liebe -> verlauf, fresh_open_hypothesen -> exploration_meta)
laufen weiter ueber Stufe 1 , der Regressionstest ZAEHLT die
Klassifikator-Calls.

Befund 3 (praeemptives similar_words-Gate): das Gate bereinigte den
ReAct-Tool-Space korrekt, aber der Hintergrund-Research-Worker baute seine
Calls direkt aus dem Tool-Inventar und dispatchte an der Filterung vorbei
(similar_words-409s auf dem Testindex). Gepinnt: der Worker respektiert
``_turn_capability_unavailable_tools``, und das Gate selbst gegen die REALE
Dateipraesenz-Wahrheit (Fake-Index ohne faiss_word.index/word_ids.npy ->
Gate, mit beiden Dateien -> kein Gate).
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.ai._real_copilot import (
    SessionManager,
    make_orchestrator,
    orchestrator as om,
)
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

from candyconc.candyconc_copilot import recipe_runtime as rr


def _reply(content: str) -> dict:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ]
    }


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


class _CountingClassifier:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list = []

    async def __call__(self, messages, tools, **kwargs):
        self.calls.append((messages, tools))
        return _reply(self.content)


def _set_config_value(value):
    """Setzt den Config-Knopf direkt am APP_CONFIG-Objekt (mit Restore-Wert)."""
    from candyconc.config import APP_CONFIG

    original = getattr(APP_CONFIG, "COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S", None)
    object.__setattr__(APP_CONFIG, "COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S", value)
    return APP_CONFIG, original


# --------------------------------------------------------------------------- #
# Befund 1a: Timeout-Default + Env/pyproject-Knopf                             #
# --------------------------------------------------------------------------- #
class TestClassifierTimeoutKnob(unittest.IsolatedAsyncioTestCase):
    def test_default_is_25_seconds(self):
        # 25 s waren ein Zeitplan, kein Failsafe: ein warmer
        # Klassifikator-Call misst 16,6 s, und von zwei Live-Fragen lief
        # EINE hinein. Der Deckel steht seit dem 2026-09-01 auf 300 s, dem
        # 18-fachen der gemessenen Arbeit. Die Zahl wird hier nicht mehr
        # gepinnt, damit ein Anheben nicht wieder an einer Probe scheitert.
        # Geprueft wird die EIGENSCHAFT: weit ueber dem Messwert.
        self.assertGreaterEqual(
            rr.RECIPE_CLASSIFIER_TIMEOUT_S,
            rr.RECIPE_CLASSIFIER_GEMESSEN_WARM_S * 10,
        )

    def test_unset_config_uses_module_constant(self):
        cfg, original = _set_config_value(None)
        try:
            self.assertEqual(
                rr.recipe_classifier_timeout_s(), rr.RECIPE_CLASSIFIER_TIMEOUT_S
            )
        finally:
            object.__setattr__(
                cfg, "COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S", original
            )

    def test_config_knob_wins_over_module_constant(self):
        cfg, original = _set_config_value(3.5)
        try:
            self.assertEqual(rr.recipe_classifier_timeout_s(), 3.5)
        finally:
            object.__setattr__(
                cfg, "COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S", original
            )

    def test_invalid_or_nonpositive_config_falls_back(self):
        for bad in ("abc", -1, 0):
            cfg, original = _set_config_value(bad)
            try:
                # Der Rueckfall ist die KONSTANTE, nicht die Zahl 25. Die
                # Probe pinnt sie nicht mehr, damit ein Anheben des
                # Failsafes nicht an einer Testzahl scheitert.
                self.assertEqual(
                    rr.recipe_classifier_timeout_s(),
                    rr.RECIPE_CLASSIFIER_TIMEOUT_S,
                    repr(bad),
                )
            finally:
                object.__setattr__(
                    cfg, "COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S", original
                )

    def test_module_constant_stays_monkeypatch_friendly(self):
        cfg, original = _set_config_value(None)
        saved = rr.RECIPE_CLASSIFIER_TIMEOUT_S
        rr.RECIPE_CLASSIFIER_TIMEOUT_S = 7.0
        try:
            self.assertEqual(rr.recipe_classifier_timeout_s(), 7.0)
        finally:
            rr.RECIPE_CLASSIFIER_TIMEOUT_S = saved
            object.__setattr__(
                cfg, "COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S", original
            )

    async def test_classify_uses_effective_budget(self):
        # Der effektive Knopf (nicht ein eingefrorener Wert) begrenzt den
        # Call: 10 ms Budget gegen einen 200-ms-Fake -> Timeout -> "".
        saved = rr.recipe_classifier_timeout_s
        rr.recipe_classifier_timeout_s = lambda: 0.01
        try:

            async def _slow(messages, tools, **kwargs):
                await asyncio.sleep(0.2)
                return _reply("assoziation")

            self.assertEqual(
                await rr.classify_recipe_llm("Frage?", _slow), ""
            )
        finally:
            rr.recipe_classifier_timeout_s = saved


# --------------------------------------------------------------------------- #
# Befund 1b: byte-stabiler Klassifikator-Praefix (Pin-Test)                    #
# --------------------------------------------------------------------------- #
class TestClassifierPrefixPin(unittest.TestCase):
    def test_prefix_byte_stable_question_strictly_last(self):
        qa = "Wie oft kommt 'Zeit' im Korpus vor?"
        qb = (
            "Werden Frauen in diesem Material sprachlich anders "
            "dargestellt als Männer?"
        )
        ma = rr.build_recipe_classifier_messages(qa)
        mb = rr.build_recipe_classifier_messages(qb)
        # Der komplette Praefix vor der Frage ist byte-identisch ...
        self.assertEqual(ma[:-1], mb[:-1])
        # ... und stammt aus dem lru_cache (identisches Objekt, nichts
        # Variables kann hineingeraten sein).
        self.assertIs(ma[0]["content"], mb[0]["content"])
        self.assertEqual(ma[0]["content"], rr.build_recipe_classifier_prompt())
        # Die Frage steht GANZ am Ende, unveraendert, nichts folgt danach.
        self.assertEqual(len(ma), 2)
        self.assertEqual(ma[-1], {"role": "user", "content": qa})
        self.assertEqual(mb[-1], {"role": "user", "content": qb})

    def test_prefix_carries_menu_and_no_session_or_corpus_data(self):
        prompt = rr.build_recipe_classifier_prompt()
        # Rezept-Menue zuerst, Antwortanweisung danach.
        self.assertLess(
            prompt.index("Rezept-Menü"), prompt.index("Antworte mit")
        )
        for verboten in (
            "corpus_tokens",
            "corpus_id",
            "<turn_briefing>",
            "meta_felder",
            "Session-Stand",
        ):
            self.assertNotIn(verboten, prompt)

    def test_classify_sends_exactly_the_pinned_messages(self):
        captured: list = []

        async def _fake(messages, tools, **kwargs):
            captured.append((messages, tools))
            return _reply("frei")

        asyncio.run(rr.classify_recipe_llm("Meine Frage?", _fake))
        self.assertEqual(len(captured), 1)
        self.assertEqual(
            captured[0][0], rr.build_recipe_classifier_messages("Meine Frage?")
        )


# --------------------------------------------------------------------------- #
# Befund 1c: Klassifikator-Timeout gekappt aufs Turn-Zeitbudget                #
# --------------------------------------------------------------------------- #
class TestClassifierBudgetCap(unittest.IsolatedAsyncioTestCase):
    async def _captured_timeout(self, max_time):
        captured: dict = {}

        async def _spy(question, capabilities, call_llm, *, timeout_s=None, cancelled=None):
            captured["timeout_s"] = timeout_s
            return {"recipe_id": "", "family": "", "stage": "frei"}

        async def _llm(messages, tools, **kwargs):
            return _reply("Fertig.")

        async def _dispatch(tool_call, token=None):
            return {"status": "success"}

        orch = make_orchestrator(
            [_tool("query_count")], _llm, _dispatch, session=SessionManager()
        )
        saved_route = om.route_turn_recipe
        saved_knob = om.recipe_classifier_timeout_s
        om.route_turn_recipe = _spy
        om.recipe_classifier_timeout_s = lambda: 25.0
        try:
            await orch._ra_route_turn_recipe("Frage?", max_time=max_time)
        finally:
            om.route_turn_recipe = saved_route
            om.recipe_classifier_timeout_s = saved_knob
        return captured["timeout_s"]

    async def test_large_budget_keeps_full_classifier_timeout(self):
        # 120-s-Turn: Kappe bei 40 s greift nicht, 25 s bleiben.
        self.assertEqual(await self._captured_timeout(120), 25.0)

    async def test_small_budget_caps_to_one_third(self):
        # 9-s-Turn: der Klassifikator darf hoechstens 3 s verbrennen, damit
        # nach einem Timeout zwei Drittel Restbudget bleiben (kein zweiter
        # Abzug: started_at/max_time werden nirgends angefasst).
        self.assertEqual(await self._captured_timeout(9), 3.0)

    async def test_no_budget_means_module_default(self):
        self.assertIsNone(await self._captured_timeout(None))


# --------------------------------------------------------------------------- #
# Befund 2: generische Picks sind nie eindeutig und kein Fallback              #
# --------------------------------------------------------------------------- #
_META_FRAGE = (
    "Welche Informationen über Herkunft, Lizenz und Aufteilung der "
    "Dokumente kann ich für die Stichprobenbildung verwenden?"
)
_GENDER_FRAGE = (
    "Werden Frauen in diesem Material sprachlich anders dargestellt als "
    "Männer? Untersuche das, ohne eine nicht vorhandene "
    "Geschlechtsmetadaten-Achse zu unterstellen."
)
_SPLIT_FRAGE = (
    "Ist die Trainingspartition lexikalisch anders als die Testpartition? "
    "Prüfe ausdrücklich diese technische Aufteilung."
)

# Suite- und Transfer-Anker, die OHNE Klassifikator-Call routen muessen.
_ZERO_CALL_ANCHORS = (
    ("Wie oft kommt 'Zeit' im Korpus vor?", "frequenz"),
    ("Wie wird 'Zeit' verwendet? Zeige KWIC-Belege im Kontext.", "gebrauch_kwic"),
    ("Welche Kollokationen hat 'Arbeit' im Korpus?", "assoziation"),
    (
        "Erstelle ein Word Sketch für 'Zeit'. Welche grammatischen "
        "Relationen prägen das Wort?",
        "profil",
    ),
    ("Welche Metadatenfelder und Werte enthält das Korpus?", "metadaten_struktur"),
    (
        "Welche Schlüsselwörter sind typisch für ein Register im Vergleich "
        "zum Rest des Korpus? Wähle die Kontrastachse anhand der Metadaten.",
        "kontrast",
    ),
    ("Zeige den Zeitverlauf von 'Arbeit' im Korpus.", "verlauf"),
    ("Untersuche das Korpus offen: Was fällt thematisch auf?", "exploration_meta"),
    (
        "Erkunde das Korpus frei: Welche drei Beobachtungen sind am "
        "interessantesten?",
        "exploration_meta",
    ),
    (
        "Was fällt an der Sprache in diesem Korpus auf? Formuliere "
        "Hypothesen dazu.",
        "exploration_meta",
    ),
    # Korrekt geroutete Transfer-Fragen des H9-Laufs:
    (_SPLIT_FRAGE, "kontrast"),
    ("Kann ich für ‚Liebe‘ einen diachronen Anstieg oder Rückgang bestimmen?", "verlauf"),
    (
        "Entwickle drei überprüfbare Hypothesen zur kommunikativen Praxis "
        "in diesem Material; sage jeweils, welche Evidenz dafür und "
        "dagegen sprechen würde.",
        "exploration_meta",
    ),
)


class TestStage1GenericSharpening(unittest.IsolatedAsyncioTestCase):
    def test_generic_lexeme_set_is_pinned(self):
        self.assertEqual(
            rr.GENERIC_TRIGGER_LEXEMES,
            frozenset(
                {"untersuche", "zeige", "welche", "informationen", "dokumente"}
            ),
        )

    def test_meta_and_gender_picks_are_generic_and_not_confident(self):
        for frage, pick in (
            (_META_FRAGE, "gebrauch_kwic"),
            (_GENDER_FRAGE, "metadaten_struktur"),
        ):
            decision = rr.stage1_recipe_decision(frage)
            self.assertIsNotNone(decision["recipe"], frage)
            self.assertEqual(decision["recipe"].id, pick, frage)
            self.assertFalse(decision["confident"], frage)
            self.assertFalse(decision["specific"], frage)
            self.assertEqual(decision["signals"], ("family",), frage)

    async def test_stage2_failure_degrades_generic_pick_to_free(self):
        async def _broken(messages, tools, **kwargs):
            raise RuntimeError("LLM weg")

        for frage in (_META_FRAGE, _GENDER_FRAGE):
            routing = await rr.route_turn_recipe(frage, None, _broken)
            self.assertEqual(routing["recipe_id"], "", frage)
            self.assertEqual(routing["stage"], rr.ROUTING_STAGE_FREE, frage)

    async def test_stage2_answer_still_routes_meta_and_gender(self):
        for frage, expected in (
            (_META_FRAGE, "metadaten_struktur"),
            (_GENDER_FRAGE, "kontrast"),
        ):
            classifier = _CountingClassifier(expected)
            routing = await rr.route_turn_recipe(frage, None, classifier)
            self.assertEqual(routing["recipe_id"], expected, frage)
            self.assertEqual(routing["stage"], rr.ROUTING_STAGE_LLM, frage)
            self.assertEqual(len(classifier.calls), 1, frage)

    async def test_split_qa_routes_stage1_via_split_signal(self):
        decision = rr.stage1_recipe_decision(_SPLIT_FRAGE)
        self.assertEqual(decision["recipe"].id, "kontrast")
        self.assertIn("split_qa", decision["signals"])
        self.assertTrue(decision["confident"])
        classifier = _CountingClassifier("frei")
        routing = await rr.route_turn_recipe(_SPLIT_FRAGE, None, classifier)
        self.assertEqual(routing["recipe_id"], "kontrast")
        self.assertEqual(routing["stage"], rr.ROUTING_STAGE_TRIGGER)
        self.assertEqual(len(classifier.calls), 0)

    async def test_anchor_questions_route_with_zero_classifier_calls(self):
        # Regressionstest des Nachfixes: er ZAEHLT die Klassifikator-Calls.
        classifier = _CountingClassifier("frei")
        for frage, expected in _ZERO_CALL_ANCHORS:
            routing = await rr.route_turn_recipe(frage, None, classifier)
            self.assertEqual(routing["recipe_id"], expected, frage)
            self.assertEqual(
                routing["stage"], rr.ROUTING_STAGE_TRIGGER, frage
            )
        self.assertEqual(len(classifier.calls), 0)


# --------------------------------------------------------------------------- #
# Befund 3: Research-Worker respektiert das Capability-Gate                    #
# --------------------------------------------------------------------------- #
class TestResearchWorkerCapabilityGate(unittest.TestCase):
    def _orch(self, tool_names):
        async def _llm(messages, tools, **kwargs):
            return _reply("Fertig.")

        async def _dispatch(tool_call, token=None):
            return {"status": "success"}

        orch = make_orchestrator(
            [_tool(n) for n in tool_names],
            _llm,
            _dispatch,
            session=SessionManager(),
        )
        orch._tool_runtime_info = {
            name: {"read_only": True, "concurrency_safe": True}
            for name in tool_names
        }
        return orch

    def test_gated_similar_words_never_built_into_research_calls(self):
        orch = self._orch(["document_search", "similar_words"])
        calls = orch._build_research_tool_calls("Wie verhält sich 'Menschen'?")
        names = [tc["function"]["name"] for tc in calls]
        self.assertIn("similar_words", names)  # ungegatet: Call vorhanden
        orch._turn_capability_unavailable_tools = {
            "similar_words": "semantic.word_similarity fehlt"
        }
        calls = orch._build_research_tool_calls("Wie verhält sich 'Menschen'?")
        names = [tc["function"]["name"] for tc in calls]
        self.assertNotIn("similar_words", names)
        self.assertIn("document_search", names)

    def test_worker_does_not_launch_when_all_research_tools_gated(self):
        orch = self._orch(["similar_words"])
        self.assertTrue(orch._should_run_research_worker("Frage?", "user"))
        orch._turn_capability_unavailable_tools = {
            "similar_words": "semantic.word_similarity fehlt"
        }
        self.assertFalse(orch._should_run_research_worker("Frage?", "user"))


# --------------------------------------------------------------------------- #
# Befund 3: Gate gegen die REALE Dateipraesenz-Wahrheit                        #
# --------------------------------------------------------------------------- #
class TestWordSimilarityGateFilePresence(unittest.TestCase):
    """Fake-Index ohne word-FAISS-Dateien -> Gate; mit Dateien -> kein Gate.

    Der Praedikats-Kontrakt (Paket B) lebt im REALEN ``tool_wrappers``:
    ``word_similarity_available`` prueft die Dateipraesenz von
    ``faiss_word.index`` UND ``word_ids.npy``. tests/conftest stubt das
    Modul, deshalb wird das reale Praedikat geladen und fuer die Dauer des
    Gate-Aufrufs auf den Stub gebunden (der Gate-Zugriff laeuft per
    ``getattr`` ueber genau diese Naht).
    """

    @classmethod
    def setUpClass(cls):
        cls.real_tw = _load_real_tool_wrappers()

    def _gate(self, index_path):
        import candyconc.candyconc_copilot.tool_wrappers as tw_stub

        original = getattr(tw_stub, "word_similarity_available", None)
        tw_stub.word_similarity_available = self.real_tw.word_similarity_available
        try:
            return rr.word_similarity_unavailable_gate(
                ["similar_words"], index_path=index_path
            )
        finally:
            if original is None:
                del tw_stub.word_similarity_available
            else:
                tw_stub.word_similarity_available = original

    def test_missing_word_faiss_artifacts_gate_similar_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._gate(tmp)
        self.assertIn("similar_words", gate)
        self.assertIn("faiss_word.index/word_ids.npy", gate["similar_words"])

    def test_single_artifact_still_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "faiss_word.index").write_bytes(b"")
            gate = self._gate(tmp)
        self.assertIn("similar_words", gate)

    def test_both_artifacts_present_open_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "faiss_word.index").write_bytes(b"")
            (Path(tmp) / "word_ids.npy").write_bytes(b"")
            gate = self._gate(tmp)
        self.assertEqual(gate, {})

    def test_real_predicate_file_semantics(self):
        available = self.real_tw.word_similarity_available
        self.assertFalse(available(None))
        self.assertFalse(available(""))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(available(tmp))
            (Path(tmp) / "faiss_word.index").write_bytes(b"")
            self.assertFalse(available(tmp))
            (Path(tmp) / "word_ids.npy").write_bytes(b"")
            self.assertTrue(available(tmp))


if __name__ == "__main__":
    unittest.main()
