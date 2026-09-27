from __future__ import annotations

from typing import get_args

from cqlhpc import ast as cql_ast
from cqlhpc.builder import to_cql
from cqlhpc.capabilities import (
    all_capabilities,
    build_cqlf_capability_contract,
    capabilities_by_level,
    capabilities_markdown_table,
    capability_by_id,
    capability_ids,
    copilot_cqlf_capability_summary,
    covered_ast_nodes,
    covered_meta_operators,
    covered_token_operators,
    language_service_meta_operators,
    language_service_snippets,
    language_service_token_attributes,
    language_service_token_operators,
    supported_capabilities,
)
from cqlhpc.parser import parse_cql


def test_cqlf_capability_ids_are_unique() -> None:
    ids = capability_ids()

    assert len(ids) == len(set(ids))
    assert ids


def test_cqlf_capabilities_cover_current_ast_contract() -> None:
    node_names = {node.__name__ for node in get_args(cql_ast.Node)}

    assert node_names <= covered_ast_nodes()
    assert {"Cond", "TokenClause", "MetaCond", "MetaExpr"} <= covered_ast_nodes()


def test_cqlf_capabilities_cover_current_parser_operators() -> None:
    assert {"=", "!=", "~", "in", "&"} <= covered_token_operators()
    assert {"=", "!=", ">=", "<=", ">", "<"} <= covered_meta_operators()


def test_cqlf_language_service_contract_exposes_autocomplete_surface() -> None:
    snippet_texts = {snippet.insert_text for snippet in language_service_snippets()}

    assert {"word", "lemma", "pos", "ent", "ner", "sim"} <= set(language_service_token_attributes())
    assert "k" in set(language_service_token_attributes(include_parameters=True))
    assert language_service_token_operators() == ("=", "!=", "~", "in")
    assert language_service_meta_operators() == ("=", "!=", ">=", "<=", ">", "<")
    assert '[sim="$1"&k=20]' in snippet_texts
    # Nachgezogen am 2026-09-02. ``where($1, $2)`` rendert zu "where(x, y)"
    # und verschweigt, dass das erste Argument feld="wert" ist. Die Form mit
    # Bedingung ist der Punkt, siehe tests/core/test_cqlf_where_conformance.py.
    assert 'where(model="x", $1)' in snippet_texts


def test_cqlf_supported_capabilities_require_execution_and_tests() -> None:
    for capability in supported_capabilities():
        assert capability.syntax in {"supported", "not_applicable"}
        assert capability.execution == "supported"
        assert capability.tests == "supported"


def test_cqlf_level3_is_not_accidentally_claimed_as_supported() -> None:
    for capability in capabilities_by_level(3):
        assert not capability.is_declared_supported
        assert capability.execution in {"planned", "unsupported"}


def test_cqlf_syntax_supported_examples_parse_and_roundtrip() -> None:
    examples = {
        "cqlf.level1.operator.equals": '[word="A"]',
        "cqlf.level1.sequence": '[word="A"] [lemma="b"]',
        "cqlf.level2.operator.not_equals": '[word!="A"]',
        "cqlf.level2.operator.regex": '[word~"^A.*"]',
        "cqlf.level2.operator.in_set": '[lemma in {"gehen", "laufen"}]',
        "cqlf.level2.token_clause.conjunction": '[word="A" & lemma="a"]',
        "cqlf.level2.grouping": '([word="A"] | [word="B"]) [pos="NN"]',
        "cqlf.level2.alternation": '[word="A"] | [word="B"]',
        "cqlf.level2.quantifiers": '[word="A"]{0,2}',
        "cqlf.level2.within": 'within(<s>, [word="A"] [word="B"])',
        "cqlf.level2.where.metadata": 'where(source="news" & year>=2024, [word="A"])',
    }

    for capability_id, query in examples.items():
        capability = capability_by_id(capability_id)
        assert capability.syntax == "supported"
        parsed = parse_cql(query)
        rendered = to_cql(parsed)
        parse_cql(rendered)


def test_cqlf_markdown_table_exports_machine_contract() -> None:
    table = capabilities_markdown_table()

    assert "| ID | Level | Syntax | Execution | Diagnostics | Explain | Tests |" in table
    for capability in all_capabilities():
        assert f"`{capability.id}`" in table


def test_cqlf_capability_contract_has_stable_fingerprint_metadata() -> None:
    contract = build_cqlf_capability_contract()

    assert contract["version"] == "cqlf-capabilities-v1"
    assert contract["current_level"] == "2-"
    assert len(str(contract["fingerprint_sha256"])) == 64
    assert any(
        item["id"] == "cqlf.level3.labels_captures"
        and item["execution"] == "unsupported"
        for item in contract["capabilities"]
    )
    assert contract == build_cqlf_capability_contract()


def test_copilot_cqlf_capability_summary_warns_against_level3_claims() -> None:
    summary = copilot_cqlf_capability_summary()

    assert "Current claimed level: 2-" in summary
    assert "do not claim Level 3" in summary
    # Die Liste der Level-3-Bezeichner ist am 2026-09-01 aus dem Prompt
    # gefallen. Sie nannte fuenf Namen fuer Dinge, die derselbe Prompt drei
    # Zeilen weiter auf Deutsch und vollstaendiger verbietet, und sie kostete
    # den Platz, an dem jetzt die Abstands-Syntax steht. Die WARNUNG bleibt
    # ("do not claim Level 3"), die doppelte Aufzaehlung geht.
    assert "cqlf.level3" not in summary
    # Und die Syntax, die den Platz bekommen hat, muss auch dastehen.
    assert "[]{1,3}" in summary
    assert "Abstand NUR mit Quantor" in summary
