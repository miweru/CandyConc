# -*- coding: utf-8 -*-
"""Plain word search discloses its case normalization."""

import os

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not (_BENCH and os.path.isdir(_BENCH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


@pytest.fixture(scope="module")
def wrapper():
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers
    vorher = getattr(qr, "_CORPUS_INDEX", None)
    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    try:
        yield _load_real_tool_wrappers()
    finally:
        qr._CORPUS_INDEX = vorher


def test_gefalteter_term_nennt_seine_schreibungen(wrapper):
    r = wrapper.query_count_tool("Arm", case_insensitive=True)
    faltung = r.get("schreibung_gefaltet")
    assert isinstance(faltung, dict) and len(faltung) >= 2, r
    # Die Aufteilung SUMMIERT sich zur gemeldeten Zahl — sonst wäre sie
    # eine Behauptung ueber eine andere Rechenebene.
    assert sum(faltung.values()) == r["total"], (faltung, r["total"])
    assert "arm" in faltung, faltung


def test_strenge_zaehlung_nennt_keine_faltung(wrapper):
    r = wrapper.query_count_tool("Arm", case_insensitive=False)
    assert "schreibung_gefaltet" not in r, r.get("schreibung_gefaltet")


def test_einschreibung_und_streifsuche_nennen_kein_feld(wrapper):
    """Kein Feld ist kein Mangel: eine Klasse mit einer Schreibung hat
    nichts zu offenbaren, ein Term ohne Treffer ebensowenig."""
    leer = wrapper.query_count_tool("zzqxgibtesnicht")
    assert "schreibung_gefaltet" not in leer


def test_mehrwort_wird_als_eingabefehler_abgewiesen(wrapper):
    """Bestehende Werkzeugwahrheit, unveraendert: ein nackter Mehrwort-
    Ausdruck ist kein gueltiger Klartextterm."""
    from candyconc.candyconc_copilot.tool_errors import ToolInputError

    with pytest.raises(ToolInputError):
        wrapper.query_count_tool("eine Rolle spielen")


def test_gefallte_zahl_erklaert_den_unter_schied_zur_strengen(wrapper):
    """Der Modell-Sicht-Fall aus dem Pilotlauf: zwei Zahlen, kein
    Widerspruch mehr — die gefaltete Totalzahl und die strenge Zahl der
    einzelnen Schreibung stehen in EINEM Antwortummschlag."""
    gefaltet = wrapper.query_count_tool("Arm", case_insensitive=True)
    streng = wrapper.query_count_tool("arm", case_insensitive=False)
    anteil = gefaltet["schreibung_gefaltet"].get("arm")
    assert anteil is not None
    # Die strenge Zahl ist kein Geheimnis mehr: sie steht als Anteil in
    # der gefalteten Antwort.
    assert streng["total"] == anteil, (streng["total"], anteil)


def test_der_helfer_greift_nicht_bei_phrase_und_zeichen():
    """Phrasen, CQL und Interpunktion gehören nicht zur Faltklasse eines
    nackten Terms; der Index darf bei ihnen nie gefragt werden."""
    from candyconc.candyconc_copilot.keyness_count_level import (
        schreibungs_faltung,
    )

    class _idx_nie:
        def _casefold_ids(self, *a, **k):
            raise AssertionError("sollte nie gefragt werden")

    for term in ("eine Rolle spielen", 'cql:[word="der"]', "und?", '"Arm"'):
        assert schreibungs_faltung(
            _idx_nie(), term, case_insensitive=True, unscoped=True) == {}, term
