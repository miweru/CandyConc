"""Unknown metadata fields are rejected at every tool boundary.

Enumerate tools from the registry so a newly registered metadata-filter
consumer must validate its input just like document_search, metadata_values
and create_docset."""

from __future__ import annotations

import inspect
import os

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

#: Parameternamen, unter denen ein Werkzeug ROHE Metadatenfilter annimmt.
FILTERPARAMETER = ("filters", "metadata_filters", "meta_filters")

#: Ein Feldname, den kein Korpus dieses Projekts traegt.
UNBEKANNT = {"gibt_es_hier_nicht": "x"}

_WRAPPER = None


def _echte_wrapper():
    """Das ECHTE tool_wrappers-Modul, nicht die conftest-Attrappe.

    ``tests/conftest.py`` legt fuer BEIDE Importpfade einen Stub in
    ``sys.modules``. Ein Test, der ihn trifft, prueft die Attrappe und
    nicht das Produkt, und genau diese Verwechslung hat heute schon einmal
    zu einer falschen Erledigt-Meldung gefuehrt.
    """

    global _WRAPPER
    if _WRAPPER is None:
        from tests.ai.test_tool_wrappers_parity_r5 import (
            _load_real_tool_wrappers,
        )

        # GEMERKT, und das ist keine Optimierung. Der Lader importiert das
        # Modul bei jedem Aufruf NEU. Funktionen und Ausnahmeklasse kamen
        # damit aus verschiedenen Modulobjekten, und ``except
        # ToolInputError`` fing die geworfene ToolInputError nicht, weil es
        # eine andere Klasse war. Der Test meldete daraufhin, die Wache sei
        # nicht erreicht worden, obwohl sie zuschlug. Ein Test, der sich
        # selbst ins Knie schiesst, ist so wertlos wie einer, der immer
        # gruen ist.
        _WRAPPER = _load_real_tool_wrappers()
    return _WRAPPER


def _werkzeuge_mit_metadatenfiltern():
    """Alle Copilot-Werkzeuge, die einen rohen Metadatenfilter annehmen.

    Aufgezaehlt aus dem Modul, nicht fest benannt. Kommt ein viertes
    Werkzeug hinzu, faellt der Test, bis es die Wache hat.
    """

    tw = _echte_wrapper()
    gefunden = []
    for name in dir(tw):
        if not name.endswith("_tool"):
            continue
        fn = getattr(tw, name, None)
        if not callable(fn):
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        treffer = [p for p in FILTERPARAMETER if p in sig.parameters]
        if treffer:
            gefunden.append((name, fn, treffer[0], sig))
    return gefunden


def test_die_aufzaehlung_findet_ueberhaupt_werkzeuge():
    """Positive Klasse. Findet die Aufzaehlung nichts, prueft der Test nichts."""

    gefunden = _werkzeuge_mit_metadatenfiltern()
    assert len(gefunden) >= 3, [n for n, *_ in gefunden]
    namen = {n for n, *_ in gefunden}
    for pflicht in ("create_docset", "document_search", "metadata_values"):
        assert any(pflicht in n for n in namen), (pflicht, sorted(namen))


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
def test_jedes_werkzeug_weist_ein_unbekanntes_feld_ab():
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    ToolInputError = _echte_wrapper().ToolInputError

    still: list[str] = []
    geprueft: list[str] = []
    anders: list[str] = []
    for name, fn, parameter, sig in _werkzeuge_mit_metadatenfiltern():
        argumente = {parameter: dict(UNBEKANNT)}
        # Pflichtargumente ohne Vorgabewert minimal befuellen, damit der
        # Aufruf ueberhaupt bis zur Wache kommt.
        for pname, p in sig.parameters.items():
            if p.default is not inspect.Parameter.empty or pname in argumente:
                continue
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            argumente[pname] = "und"
        try:
            fn(**argumente)
        except ToolInputError:
            geprueft.append(name)
            continue
        except Exception as exc:
            # Ein anderer Fehler ist kein stiller Erfolg, aber auch kein
            # Nachweis der Wache. Er wird getrennt gefuehrt, sonst zaehlt
            # ein fehlendes Pflichtargument als bestandene Pruefung, und
            # der Test waere selbst ein Artefakt.
            anders.append(f"{name}: {type(exc).__name__}")
            continue
        still.append(name)

    assert not still, (
        "Diese Werkzeuge schlucken ein unbekanntes Metadatenfeld still und "
        "melden Erfolg: " + ", ".join(still) + ". Ein unbekanntes Feld "
        "trifft nichts, das Ergebnis sieht aber wie ein Befund aus."
    )
    # Die drei bekannten Naehte muessen die Wache NACHWEISLICH erreichen,
    # nicht bloss irgendwie scheitern.
    for pflicht in ("create_docset_tool", "document_search_tool",
                    "metadata_values_tool"):
        assert pflicht in geprueft, (
            f"{pflicht} hat die Wache nicht erreicht. Geprueft: {geprueft}, "
            f"anders gescheitert: {anders}"
        )


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
def test_gueltige_felder_werden_nicht_abgewiesen():
    """Der teuerste Regressionsfall.

    Der Meta-Index meldet WENIGER Felder als die Dokumente tragen. Eine
    Vorfassung der Wache wies deshalb gueltige Filter ab, und eine
    Reparatur, die gueltige Filter bricht, ist schlimmer als der Defekt,
    den sie schliesst.

    Seit dem 2026-09-18 urteilt die Wache auch ueber WERTE (Diagnose
    Lauf 3, Naht 4: {'model': 'ai'} lieferte success mit 0 Dokumenten).
    Der fruehere Platzhalter „irgendwas" ist auf einer kategorialen Achse
    wie model daher kein neutraler Wert mehr, sondern ein ungueltiger
    Filter. Geprueft wird jetzt Feld UND Wert: jeder Wert kommt aus dem
    echten Inventar des Felds. Ein Feld ohne Wertvorrat bleibt unpruefbar
    und wird uebersprungen.
    """

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    tw = _echte_wrapper()
    ToolInputError = tw.ToolInputError
    pruefe_metadatenfelder = tw.pruefe_metadatenfelder

    idx = qr._CORPUS_INDEX
    from candyconc.core.meta_filters import metadata_fields, metadata_values

    felder = metadata_fields(idx)
    assert felder, "ohne bekannte Felder prueft dieser Test nichts"
    for feld in felder:
        werte = metadata_values(idx, feld)
        if not werte:
            continue
        try:
            pruefe_metadatenfelder(idx, {feld: werte[0]})
        except ToolInputError as exc:  # pragma: no cover
            pytest.fail(
                f"gueltiges Feld {feld!r} mit gueltigem Wert "
                f"{werte[0]!r} abgewiesen: {exc}"
            )


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
def test_ohne_filter_greift_die_wache_nicht():
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    pruefe_metadatenfelder = _echte_wrapper().pruefe_metadatenfelder

    for leer in (None, {}, ):
        pruefe_metadatenfelder(qr._CORPUS_INDEX, leer)
