"""Rounded evidence values survive both answer checks with their precision."""

import asyncio
from types import SimpleNamespace

import pytest

from candyconc.answer_language import answer_language_scope
from candyconc.candyconc_copilot import interpretation_synthesis as synthesis
from candyconc.candyconc_copilot.claim_rules._shared import _numeric_token_is_supported
from candyconc.candyconc_copilot.grounding_refs import resolve_references
from candyconc.candyconc_copilot.recipe_runtime import resolve_reference_draft
from tests.ai.test_number_check_reads_answer_language import _items


@pytest.mark.parametrize("language,text", [
    ("en", "America: log_ratio .85, CI .68 to 1.03, rate 4,022. Freedom: 1.05, CI .78 to 1.32."),
    ("de", "America: log_ratio 0,85, CI 0,68 bis 1,03, Rate 4.022. Freedom: 1,05, CI 0,78 bis 1,32."),
])
def test_keyness_rounding_reaches_the_reference_check(language, text):
    with answer_language_scope(language):
        result = resolve_reference_draft(text, _items(), "")
    assert result["bare_numbers"] == []


@pytest.mark.parametrize("claimed,source,supported", [
    ("4022", "4022.1707098758347", True),
    ("916", "915.6", True),
    ("2.29", "2.2941", True),
    ("4.61", "4.6061", True),
    ("1.03", "1.0296", True),
    ("1.00", "1.0296", False),
    ("1.24", "1.245", False),
    ("1.25", "1.245", True),
    ("-1.03", "-1.0296", True),
    ("1.03", "-1.0296", False),
    ("4023", "4022.1707098758347", False),
    ("700", "701", False),
])
def test_numeric_support_uses_decimal_rounding(claimed, source, supported):
    assert _numeric_token_is_supported(claimed, {source}) is supported


@pytest.mark.parametrize("language,decimal", [("en", "."), ("de", ",")])
@pytest.mark.parametrize("source,claim,supported", [
    ("1.0296", "1.03", True),
    ("1.0296", "1.00", False),
    ("-1.0296", "-1.03", True),
    ("1.0296", "-1.03", False),
    ("-1.0296", "1.03", False),
])
def test_reference_check_keeps_precision_and_sign(language, decimal, source, claim, supported):
    written = claim.replace(".", decimal)
    with answer_language_scope(language):
        result = resolve_references(
            f"log_ratio {written}.",
            {"grounding_surface": [f"log_ratio={source}"]},
        )
    assert bool(result["bare_numbers"]) is not supported


@pytest.mark.parametrize("language,decimal", [("en", "."), ("de", ",")])
@pytest.mark.parametrize("claim,supported", [("1.03", True), ("1.00", False)])
def test_percent_rounding_keeps_written_precision(language, decimal, claim, supported):
    with answer_language_scope(language):
        result = resolve_references(
            f"Share {claim.replace('.', decimal)} %.",
            {"grounding_surface": ["coverage_ratio=0.010296"]},
        )
    assert bool(result["bare_numbers"]) is not supported


@pytest.mark.parametrize("language,decimal", [("en", "."), ("de", ",")])
@pytest.mark.parametrize("claim,supported", [("1.03", True), ("1.00", False), ("-1.03", False), ("1.03 %", False)])
def test_synthesis_checks_fact_values_with_written_precision(
    monkeypatch, language, decimal, claim, supported,
):
    items = [{"id": "E_keyness_4", "tool": "keyness", "status": "success",
              "fact_surface": {"rows": [{"log_ratio_ci_high": 1.0296}]},
              "grounding_surface": ["word=America"]}]
    monkeypatch.setenv("CANDYCONC_ZAHLEN_STREICHEN", "1")
    monkeypatch.setattr(synthesis, "f4_wachen_aktiv", lambda: False)
    monkeypatch.setattr(synthesis, "zwischenstand", lambda *args, **kwargs: None)
    orchestrator = SimpleNamespace(
        session=SimpleNamespace(session_id=""),
        _ra_resolve_reference_draft=lambda state, text, detect_bare_numbers=False: (
            resolve_reference_draft(text, items, "", detect_bare_numbers=detect_bare_numbers)
        ),
    )
    with answer_language_scope(language):
        _, struck = asyncio.run(synthesis._verankere(
            orchestrator, SimpleNamespace(normalized_question=""), None,
            f"CI {claim.replace('.', decimal)}.", items,
        ))
    assert bool(struck) is not supported


def test_short_negative_decimal_keeps_its_sign():
    with answer_language_scope("en"):
        accepted = resolve_references("log_ratio -.85.", {"grounding_surface": ["log_ratio=-0.8533"]})
        rejected = resolve_references("log_ratio -.85.", {"grounding_surface": ["log_ratio=0.8533"]})
    assert accepted["bare_numbers"] == []
    assert [finding["number"] for finding in rejected["bare_numbers"]] == ["-.85"]


@pytest.mark.parametrize("written,source,supported", [
    ("916", 915.6, True),
    ("915", 915.6, False),
    ("917", 915.6, False),
    ("4,022", 4022.1707098758347, True),
    ("4.022", 4022.1707098758347, True),
    ("4,023", 4022.1707098758347, False),
])
def test_rate_name_accepts_only_the_correct_whole_rounding(written, source, supported):
    from candyconc.candyconc_copilot import recipe_runtime as runtime
    assert runtime._massname_gedeckt(
        "per_million", runtime._lesarten_mit_stellen(written),
        [{"target_per_million": {source}}],
    ) is supported


def test_rounded_rate_preserves_the_named_measure():
    from candyconc.candyconc_copilot import recipe_runtime as runtime
    items = [{"grounding_surface": ["per_million=915.6", "total=916", "log_ratio=4.61"]}]
    assert runtime.massname_an_feld_gebunden("per_million 916", items) == []
    assert runtime.massname_an_feld_gebunden("log_ratio 916", items)
    assert not runtime._massname_gedeckt("total", [(915, 0)], [{"total": {916}}])
