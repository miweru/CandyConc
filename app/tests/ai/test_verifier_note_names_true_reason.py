"""The verifier notice states the actual reason model verification was skipped."""

from __future__ import annotations

import ast
import pathlib

from candyconc.candyconc_copilot.recipe_runtime import (
    VERIFIER_HINWEISE,
    VERIFIER_LAEUFT_NOTE,
    VERIFIER_SKIPPED_NOTE,
    VERIFIER_UNBESTAETIGT_NOTE,
    _extract_meta_note_lines,
    verifier_skipped_answer_text,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
ORCH = SRC / "candyconc" / "candyconc_copilot" / "orchestrator.py"


def _text(grund=None):
    kw = {} if grund is None else {"grund": grund}
    return verifier_skipped_answer_text(
        "Im Korpus liegen Belege vor.",
        lambda entwurf: {"text": entwurf, "bare_numbers": []},
        lambda: "deterministisches Markdown",
        lambda meldung: meldung,
        quote_surfaces=["x"],
        **kw,
    )


def test_der_grund_steht_im_hinweis():
    assert VERIFIER_UNBESTAETIGT_NOTE in _text(VERIFIER_UNBESTAETIGT_NOTE)
    assert VERIFIER_LAEUFT_NOTE in _text(VERIFIER_LAEUFT_NOTE)


def test_ein_anderer_grund_behauptet_kein_zeitproblem():
    """Der Kern des Befundes, ausbuchstabiert."""

    for grund in (VERIFIER_UNBESTAETIGT_NOTE, VERIFIER_LAEUFT_NOTE):
        t = _text(grund)
        assert "Zeitbudget" not in t, (
            f"Der Hinweis nennt das Zeitbudget, obwohl der Grund {grund!r} "
            f"lautet:\n{t}"
        )


def test_der_zeitpfad_behaelt_seinen_wortlaut():
    """Der aelteste Verbraucher darf durch die Trennung nichts verlieren."""

    assert VERIFIER_SKIPPED_NOTE in _text()
    assert "Zeitbudget" in _text()


def test_jeder_grund_gilt_weiter_als_nicht_modellgeprueft():
    """Genauigkeit darf die Politur nicht blind machen.

    Ein Hinweis, den ``_extract_meta_note_lines`` nicht mehr erkennt,
    verliert die Ehrlichkeitszeile am Textende und bliebe stattdessen
    sichtbar im Antworttext stehen.
    """

    for grund in VERIFIER_HINWEISE:
        _bereinigt, annotationen, flagge = _extract_meta_note_lines(
            _text(grund)
        )
        assert flagge, f"{grund!r} wird nicht mehr als ungeprueft erkannt"
        assert any(grund in a.get("note", "") for a in annotationen), grund


def test_jeder_verbraucher_nennt_seinen_eigenen_grund():
    """Auszaehlend, damit ein VIERTER Verbraucher nicht wieder erbt.

    Genau so ist der Defekt entstanden: der dritte Aufrufer kam dazu und
    uebernahm die Vorgabe des ersten, ohne dass jemand widersprach.
    """

    baum = ast.parse(ORCH.read_text(encoding="utf-8"))
    aufrufe = [
        knoten
        for knoten in ast.walk(baum)
        if isinstance(knoten, ast.Call)
        and getattr(knoten.func, "id", "") == "_deterministisch_gedeckter_text"
    ]
    assert len(aufrufe) >= 3, (
        f"Nur {len(aufrufe)} Aufrufe gefunden. Wurde die Funktion "
        "umbenannt, prueft dieser Test nichts mehr."
    )
    ohne_grund = [
        k.lineno
        for k in aufrufe
        if not any(s.arg == "grund" for s in k.keywords)
    ]
    assert len(ohne_grund) == 1, (
        "Genau EIN Aufrufer darf die Vorgabe (Zeitbudget) benutzen, "
        f"gefunden in Zeile(n) {ohne_grund}. Jeder weitere Verbraucher "
        "muss seinen eigenen Grund durchreichen, sonst behauptet die "
        "Telemetrie wieder ein Zeitproblem, das es nicht gab."
    )
    gruende = {
        getattr(s.value, "id", None)
        for k in aufrufe
        for s in k.keywords
        if s.arg == "grund"
    }
    assert gruende == {
        "VERIFIER_LAEUFT_NOTE",
        "VERIFIER_UNBESTAETIGT_NOTE",
    }, gruende
