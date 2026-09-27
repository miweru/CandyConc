# -*- coding: utf-8 -*-
"""Termliste als eigene Kontrastform: Erkennung, Briefing-Note, Vertrag.

LIVE am 2026-09-02, Frage ``gemischt-markerliste-robustheit``. Das Modell
rief ``keyness`` mit ``target=['Herausforderung', 'Aspekt', 'entscheidend',
'hinaus', 'zudem', 'essentiell', 'massgeblich']`` und einer
``reference_docset_id`` auf, bekam 400, wich auf eine globale Keyness ueber
389.305 Zeilen aus und meldete am Ende ehrlich, dass keiner der sieben
Kandidaten in den sichtbaren Zeilen steht. Das stimmt und ist wertlos: in
der Spitze einer 389.305-Zeilen-Tabelle koennen sieben bestimmte Woerter
fehlen, ohne dass daraus etwas ueber sie folgt.

``keyness`` bekommt deshalb KEINE Kandidatenliste. ``target`` ist ein
Tokenstrom, aus dem ``services/tools/keyness.py`` einen ``Counter``
bildet, sieben Kandidaten waeren also sieben Tokens Gesamtmasse. Die richtige
Form ist eine andere: je Kandidat eine Zaehlung auf beiden Seiten, mit dem
Nenner der jeweiligen Seite, und der Vergleich ueber die normierte Rate.
Genau das tat die Referenzantwort (rund 20 Werkzeugaufrufe), und sie fand
damit einen tragenden, drei invertierte und zwei Einzelmodell-Kandidaten.

Die ERKENNUNG steht nicht hier, sondern in ``frageform`` (P5,
``kandidatenliste_aus_frage``). Dieses Modul hatte kurzzeitig einen
zweiten Erkenner, und die beiden waren komplementaer disjunkt: gemessen
an evaluation/fragen/deutung_rollen_2026-08-31.json las der hiesige aus
der LIVE-Fassung der Markerfrage nichts (sie fuehrt ihre sieben Terme
ohne Anfuehrungszeichen) und fing dafuer die drei Achsenwerte aus
"Welche Diskursmarker sind typisch fuer 'news' gegenueber 'chat' und
'legal'?". Ein Erkenner, zwei Verbraucher.

Was hier bleibt: die Zitat-Extraktion der Slot-Vorplanung als EINZIGE
Quelle (``recipe_runtime`` re-exportiert sie) und der Modus selbst,
also Turn-Note und Pflichtevidenz.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from .question_form import _is_word_char, kandidatenliste_aus_frage

# Anfuehrungszeichen-Paare der Slot-Extraktion: typografisch deutsch
# (einfach und doppelt), typografisch englisch, gerade Zeichen, Backticks.
_QUOTE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("‚", "‘’"),  # ‚Frau‘ und ‚Frau’
    ("‘", "’"),  # ‘Frau’
    ("„", "“"),  # „Frau“
    ("“", "”"),  # “Frau”
    ("'", "'"),
    ('"', '"'),
    ("`", "`"),
)
_MAX_TERM_CHARS = 60

# H10/G3-Robustheit: gemischt getippte Paare (typografischer Oeffner, gerader
# Schliesser wie in ``‚Frau'``) kommen in realen Fragen vor, wenn eine
# Autokorrektur nur das oeffnende Zeichen ersetzt. Sie zaehlen NACHRANGIG:
# ein gemischtes Paar wird nur akzeptiert, wenn am selben Oeffner kein
# typografisch geschlossenes Paar beginnt (sonst zerfiele ``‚geht's um
# Geld‘`` am inneren Apostroph zu ``geht``).
_MIXED_QUOTE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("‚", "'"),
    ("‘", "'"),
    ("„", '"'),
    ("“", '"'),
)

def _quote_matches(
    text: str, opener: str, closers: str
) -> List[Tuple[int, str]]:
    """(start, term)-Treffer eines Anfuehrungspaars (Wortgrenzen-Schutz)."""
    pattern = re.compile(
        re.escape(opener)
        + "([^"
        + re.escape(opener + closers)
        + "\n]{1,"
        + str(_MAX_TERM_CHARS)
        + "})["
        + re.escape(closers)
        + "]"
    )
    found: List[Tuple[int, str]] = []
    for match in pattern.finditer(text):
        start = match.start()
        if start > 0 and _is_word_char(text[start - 1]):
            continue
        term = match.group(1).strip()
        if term:
            found.append((start, term))
    return found


def extract_primary_terms(question: str) -> List[str]:
    """Terme aus Anfuehrungszeichen der Frage (Reihenfolge erhalten, Dedup).

    Nur echte Zitat-Spannen zaehlen: das oeffnende Zeichen darf nicht in
    einem Wort stehen (Apostrophe wie in "geht's" sind keine Slots), die
    Spanne bleibt einzeilig und maximal 60 Zeichen lang. Ohne
    Anfuehrungszeichen ist das Ergebnis leer, und dann gibt es KEINE
    Vorplanung. Gemischt getippte Paare (``‚Frau'``) zaehlen nachrangig
    (siehe ``_MIXED_QUOTE_PAIRS``).
    """
    text = str(question or "")
    found: List[Tuple[int, str]] = []
    for opener, closers in _QUOTE_PAIRS:
        found.extend(_quote_matches(text, opener, closers))
    strict_starts = {start for start, _ in found}
    for opener, closers in _MIXED_QUOTE_PAIRS:
        found.extend(
            (start, term)
            for start, term in _quote_matches(text, opener, closers)
            if start not in strict_starts
        )
    terms: List[str] = []
    for _, term in sorted(found, key=lambda item: item[0]):
        if term not in terms:
            terms.append(term)
    return terms


def kandidatenliste(question: str) -> List[str]:
    """Die Kandidaten der Frage, gelesen von ``frageform`` (P5).

    Gemessen am eingefrorenen Fragensatz vom 2026-08-31: sieben Terme fuer
    gemischt-markerliste-robustheit, die leere Liste fuer die uebrigen
    sieben Fragen und fuer die Diskursmarker-Frage, deren drei
    Achsenwerte keine zu pruefenden Kandidaten sind.
    """
    return list(kandidatenliste_aus_frage(question))


def ist_kandidatenliste(question: str) -> bool:
    """Traegt die Frage eine zu pruefende Kandidatenliste?"""
    return bool(kandidatenliste(question))


def kandidatenlisten_note(terme: Sequence[str]) -> str:
    """Turn-Note des Termlisten-Modus (nennt die Kandidaten beim Namen).

    Die Note nennt sie einzeln, weil genau das im Live-Turn verloren ging:
    jeder der sieben Kandidaten kam in der ganzen Antwort GENAU EINMAL vor,
    naemlich in dem Satz, der ihr Fehlen in der Keyness-Spitze meldete.

    Sie setzt ausserdem vier Felder des kontrast-Briefings ausser Kraft.
    Gemessen mit ``render_briefing(get_recipe('kontrast'))``: direkt hinter
    dem Termlisten-Absatz steht "Schritt 3. Gerichtete Keyness rechnen",
    danach ein Abbruchkriterium ueber stabile Top-Keywords, die Antwortform
    "Gerichtete Keyword-Liste (word, log_ratio mit CI, per_million
    beidseitig)" und zwei Leitplanken ueber log_ratio-CI und
    low_reliability. ``query_count`` liefert keines dieser Felder. Das
    Briefing ist statisch je Rezept (``build_turn_system_prompt`` kennt die
    Frage nicht), die Note ist die einzige Stelle, die nur im Termlisten-
    Fall spricht, also steht die Ausserkraftsetzung hier.
    """
    namen = ", ".join(f"'{str(t)}'" for t in list(terme))
    return (
        f"Termlisten-Kontrast ({len(list(terme))} Kandidaten: {namen}): "
        "die Kandidatenliste ist KEIN keyness-Argument. `target` ist ein "
        "Tokenstrom, sieben Kandidaten wären sieben Tokens Gesamtmasse. "
        "Je Kandidat query_count auf BEIDEN Seiten (Docsets aus den "
        "Achsenwerten), dazu je Seite den Nenner (word_count des Docsets), "
        "und das Verhältnis als Rate pro Million berichten. Kandidaten in "
        "der Keyness-Spitze suchen ist kein Befund: fehlt ein Wort in den "
        "sichtbaren Zeilen einer großen Keyness-Tabelle, folgt daraus "
        "nichts über dieses Wort. Für diese Frage gilt Schritt 3 des "
        "Briefings (gerichtete Keyness) NICHT als Pflichtschritt, und die "
        "Antwortform ist nicht die gerichtete Keyword-Liste, sondern eine "
        "Zeile je Kandidat mit beiden Zählungen, beiden Nennern und der "
        "Rate pro Million. Die Leitplanken zu log_ratio-CI und "
        "low_reliability gelten nur für Zeilen, die wirklich aus keyness "
        "stammen. Eine gerichtete Keyness über die beiden Docsets bleibt "
        "als Ergänzung erlaubt, sie ersetzt die Zählung je Kandidat aber "
        "nicht."
    )


def kandidatenlisten_evidenz(
    evidenz: Sequence[str], bundle: Sequence[str]
) -> List[str]:
    """Pflichtevidenz des Termlisten-Modus: Zaehlung ZUSAETZLICH zur Metrik.

    ``total_hits`` kommt hinzu, wenn ``query_count`` im Raum steht.
    ``metric_rows`` bleibt stehen, und das ist eine Korrektur an der
    ersten Fassung dieses Modus, die es ersetzte. Gemessen im Arbeitsbaum
    mit demselben Kontraktaufruf, den die Proben fahren: ohne
    ``metric_rows`` gaten beide contrast_keyness-Zweige von
    ``recipe_runtime.pending_required_evidence_tools`` nicht mehr, die
    Leiter der Markerfrage sprang in derselben Runde auf
    ['metadata_values', 'query_count'] und erreichte create_docset nie.
    Der Orchestrator gibt nur die ersten vier erzwungenen Werkzeuge frei
    (orchestrator.py:7673) und verengt den Werkzeugraum darauf
    (orchestrator.py:3070, tool_choice='required'), also waere das
    einzige moegliche query_count wieder korpusglobal gewesen: dieselbe
    Form "global statt je Seite", die dieser Modus abstellen soll.
    """
    if "query_count" not in set(bundle):
        return list(evidenz)
    ergaenzt = list(evidenz)
    if "total_hits" not in ergaenzt:
        ergaenzt.append("total_hits")
    seen: set[str] = set()
    return [e for e in ergaenzt if not (e in seen or seen.add(e))]
