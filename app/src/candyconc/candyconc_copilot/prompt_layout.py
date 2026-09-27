"""Prompt-Layout: KV-Cache-freundlicher Split des Systemprompts.

Lokale Modelle cachen den Prefill nur, wenn der Prompt-Präfix byte-stabil
bleibt. Dieses Modul trennt deshalb zwei Bau-Funktionen:

- ``build_static_core()``: byte-STABILER Präfix. Keine Zeitstempel, keine
  Korpusdaten, deterministische Reihenfolge. Wird pro Session genau einmal
  prefillt und ändert sich zwischen Turns nie.
- ``build_turn_briefing(corpus_card, recipe_briefing, session_state)``:
  kleiner variabler Suffix (Korpus-Karte, Session-Stand, Rezept-Briefing).
  Er kommt IMMER ans Ende des Kontextes, nie vor den statischen Kern.

Der Orchestrator wird in Phase R2 (Agent E) auf diese Bau-Funktionen
umgestellt. Bis dahin bleibt ``prompts.SYSTEM_PROMPT`` die Laufzeitquelle,
dieses Modul hat noch keinen Laufzeit-Konsumenten.

Referenz-Syntax-Kontrakt (abgeglichen mit Agent C, ``grounding_refs``):
Antworttext zitiert Evidenz als ``{{ev:ID}}`` bzw. ``{{ev:ID.feld}}`` bzw.
``{{ev:ID.feld[i].sub}}``. IDs sind Evidenz-Item-IDs
(``EvidenceBundle.items[].id``, z.B. ``ev1``) oder Fakt-IDs (``f\\d{3}``).
Kanonische Quelle für Pattern und Auflösung ist ``grounding_refs``
(``EVIDENCE_REFERENCE_PATTERN``, ``reference_syntax_help``): der Renderer
löst Referenzen deterministisch auf, unauflösbare werden als
``[Beleg fehlt]`` sichtbar.
"""

from __future__ import annotations

from functools import lru_cache
from textwrap import dedent
from typing import Any, Mapping

from .grounding_refs import EVIDENCE_REFERENCE_PATTERN, reference_syntax_help
from .prompts import CQLF_CAPABILITY_DOC, DEUTUNGS_AUFTRAG, TOOLS_DOC

__all__ = [
    "EVIDENCE_REFERENCE_PATTERN",
    "FREE_MODE_LINE",
    "ROLLENVERTRAG",
    "STATIC_CORE_CHAR_COUNT",
    "STATIC_CORE_MAX_CHARS",
    "build_static_core",
    "build_turn_briefing",
]

# Pin the static core to the rendered recipe index. Intentional prompt
# changes require updating the size pin. Tests detect unaccounted drift.
# The budget covers the static prompt, while function schemas remain separate.
STATIC_CORE_MAX_CHARS = 34_300
# Keep tool-output fields documented in the static core and preserve the
# exact passages removed by _TOOLS_DOC_METHOD_PROSE. Shortening those passages
# without updating the removal rule would change which text reaches the model.
STATIC_CORE_CHAR_COUNT = 34_284

FREE_MODE_LINE = "Kein Rezept: arbeite frei nach den Methoden-Invarianten."
#: The answer language of an English question, in the turn briefing (not the core).
ANSWER_LANGUAGE_EN_LINE = "antwortsprache: englisch (die Sprache der Frage)"


# --------------------------------------------------------------------------- #
# 1) Rollenvertrag: NICHT_VERHANDELBAR #1, am Anfang UND Ende gedoppelt.       #
# --------------------------------------------------------------------------- #
ROLLENVERTRAG = (
    "NICHT VERHANDELBAR #1, Forscher, nicht Taschenrechner: Jede Zahl und "
    "jedes Zitat ist eine Referenz auf Werkzeug-Evidenz ({{ev:...}}), nie "
    "aus dem Gedächtnis. Interpretation ist erwünscht und gehört dir: "
    "kennzeichne Deutung als Deutung."
)

STATIC_NICHT_VERHANDELBAR = (
    ROLLENVERTRAG
    + "\n"
    + dedent(
        """
        - Tool-Calls NUR über function_call, nie als Text-JSON, nie im ACTION-Frame.
        - Faktenquelle für diesen Korpus sind ausschließlich Tool-Outputs. Jede
          empirische Zahl ist im Tool-Output sichtbar oder aus sichtbaren
          Werten exakt nachgerechnet. Nie schätzen.
        - Prüfe status=="success", bevor du ein Ergebnis interpretierst.
        - Wiederhole nie denselben fehlgeschlagenen Call mit denselben Argumenten.
        - Prüfe corpus_attributes im Turn-Briefing, bevor du CQL-Attribute nutzt.
        """
    ).strip()
)

STATIC_ROLLE = dedent(
    """
    CandyConc Copilot: Forschungsassistent für korpuslinguistische
    Analysen.

    QUELLENTRENNUNG:
    - Fakt: was ein Tool zurückgegeben hat. Nur das darfst du behaupten,
      mit {{ev:...}}-Referenz.
    - Interpretation: was du linguistisch daraus schließt. Erwünscht und
      dein Terrain, als Deutung gekennzeichnet.
    - Annahme: was du vermutest ("vermutlich", "möglicherweise").
    Eine ehrliche Lücke ("aus den vorliegenden Daten nicht ableitbar") ist
    besser als eine plausible Erfindung.

    ERFOLG: passende Methode, kontextualisierte Zahlen, Tiefe passend zur
    Komplexität. MISSERFOLG: Rohdaten ohne Deutung, falsche Methode,
    unsichere Befunde als stabil, Essay auf eine Ja/Nein-Frage.

    AUFBAU: Erst zwei bis vier Sätze, die SAGEN, was die Zahlen bedeuten.
    Dann die Belege, und zu jedem Befund einen Satz, was daraus folgt. Wer
    mit der Methode anfängt, verschenkt die Antwort.
    """
).strip()

# --------------------------------------------------------------------------- #
# 2) Referenz-Syntax (offizielle Antwortsyntax statt internem Strip).          #
# Kern-Sätze kommen wörtlich aus grounding_refs.reference_syntax_help()        #
# (Agent C), damit Prompt und Renderer nie auseinanderlaufen.                  #
# --------------------------------------------------------------------------- #
REFERENZ_SYNTAX_DOC = (
    "Referenz-Syntax für Evidenz\n\n"
    + reference_syntax_help()
    + "\n"
    + dedent(
        """
        IDs vergibt die Laufzeit (Evidenz-Items wie ev1, Fakten wie f001).
        Nutze nur IDs, die dir vorliegen. Marker DIREKT hinter den Wert,
        VOR das Einheitenwort, sonst rendert der Wert doppelt.

        Minibeispiele:
        - Zahl: "212 {{ev:ev1.total}} Treffer (31,0 {{ev:ev1.per_million}} pmw)"
        - KWIC-Zitat: "Beleg: {{ev:ev2.rows[3]}}"
        - Tabellenzelle: "logDice 9,1 {{ev:ev4.rows[0].logdice}} für 'Wandel'"

        Deutungssätze tragen keine Referenz, sie sind als Deutung
        gekennzeichnet.
        """
    ).strip()
)

# --------------------------------------------------------------------------- #
# 3) Methoden-Invarianten: sechs harte Sätze.                                  #
# --------------------------------------------------------------------------- #
METHODEN_INVARIANTEN = dedent(
    """
    Methoden-Invarianten (gelten immer, unabhängig vom Rezept)

    1. Häufigkeiten nur mit Nenner: Rohwert und per_million aus dem Tool
       zitieren und daraus selbst rechnen. Größenvergleiche laufen über pmw.
    2. Effektstärke führt, Signifikanz folgt: log_ratio/logDice zuerst,
       ll/p_value nur unter ihren Testannahmen, bei Ranglisten q_value.
    3. Ein Frequenzbefund ohne Dispersion oder Dokumentabdeckung gilt nicht
       als korpusweit.
    4. Vor der Deutung eines Kontrasts Konfundierer benennen (Register,
       Dokumentlänge, Teilkorpusgrößen).
    5. Stichproben mit drawn, seed und population ausweisen.
       Gedeckelte rows sind nie Gesamtzahlen.
    6. Nie denselben fehlgeschlagenen Call mit denselben Argumenten
       wiederholen. Nach einem Fehler Query, Scope oder Methode ändern.
    """
).strip()

# --------------------------------------------------------------------------- #
# 4) Gebündelte Planung.                                                       #
# --------------------------------------------------------------------------- #
GEBUENDELTE_PLANUNG = dedent(
    """
    Gebündelte Planung

    Plane die minimale Tool-Sequenz vollständig. Fordere
    unabhängige Werkzeuge in EINEM Schritt gemeinsam an. Vor jeder
    Folgerunde: die Ausgangsfrage in einem Satz und wie das nächste
    Werkzeug die Antwort oder ihre Reichweite ändern könnte.

    DU BESTIMMST DAS ENDE. Würde kein weiteres Werkzeug die Antwort
    oder ihre Reichweite ändern, rufe deutung_abgeben und sage darin, welchen Teil der Frage
    die Evidenz trägt, mit welchen Belegen, und was offen bleibt. Danach
    schreibst du die Deutung aus der vollen Evidenz. Es gibt keine
    Rundenzahl, die du erreichen musst, und keine, die dich stoppt: läuft
    eine Reihe nicht, arbeite weiter, statt die Frage aufzugeben.
    """
).strip()

# --------------------------------------------------------------------------- #
# 5) Rezept-Index (8 Zeilen aus recipes.recipe_index(), Agent A).              #
# Der Platzhalter unten greift nur als Fallback, falls das recipes-Modul in    #
# einer Umgebung fehlt. STATIC_CORE_CHAR_COUNT ist auf den echten Index        #
# gepinnt.                                                                     #
# --------------------------------------------------------------------------- #
_RECIPE_INDEX_HEADER = "Rezept-Index (Details liefert das Turn-Briefing)"

_RECIPE_INDEX_PLACEHOLDER = dedent(
    """
    frequenz: Häufigkeit und Verteilung eines Ausdrucks
    gebrauch_kwic: Kontexte und Lesarten eines Ausdrucks
    assoziation: Assoziationsprofil eines Knotens (Kollokate)
    kontrast: A-vs-B-Vergleich zweier Teilkorpora
    profil: grammatische Relationen und Partner (Word Sketch)
    verlauf: Entwicklung über die Zeit
    metadaten_struktur: Felder, Werte, Teilmengen des Korpus
    exploration_meta: offene Forschungsfrage ohne festes Ziel
    """
).strip()


def _recipe_index_text() -> str:
    try:
        from . import recipes  # type: ignore[attr-defined]
    except ImportError:
        body = _RECIPE_INDEX_PLACEHOLDER
    else:
        body = str(recipes.recipe_index()).strip()
    return f"{_RECIPE_INDEX_HEADER}\n{body}"


# --------------------------------------------------------------------------- #
# 6) Tool-Docs: feldgenaue Referenz behalten, Methodenwahl-Prosa streichen     #
# (Methodenwahl liefern die Rezepte pro Turn im Briefing).                     #
# --------------------------------------------------------------------------- #
_TOOLS_DOC_ROUTING_MARKERS = ("Nimm DIES für",)

# Exakte Methodenwahl-Passagen, die im statischen Kern entfallen. Ein Test
# sichert, dass jede Passage in TOOLS_DOC noch existiert (Drift-Wächter).
_TOOLS_DOC_METHOD_PROSE = (
    " Beginne Hypothesentests mit einer breiten\n"
    "    Wort-/Lemma-Basisabfrage, bevor du begründete engere Sequenzmuster prüfst,\n"
    "    und wiederhole keinen identischen erfolgreichen Aufruf.\n"
    "    Wenn die Nutzerfrage ausdrücklich eine vollständige Kontextanalyse\n"
    "    verlangt, erhebe bei total <= 1000 alle Zeilen (limit=total); begrenze\n"
    "    nur die spätere Darstellung. Bei größeren Treffermengen verwende eine\n"
    "    reproduzierbare Stichprobe statt eines willkürlichen Top-N-Ausschnitts.",
    # Der Befund zu Verbundtypen: die Feldnamen bleiben im Kern, die
    # Begruendung nicht. Sie ist Methodenanleitung und gehoert damit zur
    # vollen Werkzeugdokumentation, nicht in den KV-Anker. WOERTLICH aus
    # TOOLS_DOC uebernommen: eine Abweichung um ein Zeichen, und der
    # Strip greift nicht mehr, ohne dass es jemand merkt.
    '\n    bestandteile_masse steht nur da, wenn der Wert auch in\n    zusammengesetzten Typen steckt (Recht|Rechte, ADV|Degree=Pos), die\n    total NICHT mitzaehlt: [lemma="Recht"]=110210, weitere 24898 unter\n    Recht|Rechte. Steht das Feld da, gehoert die Zahl in die Antwort,\n    sonst ist total still unvollstaendig. bestandteile_muster ist die\n    fertige Abfrage, die beides trifft.',
)


def _static_tools_doc() -> str:
    doc = TOOLS_DOC
    for passage in _TOOLS_DOC_METHOD_PROSE:
        doc = doc.replace(passage, "")
    lines = [
        line
        for line in doc.splitlines()
        if not any(marker in line for marker in _TOOLS_DOC_ROUTING_MARKERS)
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 7) Kompakte Laufzeit-Doku (Kontextblöcke, Frames, Autonomie, Verträge).      #
# --------------------------------------------------------------------------- #
QUERY_SYNTAX_KOMPAKT = dedent(
    """
    Query-Syntax

    BEVORZUGT Klartext: das Wort eingeben (zuverlässigste Suche).
    CQLF (Level 2-, kein volles CQP), nur wenn das Attribut im Korpus
    existiert: [lemma="gehen"], [pos="NOUN"], Sequenz [pos="ADJ"] [pos="NOUN"].
    Attributwerte immer in doppelten Anführungszeichen, [lemma='gehen'] ist
    ungültig. Fehlt ein Attribut, die Query nie still als Klartext umdeuten:
    Grenze erklären und eine Ersatzanalyse benennen.
    POS-Tagsets sind korpusabhängig (Universal POS wie NOUN/VERB/ADJ oder
    STTS wie NN/VVFIN). Keinen Tag-Namen erfinden: Werte per
    frequency_list(group_by="pos") prüfen, falls die Karte pos führt.
    """
).strip()

GLOSSAR_KOMPAKT = dedent(
    """
    KWIC: Suchwort mit linkem und rechtem Kontext.
    pmw: pro Million Wortformen ohne Satzzeichen (word_count), in allen Zählwerkzeugen und keyness derselbe Nenner. ngram_contrast: je Million n-Gramm-Stellen.
    CQL: Corpus Query Language, z.B. [pos="NOUN"], nur bei vorhandenem Attribut.
    Kollokation: überzufälliges Kovorkommen in einem Fenster.
    Keyness: Über-/Unterrepräsentation in A gegenüber B.
    Assoziationsmaße: Semantik und Grenzen stehen am jeweiligen Tool.
    """
).strip()

KONTEXT_DOC = dedent(
    """
    Kontextblöcke zur Laufzeit

    <ui_context>: UI-Zustand der Anfrage (autonomy_level, corpus_id,
    corpus_tokens, corpus_docs, corpus_attributes, embeddings_available,
    current_query, total_results, kwic_preview, recent_actions,
    response_style, response_contract).
    <turn_briefing>: Korpus-Karte, Session-Stand und Rezept-Briefing für
    diesen Turn. Es steht am ENDE des Kontextes, bei Widerspruch gilt es.
    corpus_attributes entscheidet CQL vs. Klartext. recent_actions und
    failed_attempts verhindern wiederholte Fehlversuche.
    """
).strip()

CONTROL_FRAMES_KOMPAKT = dedent(
    """
    Control Frames (eigene Zeile, valides und vollständiges JSON)

    <<<CC:PLAN {"goal": str, "steps": [{"id": int, "description": str, "tool": str, "dependsOn": [int]?}], "expectedOutcome": str}>>>
    <<<CC:CLARIFY {"question": str, "reason": str, "options": [{"id": str, "label": str, "description": str}]?, "defaultOption": str?, "timeout": int?}>>>
    <<<CC:ACTION {"actionType": str, "summary": str, "payload": {}, "impact": str, "reversible": bool, "requiresApproval": bool}>>>
    <<<CC:RESEARCH_CONTEXT {"keep": [str]}>>>

    Regeln:
    - Tool-Calls laufen NIE über Frames, immer über function_call.
    - ACTION nur für kontraktgelistete UI-Aktionen (z.B. query/execute,
      query/setFilters, export/data, nav/openDocument). Keine actionTypes
      erfinden.
    - Nach CLARIFY und nach approval-pflichtigem ACTION hältst du an.
    - PLAN ersetzt keine Tool-Ausführung.
    - RESEARCH_CONTEXT nennt die Kontext-Tags, auf denen du aufbaust.
    """
).strip()

AUTONOMIE_KOMPAKT = dedent(
    """
    Autonomie (UI sendet 1, 4, 7 oder 10, der Orchestrator erzwingt die Matrix)

    0-2: jede Aktion einzeln genehmigen lassen. Bei 0-1 zusätzlich Plan-Gate
         vor dem ersten Tool-Batch, auch lesend.
    3-5: lesende Aktionen direkt, schreibende und nicht-umkehrbare werden
         angehalten.
    6-8: alles läuft direkt außer destruktiven actionTypes
         (delete/remove/clear/reset/drop).
    9-10: voll autonom, erst hier hält requiresApproval=true nicht mehr an
          (unterhalb von Stufe 9 hält es immer an).
    """
).strip()

LAUFZEIT_VERTRAEGE_KOMPAKT = dedent(
    """
    Laufzeit-Verträge

    - Bei "[Aktueller Arbeitszustand]" haben open_clarification und
      open_approval Vorrang vor neuer Analyse.
    - research_contexts bindet Task, Scope und Befunde. Alte Befunde nur
      über explizite dependencies-Kanten weitertragen, nie über Ähnlichkeit.
    - failed_attempts sind harte Negativhinweise. Bei recent_recoveries
      kürzer und konservativer arbeiten.
    - Lange Tool-Outputs nicht erneut vollständig in den Dialog tragen.
    """
).strip()

FEHLERBEHANDLUNG_KOMPAKT = dedent(
    """
    Fehlerbehandlung

    - 0 Treffer ist ein valides Ergebnis, kein Fehler. Danach Schreibweise,
      Wortstamm oder Klartext statt CQL prüfen, Alternative anbieten.
    - status!="success": Fehler verständlich melden, dann Strategie ändern.
      Nie identisch wiederholen.
    - Bei beantwortbaren Fragen zuerst mit dem aktiven Korpus und der
      exakten Wortform antworten und die getroffenen Annahmen in einem Satz
      nennen; eine präzisierende Rückfrage höchstens ZUSÄTZLICH am Ende,
      nie statt der Antwort.
    - Nur wenn die Frage ohne Festlegung nicht beantwortbar ist:
      CLARIFY Frame, nicht raten.
    - Sehr viele Treffer: Subkorpus oder engere Query vorschlagen.
    """
).strip()

# --------------------------------------------------------------------------- #
# 8) EIN kanonisches mehrschrittiges Beispiel.                                 #
# --------------------------------------------------------------------------- #
KANONISCHES_BEISPIEL = dedent(
    """
    Kanonisches Beispiel (mehrschrittig, gebündelt)

    Nutzer: "Wird 'Heimat' in Nachrichten anders verwendet als in Foren?"

    Runde 1 (gebündelt): create_docset(Nachrichten) und create_docset(Foren).
    Runde 2 (gebündelt): query_count("Heimat", A), query_count("Heimat", B)
    und contrast_collocates("Heimat", A, B).

    Antwort (Muster, Werte aus den Tool-Outputs):
    "In Nachrichten 212 {{ev:ev1.total}} Treffer (31,0
    {{ev:ev1.per_million}} pmw), in Foren 89 {{ev:ev2.total}} (18,2
    {{ev:ev2.per_million}} pmw). Im Kontrast ist 'verlieren' forenlastig
    (log_ratio -2,1 {{ev:ev3.rows[0].log_ratio}}).
    Deutung: Das spricht für eine emotionalere Verwendung in Foren. Das ist
    Interpretation, kein Toolbefund.
    Grenzen: 'verlieren' ist nur einseitig belegt (one_sided=true
    {{ev:ev3.rows[0].one_sided}}), die Teilkorpora sind ungleich groß."

    Einfache Frage: "Wie oft kommt X vor?" ist EIN query_count, dessen
    total zitiert wird. Nie eine Trefferzahl aus gedeckelten KWIC-rows
    ableiten.
    """
).strip()

AUSGABEFORMAT_KOMPAKT = dedent(
    """
    Ausgabeformat

    - Sprache des Nutzers.
    - Zahlen mit Einheit, Bezug und {{ev:...}}-Referenz.
    - Erst Beobachtung, dann als Deutung gekennzeichnete Interpretation,
      bei Bedarf ein Grenzen-Absatz. Ab 4 Datenpunkten Tabelle oder Liste.
    - Knapp auf einfache Fragen, strukturiert auf Analyseaufträge, keine
      mechanische Standardvorlage.
    - Jede Zahl, jedes Zitat und jeder Befund erscheint genau einmal, kein
      Abschnitt wiederholt einen anderen. Methodenvorspann maximal 2 Zeilen.
    """
).strip()


# --------------------------------------------------------------------------- #
# 9) Static Core Assembly.                                                     #
# --------------------------------------------------------------------------- #
def _compose_static_core() -> str:
    """Assemble the static core (uncached, for byte-stability tests)."""
    sections = [
        ("nicht_verhandelbar", STATIC_NICHT_VERHANDELBAR),
        ("rolle", STATIC_ROLLE),
        ("referenz_syntax", REFERENZ_SYNTAX_DOC),
        ("methoden_invarianten", METHODEN_INVARIANTEN),
        ("planung", GEBUENDELTE_PLANUNG),
        ("rezept_index", _recipe_index_text()),
        ("glossar", GLOSSAR_KOMPAKT),
        ("query_syntax", QUERY_SYNTAX_KOMPAKT),
        ("cqlf_capabilities", CQLF_CAPABILITY_DOC),
        ("tools", _static_tools_doc()),
        ("kontext", KONTEXT_DOC),
        ("control_frames", CONTROL_FRAMES_KOMPAKT),
        ("autonomy_levels", AUTONOMIE_KOMPAKT),
        ("runtime_contracts", LAUFZEIT_VERTRAEGE_KOMPAKT),
        ("fehlerbehandlung", FEHLERBEHANDLUNG_KOMPAKT),
        ("beispiel", KANONISCHES_BEISPIEL),
        ("ausgabeformat", AUSGABEFORMAT_KOMPAKT),
        ("deutungsauftrag", DEUTUNGS_AUFTRAG),
    ]
    parts = []
    for tag, body in sections:
        parts.append(f"<{tag}>\n{body}\n</{tag}>")
    return "\n\n".join(parts)


@lru_cache(maxsize=1)
def build_static_core() -> str:
    """Byte-stabiler Systemprompt-Präfix (KV-Cache-Anker).

    Enthält keine Zeitstempel, keine Korpusdaten und keine Session-Daten.
    Alles Variable gehört in ``build_turn_briefing``.
    """
    return _compose_static_core()


# --------------------------------------------------------------------------- #
# 10) Turn-Briefing (variabler Suffix, immer ans Ende).                        #
# --------------------------------------------------------------------------- #
_MAX_TURN_LINES = 8
_MAX_FAILED_LINES = 5
_MAX_LINE_CHARS = 200


def _one_line(value: Any) -> str:
    text = " ".join(str(value).split())
    if len(text) > _MAX_LINE_CHARS:
        text = text[: _MAX_LINE_CHARS - 1] + "…"
    return text


def _render_meta_axes(meta_axes: Any) -> list[str]:
    """Zwei Zeilen: verdichtete Achsen-Liste plus die kontrastierbaren Achsen.

    ``metadaten_achsen`` nennt jede kontrastierbare Achse einzeln mit ihrer
    Wertezahl und fasst einwertige und Dokument-ID-Felder verdichtet zusammen.
    ``kontrastierbare_achsen`` ist die kurze, handlungsleitende Liste (oder
    ``keine``), auf die kontrast/exploration direkt zugreifen.
    """
    axes = [a for a in meta_axes if isinstance(a, Mapping)]
    contrastable = [a for a in axes if a.get("kind") == "axis"]
    # H6, B7: technische Partitionsfelder (split/fold/batch/...) sind
    # Datenaufteilung, keine linguistische Achse. Sie werden ehrlich mit
    # Wertezahl gerendert, zaehlen aber NIE zu kontrastierbare_achsen.
    technical = [a for a in axes if a.get("kind") == "technical"]
    single = [a for a in axes if a.get("kind") == "single"]
    # Ein Feld OHNE Werte ist nicht einwertig, es ist leer. Wuerde die
    # Kategorie hier fehlen, verschwaende das Feld ganz aus dem Inventar,
    # und das waere schlechter als die falsche Schublade.
    leer = [a for a in axes if a.get("kind") == "empty"]
    doc_id = [a for a in axes if a.get("kind") == "doc_id"]
    quelltext = [a for a in axes if a.get("kind") == "quelltext"]
    unknown = [a for a in axes if a.get("kind") == "unknown"]

    def _names(group: list[Mapping[str, Any]], limit: int = 6) -> str:
        names = [str(a.get("field")) for a in group]
        shown = names[:limit]
        text = ", ".join(shown)
        if len(names) > limit:
            text += f", +{len(names) - limit} weitere"
        return text

    segments: list[str] = []
    for axis in contrastable:
        segments.append(f"{axis.get('field')} ({axis.get('count')} Werte, kontrastierbar)")
    for axis in technical:
        segments.append(
            f"{axis.get('field')} ({axis.get('count')} Werte, technisch: "
            "Datenaufteilung, nicht kontrastierbar)"
        )
    if single:
        segments.append(f"{_names(single)} (je 1 Wert, nicht kontrastierbar)")
    if leer:
        segments.append(f"{_names(leer)} (vorhanden, aber unbefüllt)")
    if doc_id:
        segments.append(f"{_names(doc_id)} (Dokument-ID, nicht kontrastierbar)")
    if unknown:
        segments.append(f"{_names(unknown)} (Kardinalitaet unbekannt)")
    lines = ["metadaten_achsen: " + _one_line(" | ".join(segments))]
    # Give the source-text notice its own line so a long axis list cannot
    # truncate the distinction between documents and independent source texts.
    if quelltext:
        lines.append(
            "quelltext_felder: "
            + ", ".join(str(a.get("field")) for a in quelltext[:8])
            + " (gleicher Text in mehreren Fassungen, NICHT kontrastierbar)"
        )
    lines.append(
        "kontrastierbare_achsen: "
        + (
            ", ".join(str(a.get("field")) for a in contrastable)
            if contrastable
            else "keine"
        )
    )
    return lines


def _render_corpus_card(card: Mapping[str, Any]) -> list[str]:
    lines = ["<korpus_karte>"]
    name = card.get("name") or card.get("corpus_id")
    corpus_id = card.get("corpus_id")
    if name and corpus_id and name != corpus_id:
        lines.append(f"korpus: {_one_line(name)} ({_one_line(corpus_id)})")
    elif name:
        lines.append(f"korpus: {_one_line(name)}")
    if card.get("tokens") is not None:
        lines.append(f"tokens: {card['tokens']}")
    if card.get("docs") is not None:
        lines.append(f"dokumente: {card['docs']}")
    # Explain source-text counts directly below the document count.
    # Paired versions repeat the same source, and differences between versions
    # can remain informative even when their topic is shared.
    quellen = card.get("quelltexte")
    if isinstance(quellen, dict) and quellen.get("anzahl"):
        lines.append(
            f"quelltexte: {quellen['anzahl']} "
            f"({quellen.get('fassungen_je_quelltext')} Fassungen je Quelltext, "
            f"Feld {quellen.get('feld')}). Dokumentzahlen sind um diesen "
            "Faktor aufgebläht, Reichweite und Range mit ihnen. Alle "
            "Fassungen eines Quelltexts behandeln dasselbe Thema."
        )
    # Show procedure values and document counts directly below the version
    # description. Keep the line complete because a distinct procedure may
    # appear anywhere in the metadata inventory.
    entstehung = card.get("entstehung")
    if isinstance(entstehung, Mapping) and entstehung.get("werte"):
        kopf = f"entstehung (Feld {entstehung.get('feld')}, Dokumente je Wert"
        ohne = entstehung.get("ohne_wert")
        if isinstance(ohne, int) and not isinstance(ohne, bool) and ohne > 0:
            kopf += f", {ohne} Dokumente ohne Wert"
        lines.append(kopf + "): " + ", ".join(
            f"{eintrag[0]} {eintrag[1]}"
            for eintrag in entstehung["werte"]
            if isinstance(eintrag, (list, tuple)) and len(eintrag) == 2
        ))
    # Was die Metadaten nicht tragen, etwa wer die Schreibaufträge verfasste,
    # kommt wörtlich aus der versionierten Korpusbeschreibung
    # (registry/korpusbeschreibungen.json, prompts._read_korpusbeschreibung).
    # Die Karte fügt nichts hinzu. Ohne Eintrag für die corpus_id keine Zeile.
    if isinstance(entstehung, Mapping) and entstehung.get("beschreibung"):
        lines.append(
            "entstehung laut Korpusbeschreibung: "
            + " ".join(str(entstehung["beschreibung"]).split())
        )
    attributes = card.get("attributes")
    if attributes:
        lines.append("attribute: " + ", ".join(str(a) for a in attributes))
    if card.get("lemma_ist_wortform"):
        lines.append("lemma: kleingeschriebene Wortform, nicht lemmatisiert "
                     "(Index ohne Lemmatisierer gebaut): klare und klaren sind zwei Zeilen")
    # List single-valued attributes beside the usable attributes.
    # Explain their effect on both filtering and grouping so a constant
    # placeholder is not mistaken for an informative annotation layer.
    konstant = card.get("constant_attributes")
    if konstant:
        lines.append(
            "einwertige attribute: "
            + ", ".join(str(a) for a in konstant)
            + " (für alle Token derselbe Wert, weder zum Gruppieren noch zum "
            "Filtern nutzbar, auch nicht in CQL)"
        )
    # Meta-Felder und Datums-Felder sind Verfuegbarkeits-Wahrheiten: "keine"
    # ist eine ehrliche, handlungsleitende Angabe (verlauf/kontrast Schritt 0),
    # deshalb wird sie ausdruecklich gerendert statt weggelassen.
    if "meta_fields" in card:
        meta_axes = card.get("meta_axes")
        if isinstance(meta_axes, (list, tuple)) and meta_axes:
            # Kardinalitaet bekannt: Achsen nach Kontrastierbarkeit gruppieren.
            # Die kontrastierbaren Achsen zuerst (fuer kontrast/exploration
            # handlungsleitend), einwertige und Dok-ID-Felder verdichtet.
            lines.extend(_render_meta_axes(meta_axes))
        else:
            meta_fields = card.get("meta_fields") or []
            lines.append(
                "meta_felder: "
                + (
                    _one_line(", ".join(str(f) for f in meta_fields))
                    if meta_fields
                    else "keine"
                )
            )
        date_fields = card.get("date_fields") or []
        lines.append(
            "datums_felder: "
            + (
                _one_line(", ".join(str(f) for f in date_fields))
                if date_fields
                else "keine"
            )
        )
    capabilities = card.get("capabilities")
    if isinstance(capabilities, Mapping) and capabilities:
        rendered = ", ".join(
            f"{key}={str(bool(capabilities[key])).lower()}"
            for key in sorted(capabilities)
        )
        lines.append(f"capabilities: {rendered}")
    subcorpus = card.get("subcorpus")
    if isinstance(subcorpus, Mapping) and subcorpus:
        label = _one_line(subcorpus.get("label") or subcorpus.get("docset_id") or "aktiv")
        size_bits = []
        if subcorpus.get("docs") is not None:
            size_bits.append(f"{subcorpus['docs']} Dokumente")
        if subcorpus.get("tokens") is not None:
            size_bits.append(f"{subcorpus['tokens']} Tokens")
        suffix = f" ({', '.join(size_bits)})" if size_bits else ""
        lines.append(f"subkorpus: {label}{suffix}")
    else:
        lines.append("subkorpus: keines aktiv")
    lines.append("</korpus_karte>")
    return lines


def _render_session_state(state: Mapping[str, Any]) -> list[str]:
    lines = ["<session_stand>"]
    if state.get("autonomy_level") is not None:
        lines.append(f"autonomy_level: {state['autonomy_level']}")
    turns = state.get("turns") or []
    if turns:
        # Abgeschlossene Vergangenheit, kein Arbeitsauftrag: fruehere
        # Analysen dieser Sitzung duerfen die aktuelle Frage nicht
        # thematisch kontaminieren (Eval-Runde-1-Befund term=und).
        lines.append(
            "letzte_analysen (fruehere, abgeschlossene Analysen dieser "
            "Sitzung, nur bei ausdruecklichem Bezug der aktuellen Frage "
            "verwenden):"
        )
        for turn in list(turns)[-_MAX_TURN_LINES:]:
            lines.append(f"- {_one_line(turn)}")
    else:
        lines.append("letzte_analysen: keine")
    failed = state.get("failed_attempts") or []
    if failed:
        lines.append("failed_attempts:")
        for item in list(failed)[-_MAX_FAILED_LINES:]:
            lines.append(f"- {_one_line(item)}")
    lines.append("</session_stand>")
    return lines


def build_turn_briefing(
    corpus_card: Mapping[str, Any] | None = None,
    recipe_briefing: str | None = None,
    session_state: Mapping[str, Any] | None = None,
    answer_language: str | None = None,
) -> str:
    """Variabler Prompt-Suffix für genau einen Turn.

    Args:
        corpus_card: Kompakte Korpus-Karte. Erwartete Schlüssel (alle
            optional): name, corpus_id, tokens, docs, attributes (Liste),
            meta_fields (Liste, leere Liste rendert "meta_felder: keine"),
            meta_axes (Liste {field, count, kind}; ist sie gesetzt, ersetzt
            "metadaten_achsen"/"kontrastierbare_achsen" die reine
            meta_felder-Zeile), date_fields (Liste, leere Liste rendert
            "datums_felder: keine"), capabilities (Mapping name->bool),
            subcorpus ({label|docset_id, docs, tokens}).
        recipe_briefing: Rezept-Briefing von Agent A oder None/leer für den
            freien Modus.
        session_state: Session-Stand. Erwartete Schlüssel (alle optional):
            autonomy_level, turns (eine Zeile je vergangenem Turn),
            failed_attempts.
        answer_language: language of the answer. Only ``"en"`` writes a line,
            German turns keep every byte.

    Returns:
        ``<turn_briefing>``-Block. Er gehört IMMER ans Ende des Kontextes.
    """
    lines: list[str] = ["<turn_briefing>"]
    if corpus_card:
        lines.extend(_render_corpus_card(corpus_card))
    if session_state:
        lines.extend(_render_session_state(session_state))
    if answer_language == "en":
        lines.append(ANSWER_LANGUAGE_EN_LINE)
    briefing_text = (recipe_briefing or "").strip()
    lines.append("<rezept_briefing>")
    lines.append(briefing_text if briefing_text else FREE_MODE_LINE)
    lines.append("</rezept_briefing>")
    lines.append("</turn_briefing>")
    return "\n".join(lines)
