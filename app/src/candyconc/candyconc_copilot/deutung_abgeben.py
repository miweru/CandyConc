# -*- coding: utf-8 -*-
"""Das Werkzeug, mit dem das Modell SELBST erklaert, dass es fertig ist.

WARUM ES DAS GIBT. Bis zum 2026-09-17 bestimmte der Harnisch das Ende: nach
sechzehn Werkzeugrunden entzog er die Werkzeuge, bei erschoepftem
Werkzeugbudget lehnte er jeden weiteren Aufruf ab, und lieferte der
Deutungsaufruf leeren Inhalt, rendert er die Antwort deterministisch aus der
gesammelten Evidenz und verbuchte sie als beantwortete Frage. In einem Arm
des Piloten traf das sechs von zwanzig Fragen.

Der Auftraggeber dazu: "Das muss so gebaut sein, dass es LLM generiert
selbstbestimmt an der richtigen Stelle aufhoert. Solange das nicht so ist,
ist der Harness nicht gut genug." Und: "Es kann nicht sein, dass eine
Recherche still abgebrochen wird."

WARUM GERADE SO. Eine Websuche nach dem Stand der Technik
(docs/wuensche/recherche_selbstbestimmtes_ende.md) fand das Abschlusswerkzeug
als den verbreiteten Bauteil: ReAct ``Finish[...]``, smolagents
``final_answer``, Aviary und PaperQA2 ``complete`` mit einem PFLICHTFELD zur
Selbsteinschaetzung, Google ADK ``exit_loop``, OpenHands ``finish``. Dieselbe
Recherche warnt, dass ein gehobener Deckel OHNE solches Tor verfruehte
Abschluesse erzeugt, belegt an mehreren Messlatten. Deshalb sind die drei
Felder Pflicht: wer abgeben will, muss sagen WAS er beantwortet, WOMIT, und
WAS offen bleibt.

Das Werkzeug schreibt die Antwort NICHT. Es beendet die Werkzeugphase, und
die Deutung entsteht danach im frischen Syntheseaufruf aus der vollen
Evidenz. Die drei Felder gehen als Zwischenstand mit, damit beim Lesen einer
Runde sichtbar ist, womit das Modell seinen Abschluss begruendet hat.
"""

from __future__ import annotations

from typing import Any, Dict, List

DEUTUNG_ABGEBEN_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "deutung_abgeben",
        "description": (
            "Rufe dies, sobald die gesammelte Evidenz die Frage traegt. Es "
            "beendet die Werkzeugphase, danach schreibst du die Deutung aus "
            "der vollen Evidenz. Kein weiteres Werkzeug wuerde die Antwort "
            "aendern: dann ist hier der Ort, das zu sagen. Es gibt keine "
            "Rundenzahl, die du erreichen musst, und keine, die dich stoppt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "beantwortet": {
                    "type": "string",
                    "description": (
                        "In einem Satz: welchen Teil der gestellten Frage die "
                        "Evidenz jetzt beantwortet."
                    ),
                },
                "belege": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Die Evidenz-Kennungen (E_...), die diesen Teil tragen."
                    ),
                },
                "offen": {
                    "type": "string",
                    "description": (
                        "Was offen bleibt und warum es mit den vorhandenen "
                        "Werkzeugen nicht zu rechnen ist. Leer lassen, wenn "
                        "nichts offen ist."
                    ),
                },
            },
            "required": ["beantwortet", "belege", "offen"],
        },
    },
    "schema": {"type": "object", "properties": {}, "required": []},
}


def deutung_abgeben_tool(
    beantwortet: str,
    belege: List[str] | None = None,
    offen: str = "",
) -> Dict[str, Any]:
    """Nimmt die Abgabe entgegen und bestaetigt sie.

    Der Orchestrator setzt daraufhin ``_ra_deutung_abgegeben`` und exponiert
    keine Werkzeuge mehr. Ein leeres ``beantwortet`` ist keine Abgabe: dann
    haette das Modell nichts erklaert, und die Werkzeugphase laeuft weiter.
    """
    satz = str(beantwortet or "").strip()
    if not satz:
        return {
            "status": "error",
            "message": (
                "Abgabe ohne Inhalt. Sage in einem Satz, welchen Teil der "
                "Frage die Evidenz beantwortet, oder arbeite weiter."
            ),
        }
    ids = [str(b).strip() for b in (belege or []) if str(b).strip()]
    return {
        "status": "success",
        "abgegeben": True,
        "beantwortet": satz,
        "belege": ids,
        "offen": str(offen or "").strip(),
        "hinweis": (
            "Werkzeugphase beendet. Schreibe jetzt die Deutung aus der "
            "vollen Evidenz."
        ),
    }


def vermerke_abgabe(orch: Any, name: str, out: Any) -> None:
    """Die Abgabe am Orchestrator vermerken: Flag plus lesbarer Zwischenstand.

    Eine Funktion, zwei Aufrufer (Hauptwerkzeugschleife und
    Research-Worker im orchestrator.py). Der Zwischenstand traegt die drei
    Felder der Abgabe, damit eine Rundendatei zeigt, womit das Modell sein
    Ende begruendet hat -- so verspricht es der Werkzeugkopf oben.
    """
    if name != "deutung_abgeben" or not isinstance(out, dict):
        return
    if not out.get("abgegeben"):
        return
    orch._ra_deutung_abgegeben = True
    from .session_compaction import zwischenstand
    zwischenstand(
        "deutung_abgegeben",
        "beantwortet: {} | belege: {} | offen: {}".format(
            out.get("beantwortet", ""),
            ", ".join(out.get("belege") or []) or "keine",
            out.get("offen", "") or "keine",
        ),
        sitzung=getattr(getattr(orch, "session", None), "session_id", ""),
    )


def merke_abgabe_text(orch: Any, tool_calls: Any, text: Any) -> None:
    """Keep answer text sent in the same message as the handoff tool call.

    The synthesis uses this text when no subsequent draft is produced.
    """
    namen = [((tc or {}).get("function") or {}).get("name") for tc in (tool_calls or []) if isinstance(tc, dict)]
    inhalt = str(text or "").strip()
    if "deutung_abgeben" in namen and len(inhalt) >= 200:
        orch._ra_abgabe_entwurf = inhalt



def schrittdecke_notiz(max_steps: int) -> str:
    """State that the step limit ended the tool phase before drafting.

    The draft call follows the same path as a voluntary handoff. This note
    identifies the stopping condition without imposing the recipe-limit format.
    """
    runden = f" von {int(max_steps)} Modellrunden" if int(max_steps or 0) > 0 else ""
    return (
        f"Die Werkzeugphase endete an der Schrittdecke{runden}, nicht durch "
        "deine Abgabe. Schreibe jetzt die Deutung aus der vollen Evidenz."
    )
