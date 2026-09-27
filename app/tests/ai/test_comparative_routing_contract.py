"""Routing tests: generic A-vs-B prompts surface ``contrast_collocates``.

The human/AI-specific comparative flows must keep recommending
``compare_collocates`` exactly as before; only generic docset comparisons
(no human/AI wording) route to the pairing-free ``contrast_collocates`` tool.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path


root = Path(__file__).resolve().parents[2]
package_root = root / "src" / "candyconc" / "candyconc_copilot"

pkg = sys.modules.setdefault("candyconc_copilot", types.ModuleType("candyconc_copilot"))
if not getattr(pkg, "__path__", None):
    pkg.__path__ = [str(package_root)]  # type: ignore[attr-defined]

analysis_grounding = importlib.import_module("candyconc_copilot.analysis_grounding")

CONTRAST_TOOLS = [
    "compare_collocates",
    "contrast_collocates",
    "keyness",
    "frequency_list",
    "metadata_values",
]

LEGACY_TOOLS = [name for name in CONTRAST_TOOLS if name != "contrast_collocates"]


class DocsetComparativeDetectorTests(unittest.TestCase):
    def test_detects_generic_german_comparisons(self):
        for prompt in (
            "vergleiche subkorpus a mit subkorpus b",
            "unterschied zwischen news und blog",
            "unterschiede zwischen den registern",
            "news vs blog",
            "kontrastiere die teilkorpora",
            "register social gegenüber register news",
            "wie unterscheiden sich die parteien beim thema flucht",
            "compare docset a with docset b",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(analysis_grounding._is_docset_comparative_prompt(prompt))

    def test_does_not_fire_on_non_comparative_prompts(self):
        for prompt in (
            "wie oft kommt demokratie im korpus vor",
            "zeig mir kwic-belege für migration",
            "welche themen wirken zentral",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(analysis_grounding._is_docset_comparative_prompt(prompt))

    def test_explicit_pair_detector_distinguishes_scope_from_broad_class(self):
        self.assertTrue(
            analysis_grounding._has_explicit_comparison_pair(
                "vergleiche subkorpus news mit subkorpus blog"
            )
        )
        self.assertTrue(
            analysis_grounding._has_explicit_comparison_pair(
                "unterschiede zwischen spd und fdp"
            )
        )
        self.assertFalse(
            analysis_grounding._has_explicit_comparison_pair(
                "wie unterscheiden sich die parteien beim thema flucht"
            )
        )


class HeuristicContractRoutingTests(unittest.TestCase):
    def test_underspecified_collective_comparison_is_left_to_contract_planner(self):
        contract = analysis_grounding.heuristic_analysis_contract(
            "Wie unterscheiden sich die Parteien beim Thema Flucht?",
            available_tools=CONTRAST_TOOLS,
            read_only_tools=CONTRAST_TOOLS,
        )

        self.assertIsNone(contract)

    def test_generic_a_vs_b_prompt_yields_contrast_collocates_bundle(self):
        contract = analysis_grounding.heuristic_analysis_contract(
            "Vergleiche das Subkorpus news mit dem Subkorpus blog: welche Kollokationen unterscheiden sich?",
            available_tools=CONTRAST_TOOLS,
            read_only_tools=CONTRAST_TOOLS,
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertIn("contrast_collocates", contract.allowed_tools)
        self.assertNotIn("compare_collocates", contract.allowed_tools)
        self.assertEqual(contract.analysis_family, "contrast_keyness")
        self.assertEqual(contract.track, "comparative_analysis")
        self.assertEqual(contract.deliverable_kind, "contrast_report")
        self.assertIn("metric_rows", contract.required_evidence)

    def test_english_vs_prompt_yields_contrast_collocates_bundle(self):
        contract = analysis_grounding.heuristic_analysis_contract(
            "Show the key differences: news vs blog in this corpus.",
            available_tools=CONTRAST_TOOLS,
            read_only_tools=CONTRAST_TOOLS,
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertIn("contrast_collocates", contract.allowed_tools)

    def test_human_ai_prompt_keeps_compare_collocates_routing(self):
        # Existing human/AI-specific behavior must stay identical, including
        # when the pairing-free contrast tool is also available.
        contract = analysis_grounding.heuristic_analysis_contract(
            "Vergleiche die Kollokationen von Mensch zwischen Human- und AI-Subkorpus.",
            available_tools=CONTRAST_TOOLS,
            read_only_tools=CONTRAST_TOOLS,
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertIn("compare_collocates", contract.allowed_tools)
        self.assertNotIn("contrast_collocates", contract.allowed_tools)
        self.assertIn("metadata_values", contract.allowed_tools)
        self.assertIn("metric_rows", contract.required_evidence)
        self.assertIn("metadata_rows", contract.required_evidence)

    def test_human_ai_prompt_unchanged_without_contrast_tool(self):
        legacy = analysis_grounding.heuristic_analysis_contract(
            "Vergleiche die Kollokationen von Mensch zwischen Human- und AI-Subkorpus.",
            available_tools=LEGACY_TOOLS,
            read_only_tools=LEGACY_TOOLS,
        )
        extended = analysis_grounding.heuristic_analysis_contract(
            "Vergleiche die Kollokationen von Mensch zwischen Human- und AI-Subkorpus.",
            available_tools=CONTRAST_TOOLS,
            read_only_tools=CONTRAST_TOOLS,
        )

        self.assertIsNotNone(legacy)
        self.assertIsNotNone(extended)
        assert legacy is not None and extended is not None
        self.assertEqual(legacy.allowed_tools, extended.allowed_tools)
        self.assertEqual(legacy.required_evidence, extended.required_evidence)
        self.assertEqual(legacy.response_shape, extended.response_shape)

    def test_generic_prompt_without_contrast_tool_degrades_to_legacy_path(self):
        # When contrast_collocates is not registered, generic comparative
        # prompts must behave exactly as before the routing change.
        contract = analysis_grounding.heuristic_analysis_contract(
            "Arbeite drei Unterschiede zwischen den Registern news und blog heraus.",
            available_tools=LEGACY_TOOLS,
            read_only_tools=LEGACY_TOOLS,
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertIn("compare_collocates", contract.allowed_tools)
        self.assertNotIn("contrast_collocates", contract.allowed_tools)


class FallbackContractRoutingTests(unittest.TestCase):
    def test_generic_a_vs_b_prompt_yields_contrast_collocates_bundle(self):
        contract = analysis_grounding.fallback_analysis_contract(
            "Vergleiche das Subkorpus news mit dem Subkorpus blog.",
            available_tools=CONTRAST_TOOLS,
            read_only_tools=CONTRAST_TOOLS,
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertIn("contrast_collocates", contract.allowed_tools)
        self.assertNotIn("compare_collocates", contract.allowed_tools)
        self.assertEqual(contract.analysis_family, "contrast_keyness")
        self.assertEqual(contract.response_shape, "grounded_contrast_report")

    def test_human_ai_prompt_keeps_compare_collocates_routing(self):
        contract = analysis_grounding.fallback_analysis_contract(
            "Arbeite drei belastbare Unterschiede zwischen Human- und AI-Teil des Korpus heraus.",
            available_tools=CONTRAST_TOOLS,
            read_only_tools=CONTRAST_TOOLS,
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertIn("compare_collocates", contract.allowed_tools)
        self.assertNotIn("contrast_collocates", contract.allowed_tools)

    def test_generic_prompt_without_contrast_tool_matches_legacy_bundle(self):
        # Without contrast_collocates registered, the pre-change fallback
        # bundle (compare-first ordering) must be produced unchanged.
        contract = analysis_grounding.fallback_analysis_contract(
            "Arbeite drei Unterschiede zwischen den Registern news und blog heraus.",
            available_tools=LEGACY_TOOLS,
            read_only_tools=LEGACY_TOOLS,
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(
            contract.allowed_tools,
            ["compare_collocates", "keyness", "metadata_values", "frequency_list"],
        )


if __name__ == "__main__":
    unittest.main()
