"""Was gefragt wurde, was herauskam, auf jeder Landung.

PUNKT 5 der Anforderung vom 2026-08-31
(docs/wuensche/deutungsevaluation.md):

    Das KI-Gutachten kann erst ein TLDR erstellen mit der Interpretation
    der Ergebnisse, dann zeigt es uns an, welche Experimente es
    durchgefuehrt hat und was da rausging.

Der bisherige Methodensteckbrief nannte die PARAMETER eines Laufs:

    KWIC: Abfragemodus cqlf, Attribut explicit_in_query,
    Groß-/Kleinschreibung ignoriert: ja, Kontextbreite: 5, maximal
    angeforderte Zeilen: 1

Gemessen an zwei Live-Antworten vom 2026-08-31 machte dieser Anhang 56,6
Prozent des ausgelieferten Textes aus, ohne ein einziges ERGEBNIS zu
nennen.
"""

from __future__ import annotations

import ast
import pathlib

from candyconc.candyconc_copilot.experiment_log import (
    experimente,
    protokoll_anhaengen,
)

_QUELLE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "candyconc" / "candyconc_copilot" / "recipe_runtime.py"
)


def _beleg(tool: str, **flaeche):
    return {"tool": tool, "status": "success", "fact_surface": dict(flaeche)}


def test_ein_experiment_nennt_gegenstand_und_ergebnis():
    zeilen = experimente([_beleg("query_count", query="Nachhaltigkeit", total=2840)])
    assert zeilen == ["Trefferzahl `Nachhaltigkeit` → 2.840 Treffer"], zeilen


def test_die_staerksten_zeilen_stehen_dabei():
    """Eine Zahl ohne Material ist kein Ergebnis, sondern eine Zahl."""
    zeilen = experimente([
        _beleg("collocate_stats", requested_term="Nachhaltigkeit",
               result_count=540, rows=[{"word": "ökologische"}, {"word": "Gerechtigkeit"}]),
    ])
    assert "ökologische" in zeilen[0] and "Gerechtigkeit" in zeilen[0], zeilen


def test_dieselbe_bezeichnung_erscheint_nicht_zweimal():
    """result_count und rows_seen heissen beide "Zeilen".

    Der erste Anlauf schrieb "9 Zeilen, 61 Knotentreffer, 9 Zeilen". Das
    liest sich wie ein Fehler, weil es einer ist.
    """
    zeilen = experimente([
        _beleg("collocate_stats", requested_term="X", result_count=9,
               node_frequency=61, rows_seen=9),
    ])
    assert zeilen[0].count("Zeilen") == 1, zeilen


def test_total_heisst_nicht_ueberall_treffer():
    """Bei frequency_list zaehlt total TYPEN, nicht Treffer.

    "11.209 Treffer" waere dort schlicht falsch, und eine falsch
    beschriftete Zahl ist die Fehlerklasse, die dieses Projekt als hart
    fuehrt.
    """
    zeilen = experimente([_beleg("frequency_list", total=11209)])
    assert "11.209 Typen" in zeilen[0], zeilen
    assert "Treffer" not in zeilen[0], zeilen


def test_ein_nullbefund_wird_genannt_und_nicht_verschwiegen():
    zeilen = experimente([
        _beleg("run_cqlf_query", query='[word="a"] [word="b"]', total=0),
    ])
    assert zeilen, "der Aufruf verschwindet"
    assert "0 Treffer" in zeilen[0], zeilen


def test_ohne_werkzeuglauf_kein_abschnitt():
    """Eine Ueberschrift ohne Inhalt ist schlimmer als keine."""
    assert protokoll_anhaengen("Ein Befund.", []) == "Ein Befund."
    assert "### Experimente" not in protokoll_anhaengen("Ein Befund.", [])


def test_idempotent():
    text = protokoll_anhaengen("Ein Befund.", [_beleg("query_count", query="X", total=1)])
    assert protokoll_anhaengen(text, [_beleg("query_count", query="Y", total=2)]) == text


def test_ein_fehler_kostet_die_antwort_nicht():
    """Telemetrie darf eine Antwort nie kosten."""
    class Boese:
        tool = "query_count"

        @property
        def fact_surface(self):  # pragma: no cover - absichtlich
            raise RuntimeError("kaputt")

    assert protokoll_anhaengen("Ein Befund.", [Boese()]) == "Ein Befund."


def test_der_chokepoint_ruft_es_wirklich():
    """Die NAHT, nicht nur die Funktion.

    Geprueft werden AUFRUFE ueber den Syntaxbaum. Ein lokaler Import
    brachte den Namen schon einmal in den Rumpf, ohne dass etwas lief, und
    eine Wache dieses Projekts ist genau daran gescheitert.
    """
    baum = ast.parse(_QUELLE.read_text(encoding="utf-8"))
    ziel = next(
        k for k in ast.walk(baum)
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
        and k.name == "politur_mit_zitatwache"
    )
    gerufen = {
        getattr(k.func, "id", "") for k in ast.walk(ziel) if isinstance(k, ast.Call)
    }
    assert "_experimentprotokoll" in gerufen, sorted(gerufen)


def test_es_steht_vor_dem_methodensteckbrief():
    """Erst was gemessen wurde, dann womit.

    Steht der Parameterblock zuerst, liest die Fachperson die Einstellungen
    einer Messung, deren Ergebnis sie noch nicht kennt.
    """
    quelle = _QUELLE.read_text(encoding="utf-8")
    i = quelle.index("_experimentprotokoll(poliert")
    j = quelle.index("methodensteckbrief_anhaengen(poliert")
    assert i < j, "der Parameterblock steht vor dem Ergebnis"


def test_ein_gescheiterter_aufruf_bleibt_stehen():
    """LIVE am 2026-08-31, und es war der wichtigste Eintrag.

    In der ausgelieferten Antwort auf die Konstruktionsfrage stand viermal
    "Suche → ohne Ergebnis", und zwei davon waren die Abfragen, um die es
    der Nutzerin ging. Der Aufrufer warf sie weg, weil ein Aufruf ohne
    nennbare Zahl nichts beitraegt. Ein GESCHEITERTER Aufruf traegt aber
    bei: er sagt, dass es versucht wurde und woran es lag.

    Das Modul sagte in seinem eigenen Docstring "ein verschwiegener
    Nullbefund ist die schlimmere Variante", und der Aufrufer verschwieg
    ihn. Zwei Stellen, eine Aussage, gegenlaeufig.
    """
    beleg = {
        "tool": "run_cqlf_query",
        "status": "error",
        "error": "CQL Parse Fehler bei Position 12",
        "fact_surface": {"query": '[word="a"] within 1 s'},
    }
    zeilen = experimente([beleg])
    assert len(zeilen) == 1, zeilen
    assert "gescheitert" in zeilen[0], zeilen
    assert "CQL Parse Fehler" in zeilen[0], zeilen
    text = protokoll_anhaengen("Ein Befund.", [beleg])
    assert "### Experimente" in text, text
    assert "gescheitert" in text, text


def test_ein_gelungener_aufruf_ohne_zahl_faellt_weiterhin_weg():
    """Die Unterscheidung ist der Punkt, nicht das Behalten von allem."""
    beleg = {"tool": "list_docsets", "status": "success", "fact_surface": {}}
    assert protokoll_anhaengen("Ein Befund.", [beleg]) == "Ein Befund."


def test_ein_nullbefund_ist_kein_scheitern():
    """0 Treffer IST ein Ergebnis, und zwar oft das wichtigste."""
    beleg = _beleg("run_cqlf_query", query='[word="x"] [word="y"]', total=0)
    zeilen = experimente([beleg])
    assert "0 Treffer" in zeilen[0], zeilen
    assert "gescheitert" not in zeilen[0], zeilen


def test_ein_fehler_nennt_seinen_satz_nicht_seinen_umschlag():
    """LIVE am 2026-09-01, in einer ausgelieferten Antwort:

        4. Keyness → gescheitert: MCP Fehler: {"type":"about:blank",
           "title":"Bad Request","status":400,"detail":"Ziel- und
           Referenz-Docset duerfen keine ge

    Ein rohes Fehler-JSON, mitten im Wort abgeschnitten. Der lesbare Teil
    stand im Umschlag ganz hinten und fiel bei der stumpfen 120-Zeichen-
    Kappung heraus. Genau die Zeile, die dem Nutzer sagen soll, WORAN es
    lag, sagte ihm nichts.
    """
    beleg = {
        "tool": "keyness",
        "status": "error",
        "error": (
            'MCP Fehler: {"type":"about:blank","title":"Bad Request",'
            '"status":400,"detail":"Ziel- und Referenz-Docset dürfen keine '
            'gemeinsamen Dokumente haben."}'
        ),
        "fact_surface": {},
    }
    zeile = experimente([beleg])[0]
    assert "Ziel- und Referenz-Docset" in zeile, zeile
    assert "about:blank" not in zeile, zeile
    assert '"status":400' not in zeile, zeile


def test_ein_verschachtelter_umschlag_wird_auch_geoeffnet():
    """detail traegt manchmal selbst wieder ein Diktat."""
    from candyconc.candyconc_copilot.experiment_log import _lesbarer_grund

    text = _lesbarer_grund(
        'MCP Fehler: {"title":"Not Found","status":404,'
        '"detail":{"status":"missing","reason":"Verzeichnis fehlt"}}'
    )
    assert text == "Verzeichnis fehlt", text


def test_ohne_umschlag_bleibt_der_text():
    from candyconc.candyconc_copilot.experiment_log import _lesbarer_grund

    assert _lesbarer_grund("Zeitlimit erreicht") == "Zeitlimit erreicht"
    assert _lesbarer_grund("") == "ohne Angabe"


class TestDieMengeWirdWirklichGebildet:
    """Ein Parameter, den niemand fuellt, aendert nichts.

    Die erste Fassung dieser Erweiterung hatte den Parameter
    ``ausgewertet`` an drei Stellen in der Signatur und an keiner einzigen
    im Aufruf. Das faellt in keiner Verhaltensprobe auf, weil der
    Vorgabewert ``None`` genau das alte Verhalten ist. Diese Proben lesen
    deshalb den Syntaxbaum.
    """

    def _orchestrator_quelle(self):
        import pathlib

        return (
            pathlib.Path(__file__).resolve().parents[2]
            / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
        ).read_text(encoding="utf-8")

    def test_der_orchestrator_fuellt_das_feld(self):
        import ast

        baum = ast.parse(self._orchestrator_quelle())
        gesetzt = {
            ziel.attr
            for k in ast.walk(baum)
            if isinstance(k, ast.Assign)
            for ziel in k.targets
            if isinstance(ziel, ast.Attribute)
        }
        assert "_turn_ausgewertete_evidenz" in gesetzt, sorted(
            n for n in gesetzt if "turn" in n
        )

    def test_die_landung_reicht_es_weiter(self):
        """Gebildet und nicht uebergeben waere derselbe Fehler."""
        import ast

        baum = ast.parse(self._orchestrator_quelle())
        weitergereicht = [
            k for k in ast.walk(baum)
            if isinstance(k, ast.Call)
            and getattr(k.func, "id", "") == "politur_mit_zitatwache"
            and any(sw.arg == "ausgewertet" for sw in k.keywords)
        ]
        assert weitergereicht, (
            "keine Aufrufstelle von politur_mit_zitatwache uebergibt "
            "ausgewertet"
        )

    def test_der_weg_geht_ueber_die_angenommenen_claims(self):
        """Ein verworfener Claim traegt nichts, seine Evidenz also auch nicht.

        Als VERHALTENSPROBE, nicht als Textsuche. Die erste Fassung suchte
        "source_evidence_ids" im Umfeld der Zuweisung im Orchestrator. Die
        Rechnung ist danach ins Fachmodul gewandert (das LOC-Budget des
        Orchestrators steht auf 7800 mit Absenkungsabsicht und wird nicht
        angehoben, um einer Rechnung Platz zu machen), und die Textsuche
        haette den Umzug als Defekt gemeldet, obwohl er die Verbesserung
        war.
        """
        from candyconc.candyconc_copilot.experiment_log import (
            getragene_evidenz,
        )

        class _F:
            def __init__(self, i, ev):
                self.id, self.source_evidence_ids = i, ev

        class _C:
            def __init__(self, i, fids):
                self.id, self.fact_ids = i, fids

        fakten = [_F("f1", ["e1"]), _F("f2", ["e2"]), _F("f3", ["e3"])]
        claims = [_C("c1", ["f1"]), _C("c2", ["f2"]), _C("c3", ["f3"])]

        assert getragene_evidenz(claims, ["c1", "c3"], fakten) == {"e1", "e3"}
        # c2 ist verworfen, e2 hat also nichts getragen.
        assert "e2" not in getragene_evidenz(claims, ["c1", "c3"], fakten)
        # Ohne angenommene Claims traegt gar nichts.
        assert getragene_evidenz(claims, [], fakten) == set()
        # Ein Claim ohne Fact traegt nichts, und faellt nicht um.
        assert getragene_evidenz([_C("c9", [])], ["c9"], fakten) == set()
