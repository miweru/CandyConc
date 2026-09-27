"""Every tool response satisfies its declared schema, including empty results."""

from __future__ import annotations

import inspect
import os

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not (_BENCH and os.path.isdir(_BENCH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)

#: Argumente, mit denen ein Werkzeug ueberhaupt bis zu einer Antwort
#: kommt. Werkzeuge, die hier fehlen, werden uebersprungen UND gezaehlt:
#: eine stille Auslassung waere eine Luecke, die wie Abdeckung aussieht.
ARGUMENTE = {
    "query_count": {"query": "der"},
    "frequency_list": {"group_by": "word", "top_n": 3},
    "collocate_stats": {"term": "der", "window": 5, "min_freq": 2},
    "dispersion_offsets": {"term": "der"},
    "document_search": {"term": "der", "top_n": 2},
    "metadata_values": {"fields": ["split"]},
    "collocation_network": {"term": "der", "max_nodes": 5},
    "keyness": {"target_context_query": 'cql:[word="der"]',
                "context_window": 5, "min_freq": 5},
    "word_sketch": {"term": "der"},
    "trend_analysis": {"date_field": "split", "query": "der"},
    "run_cqlf_query": {"query": '[word="der"]', "ctx": 5},
    "kwic_context": {"query": "der", "ctx": 5, "top_n": 3},
    "ngram_frequency": {"n": 2, "top_n": 3},
    "list_docsets": {},
    "document_text": {"doc_id": 0},
    "resolve_subcorpus": {"name": "gibtsnicht"},
    "documentation_search": {"query": "kollokation"},
}

# Exercise empty tool results as well as populated tables. An empty
# collocation response follows a separate envelope and must declare
# all its keys and required fields in the MCP response schema.
ARGUMENTE_OHNE_SUBSTANZ = {
    "query_count": {"query": "zzqxgibtesnicht"},
    "collocate_stats": {"term": "zzqxgibtesnicht", "window": 5, "min_freq": 0},
    "collocate_stats_mehrwort": {"term": "eine Rolle spielen", "window": 5,
                                 "min_freq": 0},
    "dispersion_offsets": {"term": "zzqxgibtesnicht"},
    "document_search": {"term": "zzqxgibtesnicht", "top_n": 2},
    "collocation_network": {"term": "zzqxgibtesnicht", "max_nodes": 5},
    "run_cqlf_query": {"query": '[word="zzqxgibtesnicht"]', "ctx": 5},
    "kwic_context": {"query": "zzqxgibtesnicht", "ctx": 5, "top_n": 3},
    "word_sketch": {"term": "zzqxgibtesnicht"},
}


# Ein Werkzeug kann MEHRERE Zweige haben, die verschiedene Umschlaege bauen.
# Die Haupttafel ruft jedes genau einmal und trifft dann nur einen davon.
# Am 2026-08-30 kostete das den fuenften Schemabruch dieses Projekts: keyness
# ueber DOCSETS setzt diagnostics.case_policy und row.surface_variants, der
# Kontext-Zweig (target_context_query) tut das nicht. Die Suite war gruen,
# und /mcp/call keyness lieferte HTTP 500 mit
# "Additional properties are not allowed ('case_policy' was unexpected)".
#
# Eintraege hier sind Fabriken, weil ein Docset erst gebaut werden muss.
def _keyness_ueber_docset():
    import numpy as np
    from candyconc.services.backend.docsets import _store_docset
    from candyconc.core import query_runtime as qr

    idx = qr._CORPUS_INDEX
    anzahl = len(idx.fast_index.doc_metadata)
    ziel = _store_docset("default", np.arange(0, min(40, anzahl), dtype=np.uint32), anzahl)
    return {"target_docset_id": ziel, "min_freq": 1, "sort_by": "ll_signed"}


ZWEITE_ZWEIGE = {
    "keyness": _keyness_ueber_docset,
}


def _echte_wrapper():
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    return _load_real_tool_wrappers()


@pytest.fixture(autouse=True)
def _korpus_zuruecksetzen():
    from candyconc.core import query_runtime as qr

    vorher = getattr(qr, "_CORPUS_INDEX", None)
    try:
        yield
    finally:
        qr._CORPUS_INDEX = vorher


def _werkzeuge_mit_schema():
    """(Name, Funktion, Schema) aus den DEKORATOREN im Quelltext.

    Die Schemanamen bilden die Werkzeugnamen nicht ab: COLLOCATE_RESPONSE
    gehoert zu collocate_stats, DISPERSION_RESPONSE zu
    dispersion_offsets, FREQUENCY_RESPONSE zu frequency_list. Eine
    Namenskonvention zu raten haette Werkzeuge stillschweigend
    uebersprungen und wie Abdeckung ausgesehen.

    Die REGISTRY waere die richtige Quelle, ist hier aber leer: der Lader
    fuer das echte Modul stellt sys.modules danach wieder her und rollt
    die Registrierungen mit zurueck. Deshalb wird der Dekorator im
    Quelltext gelesen. Das ist dieselbe Bindung, nur statisch.
    """
    import ast
    from pathlib import Path

    tw = _echte_wrapper()
    quelle = (Path(__file__).resolve().parents[2] / "src" / "candyconc"
              / "candyconc_copilot" / "tool_wrappers.py")
    baum = ast.parse(quelle.read_text(encoding="utf-8"))
    heraus = []
    for knoten in baum.body:
        if not isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deko in knoten.decorator_list:
            if not isinstance(deko, ast.Call):
                continue
            if getattr(deko.func, "id", None) != "llm_tool":
                continue
            if len(deko.args) < 2 or not isinstance(deko.args[1], ast.Name):
                continue
            schema = getattr(tw, deko.args[1].id, None)
            fn = getattr(tw, knoten.name, None)
            if isinstance(schema, dict) and callable(fn):
                name = knoten.name
                if name.endswith("_tool"):
                    name = name[: -len("_tool")]
                heraus.append((name, fn, schema))
    return heraus


def test_die_aufzaehlung_findet_werkzeuge():
    paare = _werkzeuge_mit_schema()
    assert len(paare) >= 8, [n for n, *_ in paare]
    namen = {n for n, *_ in paare}
    for pflicht in ("collocate_stats", "contrast_collocates", "dispersion_offsets"):
        assert pflicht in namen, (pflicht, sorted(namen))


def test_jede_antwort_erfuellt_ihr_eigenes_schema():
    from jsonschema import ValidationError, validate

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    tw = _echte_wrapper()

    # Kontrast braucht zwei Docsets, die hier entstehen.
    ziel = tw.create_docset_tool(filters={"split": "test"}, label="T")
    referenz = tw.create_docset_tool(filters={"split": "train"}, label="R")
    argumente = dict(ARGUMENTE)
    argumente["contrast_collocates"] = {
        "term": "der",
        "target_docset_id": ziel["docset_id"],
        "reference_docset_id": referenz["docset_id"],
        "window": 5, "top_n": 5,
    }
    argumente["create_docset"] = {"filters": {"split": "test"}}

    geprueft, verletzt, uebersprungen = [], [], []
    for name, fn, schema in _werkzeuge_mit_schema():
        if name not in argumente:
            uebersprungen.append(name)
            continue
        try:
            ergebnis = fn(**argumente[name])
        except Exception as exc:
            uebersprungen.append(f"{name} ({type(exc).__name__})")
            continue
        try:
            validate(ergebnis, schema)
            geprueft.append(name)
        except ValidationError as exc:
            verletzt.append(f"{name}: {exc.message}")

    assert not verletzt, (
        "Diese Werkzeuge liefern Felder, die ihr eigenes Antwortschema "
        "verbietet. Auf der MCP-Route wird daraus HTTP 500: "
        + "; ".join(verletzt)
    )
    # Ohne positive Klasse prueft der Test nichts.
    assert len(geprueft) >= 6, (geprueft, uebersprungen)
    assert "contrast_collocates" in geprueft, (geprueft, uebersprungen)
    assert "dispersion_offsets" in geprueft, (geprueft, uebersprungen)
    # Die Auslassungen werden GENANNT. Ein Test, der stillschweigend
    # ueberspringt, sieht aus wie Abdeckung und ist keine.
    print(f"\ngeprueft ({len(geprueft)}): {sorted(geprueft)}")
    print(f"uebersprungen ({len(uebersprungen)}): {sorted(uebersprungen)}")


def test_auch_der_leere_zweig_haelt_sein_schema():
    """Empty and degenerate responses must satisfy the same schema as populated tables."""
    from jsonschema import ValidationError, validate

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)

    geprueft, verletzt, uebersprungen = [], [], []
    for name, fn, schema in _werkzeuge_mit_schema():
        for schluessel, argumente in ARGUMENTE_OHNE_SUBSTANZ.items():
            if schluessel != name and not schluessel.startswith(name + "_"):
                continue
            try:
                ergebnis = fn(**argumente)
            except Exception as exc:
                uebersprungen.append(f"{schluessel} ({type(exc).__name__})")
                continue
            try:
                validate(ergebnis, schema)
                geprueft.append(f"{schluessel}:{ergebnis.get('status')}")
            except ValidationError as exc:
                verletzt.append(f"{schluessel}: {exc.message}")

    assert not verletzt, (
        "Diese Werkzeuge brechen ihr eigenes Schema, sobald nichts gefunden "
        "wird. Auf der MCP-Route wird daraus HTTP 500: " + "; ".join(verletzt)
    )
    # Positive Klasse: der leere Zweig muss WIRKLICH betreten worden sein,
    # sonst besteht der Test auch auf lauter Erfolgsantworten.
    leere = [g for g in geprueft if g.endswith(":empty")]
    assert leere, (
        "Kein Aufruf hat den leeren Zweig erreicht, der Test prueft nichts. "
        f"geprueft: {geprueft}"
    )
    assert any(g.startswith("collocate_stats_mehrwort") for g in geprueft), geprueft
    print(f"\ngeprueft ({len(geprueft)}): {sorted(geprueft)}")
    print(f"uebersprungen ({len(uebersprungen)}): {sorted(uebersprungen)}")


def test_jeder_zweite_zweig_haelt_sein_schema():
    """Der Zweig, den die Haupttafel nicht betritt.

    Nicht der leere Zweig (den prueft der Test darueber), sondern ein ANDERER
    vollwertiger Pfad desselben Werkzeugs. Bei keyness ist das der Weg ueber
    Docsets: er zaehlt am Korpus, faltet dabei ueber str.casefold und legt das
    in diagnostics.case_policy und row.surface_variants offen. Der
    Kontext-Zweig tut nichts davon, und genau deshalb blieb der Bruch
    unentdeckt.
    """
    from jsonschema import ValidationError, validate

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)

    geprueft, verletzt = [], []
    for name, fn, schema in _werkzeuge_mit_schema():
        fabrik = ZWEITE_ZWEIGE.get(name)
        if fabrik is None:
            continue
        ergebnis = fn(**fabrik())
        try:
            validate(ergebnis, schema)
            geprueft.append(name)
        except ValidationError as exc:
            verletzt.append(f"{name}: {exc.message}")

    assert geprueft, "Kein zweiter Zweig gefahren, der Test misst nichts"
    assert verletzt == [], (
        "Diese Zweige liefern Schluessel, die ihr eigenes Schema verbietet. "
        "Auf der MCP-Route wird daraus HTTP 500: " + "; ".join(verletzt)
    )


def test_der_docset_zweig_legt_die_faltung_offen():
    """Der Zweig muss die Angabe auch WIRKLICH tragen, nicht nur duerfen.

    Ein Schema, das ``case_policy`` erlaubt, und ein Zweig, der es weglaesst,
    saehen beide gruen aus. Der Leser braucht die Angabe.
    """
    import numpy as np

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    tw = _echte_wrapper()
    ergebnis = tw.keyness_tool(**_keyness_ueber_docset())

    # The prior label implied casefold, but sharp s and ss stay distinct.
    assert ergebnis["diagnostics"]["case_policy"] == "case_insensitive (lowercase)"

    zeilen = ergebnis["rows"]
    mit = [z for z in zeilen if z.get("surface_variants")]
    assert mit, (
        "Keine Zeile nennt ihre Schreibungen. Auf diesem Index tragen 882 von "
        "11.355 Faltklassen mehr als eine, das kann nicht null sein."
    )
    for zeile in mit:
        teile = zeile["surface_variants"]
        assert set(teile) <= {"target", "reference"}
        for seite, schreibungen in teile.items():
            assert schreibungen, f"{zeile['word']}: leere Aufschluesselung fuer {seite}"
            feld = "target_freq" if seite == "target" else "reference_freq"
            assert sum(schreibungen.values()) == zeile[feld], (
                f"{zeile['word']}: die Schreibungen summieren nicht auf {feld}"
            )


def test_ein_etikett_das_nichts_traegt_wird_aufgeschluesselt():
    """A displayed label can contribute zero occurrences in the docset.

Check this case even when the class has just one observed spelling.
The representative label may name a different spelling."""
    from candyconc.core.corpus_index import CorpusIndex

    idx = CorpusIndex(_BENCH)
    gefunden = []
    for dok in range(min(60, len(idx.fast_index.doc_metadata))):
        teile = {}
        idx.frequency_counts_docset([dok], attr="word", case_fold=True, variants_out=teile)
        gefunden += [rep for rep, gruppe in teile.items() if rep not in gruppe]
        if gefunden:
            break
    assert gefunden, (
        "Kein Fall gefunden, in dem das Etikett im Docset nichts traegt. "
        "Auf diesem Index gibt es sie (Dok 1: 'Sie' meldet 3, traegt 0)."
    )

