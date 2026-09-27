"""Wann ein Werkzeuglauf KEIN Befund ist, obwohl er durchgelaufen ist.

Zwei toedliche Maengel der ersten Professorinnen-Runde (2026-08-29) haben
dieselbe Wurzel: das Werkzeug meldete Erfolg fuer eine Messung ohne
Substanz, und das Modell hat daraus einen Befund gemacht.

    frequency_list(group_by="pos") auf dem 142M-Index
        -> eine Zeile, {word: "X", f: 142043636, per_million: 999996.4}
        -> status success

    collocate_stats(term="eine Rolle spielen")
        -> node_frequency 0, rows [], status success
        -> im Log daneben: "No matches found for term"

Die Gutachterin zu ersterem: "Die Antwort verkauft eine degenerierte
Annotationsverteilung als Wortfrequenzbefund. Dazu kommt die zirkulaere
Rate: per_million = 999.996,4 misst das Korpus gegen sich selbst, ein
Wert, der per Konstruktion 10^6 sein muss und nichts unterscheidet."

Zu letzterem: der einzige Befund der Antwort war frei erfunden.

Die beiden werden VERSCHIEDEN behandelt, und das ist Absicht. Ein Korpus
ohne Wortartenannotation bleibt den ganzen Turn ohne sie, ein zweiter
Aufruf kann daran nichts aendern: das ist die vorhandene
Capability-Absage. Kennt der Harnisch die Attributebenen des Korpus,
nennt sie den Ausweg über ein anderes Attribut, und das Werkzeug bleibt
ungesperrt. Nur ohne einen solchen Ausweg verschwindet es aus dem
Werkzeugraum. Ein Knoten ohne Treffer sagt dagegen nichts ueber das
Korpus, nur ueber diesen einen Ausdruck. Wer das Werkzeug dafuer
entzieht, versperrt die richtige Erholung, naemlich eine andere
Formulierung des Knotens.

In beiden Faellen gilt: die Absage darf kein stiller Abbruch werden. Die
Zahlen, die sie begruenden, stehen in ihr drin, sonst tauscht man eine
erfundene Diagnose gegen ein Schweigen.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# Treat an annotation distribution as degenerate above this share.
# The threshold below one allows for small amounts of annotation noise.
ENTARTUNGSANTEIL = 0.99


def annotation_entartet(
    group_by: str,
    rows: List[Mapping[str, Any]],
    denominator_tokens: int,
    *,
    umschlag: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Fehler-Umschlag, wenn ein Attribut in diesem Korpus nichts traegt.

    ``None``, wenn die Verteilung echt ist. Nur fuer ANNOTATIONS-Attribute:
    bei ``word`` und ``lemma`` waere eine einzige dominante Type eine
    echte, wenn auch seltsame Korpuseigenschaft und kein Defekt.

    Der Umschlag traegt den Marker ``keine_annotation_im_attribut``, den
    ``recipe_runtime.CAPABILITY_UNAVAILABLE_MARKERS`` kennt: daraus wird
    eine ehrliche Absage. Nennt sie einen Ausweg über ein anderes
    Attribut, bleibt das Werkzeug ungesperrt, sonst verschwindet es für
    den Rest des Turns aus dem Werkzeugraum.

    ``umschlag`` traegt die Pflichtfelder von ``FREQUENCY_RESPONSE`` bei.
    Sie sind NICHT optional. ``_obj`` setzt ``additionalProperties=False``
    und ``required`` listet neun Felder, also faellt eine Absage, die nur
    ``status`` und ``message`` schickt, auf der MCP-Route mit HTTP 500 um,
    bevor das Modell sie sieht. Gemessen im nachher-Lauf, Zeile 910:
    "Invalid result: Additional properties are not allowed ('message' was
    unexpected)". Der Turn erlebt einen Werkzeugausfall statt einer
    Absage, und die inhaltlich richtige Auskunft geht verloren. Es ist
    derselbe Defekt, der in diesem Modul schon einmal behoben wurde
    (``knoten_ohne_treffer``, 0878744d75): ein Modul, zwei Umschlaege,
    einer davon lange uebersehen.
    """

    if group_by in ("word", "lemma") or not rows or denominator_tokens <= 0:
        return None
    if len(rows) > 2:
        return None
    try:
        spitze = float(rows[0].get("f") or 0.0)
    except (AttributeError, TypeError, ValueError):
        return None
    if spitze < ENTARTUNGSANTEIL * float(denominator_tokens):
        return None
    etikett = str(rows[0].get("word") or "")
    anteil = 100.0 * spitze / float(denominator_tokens)
    absage: Dict[str, Any] = dict(umschlag or {})
    absage.update({
        "status": "error",
        "message": (
            f"keine_annotation_im_attribut: '{group_by}' trägt in diesem "
            f"Korpus keine Annotation. {int(spitze)} von "
            f"{int(denominator_tokens)} Token ({anteil:.2f} Prozent) tragen "
            f"dasselbe Etikett '{etikett}'. Eine Frequenzverteilung über "
            "dieses Attribut ist kein Befund, sondern die Abwesenheit der "
            "Annotation. Fuer eine Wortartenfrage ist dieses Korpus nicht "
            "die Grundlage."
        ),
    })
    return absage


def knoten_ohne_treffer(
    term: str,
    node_frequency: Any,
    effective_min_freq: int,
    *,
    effective_term: str,
    term_mode: str,
    method: Mapping[str, Any],
    scope: Any,
    herkunft: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """``empty``-Umschlag, wenn der Knoten null Treffer hat.

    ``None`` bei jeder anderen Lage, insbesondere bei einer FEHLENDEN
    Angabe: ein Erzeuger, der ``node_frequency`` nicht in die ``attrs``
    schreibt, liefert ``None``, und ein ``not None`` waere True gewesen.
    Eine Kollokatliste MIT Zeilen waere dann als leer gemeldet worden. Ein
    Test mit gepatchtem ``_collocate_stats`` hat genau das aufgedeckt.
    """

    if node_frequency is None:
        return None
    try:
        if int(node_frequency) > 0:
            return None
    except (TypeError, ValueError):
        return None

    mehrwort = len(str(term).split()) > 1
    ausweg = (
        " Mehrwortausdrücke sind über die Oberflächensuche nicht "
        "adressierbar. Entweder den Kopf allein als Knoten nehmen oder eine "
        "CQL-Sequenz mit cql: formulieren."
        if mehrwort
        else " Der Ausdruck steht in diesem Korpus nicht."
    )
    return {
        "status": "empty",
        "rows": [],
        "requested_term": term,
        "effective_term": effective_term,
        "term_mode": term_mode,
        "node_frequency": 0,
        "result_count": 0,
        "min_freq": int(effective_min_freq),
        "schwelle_gebunden": False,
        "diagnosis": (
            f"Der Knoten '{term}' hat null Treffer, es wurde also nichts "
            f"gemessen. Die Mindestfrequenz {int(effective_min_freq)} hat "
            "NICHT gebunden: eine leere Liste belegt keine Seltenheit."
            + ausweg
        ),
        "method": dict(method),
        "scope": scope,
        # Auch eine leere Antwort muss sagen, MIT WELCHER Einstellung nichts
        # gefunden wurde. Fenster, Satzgrenze, Sortierung und das Glossar
        # fehlten hier, und weil sie im Schema Pflicht sind, brach die
        # Validierung selbst nach dem Nachtragen der beiden neuen Schluessel
        # weiter. Ein leerer Befund ohne Herkunft ist auch fachlich wertlos:
        # "nichts gefunden" wird erst zur Aussage, wenn danebensteht, wonach
        # gesucht wurde.
        **dict(herkunft),
    }
