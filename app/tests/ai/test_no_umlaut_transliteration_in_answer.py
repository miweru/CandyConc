"""Kein „ue" wo „ü" hingehoert, auf der Flaeche, die der Nutzer liest.

BESCHWERDE, mehrfach, zuletzt am 2026-08-31 woertlich: "ALTER und IM
Programm sind die alle auch wieder UMALUTE in den Beschreibungen uff".

WARUM DAS SCHWER ZU BEWACHEN IST, und warum frueher nichts stand. Dieses
Repo schreibt seine Kommentare und Logmeldungen absichtlich in ASCII, und
das ist in Ordnung: sie landen nie in einer Antwort. Eine Wache, die alles
prueft, meldet ueber tausend Zeilen und wird deshalb abgeschaltet.

Zwei weitere Fallen, beide beim Bau dieser Wache aufgelaufen:

1. SUCHPAARE. ``grounding_markdown`` fuehrt an mehreren Stellen BEIDE
   Schreibungen nebeneinander ("zurückgegeben", "zurueckgegeben"), um
   Modelltext in jeder Form zu fangen. Wer die Umschrift dort ersetzt,
   macht die Suche blind fuer die Haelfte ihrer Faelle.

2. FELDNAMEN. ``schluessel`` in der Modellweg-API ist ein JSON-Feld, kein
   Anzeigetext. Ein Umlaut darin waere ein Bruch des Vertrags.

3. DOCSTRINGS. Sie beschreiben Code fuer Entwickler und landen in keiner
   Antwort. Ein Zeilenscanner sieht den Unterschied nicht.

Diese Wache prueft deshalb eine BENANNTE Flaeche ueber den SYNTAXBAUM: nur
echte Zeichenkettenliterale, keine Docstrings, keine Kommentare. Sie laesst
Suchpaare in Ruhe, auch wenn die zweite Schreibung eine Zeile weiter steht.
Und sie beweist jeden Treffer: gemeldet wird nur ein Wort, dessen
Umlautform anderswo im Quellbaum tatsaechlich vorkommt. Damit kann sie kein
englisches Wort ("queue", "process", "assets") anschwaerzen.

Der erste Anlauf war ein Zeilenscanner und meldete vier Fehlalarme: zwei
Suchpaare, deren Partnerzeile direkt darunter stand, und zwei Docstrings.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "candyconc"

#: Module, deren Zeichenketten in einer ausgelieferten Antwort oder in
#: einer API-Meldung landen. Wer hier ein Modul ergaenzt, erweitert die
#: Wache. Wer eines streicht, muss sagen warum.
ANTWORTFLAECHE = (
    "candyconc_copilot/grounding_markdown.py",
    # P11: dieses Modul stellt fuer drei Landungen den KOMPLETTEN
    # Antworttext, ohne dass ein Modell ihn je anfasst. Am 2026-09-03
    # stand dort woertlich "Fuer diese Zahlen lief weder ein Werkzeug
    # noch ein Modellaufruf." auf der Flaeche, die der Nutzer liest.
    "candyconc_copilot/deterministic_landing.py",
    "candyconc_copilot/method_sheet.py",
    "candyconc_copilot/finding_substance.py",
    "candyconc_copilot/measure_basis.py",
    "candyconc_copilot/analysis_token_report.py",
    "candyconc_copilot/row_spelling_note.py",
    "candyconc_copilot/table_promise_check.py",
    "candyconc_copilot/question_coverage.py",
    "candyconc_copilot/experiment_log.py",
    "candyconc_copilot/grounding_inventory.py",
    "candyconc_copilot/keyness_tool_def.py",
    "services/backend/start_suggestions.py",
    "services/backend/routes/system.py",
    "services/backend/routes/analysis.py",
    "services/backend/routes/documents.py",
    "services/backend/routes/annotations.py",
)

_UMSCHRIFT = re.compile(r"\b[A-Za-zÄÖÜäöüß]*(?:ae|oe|ue)[A-Za-zÄÖÜäöüß]*\b")
_MIT_UMLAUT = re.compile(r"\b[A-Za-zÄÖÜäöüß]*[äöüß][A-Za-zÄÖÜäöüß]*\b")
_LITERAL = re.compile(r'"([^"\\\n]{8,240})"|\'([^\'\\\n]{8,240})\'')

#: Bekannte Ausnahmen, jede mit Grund. Kein Sammelbecken.
ERLAUBT = {
    # JSON-Feldname der Modellweg-API. Ein Umlaut waere ein Vertragsbruch.
    "schluessel",
}


def _woerterbuch() -> set[str]:
    """Alle Woerter, die im Quellbaum MIT Umlaut vorkommen.

    Das ist der Beweis. Nur was hier steht, kann eine Umschrift sein.
    """
    gefunden: set[str] = set()
    for pfad in _SRC.rglob("*.py"):
        text = pfad.read_text(encoding="utf-8", errors="replace")
        gefunden |= {w.lower() for w in _MIT_UMLAUT.findall(text)}
    return gefunden


def _literale(quelle: str) -> list[tuple[int, str]]:
    """Echte Zeichenkettenliterale, OHNE Docstrings.

    Ein Docstring beschreibt Code fuer Entwickler und landet in keiner
    Antwort. Ein Zeilenscanner sieht den Unterschied nicht, der Syntaxbaum
    schon: ein Docstring ist der erste Ausdruck eines Moduls, einer Klasse
    oder einer Funktion.
    """
    import ast

    baum = ast.parse(quelle)
    docstrings: set[int] = set()
    for knoten in ast.walk(baum):
        if not isinstance(
            knoten, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        erster = (knoten.body or [None])[0]
        if (
            isinstance(erster, ast.Expr)
            and isinstance(erster.value, ast.Constant)
            and isinstance(erster.value.value, str)
        ):
            docstrings.add(id(erster.value))
    heraus: list[tuple[int, str]] = []
    for knoten in ast.walk(baum):
        if (
            isinstance(knoten, ast.Constant)
            and isinstance(knoten.value, str)
            and id(knoten) not in docstrings
            and 8 <= len(knoten.value) <= 400
        ):
            heraus.append((knoten.lineno, knoten.value))
    return heraus


def _umlautlesarten(wort: str) -> set[str]:
    aus = {wort}
    for kurz, lang in (("ae", "ä"), ("oe", "ö"), ("ue", "ü")):
        neu = set()
        for form in aus:
            neu.add(form)
            stelle = form.find(kurz)
            while stelle != -1:
                neu.add(form[:stelle] + lang + form[stelle + len(kurz):])
                stelle = form.find(kurz, stelle + 1)
        aus = neu
    return aus - {wort}


class KeineUmschriftAufDerAntwortflaeche(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bekannt = _woerterbuch()

    def test_das_woerterbuch_ist_nicht_leer(self):
        """Ohne Woerterbuch beweist die Wache nichts und ist gruen.

        Genau diese Klasse von blinder Wache hat dieses Projekt an einem
        einzigen Tag dreimal gebaut.
        """
        self.assertGreater(len(self.bekannt), 200, len(self.bekannt))
        self.assertIn("für", self.bekannt)

    def test_die_flaeche_existiert_wirklich(self):
        """Ein Pfad, der ins Leere zeigt, prueft nichts."""
        for rel in ANTWORTFLAECHE:
            with self.subTest(modul=rel):
                self.assertTrue((_SRC / rel).is_file(), rel)

    def test_die_wache_erkennt_eine_eingeschmuggelte_umschrift(self):
        """Sie muss den Ausfall EINMAL nachweislich fangen koennen."""
        treffer = self._pruefe_text('"Die Abfrage ist ungueltig fuer dieses Korpus"')
        self.assertTrue(treffer, "die Wache sieht eine klare Umschrift nicht")

    def test_die_wache_schwaerzt_kein_englisches_wort_an(self):
        for probe in ('"the process queue has assets"',
                      '"assign the response value"'):
            with self.subTest(probe=probe):
                self.assertFalse(self._pruefe_text(probe), probe)

    def test_ein_suchpaar_bleibt_unangetastet(self):
        """Beide Schreibungen in einer Zeile sind Absicht, kein Fehler."""
        zeile = '("zurückgegeben", "zurueckgegeben"),'
        self.assertFalse(self._pruefe_text(zeile), zeile)

    def test_kein_anzeigetext_traegt_eine_umschrift(self):
        funde: list[str] = []
        for rel in ANTWORTFLAECHE:
            quelle = (_SRC / rel).read_text(encoding="utf-8")
            zeilen = quelle.splitlines()
            for nummer, inhalt in _literale(quelle):
                # Suchpaar: steht die Umlautform im UMFELD, sind beide
                # Schreibungen gewollt. Drei Zeilen reichen, weil solche
                # Paare als Nachbarn in einem Tupel stehen.
                umfeld = "\n".join(
                    zeilen[max(0, nummer - 4):nummer + 3]
                ).lower()
                for wort in self._verdaechtig(inhalt):
                    if any(f in umfeld for f in _umlautlesarten(wort.lower())):
                        continue
                    funde.append(f"{rel}:{nummer}  {wort}  |  {inhalt[:66]}")
        self.assertEqual(
            funde, [],
            "ASCII-Umschrift in nutzersichtbarem Text:\n" + "\n".join(funde),
        )

    def _verdaechtig(self, inhalt: str) -> list[str]:
        """Die verdaechtigen Woerter EINES Literals."""
        # Regex-Alternationen und Muster bleiben unangetastet.
        if "|" in inhalt or inhalt.startswith(("^", "\\b", "(?")):
            return []
        heraus: list[str] = []
        for wort in _UMSCHRIFT.findall(inhalt):
            klein = wort.lower()
            if len(klein) < 5 or klein in ERLAUBT:
                continue
            if _umlautlesarten(klein) & self.bekannt:
                heraus.append(wort)
        return heraus

    def _pruefe_text(self, zeile: str) -> list[str]:
        """Eine Quellzeile, fuer die Selbstproben dieser Wache."""
        funde = []
        for treffer in _LITERAL.finditer(zeile):
            inhalt = treffer.group(1) or treffer.group(2)
            for wort in self._verdaechtig(inhalt):
                if any(f in zeile.lower() for f in _umlautlesarten(wort.lower())):
                    continue
                funde.append(wort)
        return funde


if __name__ == "__main__":
    unittest.main()
