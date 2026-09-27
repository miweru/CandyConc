"""Eine Tabelle, die "Top-10" heisst, hat zehn Zeilen oder sagt warum nicht.

Siehe den Modulkopf von ``table_promise_check``: der Befund einer
Professorin am 2026-08-31 auf Frage kollokation-1, wo die Tabelle
"ll-Top-10 (4.672)" neun Zeilen fuehrte und Rang 2 fehlte.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from candyconc.candyconc_copilot.table_promise_check import luecken, saetze

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


def tabelle(kopf: str, zeilen: int) -> str:
    kopf_zeile = "| Wort | ll |\n|---|---|\n"
    daten = "".join(f"| w{i} | {1000 - i} |\n" for i in range(zeilen))
    return f"{kopf}\n\n{kopf_zeile}{daten}\n"


# ------------------------------------------------------------ der Befund


def test_der_gemeldete_fall():
    text = tabelle("ll-Top-10 (4.672):", 9)
    lue = luecken(text)
    assert lue == [("ll-Top-10 (4.672):", 10, 9)], lue
    s = saetze(text)[0]
    assert "9 statt 10" in s
    assert "nicht notwendig die schwächste" in s


def test_vollstaendige_tabelle_schweigt():
    assert luecken(tabelle("ll-Top-10:", 10)) == []
    assert saetze(tabelle("ll-Top-10:", 10)) == []


def test_mehr_zeilen_als_zugesagt_ist_kein_befund_dieser_wache():
    """Zu viele Zeilen ist ein anderer Fehler und nicht dieser."""
    assert luecken(tabelle("Top-5:", 8)) == []


@pytest.mark.parametrize("kopf", ["Top-10", "Top 10", "top-10", "TOP-10", "ll-Top-10 (4.672):"])
def test_schreibweisen_der_zusage(kopf):
    assert luecken(tabelle(kopf, 3)), kopf


def test_ohne_zusage_keine_pruefung():
    """Eine Tabelle ohne Zahl in der Ueberschrift sagt nichts zu."""
    assert luecken(tabelle("Die staerksten Kollokate:", 3)) == []


def test_ohne_tabelle_keine_meldung():
    """Eine Ueberschrift ohne Tabelle darunter ist kein Widerspruch."""
    assert luecken("Die Top-10 stehen weiter unten.\n\nText ohne Tabelle.\n") == []


def test_mehrere_tabellen_werden_einzeln_geprueft():
    text = tabelle("logDice-Top-10:", 10) + "\n" + tabelle("ll-Top-10:", 9) + "\n" + tabelle("MI-Top-10:", 10)
    lue = luecken(text)
    assert len(lue) == 1 and lue[0][0].startswith("ll-Top-10")


def test_unsinnige_zusagen_werden_uebergangen():
    assert luecken(tabelle("Top-0:", 3)) == []
    assert luecken(tabelle("Top-9999:", 3)) == []


def test_leere_antwort_stuerzt_nicht():
    assert luecken("") == [] and saetze("") == []


# --------------------------------------------------- die Naht, ausgezaehlt


def test_die_politur_ruft_die_wache():
    quelle = (SRC / "candyconc" / "candyconc_copilot" / "recipe_runtime.py").read_text(
        encoding="utf-8"
    )
    baum = ast.parse(quelle)
    landungen = [
        k for k in ast.walk(baum)
        if isinstance(k, ast.FunctionDef) and k.name == "politur_mit_zitatwache"
    ]
    assert len(landungen) == 1
    aufrufe = {
        getattr(k.func, "id", None)
        for k in ast.walk(landungen[0]) if isinstance(k, ast.Call)
    }
    assert "_tabellenzusage_saetze" in aufrufe, (
        "Die Politur prueft die Tabellenzusage nicht. Dann steht wieder eine "
        "Ueberschrift 'Top-10' ueber neun Zeilen."
    )


# ------------------------------------------------- leere Abschnitte


from candyconc.candyconc_copilot.table_promise_check import (  # noqa: E402
    leere_abschnitte,
    ohne_leere_abschnitte,
)


def test_der_gemeldete_leere_abschnitt():
    """variation-1: Überschrift unmittelbar vor der nächsten Überschrift.

    Der Renderer ist unschuldig, er gibt bei null überlebenden Zeilen "".
    Die Überschrift kam MIT Tabelle und wurde von der Zitatwache entkernt.
    """
    text = (
        "Fließtext.\n\n"
        "### Sichtbare gerichtete Keyness-Ergebnisse\n\n"
        "### Weiterführende Fragen\n"
        "- Eine Frage?\n"
    )
    assert leere_abschnitte(text) == ["### Sichtbare gerichtete Keyness-Ergebnisse"]
    neu = ohne_leere_abschnitte(text)
    assert "Sichtbare gerichtete" not in neu
    assert "### Weiterführende Fragen" in neu and "- Eine Frage?" in neu


def test_ueberschrift_am_textende_ist_auch_leer():
    text = "Fließtext.\n\n### Ergebnisse\n\n"
    assert leere_abschnitte(text) == ["### Ergebnisse"]


def test_gefuellte_abschnitte_bleiben():
    text = "### A\nInhalt.\n\n### B\n\n| x |\n|---|\n| 1 |\n"
    assert leere_abschnitte(text) == []
    assert ohne_leere_abschnitte(text) == text


def test_eine_intakte_antwort_bleibt_zeichengleich():
    text = (
        "## Befund\n\nEs gibt 5 Treffer.\n\n"
        "### Tabelle\n\n| Wort | f |\n|---|---|\n| a | 1 |\n\n"
        "### Deutung\nDas heißt wenig.\n"
    )
    assert ohne_leere_abschnitte(text) == text


def test_alle_ebenen_werden_erkannt():
    # A same-level heading ends this section. A populated deeper heading
    # would supply content to the current section.
    for raute in ("#", "##", "###", "####", "#####", "######"):
        text = f"Text.\n\n{raute} Leer\n\n# Danach\nInhalt.\n"
        assert leere_abschnitte(text) == [f"{raute} Leer"], raute


def test_kein_absturz_bei_leerem_text():
    assert leere_abschnitte("") == [] and ohne_leere_abschnitte("") == ""


def test_die_politur_entfernt_leere_abschnitte():
    quelle = (SRC / "candyconc" / "candyconc_copilot" / "recipe_runtime.py").read_text(
        encoding="utf-8"
    )
    baum = ast.parse(quelle)
    landung = [
        k for k in ast.walk(baum)
        if isinstance(k, ast.FunctionDef) and k.name == "politur_mit_zitatwache"
    ][0]
    aufrufe = {
        getattr(k.func, "id", None)
        for k in ast.walk(landung) if isinstance(k, ast.Call)
    }
    assert "_ohne_leere_abschnitte" in aufrufe


def test_ein_satz_ueber_eine_top_liste_sagt_keine_zeilen_zu():
    """Kandidat 4, Frage 11: Der Satz „keine Top-100-Wortliste“
    stand ueber einer vollstaendigen Tabelle mit 28 Zeilen, die Wache meldete
    „28 statt 100 Zeilen. Es fehlt mindestens eine“."""
    kopf = (
        "Die Serie ist eine Token-Längenverteilung über das gesamte Korpus, "
        "keine Top-100-Wortliste. Jenseits von 39 sind keine einzelnen "
        "Buchstabenlängen separat ausgewiesen. [[beleg:E_metadata_values_1]]"
    )
    assert luecken(tabelle(kopf, 28)) == []


def test_nummerierte_ueberschrift_bleibt_zusage():
    assert luecken(tabelle("### 2. Top-10 der Kollokate", 9))
