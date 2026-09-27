# -*- coding: utf-8 -*-
"""Das Docset-Profil nennt Tokenanteile, und mehr als den groessten Wert.

Zwei Maengel derselben Zeile. ``docset_profile`` zaehlte je Achse die
DOKUMENTE und wies den Anteil des groessten Werts aus, waehrend jeder andere
Nenner dieses Hauses in Token rechnet. Und ein einzelner groesster Wert sagt
nichts ueber die Verteilung: 51 Prozent und 99 Prozent sehen in dieser Zeile
gleich aus, sind aber verschiedene Korpora.

Wie gross der Unterschied wird, haengt daran, ob die Dokumente einer
Kategorie laenger sind als die der anderen. Am Testindex, Docset
``[word="Merkel"]``, Achse ``split``::

    Dokumentanteil train   83,9 Prozent
    Tokenanteil    train   63,6 Prozent

Zwanzig Prozentpunkte, weil die train-Dokumente dieses Docsets kuerzer sind.
Wer "train dominiert mit 83,9 Prozent" liest, zieht einen anderen Schluss als
bei 63,6.

Die ``konstant:``-Form bleibt UNVERAENDERT. ``grounding_contrast``
liest sie, um aus konstanten Metadatenwerten den NAMEN einer Kontrastseite zu
bilden. Wer sie aendert, macht aus benannten Seiten wieder "Seite A" und
"Seite B", und das ist der Rueckschritt, den diese Datei mit verhindert.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
needs_bench = pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


def _eigene_anteile(idx, doc_ids, feld):
    """Token- und Dokumentanteile unabhaengig vom Pruefobjekt."""
    starts, ends, _ = idx._doc_ranges_for_ids(doc_ids)
    laengen = np.asarray(ends, dtype=np.int64) - np.asarray(starts, dtype=np.int64)
    meta = idx.fast_index.doc_metadata
    tokens: dict[str, int] = {}
    dokumente: dict[str, int] = {}
    for lauf, doc in enumerate(np.asarray(doc_ids, dtype=np.int64).tolist()):
        wert = (meta.get(int(doc)) or {}).get(feld)
        if wert is None:
            continue
        name = str(wert)
        tokens[name] = tokens.get(name, 0) + int(laengen[lauf])
        dokumente[name] = dokumente.get(name, 0) + 1
    t = float(sum(tokens.values())) or 1.0
    d = float(sum(dokumente.values())) or 1.0
    return (
        {k: round(100.0 * v / t, 1) for k, v in tokens.items()},
        {k: round(100.0 * v / d, 1) for k, v in dokumente.items()},
    )


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_die_anteile_sind_tokenanteile_und_nicht_dokumentanteile():
    from candyconc.core import query_runtime as qr

    idx = qr._CORPUS_INDEX
    docset = tw.create_docset_tool(query='cql:[word="Merkel"]')
    _, ids = tw._resolve_docset_doc_ids(None, docset["docset_id"])
    token_anteile, dok_anteile = _eigene_anteile(idx, ids, "split")

    zeile = docset["profile"]["axes"]["split"]
    assert "Tokenanteile" in zeile, zeile
    for name, anteil in token_anteile.items():
        assert f"{name} {anteil}%" in zeile, (name, anteil, zeile)
    # Und die Dokumentanteile stehen dort NICHT mehr. Ohne diese Probe
    # koennte der Test auf einem Korpus bestehen, auf dem beide gleich sind.
    unterschiedlich = [
        n for n in token_anteile if abs(token_anteile[n] - dok_anteile.get(n, 0)) > 1.0
    ]
    assert unterschiedlich, (
        "Auf diesem Docset trennen sich Token- und Dokumentanteil nicht, "
        "der Test kann den Unterschied dann nicht nachweisen."
    )
    for name in unterschiedlich:
        assert f"{name} {dok_anteile[name]}%" not in zeile, (name, zeile)


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_der_anteil_ist_gegen_das_gemeldete_token_count_nachrechenbar():
    """Ohne Nenner ist ein Prozentwert nicht pruefbar."""
    from candyconc.core import query_runtime as qr

    idx = qr._CORPUS_INDEX
    docset = tw.create_docset_tool(query='cql:[word="Merkel"]')
    _, ids = tw._resolve_docset_doc_ids(None, docset["docset_id"])
    starts, ends, _ = idx._doc_ranges_for_ids(ids)
    summe = int(
        (np.asarray(ends, dtype=np.int64) - np.asarray(starts, dtype=np.int64)).sum()
    )
    assert summe == int(docset["token_count"]), (
        "Der Nenner der Anteile ist genau das ausgewiesene token_count. "
        "Faellt das auseinander, ist der Prozentwert nicht nachrechenbar."
    )


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_mehr_als_der_groesste_wert_steht_da():
    docset = tw.create_docset_tool(query='cql:[word="Merkel"]')
    zeile = docset["profile"]["axes"]["split"]
    assert zeile.count("%") >= 2, (
        f"Nur ein Anteil in der Zeile: {zeile}. 51 und 99 Prozent saehen "
        "dann gleich aus."
    )


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_die_konstant_form_bleibt_wie_sie_war():
    """Der Vertrag mit grounding_contrast.kontrastseiten_benennen."""
    docset = tw.create_docset_tool(query='cql:[word="Merkel"]')
    achsen = docset["profile"]["axes"]
    konstante = [w for w in achsen.values() if w.startswith("konstant: ")]
    assert konstante, "Ohne konstante Achse prueft dieser Test nichts."
    assert achsen["register"] == "konstant: social"
