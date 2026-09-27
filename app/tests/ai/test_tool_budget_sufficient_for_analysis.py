"""Das Werkzeugbudget eines Turns traegt eine registerweise Analyse.

Gemessen am 2026-09-17 an einer mitgeschriebenen Frage des Piloten
(`deutung-verknuepfung-dispersion`, PING): der Turn setzte 54 Werkzeugaufrufe
ab. Acht `create_docset` verbrauchten 1054 Einheiten, und die restlichen
dreissig Aufrufe scheiterten an "Token budget exhausted", darunter JEDE
Frequenzmessung. Die Antwort schrieb daraufhin wahrheitsgemaess, es lägen
keine Frequenzen vor, waehrend ihr Anhang die Versuche auflistete. Genau das
haben drei Linsen in beiden Korpora als schwersten Defekt gemeldet.

Die Probe faehrt beide Klassen: die echte Aufruffolge muss durchgehen, und
eine Schleife muss weiterhin auflaufen. Ohne die zweite Haelfte waere sie mit
jedem beliebig grossen Budget gruen.
"""

import json
import pathlib

def _ausgelieferter_vorgabewert() -> int:
    """Der Wert AUS DER DATEI, nicht aus dem gemeinsamen Dict.

    ``POLICY_BUDGETS`` ist modulweit und veraenderlich, und vier Proben in
    tests/backend setzen ``POLICY_BUDGETS["default"] = 1000`` ohne es
    zurueckzustellen. Diese Probe war allein gruen und fiel im Gesamtlauf,
    weil sie dann den fremden Wert las. Gemeint ist hier der ausgelieferte
    Vorgabewert, also wird das Modul frisch geladen.
    """
    import importlib.util

    pfad = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "candyconc" / "services" / "backend" / "policy_state.py"
    )
    spec = importlib.util.spec_from_file_location("_frisches_policy_state", pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return int(modul.POLICY_BUDGETS["default"])


def _echte_policy_engine():
    """Die ECHTE Klasse, nicht den Stub aus tests/conftest.py.

    conftest installiert Stubs fuer die Copilot-Module, und der Stub nimmt
    keine Argumente (``PolicyEngine() takes no arguments``). server._make_policy
    faengt genau diesen TypeError ab. Eine Probe, die gegen den Stub laeuft,
    prueft das Budget nicht.
    """
    import importlib.util

    pfad = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "candyconc" / "candyconc_copilot" / "policy_engine.py"
    )
    spec = importlib.util.spec_from_file_location("_echtes_policy_engine", pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul.PolicyEngine

#: Die Argumente, mit denen der gemessene Turn gearbeitet hat, in derselben
#: Form, in der das Modell sie schickt.
AUFRUFE = (
    [('list_docsets', '{}'), ('metadata_values', '{"fields": ["*"]}')]
    + [('create_docset',
        '{"filters": {"text_type": "%s", "register": "%s"}, "label": "%s:%s"}'
        % (art, reg, art[0].upper(), reg))
       for reg in ("blog_essay", "easy_language", "encyclopedia", "legal",
                   "narrative_contemporary", "news", "parliamentary",
                   "scientific", "social", "spoken")
       for art in ("human", "ai")]
    + [('keyness',
        '{"target_docset_id": "f0a2fdc27022464aa7f4c159fddaf3a4", '
        '"reference_docset_id": "d7a62b67d21a4d6ca299a42379ec6dc0", "min_freq": 5}')]
    + [('query_count', '{"query": "sondern", "docset_id": "%032x"}' % i)
       for i in range(20)]
    + [('run_cqlf_query',
        '{"query": "[word=\\"sondern\\"]", "docset_id": "%032x", "limit": 25}' % i)
       for i in range(20)]
)


def _kosten(roh_argumente: str) -> int:
    """Genau das, was orchestrator._ra_tool_tokens abrechnet."""
    return len(json.dumps(roh_argumente))


def _fahre(budget: int, aufrufe) -> tuple[int, int]:
    policy = _echte_policy_engine()(token_budget=budget)
    durch = abgelehnt = 0
    for name, argumente in aufrufe:
        ergebnis = policy.check("nutzer", name, _kosten(argumente))
        if ergebnis.get("status") == "ok":
            durch += 1
        else:
            abgelehnt += 1
    return durch, abgelehnt


def test_die_gemessene_aufruffolge_geht_ganz_durch():
    durch, abgelehnt = _fahre(_ausgelieferter_vorgabewert(), AUFRUFE)
    assert abgelehnt == 0, (
        f"{abgelehnt} von {len(AUFRUFE)} Aufrufen abgelehnt. Genau so ist am "
        "2026-09-17 jede Frequenzmessung eines Turns ausgefallen."
    )
    assert durch == len(AUFRUFE)


def test_mit_dem_alten_wert_stirbt_dieselbe_folge():
    durch, abgelehnt = _fahre(1000, AUFRUFE)
    assert abgelehnt > 0, (
        "Ohne diese Haelfte pruefte die Probe nichts: sie waere mit jedem "
        "beliebig grossen Budget gruen."
    )
    assert durch < 15, (
        "Der alte Wert trug nicht einmal die Teilkorpora, geschweige denn "
        f"die Messungen. Durchgekommen: {durch}."
    )


def test_eine_schleife_laeuft_weiterhin_auf():
    schleife = [("query_count", '{"query": "sondern", "docset_id": "%032x"}' % i)
                for i in range(20_000)]
    durch, abgelehnt = _fahre(_ausgelieferter_vorgabewert(), schleife)
    assert abgelehnt > 0, "Die Reissleine muss eine echte Schleife noch fangen."
