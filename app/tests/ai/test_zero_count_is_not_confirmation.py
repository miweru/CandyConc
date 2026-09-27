"""Eine Null darf nicht zur Bestaetigung werden.

LIVE GESEHEN am 2026-08-31. Eine Professorin fragte nach der Konstruktion
"nicht nur X sondern auch Y" mit bis zu acht Token Abstand. Der Turn setzte
zwei Abfragen ab:

    [word="nicht"] [word="nur"]                                 129.441
    [word="nicht"] [word="nur"] [word="sondern"] [word="auch"]         0

Ausgeliefert wurde:

    Ja. Fuer `[word="nicht"] [word="nur"]` ist im sichtbaren Suchlauf
    `total=129441` belegt.

Die eigentliche Abfrage hatte NULL Treffer, und die Antwort lautete "Ja."

URSACHE. Der Verfasser nahm den ERSTEN Wert (``if total_hits in (None,
"")``) und aktualisierte nie. Bei mehreren Abfragen eines Turns gewann
damit die erste, unabhaengig davon, welche die Frage beantwortet. Der Name
der einen Abfrage stand neben der Zahl der anderen, und das ist die
Etikettierungsklasse, die dieses Projekt als harten Fehler fuehrt.

Die Regel steht jetzt in ``_abfragerang``: passt die Abfrage zum genannten
Begriff, gewinnt sie. Sonst gewinnt die SPEZIFISCHERE, denn wo die eine ein
Praefix der anderen ist, ist die kuerzere die Vorbereitung und die laengere
die Frage.
"""

from __future__ import annotations

from candyconc.candyconc_copilot import grounding_markdown as gm
from candyconc.candyconc_copilot.grounding_schemas import EvidenceItem

VOR = '[word="nicht"] [word="nur"]'
ECHT = '[word="nicht"] [word="nur"] [word="sondern"] [word="auch"]'


def _posten(query: str, total: int) -> EvidenceItem:
    flaeche = {"query": query, "total": total}
    return EvidenceItem(
        id=f"E{abs(hash(query)) % 9999}",
        tool="run_cqlf_query",
        tool_call_id="tc",
        query=query,
        truncated=False,
        status="success",
        raw_surface=flaeche,
        fact_surface=flaeche,
    )


def _antwort(items) -> str:
    return gm._build_kwic_presence_markdown(
        items, question_scope=ECHT, evidence_gaps=[]
    )


def test_die_null_der_eigentlichen_abfrage_gewinnt():
    """Der Live-Fall, in der Reihenfolge, in der er auftrat."""
    text = _antwort([_posten(VOR, 129441), _posten(ECHT, 0)])
    assert text.startswith("Nein."), text
    assert "129441" not in text, text


def test_die_reihenfolge_entscheidet_nicht():
    """Sonst haengt die Antwort daran, in welcher Folge das Modell fragte."""
    text = _antwort([_posten(ECHT, 0), _posten(VOR, 129441)])
    assert text.startswith("Nein."), text
    assert "129441" not in text, text


def test_eine_einzelne_abfrage_mit_treffern_bleibt_ein_ja():
    """Die Reparatur darf nicht jede Antwort zu einem Nein machen."""
    text = gm._build_kwic_presence_markdown(
        [_posten(VOR, 129441)], question_scope=VOR, evidence_gaps=[]
    )
    assert text.startswith("Ja."), text
    assert "129441" in text, text


def test_das_etikett_nennt_die_abfrage_die_gezaehlt_wurde():
    """Der Rest, der am 2026-08-31 offen blieb, und am 2026-09-01 fiel.

    Die Reparatur vom Vortag band die ZAHL an die richtige Abfrage und
    liess das ETIKETT unangetastet: es kam aus ``_dominant_query_term``,
    also aus einem WORT der ERSTEN Abfrage des Turns. Live stand deshalb

        Ja. Fuer `[.*]` ist im sichtbaren Suchlauf `total=129441` belegt.

    unter einer Frage nach einer vierteiligen Konstruktion. Ein
    Platzhalter als Name, und die Zahl gehoerte einer dritten Abfrage.

    Der alte Test hielt diesen Zustand als bestanden fest und trug den
    Satz "Etikett repariert, dann diesen Test anpassen". Das ist hiermit
    geschehen. Etikett und Zahl stammen jetzt aus DEMSELBEN Beleg.
    """
    text = gm._build_kwic_presence_markdown(
        [_posten(VOR, 129441), _posten(ECHT, 0)],
        question_scope=ECHT,
        evidence_gaps=[],
    )
    # Die Zahl gehoert zur spezifischeren Abfrage: 0, nicht 129.441.
    assert "total=0" in text, text
    # Und das Etikett nennt genau diese Abfrage.
    assert ECHT in text, text
    assert VOR not in text.replace(ECHT, ""), text


def test_ohne_abfrage_bleibt_der_abgeleitete_begriff():
    """Die Reparatur darf Landungen ohne Suchlauf nicht namenlos machen."""
    text = gm._build_kwic_presence_markdown(
        [], question_scope="Nachhaltigkeit", evidence_gaps=[]
    )
    assert "[.*]" not in text, text


def test_der_rang_bevorzugt_die_spezifischere_abfrage():
    assert gm._abfragerang(ECHT, "") > gm._abfragerang(VOR, ""), (
        gm._abfragerang(ECHT, ""), gm._abfragerang(VOR, "")
    )


def test_der_rang_setzt_den_namensgleichen_ganz_nach_oben():
    assert gm._abfragerang(VOR, VOR) > gm._abfragerang(ECHT, VOR)


def test_eine_leere_abfrage_gewinnt_nie():
    assert gm._abfragerang("", "") == 0
