"""A named measure includes the input counts needed to reconstruct its value.

Check the final processing boundary used by every answer path, since a
question-specific table renderer does not cover all answers."""

from __future__ import annotations

from candyconc.candyconc_copilot.measure_basis import saetze


def _beleg(zeilen, knoten=35910):
    return {
        "tool": "collocate_stats",
        "status": "success",
        "raw_surface": {"node_frequency": knoten, "rows": zeilen},
    }


ZEILE = {"word": "spielt", "f": 4281, "f2": 11857, "logdice": 11.52}


def test_ein_genannter_logdice_ohne_f2_bekommt_seine_grundlage():
    # Seit Zyklus 10 (2026-09-26) muss der Satz das Mass beim Namen nennen,
    # siehe test_logdice_note_needs_the_measure_named.
    heraus = saetze("Der logDice für „spielt“ liegt bei 11,52.", [_beleg([ZEILE])])
    assert len(heraus) == 1, heraus
    satz = heraus[0]
    for teil in ("4.281", "11.857", "35.910", "spielt"):
        assert teil in satz, f"{teil!r} fehlt in {satz!r}"


def test_steht_f2_schon_da_wird_nichts_nachgetragen():
    """Kein Laerm. Die Lehre steht in row_spelling_note."""

    antwort = "Der logDice für „spielt“ liegt bei 11,52, bei f2 = 11.857."
    assert saetze(antwort, [_beleg([ZEILE])]) == []


def test_ohne_genannten_wert_bleibt_die_wache_still():
    """Eine Wache, die ueber jede Evidenzzeile meldet, ist keine Meldung."""

    assert saetze("Die Analyse nennt keine Zahl.", [_beleg([ZEILE])]) == []


def test_der_englische_dezimalpunkt_zaehlt_ebenso():
    assert len(saetze("logDice 11.52 für „spielt“.", [_beleg([ZEILE])])) == 1


def test_eine_laengere_zahl_ist_kein_treffer():
    """11,5 darf nicht in 11,52 treffen."""

    zeile = dict(ZEILE, logdice=11.5)
    assert saetze("Der logDice für „spielt“ liegt bei 11,52.", [_beleg([zeile])]) == []


def test_hoechstens_drei_saetze():
    """Eine Antwort, die zehn Grundlagen nachtraegt, besteht aus Fussnoten."""

    zeilen = [
        {"word": f"w{i}", "f": 100 + i, "f2": 900 + i, "logdice": 9.0 + i / 100}
        for i in range(8)
    ]
    # Jedes Kollokat mit seinem Wert im selben Satz: seit B2 (2026-09-26)
    # zaehlt ein Wert nur, wenn sein Kollokat im selben Satz steht. Geprueft
    # wird hier weiter der Deckel, nicht die Nennung.
    antwort = " ".join(
        f"w{i} mit logDice {9.0 + i / 100:.2f}".replace(".", ",") for i in range(8))
    assert len(saetze(antwort, [_beleg(zeilen)])) == 3


def test_der_chokepoint_ruft_die_wache_wirklich():
    """Die NAHT, nicht nur die Funktion.

    Geprueft werden AUFRUFE, nicht Namen: ein lokaler Import allein wuerde
    den Namen schon in den Rumpf bringen. Genau daran ist heute schon eine
    Wache dieses Projekts gescheitert.
    """

    import ast
    import pathlib

    quelle = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "candyconc" / "candyconc_copilot" / "recipe_runtime.py"
    ).read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    ziel = next(
        (
            k
            for k in ast.walk(baum)
            if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
            and k.name == "politur_mit_zitatwache"
        ),
        None,
    )
    assert ziel is not None, "politur_mit_zitatwache nicht gefunden"
    gerufen = {
        getattr(k.func, "id", "") for k in ast.walk(ziel) if isinstance(k, ast.Call)
    }
    assert "_massgrundlagen_saetze" in gerufen, (
        "Der Chokepoint ruft die Wache nicht. Sie haengt dann wieder an "
        f"einer Naht, die nicht feuert. Gerufen wird: {sorted(gerufen)}"
    )


def test_die_nachtraege_bilden_EINEN_absatz():
    """Auflage der Widerlegung: nicht vier Absaetze am Textende.

    Sonst behaelt die Leserin eine Fussnote als letzten Satz, was gegen
    die Hausregel zum Absatzende verstoesst.
    """

    import pathlib
    import re

    quelle = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "candyconc" / "candyconc_copilot" / "recipe_runtime.py"
    ).read_text(encoding="utf-8")
    anhaenge = re.findall(r'poliert = f"\{poliert\.rstrip\(\)\}\\n\\n\{_satz\}"', quelle)
    assert anhaenge == [], (
        f"{len(anhaenge)} Einzelanhaenge gefunden. Die Nachtraege gehoeren "
        "in EINEN Absatz mit fester Reihenfolge."
    )
