"""Trailing explanatory notes remain bounded relative to the answer."""

from __future__ import annotations

import ast
import pathlib

from candyconc.candyconc_copilot.recipe_runtime import (
    MAX_NACHTRAEGE,
    politur_mit_zitatwache,
)

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "candyconc"


def _beleg_mit_bilanz(gefiltert: int = 20):
    return {
        "tool": "collocate_stats",
        "status": "success",
        "fact_surface": {
            "node_frequency": 2840,
            "diagnostics": {
                "kandidaten": 560, "gefiltert": gefiltert,
                "gefiltert_spitze": ["„,“ (logdice 12,23)"],
            },
            "rows": [{"word": "ökologische", "f": 127, "f2": 900, "logdice": 9.45}],
        },
    }


#: Woran sich jede der fuenf Wachen im fertigen Text erkennen laesst.
#:
#: GEZAEHLT WERDEN WACHEN, NICHT SAETZE. Der erste Anlauf zaehlte Saetze und
#: lag daneben, weil ein Nachtrag nicht ein Satz sein muss: die
#: Massgrundlagen-Wache schreibt zwei ("... Kookkurrenz 127. Korpusfrequenz
#: ... 2.840: 14 + log2(...)"), und die deutsche Tausendertrennung in "2.840"
#: erzeugt beim Trennen an ". " einen weiteren Scheinsatz. Der alte Test
#: fing das mit einer Toleranz von plus eins auf, also mit einer Zahl, die
#: nichts bedeutete. Marken zaehlen exakt.
MARKEN = {
    "luecken": "Nicht gemessen:",
    "massgrundlagen": "entsteht aus Kookkurrenz",
    "analysetoken": "Analyse-Token-Filter",
    "schreibung": "zählt eine Schreibungsklasse",
    "tabellenzusage": "Die Tabelle „",
}

#: Wo die Marke herkommt, damit eine Umformulierung laut scheitert.
MARKENQUELLE = {
    "luecken": "question_coverage.py",
    "massgrundlagen": "measure_basis.py",
    "analysetoken": "analysis_token_report.py",
    "schreibung": "row_spelling_note.py",
    "tabellenzusage": "table_promise_check.py",
}


def _vorbehaltsbereich(text: str, antwort: str) -> str:
    """Nur der Vorbehaltsbereich, nicht jeder Anhang.

    Der Deckel schuetzt gegen FUSSNOTEN. Ein Abschnitt mit Ueberschrift ist
    Inhalt: das Experimentprotokoll nennt, was gemessen wurde und was
    herauskam, und genau das hat der Auftraggeber verlangt. Wer alles hinter
    der Antwort zaehlt, zaehlt auch "1. Suche ... 0 Treffer" mit und macht
    den Deckel zu einer Waffe gegen den Inhalt, den er nie meinte.
    """
    return text[len(antwort.rstrip()):].split("\n\n### ")[0]


def test_jede_marke_steht_noch_in_ihrem_modul():
    """Eine Marke, die niemand mehr trifft, macht den Deckel wirkungslos.

    Ohne diese Probe wuerde eine umformulierte Wache den Zaehler still auf
    null setzen, und der Deckeltest waere gruen, waehrend fuenf Nachtraege
    im Text stehen. Genau diese Klasse von blinder Wache hat dieses Projekt
    an einem Tag dreimal gebaut.
    """
    for name, marke in MARKEN.items():
        quelle = (_SRC / "candyconc_copilot" / MARKENQUELLE[name]).read_text(
            encoding="utf-8"
        )
        assert marke in quelle, f"{name}: „{marke}“ fehlt in {MARKENQUELLE[name]}"


def test_der_deckel_ist_zwei():
    """Nicht drei. Die Antwort traegt bereits den Grenzen-Absatz des Modells."""
    assert MAX_NACHTRAEGE == 2


def test_hoechstens_zwei_nachtraege_stehen_im_text():
    antwort = (
        "Die stärksten Kollokate sind ökologische, Gerechtigkeit und "
        "Digitalisierung. logDice für „ökologische“ liegt bei 9,45. "
        "Top-10 der Kollokate:\n\n| Wort | f |\n|---|---|\n| a | 1 |\n"
    )
    text, _ = politur_mit_zitatwache(antwort, [_beleg_mit_bilanz()])
    vorbehalte = _vorbehaltsbereich(text, antwort)
    gefeuert = [name for name, marke in MARKEN.items() if marke in vorbehalte]
    assert len(gefeuert) <= MAX_NACHTRAEGE, (gefeuert, vorbehalte)


def test_die_vorbehalte_stehen_unter_der_antwort_nicht_am_ende():
    """Der letzte Satz ist, was die Leserin behaelt.

    Bis heute standen die Nachtraege hinter dem Methodensteckbrief, also
    als Letztes im ganzen Text. Die Hausregel in CLAUDE.md sagt: "Kein
    Absatz und kein Abschnitt endet auf seinem eigenen Caveat." Ein
    Vorbehalt schraenkt die ANTWORT ein, also steht er bei ihr.
    """
    antwort = (
        "Die stärksten Kollokate sind ökologische, Gerechtigkeit und "
        "Digitalisierung. logDice für „ökologische“ liegt bei 9,45. "
        "Top-10 der Kollokate:\n\n| Wort | f |\n|---|---|\n| a | 1 |\n"
    )
    text, _ = politur_mit_zitatwache(antwort, [_beleg_mit_bilanz()])
    angehaengt = text[len(antwort.rstrip()):]
    if "\n\n### " not in angehaengt:
        raise AssertionError(
            "Kein Abschnitt im Text, die Probe kann nichts belegen: "
            + repr(angehaengt[:200])
        )
    vorbehalte = angehaengt.split("\n\n### ")[0].strip()
    assert vorbehalte, "keine Vorbehalte erzeugt, die Probe belegt nichts"
    assert text.index(vorbehalte) < text.index("\n\n### "), (
        "Der Vorbehalt steht hinter dem Abschnitt statt unter der Antwort."
    )


def test_was_der_deckel_nimmt_wird_annotation_und_verschwindet_nicht():
    """Ein Nachtrag, der still verschwindet, waere ein verschobener Defekt."""
    quelle = (_SRC / "candyconc_copilot" / "recipe_runtime.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    ziel = next(
        k for k in ast.walk(baum)
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
        and k.name == "politur_mit_zitatwache"
    )
    namen = {
        n.id for n in ast.walk(ziel) if isinstance(n, ast.Name)
    }
    assert "_zurueckgestellt" in namen, (
        "Der Deckel schneidet ab, ohne das Abgeschnittene weiterzugeben."
    )
    # Und es landet wirklich in der Annotationsliste, nicht in einer Variablen.
    quelltext_der_funktion = ast.get_source_segment(quelle, ziel) or ""
    assert "nachtrag_ueber_deckel" in quelltext_der_funktion, (
        "Die zurueckgestellten Saetze erreichen die Annotationen nicht."
    )


def test_die_immergleiche_zusicherung_steht_nicht_mehr_in_jeder_antwort():
    """Was IMMER dasteht, traegt keine Auskunft, nur Laenge.

    "Zahlen und Zitate sind deterministisch gegen die sichtbare
    Tool-Evidenz aufgeloest" stand in JEDER Antwort dieses Pfades. Die
    ZAEHLUNG der entfernten Zitate bleibt dagegen stehen, sie erscheint
    nur, wenn dem ausgelieferten Text wirklich etwas fehlt. Ein erster
    Anlauf hat beides gestrichen, und zwei Tests in
    test_quote_guard_verifier_skip haben das zu Recht aufgehalten.
    """
    quelle = (_SRC / "candyconc_copilot" / "recipe_runtime.py").read_text(encoding="utf-8")
    ziel = next(
        k for k in ast.walk(ast.parse(quelle))
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
        and k.name == "verifier_skipped_answer_text"
    )
    literale = " ".join(
        n.value for n in ast.walk(ziel)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )
    assert "deterministisch gegen die " not in literale, (
        "Die immergleiche Zusicherung steht wieder in jeder Antwort."
    )
    assert "ohne Deckung in der " in literale, (
        "Die Zaehlung der entfernten Zitate fehlt. Dann liest jemand eine "
        "Antwort mit einem Loch und erfaehrt den Grund nicht."
    )


def test_die_zaehlung_steht_im_text_und_nicht_im_nichts():
    """Aus der Prosa genommen war der falsche Weg, hier ist der richtige."""
    from candyconc.candyconc_copilot.recipe_runtime import verifier_skipped_answer_text

    text = verifier_skipped_answer_text(
        'Der Beleg lautet "ein frei erfundener Satz aus dem Nichts".',
        lambda draft: {"text": draft},
        lambda: "",
        lambda grund: "fail",
        quote_surfaces=["etwas ganz anderes steht in der Evidenz"],
    )
    assert "ohne Deckung" in text, text
    assert "erfundener Satz" not in text, text
