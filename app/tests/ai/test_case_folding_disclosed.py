"""Case-folded counts disclose their normalization and displayed spelling.

A representative lexicon label can differ from the spelling contributing
most of a docset count. Check every registered keyness entry point so a
new entry point also has to disclose this relationship."""

from __future__ import annotations

import ast
import pathlib

import pytest

from candyconc.analysis_defaults import (
    CASE_POLICY_GEFALTET,
    FALTENDE_FAMILIEN,
    build_method_block,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


def _methodenblock_aufrufe() -> list[tuple[str, int, str | None, set[str]]]:
    """Jeder ``build_method_block``-Aufruf mit Familie und Schluesselwoertern."""
    gefunden: list[tuple[str, int, str | None, set[str]]] = []
    for pfad in sorted(SRC.rglob("*.py")):
        baum = ast.parse(pfad.read_text(encoding="utf-8"), str(pfad))
        for knoten in ast.walk(baum):
            if not isinstance(knoten, ast.Call):
                continue
            funk = knoten.func
            name = getattr(funk, "id", None) or getattr(funk, "attr", None)
            if name != "build_method_block":
                continue
            familie = None
            if knoten.args and isinstance(knoten.args[0], ast.Constant):
                familie = knoten.args[0].value
            gefunden.append(
                (str(pfad), knoten.lineno, familie, {kw.arg for kw in knoten.keywords})
            )
    return gefunden


def test_die_naehte_werden_ueberhaupt_gefunden():
    aufrufe = _methodenblock_aufrufe()
    assert len(aufrufe) >= 15, "Der Auszaehler findet die Naehte nicht mehr"
    faltend = [a for a in aufrufe if a[2] in FALTENDE_FAMILIEN]
    assert len(faltend) >= 6, f"Nur {len(faltend)} faltende Naehte gefunden"


def test_jede_faltende_naht_benennt_ihre_zaehlebene():
    """Nicht 'setzt case_policy', sondern 'hat sich dazu geaeussert'.

    Die Wortlisten-Keyness zaehlt NICHT am Korpus und faltet nichts, sie
    uebergibt deshalb ``counting_attribute=None``. Verlangt wird die
    ANWESENHEIT des Schluesselworts, damit die Frage bei jeder neuen Naht
    einmal beantwortet werden muss.
    """
    ohne = [
        f"  {p}:{z}  family={fam!r}"
        for p, z, fam, schl in _methodenblock_aufrufe()
        if fam in FALTENDE_FAMILIEN and "counting_attribute" not in schl
    ]
    assert ohne == [], (
        "Diese Naehte zaehlen ueber str.casefold und sagen es der Antwort "
        "nicht. Ohne die Angabe liest sich eine Zeile als Aussage ueber ihre "
        "gedruckte Schreibung, waehrend sie eine Aussage ueber die ganze "
        "Faltklasse ist:\n" + "\n".join(ohne)
    )


def test_niemand_setzt_die_zeichenkette_selbst():
    """Eine zweite Schreibweise derselben Angabe ist eine zweite Wahrheit."""
    von_hand: list[str] = []
    for pfad in sorted(SRC.rglob("*.py")):
        if pfad.name == "analysis_defaults.py":
            continue
        for nr, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
            # The former label implied a different normalization rule.
            if f'"{CASE_POLICY_GEFALTET}"' in zeile or '"case_insensitive (casefold)"' in zeile:
                von_hand.append(f"  {pfad}:{nr}  {zeile.strip()[:80]}")
    assert von_hand == [], (
        "Die Angabe gehoert aus analysis_defaults.CASE_POLICY_GEFALTET, sonst "
        "koennen die Oberflaechen auseinanderlaufen:\n" + "\n".join(von_hand)
    )


@pytest.mark.parametrize("familie", sorted(FALTENDE_FAMILIEN))
def test_wortebene_wird_offengelegt(familie):
    block = build_method_block(familie, counting_attribute="word")
    assert block["case_policy"] == CASE_POLICY_GEFALTET


@pytest.mark.parametrize("familie", sorted(FALTENDE_FAMILIEN))
def test_lemma_wird_offengelegt(familie):
    assert build_method_block(familie, counting_attribute="lemma")["case_policy"]


def test_pos_wird_nicht_als_gefaltet_ausgegeben():
    """POS-Tags werden nicht gefaltet. Eine Angabe waere hier falsch."""
    assert "case_policy" not in build_method_block("keyness", counting_attribute="pos")


def test_nicht_faltende_familien_behaupten_keine_faltung():
    for familie in ("collocates", "ngrams", "dispersion", "wordsketch", "trend"):
        block = build_method_block(familie, counting_attribute="word")
        assert "case_policy" not in block, (
            f"{familie} faltet nicht und darf es nicht behaupten"
        )


def test_ohne_angabe_wird_nichts_behauptet():
    assert "case_policy" not in build_method_block("keyness")
