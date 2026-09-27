"""The method summary identifies the counting level and logDice denominator."""

from __future__ import annotations

from candyconc.candyconc_copilot.grounding_evidence import zaehlebene_und_nenner


def test_die_zaehlebene_wird_benannt():
    assert "Zählebene Wortform" in zaehlebene_und_nenner("word", None)
    assert "Zählebene Lemma" in zaehlebene_und_nenner("lemma", None)


def test_ohne_attribut_wird_nichts_behauptet():
    """Kein Attribut heisst kein Satz, nicht eine geratene Vorgabe."""

    assert zaehlebene_und_nenner(None, None) == []
    assert zaehlebene_und_nenner("", None) == []
    assert zaehlebene_und_nenner("unbekannt", None) == []


def test_die_beiden_logdice_werden_unterschieden():
    """Der Kern des zweiten Teils: zwei Spalten, zwei Nenner."""

    rychly = zaehlebene_und_nenner("word", "logdice")
    fenster = zaehlebene_und_nenner("word", "logdice_window")
    assert any("Korpusfrequenzen" in s for s in rychly), rychly
    assert any("Fenstermaße" in s for s in fenster), fenster
    assert rychly != fenster


def test_andere_masse_bekommen_keinen_nenner_angehaengt():
    """Nur wo zwei Spalten denselben Namen tragen, braucht es die Angabe."""

    for mass in ("ll", "mi", "t", "dice", None):
        heraus = zaehlebene_und_nenner("word", mass)
        assert heraus == ["Zählebene Wortform"], (mass, heraus)


def test_beide_zweige_rufen_den_satzbildner():
    """Die NAHT, in BEIDEN Werkzeugzweigen.

    Der Plan behauptete, fuer keyness sei die Angabe unerreichbar, weil
    attribute in diagnostics liege und nicht auf oberster Ebene. Der
    keyness-Zweig liest diagnostics aber bereits selbst, eine Zeile ueber
    der Stelle. Geprueft werden AUFRUFE, nicht Namen.
    """

    import ast
    import pathlib

    # Seit dem 2026-09-01 liegt der Steckbrief-Renderer in einem eigenen
    # Modul. grounding_markdown sagt, WAS gefunden wurde, method_sheet
    # sagt, WOMIT gemessen wurde. Der Scan folgt dem Umzug, sonst zaehlt er
    # null Aufrufe in einer Datei, die die Funktion nicht mehr enthaelt, und
    # meldet einen Defekt, den es nicht gibt.
    quelle = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "candyconc" / "candyconc_copilot" / "method_sheet.py"
    ).read_text(encoding="utf-8")
    aufrufe = [
        k
        for k in ast.walk(ast.parse(quelle))
        if isinstance(k, ast.Call)
        and getattr(k.func, "id", "") == "zaehlebene_und_nenner"
    ]
    assert len(aufrufe) >= 2, (
        f"Nur {len(aufrufe)} Aufruf(e). Gebraucht werden zwei: einer im "
        "collocate_stats-Zweig und einer im keyness-Zweig. Beide Werkzeuge "
        "verschweigen die Zaehlebene heute."
    )


def test_der_steckbrief_bleibt_unter_seinem_budget():
    """Die Auflage der Widerlegung: die LOC-Rechnung des Plans war falsch.

    Der Plan rechnete mit 5.993 Zeilen. In der Formatierung, die die Datei
    selbst verwendet, waren es 6.002 bei einem Budget von 6.000. Diese
    Fassung ruft in zwei Zeilen je Zweig statt in fuenf.
    """

    import json
    import pathlib

    wurzel = pathlib.Path(__file__).resolve().parents[2]
    modul = "method_sheet.py"
    zeilen = len(
        (wurzel / "src" / "candyconc" / "candyconc_copilot" / modul)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    # Die Budgetdatei hat zwei Ebenen: ``default_max_lines`` und
    # ``exceptions``. Die erste Fassung griff mit dem Modulnamen auf die
    # oberste Ebene und landete deshalb IMMER auf ihrem eigenen
    # Standardwert. Sie hatte recht, ohne die Datei zu lesen.
    budget_datei = json.loads(
        (wurzel / "tests" / "ai" / "copilot_loc_budget.json").read_text()
    )
    ausnahme = budget_datei.get("exceptions", {}).get(modul)
    budget = int(
        ausnahme["max_lines"] if ausnahme
        else budget_datei["default_max_lines"]
    )
    assert zeilen <= budget, f"{zeilen} Zeilen bei Budget {budget}"
