"""Disclose when a row label differs from the spelling contributing its count."""

from __future__ import annotations

import ast
import pathlib

import pytest

from candyconc.candyconc_copilot.row_spelling_note import (
    abweichende_schreibung,
    alle_saetze,
    satz,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


class Beleg:
    """Ein Belegposten in der Form, die die Produktion fuehrt.

    Die Zeilen liegen UNTER "rows" der Belegaufzeichnung. Die erste Fassung
    dieser Datei legte sie flach auf die Oberflaeche, eine Form, die es nie
    gab, und bestaetigte damit eine Wache, die im Produkt schwieg.
    """

    def __init__(self, *zeilen):
        self.fact_surface = {"status": "success", "rows": list(zeilen)}


def zeile(word, **seiten):
    summe = sum(sum(int(x or 0) for x in v.values()) for v in seiten.values() if v)
    return {"word": word, "target_freq": summe, "surface_variants": dict(seiten)}


def antwort_mit_zahl(text, *zeilen):
    """Eine Zeile gilt erst als zitiert, wenn ihre ZAHL dasteht."""
    zahlen = " ".join(str(z.get("target_freq", 0)) for z in zeilen)
    return f"{text} ({zahlen})"


# --------------------------------------------------------------- der Kern


def test_etikett_traegt_nichts():
    """Der gemeldete Fall. Er hat GENAU EINE Schreibung, nur nicht die gedruckte."""
    text = satz(zeile("Arm", target={"arm": 2}))
    assert "„Arm“" in text and "„arm“" in text
    assert "kommt dort nicht vor" in text
    assert "2" in text


def test_etikett_traegt_eine_minderheit():
    text = satz(zeile("Die", target={"die": 1028, "Die": 206, "DIE": 7}))
    assert "1241" in text and "206" in text and "„die“" in text


def test_mehrheit_beim_etikett_schweigt():
    """Traegt das Etikett die Mehrheit, sagt die Zeile im Wesentlichen die Wahrheit."""
    assert satz(zeile("und", target={"und": 797, "Und": 113})) == ""


def test_genau_die_haelfte_schweigt():
    """Die Grenze ist die Mehrheit, nicht 'irgendein Unterschied'."""
    assert satz(zeile("das", target={"das": 3, "Das": 3})) == ""


def test_ohne_aufschluesselung_kein_satz():
    assert satz({"word": "Rolle", "target_freq": 5}) == ""
    assert satz({"word": "Rolle", "surface_variants": {}}) == ""


def test_schlimmste_seite_wird_gemeldet():
    """Ziel und Referenz koennen verschieden verteilt sein."""
    befund = abweichende_schreibung(
        zeile("niemand", target={"Niemand": 2}, reference={"niemand": 9, "Niemand": 5})
    )
    assert befund is not None
    _, traegt, eigen, gesamt = befund
    assert (traegt, eigen, gesamt) == ("Niemand", 0, 2)


def test_leere_seite_stuerzt_nicht():
    assert satz(zeile("x", target={}, reference={"y": 3})) != ""
    assert satz(zeile("x", target={})) == ""


def test_kaputte_werte_stuerzen_nicht():
    assert satz({"word": "x", "surface_variants": {"target": None}}) == ""
    assert satz({"word": "", "surface_variants": {"target": {"a": 1}}}) == ""
    assert satz(zeile("x", target={"y": None})) == ""


# ------------------------------------------------------- nur was dasteht


def test_nur_genannte_etiketten():
    """Eine Wache, die ueber 11.209 Zeilen meldet, ist Laerm, keine Meldung."""
    z1, z2 = zeile("Arm", target={"arm": 2}), zeile("Die", target={"die": 1028, "Die": 206})
    belege = [Beleg(z1), Beleg(z2)]
    saetze = alle_saetze("Der Kontrast hebt Arm hervor (2).", belege)
    assert len(saetze) == 1 and "„Arm“" in saetze[0]


def test_jedes_etikett_hoechstens_einmal():
    belege = [Beleg(zeile("Arm", target={"arm": 2}))] * 3
    assert len(alle_saetze("Arm ist typisch (2).", belege)) == 1


def test_ohne_antwort_kein_satz():
    assert alle_saetze("", [Beleg(zeile("Arm", target={"arm": 2}))]) == []


def test_ohne_evidenz_kein_satz():
    assert alle_saetze("Arm ist typisch (2).", []) == []


# ------------------------------------------------- die Naht, ausgezaehlt


def test_jede_politur_landung_bekommt_die_wache():
    """Nicht 'die Wache existiert', sondern 'sie sitzt an JEDER Landung'.

    Dieselbe Bauart wie ``test_jede_landung_uebergibt_frage``. Faellt eine
    Landung heraus, verstummt die Wache still, und genau diese Klasse hat in
    dieser Sitzung dreimal zugeschlagen.
    """
    quelle = (SRC / "candyconc" / "candyconc_copilot" / "recipe_runtime.py").read_text(
        encoding="utf-8"
    )
    baum = ast.parse(quelle)
    landungen = [
        k for k in ast.walk(baum)
        if isinstance(k, ast.FunctionDef) and k.name == "politur_mit_zitatwache"
    ]
    assert len(landungen) == 1, "politur_mit_zitatwache nicht eindeutig"
    aufrufe = {
        getattr(k.func, "id", None)
        for k in ast.walk(landungen[0])
        if isinstance(k, ast.Call)
    }
    assert "_schreibungs_saetze" in aufrufe, (
        "Die Politur ruft die Schreibungswache nicht. Ohne sie nennt die "
        "Antwort ein Etikett, das die Zahl nicht traegt, und niemand merkt es."
    )
    assert "_alle_luecken_saetze" in aufrufe, "Die Deckungswache ist verschwunden"


# ------------------------------------------------- Wortgrenze, nicht Teilstring


def test_teilzeichenkette_loest_keinen_fehlalarm_aus():
    """Der erste Entwurf prüfte mit ``in`` und meldete für "Arm", wenn die
    Antwort "Die Armut steigt" sagte, also für eine Zeile, die niemand zitiert
    hatte. Selbst gefunden, bevor ein Prüfer es fand."""
    belege = [Beleg(zeile("Arm", target={"arm": 2}))]
    assert alle_saetze("Die Armut steigt um 2 Punkte.", belege) == []
    assert alle_saetze("Armband und Armut, 2 Stueck", belege) == []


def test_eigenstaendiges_wort_meldet_weiter():
    belege = [Beleg(zeile("Arm", target={"arm": 2}))]
    assert alle_saetze("Der Arm zeigt 2 Treffer.", belege)
    assert alle_saetze("Am Ende steht Arm mit 2.", belege)


def test_anfuehrungszeichen_sind_keine_wortzeichen():
    belege = [Beleg(zeile("Arm", target={"arm": 2}))]
    assert alle_saetze("Die Zeile „Arm“ mit 2 Treffern fällt auf.", belege)


def test_flexion_ist_ein_anderes_wort():
    """``\\w`` ist unicodefähig, sonst träfe "Grüne" in "Grünen"."""
    belege = [Beleg(zeile("Grüne", target={"grüne": 4}))]
    assert alle_saetze("Die Grünen fordern 4 mal mehr.", belege) == []
    assert alle_saetze("Die Grüne sagte das 4 mal.", belege)


def test_sonderzeichen_im_etikett_stuerzen_nicht():
    """Ein Etikett ist eine Korpuszeichenkette, kein regulärer Ausdruck."""
    for wort in ("C++", "a.b", "(SPD)", "[x]", "5%"):
        belege = [Beleg(zeile(wort, target={wort.lower(): 3}))]
        alle_saetze(f"Hier steht {wort} mit 3 im Satz.", belege)


# ------------------------------------------------------ die zitierte Zahl


import pytest as _pytest


@_pytest.mark.parametrize(
    "zahl,text,erwartet",
    [
        (2, "mit 2.", True),          # häufigste Stellung: vor dem Satzpunkt
        (2, "(2)", True),
        (2, "2, 3 und 4", True),
        (2, "Rang 2", True),
        (1241, "1241 mal", True),
        (1241, "1.241 mal", True),    # deutscher Tausenderpunkt
        (2, "2.5 Prozent", False),    # Dezimalzahl, nicht die 2
        (2, "genau 25", False),
        (1241, "12412", False),
        (1241, "x1241", False),       # Bezeichner, kein Zitat
        (1241, "doc_1241", False),
        (2, "E_2", False),
    ],
)
def test_zahlvergleich(zahl, text, erwartet):
    from candyconc.candyconc_copilot.row_spelling_note import _zahl_kommt_vor

    assert _zahl_kommt_vor(zahl, text) is erwartet
