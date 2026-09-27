"""Das Rangmass der zu replizierenden Publikation, endlich erreichbar.

Der LRC (Hardie 2014, konservative Variante nach Evert) stand frueher auf
der Kollokationsflaeche und wurde am 2026-08-18 MIT MESSUNG entfernt:

    "``observed`` ist auf BEIDEN Produktivpfaden der PAAR-gewichtete
     Kookkurrenzwert, waehrend die Korpusfrequenz ungewichtet ist. Die
     Differenz subtrahiert also zwei verschiedene Zaehlschemata
     voneinander. Am 142M-Index, Zeilen mit observed > Korpusfrequenz:
     Knoten 'der' 8.858 von 178.435, max O/F 4,5. Ein KORREKTES LRC
     braucht die union-gezaehlten Kookkurrenzen, also einen ZWEITEN
     Sweep. Es ist nicht gemacht."

Seit der Umstellung auf Everts Kontingenztafel liefert der ERSTE Sweep
sie. Der Grund fuer die Entfernung ist entfallen, ein zweiter Durchlauf
faellt nicht an, und b = f(v) - O11 ist nie negativ.

``conservative_log_ratio_arrays`` selbst ist unveraendert und gegen
Tabelle 1 der Publikation auf 0,006 validiert. Dieser Test prueft die
VERDRAHTUNG: kommt das Mass an der Werkzeugoberflaeche an, rechnet es
dort auf den richtigen Randsummen, und verhaelt es sich konservativ.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not (_BENCH and os.path.isdir(_BENCH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


@pytest.fixture(scope="module")
def rahmen():
    from candyconc.core.collocation_engine import CollocationEngine

    eng = CollocationEngine(_BENCH)
    eng.load()
    # within_sentence=True ist die Vorgabe der WERKZEUGoberflaeche. Ein
    # Vergleich mit der Engine-Vorgabe (False) liefert eine andere
    # Fenster-Vereinigung und damit andere Zahlen. Genau diese Verwechslung
    # hat mich am 2026-08-29 kurzzeitig einen Paritaetsdefekt sehen lassen,
    # den es nicht gab.
    return eng, eng.collocate_stats(
        "Merkel", min_count=3, within_sentence=True, cache_mode="off")


def test_beide_masse_stehen_in_der_tabelle(rahmen):
    _eng, df = rahmen
    assert not df.empty
    for spalte in ("log_ratio", "lrc"):
        assert spalte in df.columns, list(df.columns)


def test_lrc_rechnet_auf_everts_randsummen(rahmen):
    """Von Hand gegen eine unabhaengige Neuberechnung.

    a = O11, b = f(v) - O11, n1 = |W(u)|, n2 = N - |W(u)|. R1 wird aus
    der Distanztafel zurueckgewonnen: dice = 2*O11/(R1 + f(v)).
    """
    from candyconc.core.significance import conservative_log_ratio_arrays

    eng, df = rahmen
    lex = eng._get_lexicon("word")
    n = float(lex.total_tokens)
    geprueft = 0
    for _, z in df.head(12).iterrows():
        # f(v) kommt aus der ZEILE, nicht aus dem Lexikon ueber das gedruckte
        # Wort. Seit die Kollokatseite mit dem Knoten faltet, ist eine Zeile
        # eine Schreibungsklasse: f2 = 919 fuer die Klasse und/Und/UND,
        # waehrend das Lexikon fuer "und" 797 fuehrt. Wer am Lexikon
        # nachschlaegt, prueft eine andere Groesse als die, mit der die
        # Zeile gerechnet hat, und nennt die Uebereinstimmung dann Defekt.
        fv = float(z["f2"])
        o11 = float(z["observed"])
        if not fv or not z["dice"]:
            continue
        r1 = 2.0 * o11 / float(z["dice"]) - fv
        hand = conservative_log_ratio_arrays(
            np.array([o11]), np.array([max(fv - o11, 0.0)]),
            r1, n - r1, alpha=0.001, vocab=len(df))[0]
        assert abs(float(z["lrc"]) - hand) < 5e-4, (
            z["word"], z["lrc"], hand)
        geprueft += 1
    assert geprueft >= 8, geprueft


def test_b_ist_nie_negativ(rahmen):
    """Der Grund, aus dem das Mass frueher entfernt wurde.

    Union-gezaehlt gilt O11 <= f(v). Waere das verletzt, waere b negativ
    und der LRC eine Zahl ohne Bedeutung.
    """
    _eng, df = rahmen
    # Geprueft wird ZEILENLOKAL gegen f2, also gegen die Groesse, mit der die
    # Zeile wirklich gerechnet hat. Die Vorfassung schlug im Lexikon ueber das
    # gedruckte Wort nach. Seit die Kollokatseite faltet, ist das eine andere
    # Groesse: die Zeile "Durch" traegt O11=3 fuer ihre Klasse, waehrend die
    # Schreibung "Durch" einmal im Korpus steht. Die Vorfassung meldete das
    # als negatives b, obwohl die Tafel der Zeile stimmt.
    verletzt = [
        (z["word"], z["observed"], z["f2"])
        for _, z in df.iterrows()
        if z["f2"] and z["observed"] > z["f2"]
    ]
    assert not verletzt, verletzt[:5]


def test_lrc_verhaelt_sich_konservativ(rahmen):
    """Die EIGENSCHAFT, wegen der das Mass in der Publikation steht.

    Ein Kandidat mit weitem Intervall bekommt 0, statt nach oben zu
    rutschen. Ohne diese Pruefung waere jede Zahl "ein LRC".
    """
    _eng, df = rahmen
    # Es MUSS Nullen geben, sonst ist das Mass nicht konservativ: ein
    # weites Intervall, das die Null einschliesst, ergibt 0.
    assert (df["lrc"] == 0).any(), df["lrc"].describe()
    # Und es muss Nicht-Nullen geben, sonst prueft der Test nichts.
    assert (df["lrc"] != 0).any(), df["lrc"].describe()
    # LRC is signed. A negative value indicates a lower frequency near the
    # node than in the reference population, so requiring lrc >= 0 would
    # reject a valid result.
    assert (df["lrc"].abs() <= 40).all(), df["lrc"].abs().max()


def test_die_korrekturbasis_wird_ausgewiesen(rahmen):
    """Ohne sie ist der LRC nicht nachrechenbar.

    Die Bonferroni-Korrektur ist der einzige Schritt, der nicht aus den
    Randsummen der Zeile folgt. Ein Zwischenentwurf korrigierte ueber das
    Korpusvokabular (12.349 Typen), was bei 56 geprueften Paaren eine
    Ueberkorrektur ist: nur zwei Kandidaten ueberlebten.
    """
    _eng, df = rahmen
    assert df.attrs.get("lrc_vocab") == len(df), (
        df.attrs.get("lrc_vocab"), len(df))
    assert df.attrs.get("lrc_alpha") == 0.001


def test_engine_und_werkzeug_liefern_dieselben_werte(rahmen):
    """Zwei Flaechen, eine Zahl. Bei gleichen Parametern."""
    import os

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    _eng, df = rahmen
    vorher = getattr(qr, "_CORPUS_INDEX", None)
    try:
        qr._CORPUS_INDEX = CorpusIndex(_BENCH)
        tw = _load_real_tool_wrappers()
        ergebnis = tw.collocate_stats_tool(
            term="Merkel", window=5, min_freq=3, sort_by="lrc")
    finally:
        qr._CORPUS_INDEX = vorher
    engine_werte = {z["word"]: float(z["lrc"]) for _, z in df.iterrows()}
    verglichen = 0
    for zeile in ergebnis["rows"][:10]:
        if zeile["word"] not in engine_werte:
            continue
        verglichen += 1
        assert abs(engine_werte[zeile["word"]] - float(zeile["lrc"])) < 1e-9, (
            zeile["word"], engine_werte[zeile["word"]], zeile["lrc"])
    assert verglichen >= 5, verglichen


def test_die_rangfolge_nach_lrc_ist_fachlich_besser(rahmen):
    """Am Testindex gemessen, und der Unterschied ist der Punkt.

    Nach logDice steht "Vasallen" auf Rang 1 und "Angela" gar nicht oben.
    Nach LRC steht "Angela" vorn. LRC bestraft die weite Unsicherheit
    seltener Paare, und das ist keine Geschmacksfrage.

    DIE VORFASSUNG VERLANGTE "Kanzlerin" unter den ersten VIER nach lrc und
    pinnte damit eine Reihenfolge unter Gleichstaenden. Nachgemessen am
    2026-08-31: von 56 Zeilen tragen 51 den Wert lrc == 0.0 EXAKT, weil ihr
    Konfidenzintervall die Null einschliesst. Vier Zeilen sind trennbar, und
    zwei davon liegen auf demselben Wert:

        Angela    2.1293   O11=4 f2=4
        Vasallen  1.5200   O11=6 f2=15
        Vasall    0.0075   O11=3 f2=4
        Kanzlerin 0.0075   O11=3 f2=4     <- Gleichstand mit Vasall

    Die Aussage "Kanzlerin kommt dazu" stimmt also. Welchen der beiden
    Gleichstaende die Sortierung auf Platz 3 legt, ist keine Aussage ueber
    das Mass. Geprueft wird deshalb, WAS das Mass trennt und in welcher
    Groessenordnung, nicht die Reihenfolge der Ununterscheidbaren.
    """
    _eng, df = rahmen
    trennbar = df[df["lrc"] > 0].sort_values("lrc", ascending=False)
    namen = [str(w) for w in trennbar["word"].tolist()]
    # Die beiden klar trennbaren stehen vorn, und zwar in dieser Reihenfolge.
    assert namen[:2] == ["Angela", "Vasallen"], namen
    # Kanzlerin ist trennbar, aber im Gleichstand mit Vasall. Eine Zusicherung
    # ueber seinen PLATZ waere eine Zusicherung ueber die Sortierstabilitaet.
    assert set(namen) == {"Angela", "Vasallen", "Vasall", "Kanzlerin"}, namen
    werte = {str(z["word"]): float(z["lrc"]) for _, z in trennbar.iterrows()}
    assert werte["Kanzlerin"] == werte["Vasall"], (
        "Gleichstand aufgeloest: dann darf der Test wieder Plaetze pruefen."
    )
    # Und die Groessenordnung ist der eigentliche Befund: die beiden vorn
    # liegen zwei Zehnerpotenzen ueber den beiden im Gleichstand.
    assert werte["Vasallen"] > 100 * werte["Kanzlerin"], werte
