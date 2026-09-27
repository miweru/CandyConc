from __future__ import annotations

from cqlhpc.diagnostics import diagnose


def test_diagnose_labels_capture_syntax_mentions_cqlf_level3_contract() -> None:
    diagnostics = diagnose('a:[pos="ADJ"] [pos="NN"]')

    assert any(diag.severity == "error" for diag in diagnostics)
    assert any("cqlf.level3.labels_captures" in diag.message for diag in diagnostics)
    assert any("CQLF Level 3" in diag.message for diag in diagnostics)


def test_diagnose_regex_mentions_partial_cqlf_contract() -> None:
    diagnostics = diagnose('[word~"^un.*"]')

    assert any(diag.severity == "warning" for diag in diagnostics)
    assert any("cqlf.level2.operator.regex" in diag.message for diag in diagnostics)


def test_diagnose_quantifier_mentions_partial_cqlf_contract() -> None:
    diagnostics = diagnose('[word="der"]{0,2} [pos="NN"]')

    assert any(diag.severity == "warning" for diag in diagnostics)
    assert any("cqlf.level2.quantifiers" in diag.message for diag in diagnostics)


def test_diagnose_where_mentions_metadata_index_contract() -> None:
    # "info", nicht mehr "warning": ``_append_once`` leitet die Stufe aus
    # ``cap.execution == "partial"`` ab, und where() steht seit dem
    # 2026-09-02 auf supported (tests/core/test_cqlf_where_conformance.py
    # zaehlt die Matrix an einem 29-Token-Index nach). Der Hinweis auf den
    # Meta-Index BLEIBT, denn ohne ihn wirft die Abfrage weiterhin. Eine
    # Warnung vor teilweiser Ausfuehrung waere jetzt falsch.
    diagnostics = diagnose('where(source="news" & year>=2024, [word="A"])')

    assert any(diag.severity == "info" for diag in diagnostics)
    assert any("cqlf.level2.where.metadata" in diag.message for diag in diagnostics)
    assert not any(diag.severity == "warning" for diag in diagnostics)


def test_diagnose_branch_local_where_is_release_error() -> None:
    diagnostics = diagnose('where(source="a", [word="A"]) | where(source="b", [word="B"])')

    assert any(diag.severity == "error" for diag in diagnostics)
    assert any("Branch-lokales where" in diag.message for diag in diagnostics)
