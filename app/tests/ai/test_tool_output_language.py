"""Analysis tool text follows the answer language without changing the numbers."""

from types import SimpleNamespace

import numpy as np

from candyconc.analysis_defaults import analysetoken_spitze
from candyconc.answer_language import answer_language_scope, resolve
from candyconc.candyconc_copilot.sample_order import in_ziehungsfolge, liegt_in_ziehungsfolge
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()


def tool_texts(monkeypatch):
    from candyconc.services.backend import server
    from candyconc.services.backend.routes import analysis
    from candyconc.tools import collocate_stats

    index = SimpleNamespace(fast_index=SimpleNamespace(doc_metadata={0: {"date": "2020"}, 1: {"date": "bad"}}))
    monkeypatch.setattr(_TW, "_resolve_docset_doc_ids", lambda *_args: (index, None))
    monkeypatch.setattr(_TW, "_where_dokumente", lambda *_args: None)
    monkeypatch.setattr(_TW, "_get_doc_count", lambda _idx: 2)
    monkeypatch.setattr(_TW, "_wortnenner", lambda *_args: {"woerter": 4, "roh": 5})
    monkeypatch.setattr(_TW, "_analysis_scope_provenance", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda _idx: np.array([5, 10]))
    monkeypatch.setattr(server, "_compute_query_count", lambda *_args, **_kwargs: (1, 0, True))
    monkeypatch.setattr(analysis, "_index_fingerprint", lambda _idx: "synthetic")
    monkeypatch.setattr(collocate_stats, "collocate_network_data", lambda *_args, **_kwargs: {
        "term": "alpha", "measure": "logdice", "nodes": [], "edges": [], "diagnostics": {},
    })
    trend = _TW.trend_analysis_tool(date_field="date", query="alpha")
    _, sample = in_ziehungsfolge(list(range(8)), {"seed": 7}, limit=3, sortiert=False)
    return {
        "sample": sample,
        "collocates": _TW._kollokat_einheiten(),
        "network": _TW.collocation_network_tool("alpha")["metric_units"],
        "trend": {"method": {key: trend["method"][key] for key in (
            "rate_definition", "ci_formula", "empty_period_policy", "undated_policy",
        )}, "warnings": trend["warnings"], "periods": trend["periods"]},
        "filtered": analysetoken_spitze([{"word": ",", "logdice": 12.23}, {"word": "#", "logdice": 8.03}], "logdice"),
        "unscored": analysetoken_spitze([{"word": "|"}]),
        "invalid_score": analysetoken_spitze([{"word": "?", "logdice": "bad"}], "logdice"),
    }


def test_analysis_text_fields_resolve_to_english(monkeypatch):
    payload = tool_texts(monkeypatch)
    with answer_language_scope("en"):
        english = resolve(payload)
    with answer_language_scope("de"):
        german = resolve(payload)
    for section in ("collocates", "network"):
        for field, value in english[section].items():
            assert value != german[section][field], (section, field)
    for field, value in english["trend"]["method"].items():
        assert value != german["trend"]["method"][field], field
    assert english["trend"]["method"]["rate_definition"].endswith("per period")
    assert english["trend"]["warnings"][0].startswith("1 document(s)")
    assert english["trend"]["warnings"][1].startswith("Hit count incomplete")
    assert english["trend"]["periods"] == german["trend"]["periods"]
    assert english["filtered"] == ["“,” (logdice 12.23)", "“#” (logdice 8.03)"]
    assert german["filtered"] == ["„,“ (logdice 12,23)", "„#“ (logdice 8,03)"]
    assert english["unscored"] == ["“|”"]
    assert english["invalid_score"] == ["“?”"]


def test_sample_order_survives_answer_language_resolution(monkeypatch):
    payload = tool_texts(monkeypatch)
    for language, expected in (("de", "gezogen, nicht nach Korpusposition"), ("en", "draw order, not corpus position")):
        with answer_language_scope(language):
            translated = resolve(payload)
        assert translated["sample"]["order"] == expected
        assert liegt_in_ziehungsfolge(translated)
    assert not liegt_in_ziehungsfolge({"sample": {"order": "corpus position"}})
