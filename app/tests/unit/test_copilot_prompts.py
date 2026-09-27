"""Tests for the Copilot prompts module.

Tests control frame parsing, context building, and system prompt generation.
"""

import pytest

from candyconc.candyconc_copilot.prompts import (
    parse_control_frame,
    extract_all_control_frames,
    remove_control_frames,
    build_context_message,
    get_system_prompt,
    get_system_prompt_with_context,
    compact_runtime_system_prompt,
    CQLF_CAPABILITY_DOC,
    CQLF_SYNTAX_DOC,
    TOOLS_DOC,
    CONTROL_FRAMES_DOC,
    AUTONOMY_LEVELS_DOC,
    SCIENCE_GUIDE,
    EXAMPLE_CONVERSATIONS,
    ERROR_HANDLING_GUIDE,
    AGENT_POLICY,
    NICHT_VERHANDELBAR,
    GLOSSAR,
    ROLE_DOC,
    VERIFIKATION,
    OUTPUT_GUIDE,
)


# ============================================================================
# Control Frame Parser Tests
# ============================================================================

class TestParseControlFrame:
    """Tests for parse_control_frame function."""

    def test_parse_plan_frame(self):
        """Parse a valid PLAN control frame."""
        text = '<<<CC:PLAN {"goal": "Test analysis", "steps": [], "expectedOutcome": "Results"}>>>'
        result = parse_control_frame(text)

        assert result is not None
        frame_type, data = result
        assert frame_type == "PLAN"
        assert data["goal"] == "Test analysis"
        assert data["steps"] == []
        assert data["expectedOutcome"] == "Results"

    def test_parse_clarify_frame(self):
        """Parse a valid CLARIFY control frame."""
        text = '''<<<CC:CLARIFY {
            "question": "Welchen Korpus?",
            "reason": "Auswahl erforderlich",
            "options": [{"id": "a", "label": "Option A"}],
            "timeout": 30
        }>>>'''
        result = parse_control_frame(text)

        assert result is not None
        frame_type, data = result
        assert frame_type == "CLARIFY"
        assert data["question"] == "Welchen Korpus?"
        assert data["timeout"] == 30

    def test_parse_action_frame(self):
        """Parse a valid ACTION control frame."""
        text = '''<<<CC:ACTION {
            "actionType": "run_cqlf_query",
            "summary": "Suche nach Politik",
            "payload": {"query": "[word=\\"Politik\\"]", "ctx": 5},
            "impact": "Durchsucht den Korpus",
            "reversible": true
        }>>>'''
        result = parse_control_frame(text)

        assert result is not None
        frame_type, data = result
        assert frame_type == "ACTION"
        assert data["actionType"] == "run_cqlf_query"
        assert data["reversible"] is True

    def test_parse_no_frame(self):
        """Return None when no control frame is present."""
        text = "This is just regular text without any control frame."
        result = parse_control_frame(text)
        assert result is None

    def test_parse_invalid_json(self):
        """Return None for invalid JSON in control frame."""
        text = '<<<CC:PLAN {invalid json}>>>'
        result = parse_control_frame(text)
        assert result is None

    def test_parse_frame_in_larger_text(self):
        """Extract control frame from surrounding text."""
        text = '''
        Here is some analysis text.

        <<<CC:PLAN {"goal": "Test", "steps": [], "expectedOutcome": "Done"}>>>

        More text follows.
        '''
        result = parse_control_frame(text)

        assert result is not None
        frame_type, data = result
        assert frame_type == "PLAN"
        assert data["goal"] == "Test"


class TestExtractAllControlFrames:
    """Tests for extract_all_control_frames function."""

    def test_extract_multiple_frames(self):
        """Extract multiple control frames from text."""
        text = '''
        <<<CC:PLAN {"goal": "Step 1", "steps": [], "expectedOutcome": "Done"}>>>
        Some text in between.
        <<<CC:ACTION {"actionType": "search", "summary": "test", "payload": {}, "impact": "none"}>>>
        '''
        frames = extract_all_control_frames(text)

        assert len(frames) == 2
        assert frames[0][0] == "PLAN"
        assert frames[1][0] == "ACTION"

    def test_extract_no_frames(self):
        """Return empty list when no frames present."""
        text = "Just regular text."
        frames = extract_all_control_frames(text)
        assert frames == []

    def test_extract_skips_invalid_json(self):
        """Skip frames with invalid JSON but continue parsing."""
        text = '''
        <<<CC:PLAN {invalid}>>>
        <<<CC:ACTION {"actionType": "test", "summary": "ok", "payload": {}, "impact": "none"}>>>
        '''
        frames = extract_all_control_frames(text)

        # Only the valid ACTION frame should be extracted
        assert len(frames) == 1
        assert frames[0][0] == "ACTION"


class TestRemoveControlFrames:
    """Tests for remove_control_frames function."""

    def test_remove_single_frame(self):
        """Remove a single control frame from text."""
        text = 'Before <<<CC:PLAN {"goal": "x", "steps": [], "expectedOutcome": "y"}>>> After'
        result = remove_control_frames(text)
        assert result == "Before  After"

    def test_remove_multiple_frames(self):
        """Remove multiple control frames from text."""
        text = '''Text <<<CC:PLAN {"goal": "a", "steps": [], "expectedOutcome": "b"}>>> middle <<<CC:ACTION {"actionType": "x", "summary": "y", "payload": {}, "impact": "z"}>>> end'''
        result = remove_control_frames(text)
        assert "<<<CC:" not in result
        assert "Text" in result
        assert "middle" in result
        assert "end" in result

    def test_remove_provider_protocol_tail(self):
        text = (
            "Die Analyse ist wegen der fehlenden Gegenstelle nicht möglich."
            "} ] } </s> interner Nachlauf <end> "
            "<assistant<|channel|>final<|message|>{"
        )

        assert remove_control_frames(text) == (
            "Die Analyse ist wegen der fehlenden Gegenstelle nicht möglich."
        )

    @pytest.mark.parametrize(
        "text",
        [
            "VRT-Beleg: <s>Hallo Welt</s> Danach folgt die Analyse.",
            "Das Token <end> ist hier Gegenstand der Erklärung.",
            (
                "Inline-Code: "
                "`<assistant<|channel|>final<|message|>{` bleibt sichtbar."
            ),
            (
                "```text\n"
                "<assistant<|channel|>final<|message|>{\n"
                "```\nDer Codeblock ist der Beleg."
            ),
        ],
    )
    def test_literal_protocol_like_markup_is_preserved(self, text):
        assert remove_control_frames(text) == text

    def test_valid_json_before_a_confirmed_protocol_tail_is_preserved(self):
        text = (
            'Ergebnis: {"rows": [{"word": "Haus"}]} </s> Nachlauf '
            "<assistant<|channel|>final<|message|>{"
        )

        assert remove_control_frames(text) == (
            'Ergebnis: {"rows": [{"word": "Haus"}]}'
        )


# ============================================================================
# Control Frame Literal Roundtrip Tests
# ============================================================================
# The build_* frame helpers were deleted (no runtime consumer — the LLM emits
# frames as text, only the parser side is active). These tests keep the same
# payload coverage with literal frame strings.

class TestParsePlanFrameLiteral:
    """PLAN frame literals parse with full payload fidelity."""

    def test_parse_simple_plan(self):
        frame = (
            '<<<CC:PLAN {"goal": "Analyse der Kollokationen", '
            '"steps": [{"id": 1, "description": "Query ausführen", '
            '"tool": "run_cqlf_query"}], '
            '"expectedOutcome": "Kollokationsliste"}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        _, data = result
        assert data["goal"] == "Analyse der Kollokationen"
        assert len(data["steps"]) == 1

    def test_parse_plan_with_unicode(self):
        frame = (
            '<<<CC:PLAN {"goal": "Überprüfung der Häufigkeit", '
            '"steps": [], "expectedOutcome": "Ergebnisübersicht"}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        _, data = result
        assert "Überprüfung" in data["goal"]


class TestParseClarifyFrameLiteral:
    """CLARIFY frame literals parse with options and defaults."""

    def test_parse_clarify_with_options(self):
        frame = (
            '<<<CC:CLARIFY {"question": "Welches Subkorpus soll analysiert werden?", '
            '"reason": "Mehrere Korpora verfügbar", '
            '"options": [{"id": "news", "label": "Nachrichten"}, '
            '{"id": "wiki", "label": "Wikipedia"}], '
            '"timeout": 45, "defaultOption": "news"}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        _, data = result
        assert data["question"] == "Welches Subkorpus soll analysiert werden?"
        assert len(data["options"]) == 2
        assert data["defaultOption"] == "news"
        assert data["timeout"] == 45


class TestParseActionFrameLiteral:
    """ACTION frame literals parse with nested payload."""

    def test_parse_action_with_payload(self):
        frame = (
            '<<<CC:ACTION {"actionType": "run_cqlf_query", '
            '"summary": "Suche nach \'Politik\'", '
            '"payload": {"query": "[word=\\"Politik\\"]", "ctx": 5}, '
            '"impact": "Durchsucht den gesamten Korpus", '
            '"reversible": true, "requiresApproval": true}>>>'
        )

        result = parse_control_frame(frame)
        assert result is not None
        _, data = result
        assert data["actionType"] == "run_cqlf_query"
        assert data["payload"]["query"] == '[word="Politik"]'
        assert data["requiresApproval"] is True


# ============================================================================
# Context Builder Tests
# ============================================================================

class TestBuildContextMessage:
    """Tests for build_context_message function."""

    def test_simple_context(self):
        """Build context from simple flat format."""
        context = {
            "autonomy_level": 5,
            "current_query": "Politik",
            "total_results": 1234,
            "selected_count": 3,
            "active_tab": "kwic",
            "response_style": "brief_presence_answer",
            "response_contract": "Kurz antworten"
        }

        result = build_context_message(context)

        assert "<ui_context>" in result
        assert "</ui_context>" in result
        assert "autonomy_level: 5" in result
        assert "current_query: Politik" in result
        assert "total_results: 1234" in result
        assert "response_style: brief_presence_answer" in result
        assert "response_contract: Kurz antworten" in result

    def test_snapshot_context(self):
        """Build context from full UIContextSnapshotV1 format."""
        context = {
            "session": {
                "autonomy": 7,
                "locale": "de"
            },
            "view": {
                "activeTab": "collocations"
            },
            "corpus": {
                "corpusId": "test_corpus",
                "subcorpus": {
                    "filters": [
                        {"field": "register", "op": "in", "value": ["news", "wiki"]}
                    ],
                    "size": {"tokens": 5000000, "docs": 1000}
                }
            },
            "query": {
                "mode": "cqlf",
                "cqlf": '[lemma="gehen"]',
                "context": {"left": 5, "right": 5}
            },
            "kwic": {
                "resultSet": {"rows": 500, "hash": "abc"},
                "selection": {"rowIds": ["row-1", "row-5"]},
                "preview": [
                    {"rowId": "row-0", "left": "er wollte", "match": "gehen", "right": "aber", "docId": "doc1"}
                ]
            },
            "history": {
                "recentActions": [
                    {"source": "user", "type": "query/execute", "ok": True, "summary": "gehen"}
                ]
            }
        }

        result = build_context_message(context)

        assert "autonomy_level: 7" in result
        assert "corpus_id: test_corpus" in result
        assert "corpus_size: 5000000 tokens, 1000 docs" in result
        assert "active_filters:" in result
        assert "register in news, wiki" in result
        assert 'current_query: [lemma="gehen"]' in result
        assert "total_results: 500" in result
        assert "selected_rows: 2" in result
        assert "kwic_preview:" in result
        assert "<<gehen>>" in result
        assert "recent_actions:" in result
        assert "[user] query/execute" in result

    def test_context_with_empty_values(self):
        """Handle context with missing/empty fields gracefully."""
        context = {
            "session": {"autonomy": 5},
            "view": {},
            "corpus": {"corpusId": "empty"},
            "query": {},
            "kwic": {},
            "history": {}
        }

        # Should not raise
        result = build_context_message(context)
        assert "autonomy_level: 5" in result


# ============================================================================
# System Prompt Tests
# ============================================================================

class TestSystemPrompt:
    """Tests for system prompt generation."""

    def test_get_system_prompt_contains_key_sections(self):
        """System prompt includes all required documentation sections.

        Seit R2 ist der KV-stabile statische Kern aus ``prompt_layout`` die
        Laufzeitquelle; die Sektionen entsprechen dessen Aufbau.
        """
        prompt = get_system_prompt()

        # Check for key sections (prompt_layout._compose_static_core)
        assert "<nicht_verhandelbar>" in prompt
        assert "<rolle>" in prompt
        assert "<referenz_syntax>" in prompt
        assert "<methoden_invarianten>" in prompt
        assert "<planung>" in prompt
        assert "<rezept_index>" in prompt
        assert "<glossar>" in prompt
        assert "<tools>" in prompt
        assert "<query_syntax>" in prompt
        assert "<cqlf_capabilities>" in prompt
        assert "<kontext>" in prompt
        assert "<control_frames>" in prompt
        assert "<autonomy_levels>" in prompt
        assert "<runtime_contracts>" in prompt
        assert "<fehlerbehandlung>" in prompt
        assert "<beispiel>" in prompt
        assert "<ausgabeformat>" in prompt

    def test_get_system_prompt_contains_cqp_syntax(self):
        """System prompt includes CQLF syntax documentation."""
        prompt = get_system_prompt()

        # CQLF basics should be present
        assert "lemma=" in prompt
        assert "pos=" in prompt
        assert "STTS" in prompt  # POS tag reference
        assert "Klartext" in prompt  # Plain text preferred

    def test_get_system_prompt_contains_cqlf_capability_contract(self):
        """System prompt includes CQLF capability constraints."""
        prompt = get_system_prompt()

        assert "CQLF capability contract" in prompt
        assert "Current claimed level: 2-" in prompt
        assert "cqlf.level2.semantic_similarity_macro" in prompt
        # Die Level-3-Bezeichnerliste ist am 2026-09-01 aus dem Prompt
        # gefallen, ihre Warnung nicht. Der Platz traegt jetzt Syntax.
        assert "do not claim Level 3" in prompt
        assert '[word="a"] []{1,8} [word="b"]' in prompt
        assert "do not claim Level 3" in prompt

    def test_get_system_prompt_contains_tools(self):
        """System prompt includes tool documentation."""
        prompt = get_system_prompt()

        assert "run_cqlf_query" in prompt
        assert "collocate_stats" in prompt
        assert "frequency_list" in prompt
        assert "semantic_search" in prompt

    def test_get_system_prompt_with_context(self):
        """System prompt combined with context includes both."""
        context = {"autonomy_level": 3, "current_query": "test"}
        prompt = get_system_prompt_with_context(context)

        # Has system prompt sections
        assert "<query_syntax>" in prompt

        # Has context
        assert "<ui_context>" in prompt
        assert "autonomy_level: 3" in prompt

    def test_runtime_prompt_uses_dynamic_tool_space_instead_of_all_tools_manual(self):
        prompt = compact_runtime_system_prompt(
            get_system_prompt_with_context({"autonomy_level": 3})
        )

        assert "RUNTIME-TOOL-SPACE" in prompt
        assert "Tool Reference — Alle Tools" not in prompt
        assert "<query_syntax>" in prompt

    def test_system_prompt_length_reasonable(self):
        """System prompt is within reasonable length for LLM context."""
        prompt = get_system_prompt()

        # With corrected science guidance (keyness effect-size fields, dice vs
        # logDice, one_sided, FDR caveat) PLUS the r7 tool-surface expansion
        # (TOOLS_DOC realignment, create_docset/list_docsets + n-gram tooling,
        # collocation-network hints, response_schema docs) PLUS field-exact
        # cluster-tool OUTPUT docs and the 4-level autonomy matrix: ~42K chars
        # / ~8K tokens. Still well within a 128K-token context window.
        assert 12000 < len(prompt) < 45000, f"Prompt length: {len(prompt)}"


# ============================================================================
# Documentation Constant Tests
# ============================================================================

class TestDocumentationConstants:
    """Tests for documentation string constants."""

    def test_cqp_syntax_doc_complete(self):
        """CQLF syntax doc includes essential elements."""
        assert "Klartext" in CQLF_SYNTAX_DOC  # Plain text preferred
        assert "lemma=" in CQLF_SYNTAX_DOC
        assert "pos=" in CQLF_SYNTAX_DOC
        assert "einfache" in CQLF_SYNTAX_DOC
        assert "[lemma='gehen']" in CQLF_SYNTAX_DOC
        assert "NN" in CQLF_SYNTAX_DOC  # Nomen
        assert "VVFIN" in CQLF_SYNTAX_DOC  # Finite verb

    def test_cqlf_capability_doc_complete(self):
        """CQLF capability doc exposes query constraints for the Copilot."""
        assert "CQLF Capability Contract" in CQLF_CAPABILITY_DOC
        assert "Partial/guarded CQLF capabilities" in CQLF_CAPABILITY_DOC
        # Seit dem 2026-09-01 nennt der Vertrag SYNTAX statt nur Bezeichner.
        # Eine Nutzerin diktierte am Vorabend ihre Abfrage woertlich ("bis zu
        # acht beliebige Token"), und der Harnisch lieferte 0 Treffer, weil
        # Quantoren nur als Name in einer Liste standen. Dieselbe Abfrage mit
        # []{0,8} liefert am selben Index 45.599 Treffer.
        assert "[]{1,3}" in CQLF_CAPABILITY_DOC
        assert '[word="a"] []{1,8} [word="b"]' in CQLF_CAPABILITY_DOC
        # Die Level-3-Warnung bleibt, die doppelte Bezeichnerliste geht.
        assert "do not claim Level 3" in CQLF_CAPABILITY_DOC
        assert "Region-Algebra" in CQLF_CAPABILITY_DOC

    def test_tools_doc_has_outputs(self):
        """Tool documentation includes OUTPUT descriptions."""
        assert "OUTPUT:" in TOOLS_DOC
        assert "status" in TOOLS_DOC
        assert "rows" in TOOLS_DOC

    def test_control_frames_doc_complete(self):
        """Control frames doc includes all frame types."""
        assert "PLAN" in CONTROL_FRAMES_DOC
        assert "CLARIFY" in CONTROL_FRAMES_DOC
        assert "ACTION" in CONTROL_FRAMES_DOC
        assert "<<<CC:" in CONTROL_FRAMES_DOC

    def test_autonomy_levels_doc_complete(self):
        """Autonomy levels doc describes all levels."""
        assert "0-2" in AUTONOMY_LEVELS_DOC
        assert "3-5" in AUTONOMY_LEVELS_DOC
        assert "6-8" in AUTONOMY_LEVELS_DOC
        assert "9-10" in AUTONOMY_LEVELS_DOC

    def test_autonomy_levels_doc_matches_orchestrator_matrix(self):
        """Doc mirrors the enforced matrix (orchestrator._should_require_approval
        / _plan_gate_active) and the 4-level frontend truth (1/4/7/10)."""
        # Frontend sends exactly these four values.
        assert "1, 4, 7 oder 10" in AUTONOMY_LEVELS_DOC
        # Plan gate fires only at levels 0-1.
        assert "Plan-Gate" in AUTONOMY_LEVELS_DOC
        assert "0-1" in AUTONOMY_LEVELS_DOC
        # 6-8 gates only destructive action types.
        assert "delete" in AUTONOMY_LEVELS_DOC
        assert "drop" in AUTONOMY_LEVELS_DOC
        # Explicit requiresApproval only skipped at >=9.
        assert "requiresApproval=true" in AUTONOMY_LEVELS_DOC

    def test_science_guide_comprehensive(self):
        """Science guide includes report structure and statistics."""
        # Report structure
        assert "Fragestellung" in SCIENCE_GUIDE
        assert "Interpretation" in SCIENCE_GUIDE
        assert "Limitationen" in SCIENCE_GUIDE

        # Statistical thresholds
        assert "t-score" in SCIENCE_GUIDE
        # logDice (corpus-size-independent) is now distinguished from raw dice.
        assert "logDice" in SCIENCE_GUIDE
        assert "dice" in SCIENCE_GUIDE
        assert "LL" in SCIENCE_GUIDE  # Log-Likelihood
        # Keyness leads with effect size + FDR caveat for multiple comparisons.
        assert "q_value" in SCIENCE_GUIDE

        # Normalization guidance
        assert "pmw" in SCIENCE_GUIDE
        assert "starrer Vorlage" in SCIENCE_GUIDE

    def test_example_conversations_has_patterns(self):
        """Example conversations show chat+action patterns."""
        # Has actual conversation examples
        assert "Nutzer:" in EXAMPLE_CONVERSATIONS
        assert "Copilot:" in EXAMPLE_CONVERSATIONS

        # Shows tool call via function_call, not ACTION frame
        assert "function_call" in EXAMPLE_CONVERSATIONS
        assert "<<<CC:CLARIFY" in EXAMPLE_CONVERSATIONS

        # Shows interpretation after results
        assert "pmw" in EXAMPLE_CONVERSATIONS

    def test_error_handling_guide_covers_scenarios(self):
        """Error handling guide covers common error scenarios."""
        # Zero results
        assert "0 Treffer" in ERROR_HANDLING_GUIDE or "Keine Treffer" in ERROR_HANDLING_GUIDE

        # Tool errors
        assert "Fehler" in ERROR_HANDLING_GUIDE

        # Ambiguity handling
        assert "CLARIFY" in ERROR_HANDLING_GUIDE

        # Too many results
        assert "100.000" in ERROR_HANDLING_GUIDE or "viele" in ERROR_HANDLING_GUIDE.lower()

    def test_agent_policy_covers_behavior(self):
        """Agent policy covers key behavioral guidelines."""
        # Operative principles
        assert "Entscheidungsprinzipien" in AGENT_POLICY or "ENTSCHEIDUNGSPRINZIPIEN" in AGENT_POLICY

        # Communication guidance
        assert "Interpretiere" in AGENT_POLICY or "interpretiere" in AGENT_POLICY.lower()

        # Proactivity
        assert "proaktiv" in AGENT_POLICY.lower()

    def test_nicht_verhandelbar_has_critical_constraints(self):
        """Non-negotiable constraints cover the most critical rules."""
        assert "function_call" in NICHT_VERHANDELBAR
        assert "Faktenquelle" in NICHT_VERHANDELBAR
        assert "Tool-Outputs" in NICHT_VERHANDELBAR
        assert "corpus_attributes" in NICHT_VERHANDELBAR
        assert "status" in NICHT_VERHANDELBAR
        assert "exakt und transparent nachrechenbar" in NICHT_VERHANDELBAR

    def test_glossar_defines_key_terms(self):
        """Glossary defines all key domain terms."""
        assert "KWIC" in GLOSSAR
        assert "pmw" in GLOSSAR
        assert "CQL" in GLOSSAR
        assert "Kollokation" in GLOSSAR
        assert "Keyness" in GLOSSAR
        assert "MI" in GLOSSAR
        assert "t" in GLOSSAR
        assert "LL" in GLOSSAR
        assert "dice" in GLOSSAR

    def test_role_doc_has_success_criteria(self):
        """Role doc defines domain-specific success and failure criteria."""
        assert "ERFOLG" in ROLE_DOC
        assert "MISSERFOLG" in ROLE_DOC
        # Domain-specific, not generic
        assert "Analysemethode" in ROLE_DOC
        assert "kontextualisiert" in ROLE_DOC or "Interpretation" in ROLE_DOC

    def test_role_doc_has_source_separation(self):
        """Role doc defines what the copilot may claim from which source."""
        assert "QUELLENTRENNUNG" in ROLE_DOC
        assert "Fakt" in ROLE_DOC
        assert "Interpretation" in ROLE_DOC
        assert "Annahme" in ROLE_DOC
        # Permission to not know
        assert "nicht ableiten" in ROLE_DOC

    def test_verifikation_has_pre_and_post_checks(self):
        """Verification section covers pre-call and post-call checks."""
        assert "Vor Tool-Aufruf" in VERIFIKATION
        assert "Nach Tool-Aufruf" in VERIFIKATION
        assert "corpus_attributes" in VERIFIKATION
        assert "status" in VERIFIKATION
        assert "Fallzahl" in VERIFIKATION
        assert "Pauschalschwelle" in VERIFIKATION

    def test_output_guide_specifies_format(self):
        """Output guide specifies answer format requirements."""
        assert "pmw" in OUTPUT_GUIDE
        assert "Tabelle" in OUTPUT_GUIDE
        assert "Interpretation" in OUTPUT_GUIDE or "interpretation" in OUTPUT_GUIDE.lower()
        assert "keine starre oder mechanische Standardvorlage" in OUTPUT_GUIDE


class TestSystemPromptComplete:
    """Tests for system prompt with all new sections."""

    def test_system_prompt_has_all_new_sections(self):
        """System prompt includes all R2 static-core documentation sections."""
        prompt = get_system_prompt()

        assert "<referenz_syntax>" in prompt
        assert "<methoden_invarianten>" in prompt
        assert "<rezept_index>" in prompt
        assert "<beispiel>" in prompt
        assert "<fehlerbehandlung>" in prompt
        assert "<runtime_contracts>" in prompt
        assert "<ausgabeformat>" in prompt

    def test_system_prompt_size_reasonable(self):
        """System prompt is within reasonable size after optimization."""
        prompt = get_system_prompt()

        # With corrected science guidance (keyness effect-size fields, dice vs
        # logDice, one_sided, FDR caveat) PLUS the r7 tool-surface expansion
        # (TOOLS_DOC realignment, create_docset/list_docsets + n-gram tooling,
        # collocation-network hints, response_schema docs) PLUS field-exact
        # cluster-tool OUTPUT docs and the 4-level autonomy matrix: ~42K chars
        # / ~8K tokens. Still well within a 128K-token context window.
        assert 12000 < len(prompt) < 45000, f"Prompt length: {len(prompt)}"

    def test_science_guide_in_prompt_qualifies_statistical_thresholds(self):
        """The prompt does not mislabel association scores as significance.

        Seit R2 liegt die Maß-Semantik am jeweiligen Tool (statischer Kern);
        der SCIENCE_GUIDE bleibt als Referenzdokument korrekt qualifiziert.
        """
        prompt = get_system_prompt()

        assert "t-score > 2" not in prompt
        assert "Effektstärke führt, Signifikanz folgt" in prompt
        assert "kein Signifikanztest" in prompt
        assert "10.83" in prompt

        from candyconc.candyconc_copilot.prompts import METHOD_HINTS

        assert "t-score ist ein frequenzsensitives Assoziationsmaß" in METHOD_HINTS

    def test_example_conversations_in_prompt(self):
        """Example conversations are included in the system prompt."""
        prompt = get_system_prompt()

        # Should show real conversation patterns
        assert "Nutzer:" in prompt
        assert "Copilot:" in prompt

    def test_nicht_verhandelbar_in_prompt(self):
        """Non-negotiable constraints appear at the top of the prompt.

        Der statische Kern fuehrt NICHT_VERHANDELBAR einmal am Anfang.
        Das Rollenvertrag-Echo am Ende ist durch den Deutungsauftrag
        ersetzt (Runde 2, Arm-4-Urteile: Recency gehoert dem Auftrag).
        """
        prompt = get_system_prompt()

        from candyconc.candyconc_copilot.prompt_layout import ROLLENVERTRAG

        count = prompt.count(ROLLENVERTRAG)
        assert count == 1, f"Expected 1 occurrence, got {count}"
        assert "<ausgabeformat>" in prompt
