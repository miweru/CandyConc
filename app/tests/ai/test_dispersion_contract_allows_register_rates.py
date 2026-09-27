"""Register dispersion questions expose tools for register-specific rates."""

from candyconc.candyconc_copilot.grounding_contracts import heuristic_analysis_contract

FRAGE = ('Ich behaupte in einem Kapitel zur Sportberichterstattung, dass "Fußball" ein Marker des '
         'News-Registers ist. Pruefen Sie das am ganzen Korpus: Wie verteilen sich die Belege von '
         '"Fußball" ueber die zehn Register, wenn man auf die Tokenmassen der Register normalisiert? '
         'Ist das Wort gleichverteilt oder gebuendelt? Ich brauche ein Dispersionsmass ueber die '
         'Register als Partition.')
WERKZEUGE = ["run_cqlf_query", "dispersion_offsets", "create_docset", "query_count",
             "metadata_values", "frequency_list", "keyness"]


def test_der_dispersionsvertrag_erlaubt_die_registerzaehlung():
    vertrag = heuristic_analysis_contract(FRAGE, available_tools=WERKZEUGE, read_only_tools=WERKZEUGE)
    assert vertrag is not None and vertrag.analysis_family == "term_profile"
    assert {"create_docset", "query_count"} <= set(vertrag.allowed_tools), vertrag.allowed_tools
    assert "dispersion_offsets" in vertrag.allowed_tools
