"""query_count groups counts by a metadata field within one call."""

import pytest


@pytest.fixture(scope="module")
def tw():
    import os

    from candyconc.core import query_runtime as qrt
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.services.backend import server as _server
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    pfad = os.environ.get("CANDYCONC_INDEX_PATH")
    if not pfad or not os.path.isdir(pfad):
        pytest.skip("CANDYCONC_INDEX_PATH zeigt nicht auf einen Index")
    idx = CorpusIndex(pfad)
    vorher_qrt, vorher_server = qrt._CORPUS_INDEX, getattr(_server, "_INDEX", None)
    qrt._CORPUS_INDEX = idx
    _server.set_default_index(idx)
    try:
        yield _load_real_tool_wrappers(), idx
    finally:
        qrt._CORPUS_INDEX = vorher_qrt
        _server.set_default_index(vorher_server)


def _feld_mit_wenigen_werten(idx):
    from candyconc.core.meta_filters import metadata_fields

    for feld in metadata_fields(idx):
        werte = idx.metadata_values(feld) or []
        if 2 <= len(werte) <= 12:
            return feld, werte
    pytest.skip("kein Feld mit 2 bis 12 Werten")


def test_jede_zeile_gleich_teilkorpus_plus_zaehlung(tw):
    wrapper, idx = tw
    feld, werte = _feld_mit_wenigen_werten(idx)
    auf = wrapper.query_count_tool("und", nach=feld)
    zeilen = {z["wert"]: z for z in auf["rows"]}
    assert zeilen, auf
    for wert in werte:
        if str(wert) not in zeilen:
            continue
        ds = wrapper.create_docset_tool(filters={feld: wert})
        einzeln = wrapper.query_count_tool("und", docset_id=ds["docset_id"])
        z = zeilen[str(wert)]
        assert (z["total"], z["tokens"], z["per_million"]) == (
            einzeln["total"], einzeln["denominator_tokens"], einzeln["per_million"]), (wert, z, einzeln)


def test_filter_und_gesamtzahl(tw):
    wrapper, idx = tw
    feld, werte = _feld_mit_wenigen_werten(idx)
    ds = wrapper.create_docset_tool(filters={feld: werte[0]})
    mit_filter = wrapper.query_count_tool("und", filters={feld: werte[0]})
    einzeln = wrapper.query_count_tool("und", docset_id=ds["docset_id"])
    assert (mit_filter["total"], mit_filter["denominator_tokens"]) == (einzeln["total"], einzeln["denominator_tokens"])


def test_zu_viele_werte_nennt_die_zahl(tw):
    from candyconc.core.meta_filters import metadata_fields

    wrapper, idx = tw
    feld = next((f for f in metadata_fields(idx) if len(idx.metadata_values(f) or []) > 50), None)
    if feld is None:
        pytest.skip("kein Feld mit mehr als 50 Werten")
    with pytest.raises(Exception, match="höchstens 50"):  # zwei Paketnamen der Fehlerklasse im Testaufbau
        wrapper.query_count_tool("und", nach=feld)


def _schema_von(name):
    from tests.ai.test_every_tool_meets_its_schema import _werkzeuge_mit_schema

    return next(schema for n, _fn, schema in _werkzeuge_mit_schema() if n == name)


def test_aufschluesselung_und_mit_c_halten_das_antwortschema(tw):
    """The MCP response schema accepts rows, nach, filters and mit_c.

Exercise schema validation as well as direct tool calls."""
    from jsonschema import validate

    wrapper, idx = tw
    feld, werte = _feld_mit_wenigen_werten(idx)
    schema = _schema_von("query_count")
    validate(wrapper.query_count_tool("und", nach=feld, filters={feld: werte[0]}), schema)
    ausgabe = wrapper.query_count_tool('[word="und"]')
    assert "mit_c" in ausgabe
    validate(ausgabe, schema)


def test_zu_weites_muster_in_der_aufschluesselung_zaehlt_je_wert(tw, monkeypatch):
    """A broad regex cell counts by metadata value without a vocabulary-type cap.

Lower all three limits in the test process and require the same counts
as the uncapped single-cell postings path."""
    import cqlhpc.predicates as pr
    from candyconc.core.fast_index_backend import FastIndexBackend

    wrapper, idx = tw
    feld, _werte = _feld_mit_wenigen_werten(idx)
    abfrage = '[word=".{13,}"]'
    # Die Vergleichszahl mit gleichwertigem, anders geschriebenem Muster: dasselbe
    # Muster laege danach in einem Ergebniszwischenspeicher, und die Probe
    # liefe am alten Code vorbei an der Grenze (am alten Code geprueft).
    gleichwertig = '[word=".{13}.*"]'
    ohne_grenze = {str(z["wert"]): z["total"] for z in wrapper.query_count_tool(gleichwertig, nach=feld)["rows"]}
    monkeypatch.setattr(pr, "_MAX_REGEX_FREQ", 5)
    monkeypatch.setattr(pr, "_MAX_REGEX_TYPES", 5)
    monkeypatch.setattr(FastIndexBackend, "_MAX_REGEX_POSITIONS", 5)
    auf = wrapper.query_count_tool(abfrage, nach=feld)
    mit_grenze = {str(z["wert"]): z["total"] for z in auf["rows"]}
    assert mit_grenze == ohne_grenze, (mit_grenze, ohne_grenze)
    assert sum(mit_grenze.values()) > 5


def test_dp_ueber_die_werte():
    """Nachgerechnet an der Muse-Probe zu Frage 9: zehn Register, DP 0,552."""
    from candyconc.candyconc_copilot.count_breakdown import streuung

    zeilen = [{"total": n, "tokens": t} for n, t in [
        (5411, 31267499), (996, 26737159), (485, 3205759), (87, 32965118), (0, 5472678),
        (34, 13350544), (69, 12124537), (127, 11864766), (169, 2702718), (77, 2353371)]]
    aus = streuung(zeilen)
    assert abs(aus["dp_nach"] - 0.552) < 0.001, aus
    assert aus["dp_norm_nach"] > aus["dp_nach"]
    assert streuung(zeilen[:1]) == {}


def test_dp_steht_im_antwortschema(tw):
    from jsonschema import validate

    wrapper, idx = tw
    feld, _werte = _feld_mit_wenigen_werten(idx)
    ausgabe = wrapper.query_count_tool("und", nach=feld)
    assert "dp_nach" in ausgabe
    validate(ausgabe, _schema_von("query_count"))


def test_dp_und_nach_erreichen_die_belegzeilen(tw):
    """Qwen auf 333cd13a42, Frage 9: der Entwurf nannte dp 0,5512 aus der
    Werkzeugausgabe, das Paket führte das Feld nicht, und die Synthese rechnete
    selbst 0,452."""
    from candyconc.candyconc_copilot import grounding_evidence as ge

    wrapper, idx = tw
    feld, _werte = _feld_mit_wenigen_werten(idx)
    ausgabe = wrapper.query_count_tool("und", nach=feld)
    zeilen = ge.build_grounding_surface(ge.extract_raw_surface(ausgabe, werkzeug="query_count"))
    text = "\n".join(zeilen)
    assert f"dp_nach={ausgabe['dp_nach']}" in text, text
    assert f"nach={feld}" in text, text
