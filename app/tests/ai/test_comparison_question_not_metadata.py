"""Wer nach sprachlichen Unterschieden fragt, will keine Feldliste.

LIVE GESEHEN am 2026-08-31, 15:16. Die Frage

    "Schau dir mal das Verhalten der unterschiedlichen Modelle fuer einen
     Text an und analysiere die sprachlichen Unterschiede."

fuehrte zu zwei ``metadata_values``-Aufrufen und nach 502,3 Sekunden zu
einem Inventar der Metadatenfelder: wie viele Werte ``model``, ``variant``
und ``profile_name`` haben. Kein Wort aus dem Korpus. Die Antwort schrieb
in ihre eigenen Limitationen:

    "Ohne sichtbare Textinhalte lassen sich aus diesen Fakten keine
     konkreten sprachlichen Unterschiede zwischen Modellen ableiten."

Sie stellte also fest, dass sie die Frage nicht beantwortet hatte, und
lieferte trotzdem.

URSACHE. ``_metadata_request_is_focused`` hat ZWEI Tore. Das erste loest
bei einem Metadatenwort aus, und "Modelle" ist eines. Das zweite holt die
Frage wieder heraus, wenn sie ein VERFAHREN beim Namen nennt: frequenz,
kwic, kollok, keyness, dispersion, ngram, word sketch, semantik,
embedding.

So fragt niemand. Eine Fachperson schreibt nicht "mach mir eine Keyness",
sie schreibt "analysiere die sprachlichen Unterschiede". Damit war jede
Frage, die "Modell" oder "Register" sagt und kein Werkzeug nennt, ein
Feldinventar.

Der Nutzer hat es so zusammengefasst: der Harnisch bezieht sich auf
Belegbarkeit statt auf die Frage.
"""

from __future__ import annotations

import pytest

from candyconc.candyconc_copilot.grounding_contracts import (
    heuristic_analysis_contract,
    select_recipe,
)

WERKZEUGE = (
    "metadata_values", "keyness", "contrast_collocates", "collocate_stats",
    "frequency_list", "run_cqlf_query", "query_count", "create_docset",
    "list_docsets", "ngram_contrast", "ngram_frequency", "document_search",
    "document_text", "dispersion_offsets", "lexical_diversity", "word_sketch", "compare_collocates",
)

#: Fragen nach einer ANALYSE. Sie nennen ein Metadatenwort, meinen es aber
#: als Scope und nicht als Ergebnis.
ANALYSE = [
    "Schau dir mal das Verhalten der unterschiedlichen Modelle für einen "
    "Text an und analysiere die sprachlichen Unterschiede.",
    "Vergleiche die Modelle stilistisch.",
    "Worin unterscheiden sich die KI-Modelle sprachlich vom Menschen?",
    "Wie schreibt gpt-5.2 anders als der Mensch?",
    "Was ist typisch für die Wortwahl im Register easy_language?",
    "Gibt es Eigenheiten der einzelnen Quellen im Sprachgebrauch?",
]

#: Fragen nach dem INVENTAR. Hier ist die Feldliste die Antwort.
INVENTAR = [
    "Welche Register gibt es im Korpus?",
    "Welche Modelle sind im Korpus enthalten?",
    "Zeig mir die Metadatenfelder.",
    "Welche Quellen hat das Korpus?",
    "Welche Werte hat das Feld source?",
]


@pytest.mark.parametrize("frage", ANALYSE)
def test_die_analysefrage_erreicht_nicht_den_metadatenvertrag(frage):
    """Die NAHT, nicht nur der Helfer.

    Geprueft wird der ganze Vertragsentscheid, denn ein Helfer, der richtig
    antwortet, sagt noch nichts darueber, welchen Werkzeugsatz der Turn
    bekommt.
    """
    vertrag = heuristic_analysis_contract(
        frage, available_tools=WERKZEUGE, read_only_tools=WERKZEUGE
    )
    familie = getattr(vertrag, "analysis_family", None)
    assert familie != "metadata_capability", (
        f"{frage!r} bekommt weiterhin nur Metadatenwerkzeuge: "
        f"{list(getattr(vertrag, 'allowed_tools', []))}"
    )


@pytest.mark.parametrize("frage", INVENTAR)
def test_die_inventarfrage_bekommt_weiterhin_ihren_vertrag(frage):
    vertrag = heuristic_analysis_contract(
        frage, available_tools=WERKZEUGE, read_only_tools=WERKZEUGE
    )
    assert getattr(vertrag, "analysis_family", None) == "metadata_capability", frage


@pytest.mark.parametrize("frage", ANALYSE)
def test_die_analysefrage_bekommt_ein_analyserezept(frage):
    """Und zwar bis zum Rezept, nicht nur bis zur Familie."""
    rezept = select_recipe(
        frage, {"available_tools": WERKZEUGE, "read_only_tools": WERKZEUGE}
    )
    assert getattr(rezept, "id", None) != "metadaten_struktur", (
        f"{frage!r} bekommt weiterhin das Metadatenrezept."
    )
