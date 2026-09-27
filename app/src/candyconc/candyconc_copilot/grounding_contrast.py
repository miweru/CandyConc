"""Die beiden Seiten eines Kontrasts bei ihrem Namen nennen.

Der deterministische Kontrastverfasser schrieb bis zum 2026-08-29 "Seite A"
und "Seite B". Eine Professorin-Subagentin hat das als toedlichen Mangel
gewertet:

    "Die Richtung des Kontrasts ist aus der Antwort nicht rekonstruierbar.
     Der Text spricht von Seite A und Seite B und bindet beide nirgends an
     Metadaten."

Damit sind die Zahlen unzitierfaehig: welche Seite die 122 traegt und
welche die 0, steht nirgends.

Die Bezeichnungen liegen im selben Turn. ``create_docset`` liefert ein
``label`` und ein ``profile.axes`` mit den konstanten Metadatenwerten,
``contrast_collocates`` seit derselben Runde die beiden Docset-Kennungen.
Es wird also nichts neu berechnet, nur zusammengefuehrt.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence


def kontrastseiten_benennen(
    evidence_items: Sequence[Any],
    normalisieren: Callable[[Any], str],
) -> tuple[str, str]:
    """Die beiden Kontrastseiten mit ihren echten Bezeichnungen.

    Reihenfolge der Quellen, absteigend nach Aussagekraft: das ``label`` des
    ``create_docset``-Postens, dann sein ``axes``-Profil (dort stehen die
    konstanten Metadatenwerte, etwa ``split: konstant: test``), zuletzt die
    Docset-Kennung. Erst wenn auch die fehlt, bleibt es beim generischen
    Wort, und dann ist es keine Behauptung mehr, sondern das Eingestaendnis,
    dass die Zuordnung nicht vorliegt.
    """

    namen: dict[str, str] = {}
    for item in evidence_items:
        if item.tool != "create_docset":
            continue
        roh = item.raw_surface or {}
        kennung = str(roh.get("docset_id") or "").strip()
        if not kennung:
            continue
        etikett = normalisieren(roh.get("label") or "").strip()
        if not etikett:
            achsen = ((roh.get("profile") or {}).get("axes") or {})
            konstant = [
                f"{feld}={str(wert).split(':', 1)[-1].strip()}"
                for feld, wert in achsen.items()
                if isinstance(wert, str) and wert.startswith("konstant:")
            ]
            etikett = ", ".join(sorted(konstant)[:2])
        namen[kennung] = etikett or kennung

    ziel = referenz = ""
    for item in evidence_items:
        if item.tool != "contrast_collocates":
            continue
        roh = item.raw_surface or {}
        ziel = str(roh.get("target_docset_id") or "").strip() or ziel
        referenz = str(roh.get("reference_docset_id") or "").strip() or referenz

    def _name(kennung: str, ersatz: str) -> str:
        if not kennung:
            return ersatz
        etikett = namen.get(kennung)
        return f"„{etikett}“" if etikett and etikett != kennung else (
            f"Docset {kennung[:8]}"
        )

    return (
        _name(ziel, "der Zielseite (Docset nicht zuzuordnen)"),
        _name(referenz, "der Referenzseite (Docset nicht zuzuordnen)"),
    )


def kontrastnenner_satz(evidence_items: Sequence[Any]) -> str:
    """Ein Satz, der die Bezugsgroessen beider Seiten nennt.

    Ohne ihn stehen freq_target und freq_reference als nackte Zahlen im
    Bericht: "122 gegen 0" ist dann kein Verhaeltnis, sondern zwei Zahlen.
    Ein adversarialer Pruefer hat am 2026-08-29 festgestellt, dass die vier
    Nenner zwar in der Nutzlast ankamen, aber nirgends im deterministischen
    Text auftauchten. Die Haelfte eines Befundes einzuloesen und ihn als
    erledigt zu melden, ist die haeufigste Fehlerklasse dieses Projekts.

    Leerer String, wenn die Groessen fehlen. Ein Satz ueber Nenner, die
    nicht vorliegen, waere wieder eine Behauptung.
    """

    for item in evidence_items:
        if getattr(item, "tool", None) != "contrast_collocates":
            continue
        diag = (getattr(item, "raw_surface", None) or {}).get("diagnostics")
        if not isinstance(diag, dict):
            continue
        werte = {}
        for feld in ("node_frequency_target", "node_frequency_reference",
                     "context_mass_target", "context_mass_reference"):
            try:
                zahl = int(diag.get(feld))
            except (TypeError, ValueError):
                zahl = None
            if zahl is None or zahl <= 0:
                break
            werte[feld] = zahl
        else:
            return (
                "Die Rohzahlen sind gegen ihre Bezugsgrössen zu lesen: auf "
                f"der Zielseite {werte['node_frequency_target']} Treffer des "
                f"Knotens in {werte['context_mass_target']} Fenster-Token, "
                f"auf der Referenzseite {werte['node_frequency_reference']} "
                f"in {werte['context_mass_reference']}."
            )
    return ""
