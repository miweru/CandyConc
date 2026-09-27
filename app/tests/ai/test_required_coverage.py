"""Mehr Abdeckung ist nicht weniger.

``missing_response_requirements`` pruefte mit ``len(candidates) != 1``:
genau EIN deckender Claim erfuellte eine Antwortpflicht, zwei oder drei
liessen sie als UNERFUELLT gelten. Nachgemessen am 2026-08-28 vor dem Fix:

    0 deckende Claims -> unerfuellt
    1 deckender Claim -> erfuellt
    2 deckende Claims -> UNERFUELLT
    3 deckende Claims -> UNERFUELLT

Das ist nicht nur sachlich falsch, es treibt die Verifikationsschleife:
eine unerfuellte Pflicht laesst ``_accepted_claims_complete`` scheitern,
das Tor setzt ``verdict`` auf ``retry``, und die GANZE Antwort wird neu
synthetisiert. Im live mitgeschnittenen Turn siebenmal zu je rund 360
Sekunden, bei einem Modell, das in allen sieben Verdicts „pass“ sagte und
nichts zurueckwies.

Das Modell schrieb also eine BESSER gedeckte Antwort und bekam dafuer eine
Neuschrift.

Die Schutzregel bleibt: ein und derselbe Claim darf nicht zwei Pflichten
decken. Deshalb wird der erste noch UNVERBRAUCHTE Kandidat genommen, nicht
blind der erste.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot.grounding_schemas import (  # noqa: E402
    AnswerEnvelope,
    ClaimDraft,
    ResponseRequirement,
)
from candyconc.candyconc_copilot.grounding_validation import (  # noqa: E402
    missing_response_requirements,
)


def _pflicht(kennung: str) -> ResponseRequirement:
    return ResponseRequirement(
        id=kennung, description="Nenne einen Befund.", claim_kind="observation"
    )


def _claim(kennung: str, text: str, pflicht: str = "r1") -> ClaimDraft:
    return ClaimDraft(
        id=kennung, claim_kind="observation", text=text,
        fact_ids=["f1"], response_requirement_id=pflicht,
    )


def _offen(claims, pflichten):
    return [
        p.id
        for p in missing_response_requirements(
            AnswerEnvelope(claims=claims), [c.id for c in claims], [], pflichten
        )
    ]


class ZweiDeckendeClaimsErfuellenAuch(unittest.TestCase):
    def test_null_claims_lassen_die_pflicht_offen(self):
        self.assertEqual(_offen([], [_pflicht("r1")]), ["r1"])

    def test_ein_claim_erfuellt(self):
        claims = [_claim("c1", "Erster Befund.")]
        self.assertEqual(_offen(claims, [_pflicht("r1")]), [])

    def test_zwei_und_drei_claims_erfuellen_ebenfalls(self):
        # Der eigentliche Fix. Vorher galten beide als unerfuellt.
        for anzahl in (2, 3):
            with self.subTest(anzahl=anzahl):
                claims = [
                    _claim(f"c{k}", f"Befund Nummer {k}.")
                    for k in range(1, anzahl + 1)
                ]
                self.assertEqual(_offen(claims, [_pflicht("r1")]), [])


class DieSchutzregelBleibt(unittest.TestCase):
    """Ein Claim darf nicht zwei Pflichten decken."""

    def test_identische_substanz_deckt_nur_eine_pflicht(self):
        claims = [
            _claim("c1", "Derselbe Satz.", "r1"),
            _claim("c2", "Derselbe Satz.", "r2"),
        ]
        offen = _offen(claims, [_pflicht("r1"), _pflicht("r2")])
        self.assertEqual(len(offen), 1, "genau eine Pflicht muss offen bleiben")

    def test_verschiedene_substanzen_decken_beide_pflichten(self):
        claims = [
            _claim("c1", "Erster Befund.", "r1"),
            _claim("c2", "Zweiter Befund.", "r1"),
            _claim("c3", "Dritter Befund.", "r2"),
            _claim("c4", "Vierter Befund.", "r2"),
        ]
        self.assertEqual(_offen(claims, [_pflicht("r1"), _pflicht("r2")]), [])

    def test_der_erste_unverbrauchte_kandidat_wird_genommen(self):
        # Deckt c1 bereits r1, muss r2 auf c2 ausweichen statt offen zu
        # bleiben. Blind den ersten Kandidaten zu nehmen wuerde hier eine
        # Pflicht offen lassen, obwohl ein freier Claim sie deckt.
        claims = [
            _claim("c1", "Gemeinsamer Satz.", "r1"),
            _claim("c2", "Gemeinsamer Satz.", "r2"),
            _claim("c3", "Eigener Satz.", "r2"),
        ]
        self.assertEqual(_offen(claims, [_pflicht("r1"), _pflicht("r2")]), [])


if __name__ == "__main__":
    unittest.main()
