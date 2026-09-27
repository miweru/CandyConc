# -*- coding: utf-8 -*-
"""Die Bezugsgroesse einer n-Gramm-Rate ist keine Tokenzahl.

Ein Dokument der Laenge L traegt ``L - n + 1`` Positionen der Ordnung n,
und ein Dokument kuerzer als n traegt keine. ``_ngram_counts`` zaehlt
bereits innerhalb der Dokumentgrenzen, die Zaehlung war also richtig und
nur der Nenner falsch: beide Nahtstellen teilten durch die Tokenzahl.

Am Testindex gemessen, mit demselben Helfer, den der Produktivpfad zum
Zaehlen benutzt::

    n=2   54.191 Positionen gegen 56.191 Tokens    3,69 Prozent zu gross
    n=3   52.191                                   7,66
    n=5   48.191                                  16,60

Das Entscheidende ist nicht die Groesse des Fehlers, sondern seine
Unsymmetrie. Er haengt am Anteil kurzer Dokumente, faellt also fuer Ziel-
und Referenzmenge VERSCHIEDEN aus und verschiebt damit die Differenz
selbst, nicht nur beide Raten gemeinsam. Bei einem Kontrast Merkel gegen
Verben waren es 2,83 gegen 2,64 Prozent.

Geprueft wird dreierlei: dass der Nenner an der ORDNUNG haengt und nicht am
Aufruf, dass die Rate aus der Antwort selbst nachrechenbar ist, und dass
Copilot und REST auf denselben Wert kommen.
"""

from __future__ import annotations

import asyncio
import os

import numpy as np
import pytest

from candyconc.services.backend import server as S

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
needs_bench = pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_die_stellenzahl_haelt_einer_eigenen_rechnung_stand():
    """Unabhaengig aus den Dokumentlaengen nachgerechnet."""
    from candyconc.core import query_runtime as qr

    idx = qr._CORPUS_INDEX
    from candyconc.services.backend.doc_meta import _doc_count_for_index

    doc_ids = np.arange(_doc_count_for_index(idx), dtype=np.uint32)
    starts, ends, _ = idx._doc_ranges_for_ids(doc_ids)
    laengen = np.asarray(ends, dtype=np.int64) - np.asarray(starts, dtype=np.int64)

    stellen = S._ngram_populations(idx, None, 1, 5)
    for n in range(1, 6):
        erwartet = int(np.maximum(laengen - (n - 1), 0).sum())
        assert stellen[n] == erwartet, f"n={n}"
    # Die Tokenzahl ist NUR fuer n=1 die richtige Bezugsgroesse.
    tokens = int(idx.token_count())
    assert stellen[1] == tokens
    assert stellen[2] < tokens, "Sonst waere der ganze Befund gegenstandslos."


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_der_nenner_haengt_an_der_ordnung_nicht_am_aufruf():
    """Ein Aufruf liefert min_n bis max_n zugleich, mit je eigenem Nenner."""
    ziel = tw.create_docset_tool(query='cql:[word="Merkel"]')["docset_id"]
    referenz = tw.create_docset_tool(query='cql:[pos="VERB"]')["docset_id"]
    ergebnis = tw.ngram_contrast_tool(
        target_docset_id=ziel, reference_docset_id=referenz, min_n=2, max_n=3
    )
    stellen = {z["n"]: z for z in ergebnis["populations"]}
    assert set(stellen) == {2, 3}
    assert stellen[3]["target"] < stellen[2]["target"], (
        "Trigramme haben weniger Positionen als Bigramme. Gleiche Nenner "
        "hiessen: der Nenner haengt am Aufruf statt an der Ordnung."
    )
    assert stellen[3]["reference"] < stellen[2]["reference"]


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_die_rate_ist_aus_der_antwort_selbst_nachrechenbar():
    """Ohne ausgewiesenen Nenner ist eine Rate nicht pruefbar."""
    ziel = tw.create_docset_tool(query='cql:[word="Merkel"]')["docset_id"]
    referenz = tw.create_docset_tool(query='cql:[pos="VERB"]')["docset_id"]
    ergebnis = tw.ngram_contrast_tool(
        target_docset_id=ziel, reference_docset_id=referenz, min_n=2, max_n=3
    )
    stellen = {z["n"]: z for z in ergebnis["populations"]}
    assert ergebnis["rows"], "Ohne Zeilen prueft dieser Test nichts."
    for zeile in ergebnis["rows"][:25]:
        n = int(zeile["n"])
        for seite, feld in (("target", "freq_target"), ("reference", "freq_reference")):
            nenner = stellen[n][seite]
            erwartet = zeile[feld] * 1_000_000.0 / nenner if nenner else 0.0
            assert abs(erwartet - zeile[f"per_million_{seite}"]) < 1e-3, (
                f"{zeile['ngram']} ({seite}): {zeile[f'per_million_{seite}']} "
                f"laesst sich nicht aus {zeile[feld]} und {nenner} herstellen."
            )


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_copilot_und_rest_kommen_auf_dieselbe_rate():
    """Der vorhandene Paritaetstest vergleicht Reihenfolge, nicht die Werte."""
    ziel = tw.create_docset_tool(query='cql:[word="Merkel"]')["docset_id"]
    referenz = tw.create_docset_tool(query='cql:[pos="VERB"]')["docset_id"]
    _, ziel_ids = tw._resolve_docset_doc_ids(None, ziel)
    _, ref_ids = tw._resolve_docset_doc_ids(None, referenz)
    copilot = tw.ngram_contrast_tool(
        target_docset_id=ziel, reference_docset_id=referenz, min_n=2, max_n=2, limit=40
    )

    async def _rest():
        auftrag = S.analysis_jobs.create("ngrams_diff", "default", {})
        await S._run_ngrams_diff_job(
            auftrag.job_id, corpus=None, min_n=2, max_n=2,
            target_doc_ids=ziel_ids, reference_doc_ids=ref_ids,
            limit=40, min_freq=1,
        )
        return S.analysis_jobs.get(auftrag.job_id).result or {}

    rest = asyncio.run(_rest())
    rest_raten = {
        z["ngram"]: (z["target_per_million"], z["reference_per_million"])
        for z in rest["rows"]
    }
    verglichen = 0
    for zeile in copilot["rows"]:
        gegen = rest_raten.get(zeile["ngram"])
        if gegen is None:
            continue
        verglichen += 1
        assert abs(zeile["per_million_target"] - gegen[0]) < 1e-3, zeile["ngram"]
        assert abs(zeile["per_million_reference"] - gegen[1]) < 1e-3, zeile["ngram"]
    assert verglichen >= 5, f"Nur {verglichen} gemeinsame n-Gramme, das prueft nichts."
    # Und der REST-Methodenblock sagt, woraus gerechnet wurde.
    methode = rest.get("method") or {}
    zusatz = methode.get("extra") or methode
    assert zusatz.get("rate_basis") == "ngram_positions_per_order", methode
    assert str(2) in (zusatz.get("ngram_positions_target") or {}), methode
