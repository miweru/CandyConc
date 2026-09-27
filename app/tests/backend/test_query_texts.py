"""Bilingual texts of the query engine: parse errors, filter errors, search hints.

The parser, the editor diagnostics, the autocomplete and the metadata filter
checks write their user-visible texts as German and English pairs. ``str()``
of an exception and every compared value stay German, so the classifiers and
the existing tests see the same text as before. A response resolves the pair
to the request language.
"""

from __future__ import annotations

import os

import pytest

from candyconc.i18n import LocalizedText, exception_text, language_scope, localize

EN = {"Accept-Language": "en, de;q=0.5"}


# --- parse errors ---------------------------------------------------------------


def test_parse_error_message_is_a_pair_and_str_stays_german():
    from cqlhpc.parser import ParseError, parse_cql

    with pytest.raises(ParseError) as info:
        parse_cql('[word="a"]{3,1}')
    exc = info.value

    assert str(exc) == (
        "CQL Parse Fehler: Ungültige Wiederholung {3,1}: Obergrenze < Untergrenze. at 10:15"
    )
    text = exception_text(exc)
    assert isinstance(text, LocalizedText)
    assert text == str(exc)
    assert text.resolve("en") == (
        "CQL parse error: Invalid repetition {3,1}: upper bound < lower bound. at 10:15"
    )
    with language_scope("en"):
        assert localize({"detail": text}) == {"detail": text.en}
    assert localize({"detail": text}) == {"detail": str(exc)}
    assert (exc.start, exc.end) == (10, 15)


def test_parser_token_errors_stay_english_in_both_languages():
    """Token errors are English only. The interface humanizes them by pattern."""
    from cqlhpc.parser import ParseError, parse_cql

    with pytest.raises(ParseError) as info:
        parse_cql("[word=]")
    text = exception_text(info.value)
    assert text == "CQL Parse Fehler: expected value, got RBRACK:] at 6:7"
    assert text.resolve("en") == "CQL parse error: expected value, got RBRACK:] at 6:7"


def test_editor_diagnostics_carry_the_bare_reason_in_both_languages():
    from cqlhpc.diagnostics import diagnose

    diags = diagnose('where(split="", [word="a"]')
    messages = [d.message for d in diags if d.severity == "error"]
    assert "Fehlende schließende Klammer(n)" in messages
    assert (
        "leerer Wert: schraenkt nichts ein. Entweder einen Wert angeben oder die "
        "Bedingung weglassen." in messages
    )
    with language_scope("en"):
        english = localize(messages)
    assert "Missing closing bracket(s)" in english
    assert "empty value: restricts nothing. Either give a value or leave out the condition." in english


def test_regex_refusal_uses_the_number_format_of_each_language():
    from cqlhpc.predicates import regex_zu_gross

    exc = regex_zu_gross(gemessen=83_056_089, grenze=5_000_000, dimension="Tokens", muster=".*e.*")
    assert str(exc) == (
        "Regex Treffer zu gross fuer '.*e.*': 83.056.089 Tokens gegen eine Grenze von "
        "5.000.000 (16,6-fach). Bitte Suchmuster einschraenken."
    )
    assert exception_text(exc).resolve("en") == (
        "Too many regex hits for '.*e.*': 83,056,089 tokens against a limit of "
        "5,000,000 (16.6 times). Narrow the search pattern."
    )


# --- metadata filter errors -------------------------------------------------------


def test_filter_form_error_is_a_pair():
    from candyconc.core.meta_filters import EingabeFormFehler, pruefe_filterform

    with pytest.raises(EingabeFormFehler) as info:
        pruefe_filterform("party", {"gte": "x"})
    text = exception_text(info.value)
    assert str(info.value).startswith("Ungueltiger Metadaten-Filter fuer 'party': {'gte': 'x'}.")
    assert text.resolve("en").startswith(
        "Invalid metadata filter for 'party': {'gte': 'x'}. Ranges are written as "
        "{'op': 'between', 'lo': ..., 'hi': ...}, comparisons as {'op': '>=', 'value': ...}."
    )


@pytest.fixture(scope="module")
def client():
    if not os.environ.get("CANDYCONC_INDEX_PATH"):
        pytest.skip("CANDYCONC_INDEX_PATH not set")
    from fastapi.testclient import TestClient

    from candyconc.services.backend.server import app

    return TestClient(app, raise_server_exceptions=False)


def test_filter_form_error_answer_follows_the_request_language(client):
    body = {"filters": {"party": []}}
    de = client.post("/api/v1/analysis/docset_from_meta", json=body)
    en = client.post("/api/v1/analysis/docset_from_meta", json=body, headers=EN)

    assert de.status_code == en.status_code == 400
    assert de.headers["content-type"].startswith("application/problem+json")
    assert de.json()["detail"] == (
        "Leerer Werte-Filter fuer 'party'. Ein leerer Filter faellt still weg und "
        "liefert das UNGEFILTERTE Korpus mit Erfolgsmeldung. Weglassen, wenn nicht "
        "gefiltert werden soll."
    )
    assert en.json()["detail"] == (
        "Empty value filter for 'party'. An empty filter is silently dropped and "
        "returns the UNFILTERED corpus with a success message. Leave it out if no "
        "filtering is wanted."
    )


# --- search hints -----------------------------------------------------------------


def test_autocomplete_hints_are_pairs():
    from cqlhpc.autocomplete import complete

    details = [s.detail for s in complete('[word="a" & sim="x"', 19)]
    assert details == ["weitere Bedingung", "Anzahl ähnlicher Wörter", "Tokenklausel schließen"]
    assert localize(details, "en") == ["Another condition", "Number of similar words", "Close token clause"]


def test_query_analysis_keeps_hints_and_errors_in_both_languages(client):
    """The dict of the analysis route before it is rendered."""
    from candyconc.core.cql_engine import analyse_cql_backend
    from candyconc.services.backend.server import get_corpus

    result = analyse_cql_backend(get_corpus(None).fast_index, 'cql:[word="a"')
    assert "Fehlende schließende Klammer(n)" in result["errors"]
    assert "Klammern schließen" in result["hints"]
    assert "weitere Bedingung" in result["hints"]

    english = localize(result, "en")
    assert "Missing closing bracket(s)" in english["errors"]
    assert "Close brackets" in english["hints"]
    assert "Another condition" in english["hints"]
    fixes = [fix["label"] for diag in english["diagnostics"] for fix in diag["fixes"]]
    assert "Close brackets" in fixes


# --- the routes that carry these texts to the interface --------------------------


def test_query_parse_error_answer_follows_the_request_language(client):
    params = {"term": 'cql:[word="a"]{3,1}'}
    de = client.get("/api/v1/query", params=params)
    en = client.get("/api/v1/query", params=params, headers=EN)

    assert de.status_code == en.status_code == 400
    assert de.json()["detail"] == (
        "CQL Parse Fehler: Ungültige Wiederholung {3,1}: Obergrenze < Untergrenze. at 10:15"
    )
    assert en.json()["detail"] == (
        "CQL parse error: Invalid repetition {3,1}: upper bound < lower bound. at 10:15"
    )


def test_query_analysis_answer_follows_the_request_language(client):
    body = {"query": 'cql:[word="a"]{3,1}'}
    de = client.post("/api/v1/query/analyse", json=body).json()
    en = client.post("/api/v1/query/analyse", json=body, headers=EN).json()

    assert de["errors"] == ["Ungültige Wiederholung {3,1}: Obergrenze < Untergrenze."]
    assert en["errors"] == ["Invalid repetition {3,1}: upper bound < lower bound."]
    assert en["diagnostics"][0]["message"] == en["errors"][0]
