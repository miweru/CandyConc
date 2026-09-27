"""Frequency answers include rankings only when requested.

Preserve the requested raw count, rate and denominator while omitting an
unrequested corpus-wide frequency list. Explicit ranking requests remain
supported."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot.analysis_grounding import (  # noqa: E402
    _build_term_frequency_markdown,
)
from candyconc.candyconc_copilot.grounding_evidence import (  # noqa: E402
    rangliste_ausdruecklich_bestellt,
)
from candyconc.candyconc_copilot.grounding_facts import (  # noqa: E402
    make_evidence_item,
)

ZAEHLUNG = {
    "status": "success", "query": "Flüchtling", "total": 805,
    "corpus_tokens": 273550093, "denominator_tokens": 273550093,
    "denominator_scope": "corpus", "per_million": 2.9,
    "scope": {"corpus_id": "sample_corpus", "level": "corpus"},
    "query_mode": "plain_word", "attribute": "word", "case_insensitive": True,
}

RANGLISTE = {
    "status": "success", "group_by": "word", "total": 49996,
    "scope": {"corpus_id": "sample_corpus", "level": "corpus"},
    "rows": [
        {"word": "Beifall", "f": 946766, "per_million": 3461.0},
        {"word": "Herr", "f": 857969, "per_million": 3136.4},
    ],
}


def _posten(frequenz_ausgabe: dict, frequenz_args: dict) -> list:
    return [
        make_evidence_item(
            item_id="e1", tool="query_count", tool_call_id="c1",
            query={"query": "Flüchtling"}, output=ZAEHLUNG,
            analysis_family="term_frequency",
        ),
        make_evidence_item(
            item_id="e2", tool="frequency_list", tool_call_id="c2",
            query=frequenz_args, output=frequenz_ausgabe,
            analysis_family="term_frequency",
        ),
    ]


class DieZaehlfrageBekommtNurIhreAntwort(unittest.TestCase):
    def test_die_korpusrangliste_faellt_weg(self):
        markdown = _build_term_frequency_markdown(
            _posten(RANGLISTE, {}), evidence_gaps=[]
        )
        self.assertIn("805-mal", markdown)
        self.assertNotIn("Beifall", markdown)
        self.assertNotIn("946766", markdown)

    def test_die_zaehlung_selbst_bleibt_vollstaendig(self):
        # Rohzahl, Rate und Nenner sind die Frage. Sie duerfen nicht mit
        # der Rangliste zusammen verschwinden.
        markdown = _build_term_frequency_markdown(
            _posten(RANGLISTE, {}), evidence_gaps=[]
        )
        for pflicht in ("805", "2.9", "273550093"):
            self.assertIn(pflicht, markdown)


class EineBestellteRanglisteBleibt(unittest.TestCase):
    """Wer sie ausdruecklich als Rangliste formt, bekommt sie."""

    def test_pos_filter_gilt_als_bestellung(self):
        markdown = _build_term_frequency_markdown(
            _posten(dict(RANGLISTE, pos="NOUN"), {"pos": "NOUN"}),
            evidence_gaps=[],
        )
        self.assertIn("Beifall", markdown)

    def test_gesetzte_obergrenze_gilt_als_bestellung(self):
        markdown = _build_term_frequency_markdown(
            _posten(dict(RANGLISTE, limit=20), {"limit": 20}),
            evidence_gaps=[],
        )
        self.assertIn("Beifall", markdown)

    def test_ohne_gezaehlten_term_ist_die_liste_die_antwort(self):
        nur_liste = [
            make_evidence_item(
                item_id="e2", tool="frequency_list", tool_call_id="c2",
                query={}, output=RANGLISTE, analysis_family="term_frequency",
            )
        ]
        markdown = _build_term_frequency_markdown(nur_liste, evidence_gaps=[])
        self.assertIn("Beifall", markdown)


class DasPraedikatFuerSich(unittest.TestCase):
    def test_ein_blosser_aufruf_ist_keine_bestellung(self):
        # Den macht der Vorplan von sich aus.
        self.assertFalse(rangliste_ausdruecklich_bestellt(_posten(RANGLISTE, {})))

    def test_pos_obergrenze_und_gruppierung_sind_bestellungen(self):
        for ausgabe, args in (
            (dict(RANGLISTE, pos="NOUN"), {}),
            (RANGLISTE, {"pos": "VERB"}),
            (dict(RANGLISTE, limit=20), {}),
            (dict(RANGLISTE, group_by="lemma"), {}),
        ):
            with self.subTest(args=args):
                self.assertTrue(
                    rangliste_ausdruecklich_bestellt(_posten(ausgabe, args))
                )

    def test_gruppierung_nach_wortform_ist_die_voreinstellung(self):
        # group_by=word ist der Standard und damit keine Bestellung.
        self.assertFalse(
            rangliste_ausdruecklich_bestellt(
                _posten(dict(RANGLISTE, group_by="word"), {})
            )
        )

    def test_ohne_frequenzposten_ist_nichts_bestellt(self):
        self.assertFalse(rangliste_ausdruecklich_bestellt([]))


if __name__ == "__main__":
    unittest.main()
