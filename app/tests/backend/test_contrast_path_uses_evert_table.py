"""The contrast and collocation paths use the same contingency table."""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not (_BENCH and os.path.isdir(_BENCH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


@pytest.fixture(scope="module")
def kontrast():
    """Zeilen UND die Basis, aus der sie entstanden sind.

    Die Basis wird im Durchlauf abgefangen, weil nur sie die Randsummen
    traegt. Ein Test, der die Zeilen gegen sich selbst prueft, prueft
    nichts.
    """
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.services.backend import server

    idx = CorpusIndex(_BENCH, read_only=True)
    md = idx.fast_index.doc_metadata
    ziel = np.array(
        [i for i in range(len(md)) if (md[i] or {}).get("split") == "test"],
        dtype=np.uint32)
    referenz = np.array(
        [i for i in range(len(md)) if (md[i] or {}).get("split") == "train"],
        dtype=np.uint32)
    assert ziel.size and referenz.size, "Testindex ohne split-Metadaten"

    gefangen = {}
    original = server._collocates_diff_rows_from_basis

    def _spion(*args, **kwargs):
        gefangen["basis"] = next(
            a for a in args if hasattr(a, "target_context_mass"))
        return original(*args, **kwargs)

    server._collocates_diff_rows_from_basis = _spion
    try:
        zeilen = server._collocates_diff_rows_for_term(
            idx, "der", target_doc_ids=ziel, reference_doc_ids=referenz,
            target_docset_key="T", reference_docset_key="R",
            window=5, within_sentence=False, sort_by="logdice", limit=30)
    finally:
        server._collocates_diff_rows_from_basis = original
    if isinstance(zeilen, tuple):
        zeilen = zeilen[0]
    return idx, gefangen["basis"], zeilen


def _paare(idx, basis, zeilen):
    """(O11, f(v), Zeile) je gelieferter Zeile auf der Zielseite."""
    lex = idx.fast_index.lexicons.word
    ids = list(basis.word_ids)
    heraus = []
    for z in zeilen:
        wid = lex.get_id(z["word"])
        if wid not in ids:
            continue
        i = ids.index(wid)
        o11 = float(basis.target_observed[i])
        if o11 <= 0:
            continue
        heraus.append((o11, float(basis.target_freqs[i]), z))
    return heraus


def test_die_probe_ist_nicht_leer(kontrast):
    """Ohne Zeilen prueft alles Folgende nichts."""
    idx, basis, zeilen = kontrast
    paare = _paare(idx, basis, zeilen)
    assert len(paare) >= 10, len(paare)
    assert basis.target_match_count > 0
    assert basis.target_context_mass > basis.target_match_count


def test_logdice_ist_rychly_und_nicht_die_fensterformel(kontrast):
    idx, basis, zeilen = kontrast
    m = float(basis.target_match_count)
    r1 = float(basis.target_context_mass)
    rychly_treffer = fenster_treffer = paarraum_treffer = 0
    for o11, fv, z in _paare(idx, basis, zeilen):
        wert = float(z["target_score"])
        rychly = 14.0 + math.log2(2.0 * o11 / (m + fv))
        fenster = 14.0 + math.log2(2.0 * o11 / (r1 + fv))
        paarraum = 14.0 + math.log2(2.0 * o11 / (r1 + fv * m))
        rychly_treffer += abs(wert - rychly) < 5e-4
        fenster_treffer += abs(wert - fenster) < 5e-4
        paarraum_treffer += abs(wert - paarraum) < 5e-4
    gesamt = len(_paare(idx, basis, zeilen))
    assert rychly_treffer == gesamt, (rychly_treffer, gesamt)
    # AUSDRUECKLICHER AUSSCHLUSS. Ohne ihn waere der Test auch gruen, wenn
    # zwei Formeln zufaellig nahe beieinander laegen.
    assert fenster_treffer == 0, fenster_treffer
    assert paarraum_treffer == 0, paarraum_treffer


def test_per_million_ist_eine_tokenrate(kontrast):
    """Vorher war es eine Rate je Anker-Token-Paar.

    Fuer dieselbe Zeile stand 1,42 statt 581,6 in der Antwort, ein Faktor
    von m=409. Ziel- und Referenzseite wurden zudem durch VERSCHIEDENE m
    geteilt, womit diff_per_million als primaerer Rangschluessel zwei
    verschieden skalierte Groessen verglich.
    """
    idx, basis, zeilen = kontrast
    n = float(basis.target_token_total)
    m = float(basis.target_match_count)
    geprueft = 0
    for o11, _fv, z in _paare(idx, basis, zeilen):
        geprueft += 1
        assert abs(float(z["target_per_million"]) - o11 * 1e6 / n) < 1e-6
        # Und ausdruecklich NICHT die alte Groesse.
        assert abs(float(z["target_per_million"]) - o11 * 1e6 / (n * m)) > 1e-6
    assert geprueft >= 10


def test_die_randsummen_tragen_keine_ankermultiplikation_mehr():
    """Der Quelltextbeleg, ausgezaehlt statt geraten.

    Ein repo-weiter grep fand die Multiplikation NUR an dieser einen
    Stelle. Kommt sie zurueck, faellt dieser Test, bevor eine Golden-Datei
    sie wieder einfrieren kann.
    """
    from pathlib import Path

    quelle = Path(__file__).resolve().parents[2] / "src" / "candyconc"
    treffer = []
    for pfad in quelle.rglob("*.py"):
        text = pfad.read_text(encoding="utf-8", errors="ignore")
        for zeile in text.splitlines():
            if "target_multiplier" in zeile or "reference_multiplier" in zeile:
                treffer.append(f"{pfad.name}: {zeile.strip()}")
    assert not treffer, treffer


# --------------------------------------------------------------------------- #
# Ein Wort ist kein Kollokat von sich selbst.
# --------------------------------------------------------------------------- #

def test_der_cql_pfad_fuehrt_den_knoten_nicht_als_eigenes_kollokat():
    """Ein aelterer Defekt, den erst der LRC sichtbar gemacht hat.

    Der Klartextpfad der Engine schliesst den Knoten ueber
    ``_resolve_term_ids`` aus. Der CQL-Pfad geht von POSITIONEN aus und
    hatte kein Gegenstueck: fuer ``cql:[word="die"%c]`` standen "die" UND
    "Die" als Kollokate ihrer selbst in der Kandidatenliste.

    Aufgefallen ist es, weil die Kandidatenzahl dadurch abwich (284 gegen
    282) und der LRC ueber seine Bonferroni-Korrektur daran haengt: der
    Paritaetstest zwischen den beiden Schreibweisen fiel mit 0,1381 gegen
    0,1384. Alle anderen Masse hatten den Unterschied auf zwei
    Nachkommastellen verschluckt. Der Defekt ist aelter als der LRC und
    fachlich unabhaengig von ihm.

    Die Selbst-IDs werden aus den ANKERN gelesen, nicht aus dem
    Abfragetext: das gilt auch fuer Sequenzen und Muster, wo es keinen
    aufloesbaren Term gibt.
    """
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.services.backend import server

    idx = CorpusIndex(_BENCH, read_only=True)
    try:
        klartext = server._collocate_stats_for_term(
            idx, "die", window=5, within_sentence=False,
            sort_by="dice", doc_ids=None)
        gefaltet = server._collocate_stats_for_term(
            idx, 'cql:[word="die"%c]', window=5, within_sentence=False,
            sort_by="dice", doc_ids=None)
    finally:
        idx.close()

    for name, rahmen in (("klartext", klartext), ("cql", gefaltet)):
        selbst = [w for w in rahmen["word"].tolist() if str(w).lower() == "die"]
        assert not selbst, (name, selbst)

    # Und beide Schreibweisen liefern DIESELBEN Zahlen. Ohne diese Probe
    # waere der Selbstausschluss allein noch kein Beleg fuer Paritaet.
    a = {z["word"]: round(float(z["lrc"]), 6) for _, z in klartext.iterrows()}
    b = {z["word"]: round(float(z["lrc"]), 6) for _, z in gefaltet.iterrows()}
    gemeinsam = set(a) & set(b)
    assert len(gemeinsam) >= 100, len(gemeinsam)
    abweichend = [w for w in gemeinsam if a[w] != b[w]]
    assert not abweichend, abweichend[:5]
