"""H10/G4: Ehrliche, deliverable-bewusste Todespfad-Landungen.

EIN gemeinsamer Einstieg (``build_death_landing``) waehlt fuer jeden
Todespfad (kooperatives Timeout, Verifier-Skip ohne Entwurf,
Server-Backstop, Engine-Fehler-Salvage) die Landungsform nach Rezept und
Deliverable:

* ``gebrauch_kwic``  -> KWIC-Gebrauchsreport mit ALLEN sichtbaren Zeilen
  als Basis (mindestens 4 Belege wenn vorhanden, Typologie-Skelett,
  Gegenbeleg-Hinweis).
* ``frequenz``       -> Fakt-Antwort (Zahl, pmw, Zaehlweise) aus der
  Evidenz des Frage-Terms.
* ``metadaten_struktur`` -> Metadaten-Inventar.
* ``profil``         -> Word-Sketch-Bericht.

Der generische Digest bleibt LETZTER Ausweg: Rueckgabe ``None`` heisst,
der Aufrufer faellt auf seinen bisherigen Pfad zurueck. Alle Werte
stammen ausschliesslich aus Evidenz mit passender Term-/Query-Provenienz
(G2-Regel auf Builder-Ebene). Eigenes Modul statt Anbau an
``grounding_markdown`` wegen des LOC-Budget-Waechters
(tests/ai/test_copilot_loc_budget.py): Dekomposition statt Budget.
"""

from __future__ import annotations

from candyconc.answer_language import choose as _t

import json
import re
from typing import Any, Dict, List, Sequence, Tuple

from .grounding_markdown import (
    EvidenceItem,
    _build_metadata_capability_markdown,
    _build_term_frequency_markdown,
    _build_term_profile_markdown,
    _build_word_sketch_markdown,
    _compact_sentences,
    _dominant_query_term,
    _kwic_text_from_row,
    _kwic_zaehlungen,
    _normalise_example_text,
    _normalise_text_list,
    _question_term,
    _user_facing_evidence_gap,
    _zaehl_zeilen,
)


_DEATH_LANDING_MAX_QUOTES = 8
_KWIC_NEGATION_TOKENS = frozenset(
    {
        "kein", "keine", "keinen", "keinem", "keiner", "keines",
        "nicht", "ohne", "nie", "kaum",
    }
)
_KWIC_QUANT_TOKENS = frozenset(
    {"viel", "viele", "wenig", "wenige", "mehr", "genug", "alle"}
)
_KWIC_COORD_TOKENS = frozenset({"und", "oder"})


def _item_query_text(item: EvidenceItem) -> str:
    """Provenienz-Query eines Evidenz-Items (raw_surface vor Call-Args)."""

    query = _normalise_example_text(item.raw_surface.get("query"))
    if query:
        return query
    try:
        args = json.loads(item.query or "")
    except (TypeError, ValueError):
        args = None
    if isinstance(args, dict):
        for key in ("query", "term", "word", "lemma", "cql"):
            value = _normalise_example_text(args.get(key))
            if value:
                return value
    return _normalise_example_text(item.query)


def _item_matches_term(item: EvidenceItem, term: str) -> bool:
    folded = str(term or "").strip().casefold()
    if not folded:
        return False
    return folded in _item_query_text(item).casefold()


def _kwic_example_bucket(example: str, term_head: str) -> str:
    """Grobe Gebrauchstypologie EINER sichtbaren KWIC-Zeile (Skelett)."""

    tokens = [
        token.lower()
        for token in re.findall(r"[\wÄÖÜäöüß]+", str(example or ""))
    ]
    if not tokens:
        return _t("sonstige Kontexte", 'other contexts')
    positions = [
        index
        for index, token in enumerate(tokens)
        if term_head
        and (
            token == term_head
            or token.startswith(term_head)
            or term_head.startswith(token)
        )
    ]
    index = positions[0] if positions else len(tokens) // 2
    window = tokens[max(0, index - 4) : index] + tokens[index + 1 : index + 5]
    adjacent = [
        tokens[pos]
        for pos in (index - 1, index + 1)
        if 0 <= pos < len(tokens) and pos != index
    ]
    if any(token in _KWIC_NEGATION_TOKENS for token in window):
        return _t("negierte oder limitierende Kontexte", 'negated or limiting contexts')
    if any(token in _KWIC_QUANT_TOKENS for token in adjacent):
        return _t("quantifizierende Kontexte", 'quantifying contexts')
    if len(positions) >= 2:
        return _t("wiederholte oder formelhafte Verwendung", 'repeated or formulaic use')
    if any(token in _KWIC_COORD_TOKENS for token in adjacent):
        return _t("Koordinations- oder Aufzählungskontexte", 'coordination or enumeration contexts')
    return _t("sonstige Kontexte", 'other contexts')


def _kwic_death_evidence(
    evidence_items: Sequence[EvidenceItem],
    *,
    question_scope: str = "",
) -> Tuple[str, Any, Any, List[str], List[Tuple[str, Any, Any]]] | None:
    """Alle sichtbaren KWIC-Zeilen mit passender Term-Provenienz einsammeln.

    Traegt die Frage einen Term und existiert dafuer KEINE passende
    Trefferzeile, werden die fremden Werte NICHT mit dem Frage-Term
    verheiratet: der Term wird dann aus den Items selbst abgeleitet.

    P6-NACHBESSERUNG: die ``query_count``-Posten kommen als fuenftes
    Element mit. Seit P6 stehen im Werkzeugraum dieser Familie DREI
    Zaehlschritte vor dem einzigen KWIC-Abruf (satzintern, within(<doc>),
    je Seite mit Nenner), und diese Funktion las ausschliesslich
    ``run_cqlf_query``. Gemessen am 2026-09-03: eine Landung mit einem
    query_count(total=45599, denominator_tokens=142044149) war ``None``.
    """

    kwic_items = [
        item
        for item in evidence_items
        if item.tool == "run_cqlf_query"
        and str(item.status).casefold() != "error"
    ]
    term = _question_term(question_scope)
    if term:
        matching = [
            item for item in kwic_items if _item_matches_term(item, term)
        ]
        if matching:
            kwic_items = matching
        else:
            term = ""
    if not kwic_items:
        return None
    if not term:
        term = _dominant_query_term(kwic_items, fallback=_t("der Suchbegriff", 'the search term'))
    total_hits: Any = None
    rows_seen: Any = None
    examples: List[str] = []
    for item in kwic_items:
        if total_hits in (None, "") and item.raw_surface.get("total") not in (None, ""):
            total_hits = item.raw_surface.get("total")
        if rows_seen in (None, "") and item.raw_surface.get("rows_seen") not in (None, ""):
            rows_seen = item.raw_surface.get("rows_seen")
        rows = item.raw_surface.get("rows")
        if isinstance(rows, list):
            examples.extend(
                example
                for example in (
                    _kwic_text_from_row(row)
                    for row in rows
                    if isinstance(row, dict)
                )
                if example
            )
    examples = list(dict.fromkeys(examples))
    if not examples:
        return None
    return term, total_hits, rows_seen, examples, _kwic_zaehlungen(
        evidence_items
    )


def _kwic_death_report(
    *,
    query_term: str,
    total_hits: Any,
    rows_seen: Any,
    examples: Sequence[str],
    zaehlungen: Sequence[Tuple[str, Any, Any]] = (),
    evidence_gaps: Sequence[str] = (),
) -> str:
    """KWIC-Gebrauchsreport fuer Todespfade: ALLE sichtbaren Zeilen als Basis.

    Mindestens 4 woertliche Belege (wenn vorhanden), ein Typologie-Skelett
    ueber saemtliche sichtbaren Zeilen und ein Gegenbeleg-Hinweis. Kein
    Zwei-Fragmente-Digest, kein Presence-Rahmen.
    """

    visible_count = len(examples)
    shown = list(examples[:_DEATH_LANDING_MAX_QUOTES])
    # Die Leserin ist Korpuslinguistin, keine Informatikerin. ``total=1``
    # ist ein Variablenname, kein Deutsch, und "1 sichtbare Trefferzeilen"
    # ist falsch flektiert. Die UNTERSCHEIDUNG, die der alte Text machen
    # wollte, bleibt und ist fachlich wichtig: die Gesamttrefferzahl im
    # Korpus ist etwas anderes als die Zahl der angezeigten Zeilen.
    zeilen = (
        "1 Belegzeile" if visible_count == 1
        else f"{visible_count} Belegzeilen"
    )
    if total_hits not in (None, ""):
        mal = "1 Mal" if str(total_hits) == "1" else f"{total_hits} Mal"
        head = (
            _t(f"`{query_term}` kommt im durchsuchten Korpus {mal} vor. "
            f"Ausgewertet {'wird' if visible_count == 1 else 'werden'} "
            f"hier {zeilen}.", f"""`{query_term}` occurs {total_hits} time(s) in the searched corpus. This report examines {visible_count} concordance line(s).""")
        )
    elif rows_seen not in (None, ""):
        head = (
            _t(f"Zu `{query_term}` liegen {rows_seen} Belegzeilen vor. Eine "
            "Gesamttrefferzahl für das Korpus wurde nicht mehr ermittelt.", f"""There are {rows_seen} concordance lines for `{query_term}`. The total number of corpus hits was not determined.""")
        )
    else:
        head = (
            _t(f"Zu `{query_term}` {'liegt' if visible_count == 1 else 'liegen'} "
            f"{zeilen} vor. Eine Gesamttrefferzahl für das Korpus wurde "
            "nicht mehr ermittelt.", f"""There are {visible_count} concordance line(s) for `{query_term}`. The total number of corpus hits was not determined.""")
        )
    lines = [head, "", _t("Belegzeilen:", 'Concordance lines:')]
    lines.extend(f"- „{example}“" for example in shown)
    # P6-NACHBESSERUNG: die gezaehlten Zahlen samt Nenner, jede neben
    # IHRER Abfrage. Ohne diesen Block fielen die zwei verlangten
    # Zaehlungen (satzintern und within(<doc>)) und jede Rate je Seite
    # aus der Landung, obwohl das Briefing sie ausdruecklich verlangt.
    gezaehlt = _zaehl_zeilen(zaehlungen)
    if gezaehlt:
        lines.extend(["", _t("Gezählt:", 'Counts:')])
        lines.extend(gezaehlt)
    term_tokens = re.findall(
        r"[\wÄÖÜäöüß]+", str(query_term or "").lower()
    )
    term_head = term_tokens[0] if term_tokens else ""
    buckets: Dict[str, List[str]] = {}
    for example in examples:
        buckets.setdefault(
            _kwic_example_bucket(example, term_head), []
        ).append(example)
    ordered = sorted(
        buckets.items(), key=lambda entry: (-len(entry[1]), entry[0])
    )
    lines.append("")
    lines.append(
        _t(f"Wie sich die {zeilen} verteilen:", f"""How the {visible_count} concordance lines are grouped:""")
        if visible_count != 1
        else _t("Wie sich die Belegzeile einordnet:", 'How the concordance line is classified:')
    )
    for label, bucket in ordered:
        lines.append(
            _t(f"- {label}: {len(bucket)} von {visible_count} Zeilen, "
            f"zum Beispiel „{bucket[0]}“", f"""- {label}: {len(bucket)} of {visible_count} lines, for example “{bucket[0]}”""")
        )
    lines.append("")
    lines.append(_t("Gegenbelege", 'Counterexamples'))
    if len(ordered) > 1:
        dominant_label = ordered[0][0]
        counter_example = ordered[-1][1][0]
        lines.append(
            _t(f"Nicht alle Zeilen folgen dem dominanten Muster "
            f"({dominant_label}). Ein sichtbarer Gegenbeleg-Kandidat: "
            f"„{counter_example}“.", f"""Not all lines follow the dominant pattern ({dominant_label}). A visible candidate counterexample: “{counter_example}”.""")
        )
    else:
        lines.append(
            _t("Ein systematischer Gegenbeleg-Durchgang ist nicht mehr "
            "gelaufen. Die sichtbaren Zeilen widersprechen dem Muster "
            "nicht, belegen seine Ausnahmslosigkeit aber auch nicht.", 'A systematic search for counterexamples was not completed. The visible lines fit the pattern, but do not establish that it has no exceptions.')
        )
    lines.append(
        _t("Die Typologie beschreibt nur den zitierten Ausschnitt und ist "
        "keine Aussage über ein korpusweites Gebrauchsmuster. Eine "
        "weitergehende Gebrauchsanalyse ist nicht enthalten, der Turn "
        "endete vor der Modell-Synthese.", 'The classification describes the quoted excerpt. A corpus-wide usage analysis requires model synthesis, which this turn did not reach.')
    )
    lines.append("")
    # KEINE erfundene Kappung. Der Satz behauptete frueher pauschal einen
    # "gekappten Ausschnitt (limit)". Gemessen am 2026-08-29: bei 37
    # Treffern lieferte das Werkzeug mit ``limit=50`` ALLE 37 Zeilen,
    # ``truncated`` war False. Gekappt hatte nicht das Werkzeug, sondern
    # der Turn, der vor der Verarbeitung der restlichen 17 endete. Die
    # Landung kennt ``truncated`` nicht, aber sie kennt beide Zahlen, und
    # daraus laesst sich die Wahrheit bilden statt sie zu raten.
    #
    # Steht die Zahl der ausgewerteten Zeilen der Gesamtzahl gegenueber,
    # sagt das der Leitsatz oben bereits. Hier steht deshalb NUR, was er
    # nicht sagt, und nichts, wenn es nichts zu sagen gibt: eine
    # Konzession, ein Ort.
    if total_hits not in (None, "") and str(total_hits) != str(visible_count):
        lines.append(
            _t("Grenzen: Die Einordnung oben beruht auf den ausgewerteten "
            f"Zeilen, nicht auf allen {total_hits} Treffern.", f"""Scope: The classification above is based on the analysed lines, rather than all {total_hits} hits.""")
        )
    elif total_hits in (None, ""):
        lines.append(
            _t("Grenzen: Eine Gesamttrefferzahl liegt nicht vor. Welchen "
            "Anteil die gezeigten Zeilen ausmachen, ist damit offen.", 'Scope: The total hit count is unavailable, so the proportion represented by the displayed lines is unknown.')
        )
    else:
        lines.append(
            _t("Grenzen: Die Einordnung ist eine Lesart der Zeilen, keine "
            "Messung.", 'Scope: The classification is a reading of the lines, rather than a measurement.')
        )
    gaps = _normalise_text_list(
        [
            line
            for line in (
                _user_facing_evidence_gap(gap) for gap in evidence_gaps
            )
            if line
        ],
        max_items=6,
        item_limit=220,
    )
    if gaps:
        lines.append("")
        lines.append(_t("Limitationen:", 'Limitations:'))
        lines.extend(f"- {gap}" for gap in gaps)
    return "\n".join(lines)


def _frequency_death_answer(
    evidence_items: Sequence[EvidenceItem],
    *,
    question_scope: str = "",
    evidence_gaps: Sequence[str] = (),
) -> str | None:
    """Fakt-Antwort (Zahl, pmw, Zaehlweise) NUR aus Evidenz des Frage-Terms.

    Traegt die Frage einen Term und existiert kein query_count mit passender
    Query-Provenienz, gibt es KEINE Landung (None). Fremde Zahlen werden nie
    mit dem Frage-Term verheiratet.
    """

    counts = [
        item
        for item in evidence_items
        if item.tool == "query_count"
        and str(item.status).casefold() != "error"
        and item.raw_surface.get("total") not in (None, "")
    ]
    term = _question_term(question_scope)
    if term:
        matching = [item for item in counts if _item_matches_term(item, term)]
        if not matching:
            return None
        return _build_term_frequency_markdown(
            matching, evidence_gaps=evidence_gaps
        )
    if counts:
        return _build_term_frequency_markdown(
            counts, evidence_gaps=evidence_gaps
        )
    has_frequency_rows = any(
        item.tool == "frequency_list"
        and str(item.status).casefold() != "error"
        and isinstance(item.raw_surface.get("rows"), list)
        and item.raw_surface.get("rows")
        for item in evidence_items
    )
    if has_frequency_rows:
        return _build_term_frequency_markdown(
            evidence_items, evidence_gaps=evidence_gaps
        )
    return None


def build_death_landing(
    evidence_items: Sequence[EvidenceItem],
    *,
    recipe_id: str = "",
    deliverable_kind: str = "",
    question_scope: str = "",
    evidence_gaps: Sequence[str] = (),
    reason: str = "",
) -> str | None:
    """EIN Einstieg fuer alle Todespfade: Landungsform nach Rezept/Deliverable.

    gebrauch_kwic -> KWIC-Gebrauchsreport mit allen sichtbaren Zeilen,
    frequenz -> Fakt-Antwort aus der Term-Evidenz, metadaten_struktur ->
    Inventar, profil -> Sketch-Bericht. ``None`` heisst: kein rezeptbewusster
    Builder greift, der Aufrufer nutzt seinen generischen Digest als LETZTEN
    Ausweg. ``reason`` (z. B. Engine-Fehler) wird als genau EIN Satz
    angehaengt.
    """

    recipe = str(recipe_id or "").strip()
    landing: str | None = None
    if recipe == "gebrauch_kwic" or (
        not recipe and deliverable_kind == "analysis_report"
    ):
        gathered = _kwic_death_evidence(
            evidence_items, question_scope=question_scope
        )
        if gathered:
            term, total_hits, rows_seen, examples, zaehlungen = gathered
            landing = _kwic_death_report(
                query_term=term,
                total_hits=total_hits,
                rows_seen=rows_seen,
                examples=examples,
                zaehlungen=zaehlungen,
                evidence_gaps=evidence_gaps,
            )
        else:
            # KEINE Belegzeile, aber gezaehlt. Seit P6 stellt das
            # Briefing dieses Rezepts drei query_count-Schritte VOR den
            # einzigen KWIC-Abruf, und genau die Turns, die an der
            # Schranke enden, haben deshalb Zahlen und keine Zeilen.
            # Gemessen am 2026-09-03: ein Posten
            # query_count(total=45599, denominator_tokens=142044149)
            # ergab hier None, und der Aufrufer lieferte "Es liegen noch
            # keine hinreichend belegten Beobachtungen ... vor". Derselbe
            # Verfasser, den das Rezept frequenz laengst nutzt, macht aus
            # dieser Evidenz eine Zahl mit Nenner und Zaehlweise.
            landing = _frequency_death_answer(
                evidence_items,
                question_scope=question_scope,
                evidence_gaps=evidence_gaps,
            )
    elif recipe == "frequenz":
        landing = _frequency_death_answer(
            evidence_items,
            question_scope=question_scope,
            evidence_gaps=evidence_gaps,
        )
    elif recipe == "metadaten_struktur":
        if any(
            item.tool == "metadata_values"
            and str(item.status).casefold() != "error"
            for item in evidence_items
        ):
            landing = _build_metadata_capability_markdown(
                evidence_items,
                question_scope=question_scope,
                evidence_gaps=evidence_gaps,
            )
    elif recipe == "assoziation":
        # Die zweite Naht. Ohne diesen Zweig faellt eine gestorbene
        # Assoziationsfrage auf den generischen Digest, und der Fix am
        # Verfasserpfad waere eine Verschiebung statt einer Reparatur.
        #
        # NIE SCHLECHTER: der Verfasser liest die Beschriftung einer Zeile
        # aus 'word' oder 'kw'. Traegt keine Zeile davon eines, liefert er
        # den konservativen Rueckfall, und der ist AERMER als der
        # generische Digest, den es ohne diese Landung gaebe. Die Landung
        # verlangt deshalb genau das, was der Verfasser braucht, und
        # weicht sonst zurueck.
        if any(
            item.tool == "collocate_stats"
            and str(item.status).casefold() != "error"
            and isinstance(item.raw_surface.get("rows"), list)
            and any(
                isinstance(row, dict)
                and (row.get("word") or row.get("kw"))
                for row in item.raw_surface["rows"]
            )
            for item in evidence_items
        ):
            landing = _build_term_profile_markdown(
                [], evidence_items, evidence_gaps=evidence_gaps
            )
    elif recipe == "profil":
        if any(
            item.tool == "word_sketch"
            and str(item.status).casefold() != "error"
            and isinstance(item.raw_surface.get("tables"), dict)
            and item.raw_surface.get("tables")
            for item in evidence_items
        ):
            landing = _build_word_sketch_markdown(
                evidence_items, evidence_gaps=evidence_gaps
            )
    if not (isinstance(landing, str) and landing.strip()):
        return None
    landing = landing.rstrip()
    reason_line = _compact_sentences(str(reason or "").strip(), 240)
    if reason_line:
        landing += _t("\n\nHinweis: ", '\n\nNote: ') + reason_line
    return landing


def death_landing_from_turn_state(
    raw_evidence_items: Sequence[Any],
    *,
    recipe_id: str = "",
    contract: Any = None,
    evidence_gaps: Sequence[str] = (),
    reason: str = "",
    question: str = "",
) -> str | None:
    """Todespfad-Landung direkt aus dem Turn-Zustand des Orchestrators.

    Nimmt die rohen Evidenz-Dicts (``_turn_evidence_items``), das aktive
    Rezept und den (moeglicherweise leeren) Kontrakt. Braucht KEINEN
    Kontrakt: bei einem Engine-Ausfall vor der Kontrakt-Phase liegt dank
    der Vorplanung trotzdem Evidenz vor.
    """

    items: List[EvidenceItem] = []
    for raw in list(raw_evidence_items or []):
        if isinstance(raw, EvidenceItem):
            items.append(raw)
            continue
        if isinstance(raw, dict):
            try:
                items.append(EvidenceItem(**dict(raw)))
            except TypeError:
                continue
    if not items:
        return None
    contract_map = contract if isinstance(contract, dict) else {}
    deliverable_kind = str(contract_map.get("deliverable_kind", "") or "")
    question_scope = (
        str(contract_map.get("question_scope", "") or "")
        or str(question or "")
    )
    try:
        return build_death_landing(
            items,
            recipe_id=recipe_id,
            deliverable_kind=deliverable_kind,
            question_scope=question_scope,
            evidence_gaps=list(evidence_gaps or []),
            reason=reason,
        )
    except Exception:
        return None
