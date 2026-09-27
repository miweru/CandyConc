"""Every displayed evidence path resolves to the value it labels.

Container paths use plural names and zero-based positions, including
rows[0], periods[0], tables.obj[1] and values.party[0]. Flat query_count
results use total rather than rows[0].total. Check each displayed path
against the resolver to catch both missing references and adjacent rows."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot import grounding_refs as gr  # noqa: E402
from candyconc.candyconc_copilot.grounding_contracts import (  # noqa: E402
    AnalysisContract,
)
from candyconc.candyconc_copilot.grounding_facts import (  # noqa: E402
    build_evidence_bundle,
    make_evidence_item,
)

#: Werkzeugausgaben in der Gestalt, die die echten Wrapper liefern.
AUSGABEN = {
    "query_count": {
        "status": "success", "query": '[lemma="kunne"]', "total": 460712,
        "corpus_tokens": 47058875, "denominator_tokens": 47058875,
        "per_million": 9790.1,
    },
    "frequency_list": {
        "status": "success", "total": 2,
        "rows": [
            {"word": "kunne", "freq": 100223, "per_million": 2129.7},
            {"word": "skulle", "freq": 44905, "per_million": 954.2},
        ],
    },
    "trend_analysis": {
        "status": "success",
        "periods": [
            {"period": "2015", "hits": 111, "tokens": 1000},
            {"period": "2016", "hits": 222, "tokens": 2000},
        ],
    },
    "word_sketch": {
        "status": "success",
        "tables": {"obj": [{"word": "Antrag", "ll": 55.5},
                           {"word": "Gesetz", "ll": 44.4}]},
    },
    "metadata_values": {
        "status": "success", "values": {"party": ["AfD", "GRUENE"]},
    },
}

#: Praefixe, die in der Oberflaeche einen ECHTEN Referenzpfad ankuendigen.
PFAD_PRAEFIXE = ("rows[", "periods[", "tables.", "values.")


def _item_und_bundle(tool: str):
    item = make_evidence_item(
        item_id="ev1", tool=tool, tool_call_id="c1", query={},
        output=AUSGABEN[tool], analysis_family="x",
    )
    return item, build_evidence_bundle(AnalysisContract(), [item])


def _oberflaeche(item) -> list[str]:
    d = item.model_dump() if hasattr(item, "model_dump") else dict(item.__dict__)
    return list(d.get("grounding_surface") or [])


def _loest_auf(bundle, pfad: str) -> bool:
    res = gr.resolve_references(
        "X {{ev:%s}}." % pfad, bundle, detect_bare_numbers=False
    )
    return "[Beleg fehlt]" not in str(res.get("text") or "")


class AngezeigtePfadeLoesenAuf(unittest.TestCase):
    """Die Invariante. Ohne sie ist die Anzeige eine Falle."""

    def test_jeder_angezeigte_pfad_loest_auf(self):
        geprueft = 0
        for tool in AUSGABEN:
            item, bundle = _item_und_bundle(tool)
            for zeile in _oberflaeche(item):
                if not zeile.startswith(PFAD_PRAEFIXE):
                    continue
                pfad = re.split(r"[ =]", zeile, 1)[0]
                if not pfad.endswith("]"):
                    pfad = pfad + "[0]"
                geprueft += 1
                self.assertTrue(
                    _loest_auf(bundle, "ev1." + pfad),
                    f"{tool}: Oberflaeche zeigt {pfad!r}, Resolver findet es nicht",
                )
        self.assertGreaterEqual(geprueft, 7, "zu wenige Pfade geprueft")

    def test_rows_null_ist_die_erste_zeile(self):
        """Der Off-by-one, der die Nachbarzeile lieferte."""
        item, bundle = _item_und_bundle("frequency_list")
        res = gr.resolve_references(
            "X {{ev:ev1.rows[0].word}}.", bundle, detect_bare_numbers=False
        )
        self.assertIn("kunne", str(res.get("text")))
        self.assertTrue(
            any(z.startswith("rows[0] ") and "kunne" in z
                for z in _oberflaeche(item)),
            "die Anzeige muss dieselbe Zeile als rows[0] fuehren",
        )

    def test_keine_singularform_und_keine_eins_basis_mehr(self):
        for tool in ("frequency_list", "trend_analysis"):
            item, _ = _item_und_bundle(tool)
            for zeile in _oberflaeche(item):
                self.assertFalse(
                    zeile.startswith(("row[", "period[")),
                    f"{tool}: {zeile!r} kuendigt einen Pfad an, den es nicht gibt",
                )

    def test_word_sketch_nennt_punkt_statt_klammer(self):
        item, _ = _item_und_bundle("word_sketch")
        zeilen = _oberflaeche(item)
        self.assertTrue(any(z.startswith("tables.obj[0] ") for z in zeilen))
        self.assertFalse(any(z.startswith("table[obj]") for z in zeilen))


class FlacheErgebnisseHabenKeinenContainer(unittest.TestCase):
    """query_count: hier kostete ein Griff nach rows die Rohzahl."""

    def test_total_loest_auf(self):
        _item, bundle = _item_und_bundle("query_count")
        for feld in ("total", "per_million", "denominator_tokens"):
            self.assertTrue(_loest_auf(bundle, "ev1." + feld), feld)

    def test_rows_griff_faellt(self):
        _item, bundle = _item_und_bundle("query_count")
        self.assertFalse(_loest_auf(bundle, "ev1.rows[0].total"))

    def test_die_oberflaeche_kuendigt_hier_keinen_container_an(self):
        item, _ = _item_und_bundle("query_count")
        for zeile in _oberflaeche(item):
            self.assertFalse(zeile.startswith(("rows[", "periods[", "tables.")))


class DieSyntaxhilfeNenntDieContainer(unittest.TestCase):
    """Vorher stand dort nur rows[i], also die gefaehrlichere Haelfte."""

    def test_alle_vier_container_werden_genannt(self):
        hilfe = gr.reference_syntax_help()
        for container in ("rows[i]", "periods[i]", "tables.", "values."):
            self.assertIn(container, hilfe)

    def test_die_basis_wird_genannt(self):
        self.assertIn("ab 0", gr.reference_syntax_help())

    def test_flache_ergebnisse_werden_genannt(self):
        hilfe = gr.reference_syntax_help()
        self.assertIn("query_count", hilfe)
        self.assertIn("{{ev:ID.total}}", hilfe)


if __name__ == "__main__":
    unittest.main()
