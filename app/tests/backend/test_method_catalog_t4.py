"""T4 — Methodenkatalog: formula_mathml / explanation / reference auf JEDEM
METHOD_META-Eintrag (Server-Wahrheit für die Formel-Tooltips).

Additive contract: the pre-existing fields (name, latex_formula, smoothing,
sort_key) stay byte-identical — pinned below for representative measures — and
every entry gains well-formed presentation MathML, a neutral German
explanation, and an established reference.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MATHML_NS = "{http://www.w3.org/1998/Math/MathML}"


def _all_entries():
    from candyconc.analysis_defaults import METHOD_META

    return METHOD_META


def test_every_entry_has_complete_catalog_fields():
    meta = _all_entries()
    for key, entry in meta.items():
        for field in ("name", "latex_formula", "smoothing", "sort_key",
                      "formula_mathml", "explanation", "reference"):
            assert field in entry, f"{key} fehlt {field}"
            assert str(entry[field]).strip() != "" or field == "smoothing", (key, field)
        assert len(entry["explanation"]) >= 60, f"{key}: explanation zu knapp"
        assert entry["reference"].strip(), key


def test_formula_mathml_is_wellformed_presentation_mathml():
    meta = _all_entries()
    for key, entry in meta.items():
        root = ET.fromstring(entry["formula_mathml"])
        assert root.tag == f"{MATHML_NS}math", key
        # Presentation MathML with real layout markup, not flat text. The one
        # plain-count formula (frequency: f = #{Vorkommen}) has no fraction or
        # script by nature; every actual statistic must carry layout elements.
        markup = entry["formula_mathml"]
        if key == "frequency":
            assert "<mrow>" in markup, key
            continue
        assert ("<mfrac>" in markup or "<msub>" in markup or "<msup>" in markup), (
            f"{key}: kein <mfrac>/<msub>/<msup> im MathML"
        )


def test_pair_event_overrides_carry_matching_mathml():
    """Overridden LaTeX (pair-event space) must not ship the word-sketch MathML."""
    from candyconc.analysis_defaults import method_statistics

    collocates = {e["key"]: e for e in method_statistics("collocates")}
    wordsketch = {e["key"]: e for e in method_statistics("wordsketch")}

    # Seit dem 2026-08-29: logdice traegt Rychlys Wortfrequenz-Nenner,
    # logdice_window die Randsummen der Distanztafel. BEIDE Formelfelder
    # muessen dem jeweiligen Nenner folgen, sonst zeigt die Oberflaeche
    # eine andere Rechnung als die Zahl.
    assert r"f(u) + f(v)" in collocates["logdice"]["latex_formula"]
    assert "<mi>f</mi><mo>(</mo><mi>u</mi>" in collocates["logdice"]["formula_mathml"]
    assert r"R_1 + C_1" in collocates["logdice_window"]["latex_formula"]
    assert ("<msub><mi>R</mi><mn>1</mn></msub>"
            in collocates["logdice_window"]["formula_mathml"])
    # Word sketches keep the token-count marginals f1+f2 in BOTH fields.
    assert r"f_1 + f_2" in wordsketch["logdice"]["latex_formula"]
    assert "<msub><mi>f</mi><mn>1</mn></msub>" in wordsketch["logdice"]["formula_mathml"]
    for entry in collocates.values():
        ET.fromstring(entry["formula_mathml"])  # overrides stay well-formed


def test_legacy_fields_byte_identical_anchors():
    """The additive catalog must not have touched existing published strings."""
    meta = _all_entries()
    assert meta["logdice"]["latex_formula"] == r"14 + \log_2\!\left(\frac{2\,O_{11}}{f_1 + f_2}\right)"
    assert meta["mi"]["latex_formula"] == (
        r"\log_2\!\left(\frac{O_{11}}{E_{11}}\right),\quad E_{11} = \frac{R_1 \cdot C_1}{N_\Omega}"
    )
    assert meta["ll"]["latex_formula"] == r"2 \sum_{ij} O_{ij}\,\ln\!\left(\frac{O_{ij}}{E_{ij}}\right)"
    assert meta["log_ratio"]["smoothing"] == "Haldane-Anscombe +0.5"
    assert meta["logdice"]["sort_key"] == "dice"
    assert meta["ll_signed"]["sort_key"] == "ll_signed"


def test_references_are_the_established_sources():
    meta = _all_entries()
    expected = {
        "mi": "Church & Hanks 1990",
        "t": "Church et al. 1991",
        "logdice": "Rychlý 2008",
        "ll": "Dunning 1993",
        "ll_signed": "Dunning 1993",
        "log_ratio": "Hardie 2014",
        "chi2": "Pearson 1900",
        "npmi": "Bouma 2009",
        "lmi": "Evert 2005",
        "dice": "Dice 1945",
        "dp": "Gries 2008",
        "dpnorm": "Lijffijt & Gries 2012",
        "bic": "Wilson 2013",
        "mi3": "Oakes 1998",
        # STTR comes from WordSmith Tools (Scott), Covington & McFall 2010
        # introduce MATTR (methoden.md B11).
        "sttr": "Scott, WordSmith Tools",
        "mattr": "Covington & McFall 2010",
        "juilland_d": "Juilland & Chang-Rodríguez 1964",
        "q_value": "Benjamini & Hochberg 1995",
        "wilson_ci": "Wilson 1927",
    }
    for key, ref in expected.items():
        assert meta[key]["reference"] == ref, (key, meta[key]["reference"])
    # Delta P: Allan 1980 defines it, Gries 2013 brings it to collocation
    # analysis. Gries 2008 is the DP dispersion paper (methoden.md B11).
    for key in ("delta_p_nc", "delta_p_cn"):
        assert "Gries 2008" not in meta[key]["reference"]
        assert "Allan 1980" in meta[key]["reference"]
        assert "Gries 2013" in meta[key]["reference"]
        assert "Ellis 2006" in meta[key]["reference"]
    # LRC: Evert 2022 (Clopper-Pearson), Hardie 2014 has no interval.
    assert "Hardie" not in meta["lrc"]["reference"]
    assert "Evert 2022" in meta["lrc"]["reference"]


def test_new_t1_t3_measures_are_registered():
    from candyconc.analysis_defaults import build_method_block, method_statistics

    collocate_keys = [e["key"] for e in method_statistics("collocates")]
    assert "mi3" in collocate_keys
    # mi3 sits next to mi in the display order.
    assert collocate_keys.index("mi3") == collocate_keys.index("mi") + 1

    trend = build_method_block("trend")
    assert [s["key"] for s in trend["statistics"]] == ["per_million", "wilson_ci"]
    assert trend["default_sort"] == "period"

    sample = build_method_block("sample")
    assert [s["key"] for s in sample["statistics"]] == ["random_sample"]


def test_no_valuation_labels_in_user_visible_strings():
    meta = _all_entries()
    for key, entry in meta.items():
        for field in ("name", "explanation"):
            lowered = str(entry[field]).lower()
            assert "empfohlen" not in lowered, (key, field)
            assert "recommended" not in lowered, (key, field)


def test_network_docstring_is_valuation_free():
    from candyconc.services.backend.routes import analysis as a

    doc = a.analysis_collocation_network_get.__doc__ or ""
    assert "empfohlen" not in doc.lower()
    assert "mi3" in doc  # the new measure is documented in the OpenAPI docstring
