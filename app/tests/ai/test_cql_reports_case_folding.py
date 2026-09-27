"""CQL results disclose whether and how they fold letter case."""

from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

# conftest ersetzt tool_wrappers durch einen Stub, geprueft wird das echte Modul.
_query_method_provenance = _load_real_tool_wrappers()._query_method_provenance


def test_cql_ohne_flag_faltet_nicht():
    assert _query_method_provenance('[word="zusammenfassend"]', case_insensitive=True)[
        "case_insensitive"] is False
    assert _query_method_provenance('[word="nicht"] [word="nur"] []{0,8} [word="sondern"]',
                                    case_insensitive=True)["case_insensitive"] is False


def test_cql_mit_flag_faltet():
    assert _query_method_provenance('[word="und" %c]', case_insensitive=False)["case_insensitive"] is True
    assert _query_method_provenance('cql:[word="und"%c] [word="auch"%c]', case_insensitive=False)[
        "case_insensitive"] is True
    # Nur ein Teil der Werte gefaltet: die Abfrage als Ganzes faltet nicht.
    assert _query_method_provenance('[word="und" %c] [word="auch"]', case_insensitive=True)[
        "case_insensitive"] is False


def test_einfache_wortsuche_meldet_den_parameter():
    assert _query_method_provenance("und", case_insensitive=True)["case_insensitive"] is True
    assert _query_method_provenance("und", case_insensitive=False)["case_insensitive"] is False
