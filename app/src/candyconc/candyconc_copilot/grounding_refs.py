"""Deterministischer Referenz-Renderer: Evidenz-Referenzen statt Zahlen im Modelltext.

Das Modell schreibt Referenzen, der Renderer setzt deterministisch die Werte
aus der Evidenz ein. Der Renderer blockiert nie Interpretation: er liefert
ausschliesslich Befunde (aufgeloester Text, unaufloesbare Referenzen,
ungebundene Zahlen). Ob ein Befund hart oder beratend behandelt wird,
entscheidet die Politik (Severity-Split), nicht dieses Modul. Alle Pfade sind
rein deterministisch (Regex + Set-Membership, keine LLM-Aufrufe).

Offizielle Referenz-Syntax (API-Kontrakt, Obermenge des internen
Fakt-Zitationsformats aus ``grounding_schemas._INTERNAL_FACT_REFERENCE_PATTERN``):

``{{ev:ID}}``
    Referenz auf ein Evidenz-Item (``EvidenceBundle.items[].id``) oder einen
    ``ObservedFact`` (``f\\d{3}``-Stil oder beliebige kompakte ID).
    * Fakt-ID ohne Pfad = Zitation: wird wie bisher entfernt (kein Wert im
      Text), aber als aufgeloeste Referenz protokolliert.
    * Item-ID ohne Pfad = Primaerwert des Items (erster vorhandener
      Zaehlwert ``total``/``total_hits``/``result_count``/``doc_count``/
      ``token_count``/``corpus_tokens``/``n_tokens`` aus ``raw_surface``),
      sonst Zitations-Semantik.

``{{ev:ID.feld}}`` / ``{{ev:ID.feld[i]}}`` / ``{{ev:ID.feld[i].sub}}``
    Pfadzugriff. Fuer Evidenz-Items wird der Pfad nacheinander gegen das
    Item selbst, ``raw_surface``, ``fact_surface`` und ``result_scope``
    aufgeloest (erster Treffer gewinnt), fuer Fakten gegen die Fakt-Felder
    (``statement``, ``grounding_quotes[i]``, ...). ``[i]`` indiziert Listen
    (0-basiert).

Rueckwaertskompatibilitaet: die internen Fakt-Zitationen im Klartext
(``(f001)``, ``[f001, f002]``, ``mit den IDs f001–f003``, bare ``f001`` ...)
bleiben gueltig. Sie werden byte-identisch zu
``_strip_internal_fact_references`` entfernt und dabei als Zitationen
protokolliert; unbekannte zitierte IDs landen in ``unresolved``.

Formatierung eingesetzter Werte (angelehnt an ``grounding_markdown``,
``_analysis_provenance_lines._number``):
    * Ganzzahlen: Tausenderpunkt (``56191`` -> ``56.191``).
    * Dezimalwerte: unveraendert mit Dezimalpunkt (``0.5946``).
    * KWIC-Zeilen (dict mit left/kw/right): ``„left kw right“ (ID, Zeile i)``.
    * Tabellenzellen: der Zellwert; ganze Zeilen als ``feld=wert``-Liste.
    * Bool: ``ja``/``nein``.

Unaufloesbare Referenzen werden durch den ehrlichen Platzhalter
``[Beleg fehlt]`` ersetzt und mit Meldung protokolliert.

Bare-Number-Detektion: Zahlen im Text, die keine Referenz sind, werden gegen
die Evidenz-Oberflaeche gebunden. Die Binde-Maschinerie kommt vollstaendig aus
``claim_rules._shared`` (Normalisierung, Set-Membership, Prozent-Ableitung).
Ergebnisklassen: gebunden (still), harmlos (still, konservative Allowlist:
Jahreszahl mit Datums-Metadaten in der Evidenz und temporalem Kontext,
Markdown-Listenordinale), ungebunden (``bare_numbers``-Befund, potentielle
Fabrikation). Werte, die dieser Renderer selbst eingesetzt hat, sind per
Konstruktion belegt und werden nie als bare number gemeldet.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from candyconc.answer_language import is_english, yes_no
from .claim_rules._shared import (
    _MARKDOWN_LIST_ORDINAL_PATTERN,
    _SIGNED_NUMBER_PATTERN,
    _extract_numeric_tokens,
    _normalize_number_token,
    _number_has_integer_grouping_context,
    _numeric_token_is_supported,
    _percent_token_is_supported,
)
from .claim_rules.frequency import (
    _pmw_pair_findings,
    _unique_token_denominator,
)
from .grounding_schemas import (
    _INTERNAL_FACT_REFERENCE_PATTERN,
    _compact_text,
)

__all__ = [
    "EVIDENCE_REFERENCE_PATTERN",
    "MISSING_EVIDENCE_PLACEHOLDER",
    "MISSING_EVIDENCE_PLACEHOLDER_EN",
    "format_evidence_value",
    "reference_syntax_help",
    "resolve_references",
]


MISSING_EVIDENCE_PLACEHOLDER = "[Beleg fehlt]"
#: What a finished English answer shows instead (glossary: "[evidence missing]").
#: Every guard inside the pipeline detects the German form, the English one is
#: written only at the end (recipe_runtime.politur_mit_zitatwache).
MISSING_EVIDENCE_PLACEHOLDER_EN = "[evidence missing]"

# Offizielle Marker-Syntax. Kein Zeilenumbruch, maximal 200 Zeichen Rumpf,
# damit ein vergessenes ``}}`` nicht den halben Text konsumiert.
EVIDENCE_REFERENCE_PATTERN = re.compile(r"\{\{\s*ev\s*:\s*([^{}\n]{1,200}?)\s*\}\}")

_PATH_TOKEN_PATTERN = re.compile(r"\.([A-Za-z_][\w\-]*)|\[(\d{1,6})\]")
_CITED_ID_PATTERN = re.compile(r"f?\d{3}", re.IGNORECASE)

# Bereinigung nach Entfernen von Zitationen: byte-identisch zur Sequenz in
# grounding_schemas._strip_internal_fact_references.
_DANGLING_DASH_PATTERN = re.compile(r"\s+[–—-]\s*(?=[)\],.;:!?]|$)")
_EMPTY_PARENS_PATTERN = re.compile(r"\(\s*\)")
_SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"\s+([,.;:!?])")

# Mark only positions where a reference or legacy citation was removed.
# Limit _cleanup_both to those positions so ordinary punctuation and
# literal concordance quotations keep their original spacing and characters.
_ENTFERNT = "\x02"
_ENTFERNT_RAUM = r"[\s\x02]"
_DANGLING_DASH_AN_ENTFERNUNG = re.compile(
    _ENTFERNT_RAUM + r"+[–—-]" + _ENTFERNT_RAUM + r"*(?=[)\],.;:!?]|$)"
)
_EMPTY_PARENS_AN_ENTFERNUNG = re.compile(r"\(" + _ENTFERNT_RAUM + r"*\)")
_SPACE_BEFORE_PUNCT_AN_ENTFERNUNG = re.compile(_ENTFERNT_RAUM + r"+([,.;:!?])")

# Primaerwert eines Evidenz-Items fuer die pfadlose Referenz.
_PRIMARY_SCALAR_KEYS = (
    "total",
    "total_hits",
    "result_count",
    "doc_count",
    "token_count",
    "corpus_tokens",
    "n_tokens",
)

# Konservative Allowlist: eine Jahreszahl ist nur dann harmlos, wenn die
# Evidenz Datums-Metadaten zeigt UND der Kontext temporal ist. Alles andere
# muss binden (lieber einmal zu viel binden).
_YEAR_TOKEN_PATTERN = re.compile(r"(?:19|20)\d{2}")
_DATE_METADATA_PATTERN = re.compile(
    r"\b(?:date_field|granularity|periods_total|date|datum|year|jahr)\s*[=:]",
    re.IGNORECASE,
)
_TEMPORAL_CUE_PATTERN = re.compile(
    r"(?:\bjahr(?:e|es|en)?|\bseit|\bvon|\bbis|\bab|\bzwischen|"
    r"\bzeitraum|\bperiode(?:n)?|\bjahrgang)\s*$",
    re.IGNORECASE,
)
_YEAR_RANGE_BEFORE_PATTERN = re.compile(
    r"(?:19|20)\d{2}\s*(?:-|–|bis)\s*$",
    re.IGNORECASE,
)
_YEAR_RANGE_AFTER_PATTERN = re.compile(
    r"^\s*(?:-|–|bis)\s*(?:19|20)\d{2}",
    re.IGNORECASE,
)
_PERCENT_SUFFIX_PATTERN = re.compile(r"\s*(?:%|prozent)", re.IGNORECASE)


def reference_syntax_help() -> str:
    """Describe reference paths for the system prompt.

    Container paths depend on the tool. Flat query_count results use
    ``ev1.total``, while table rows require their actual container path.
    The evidence surface labels rows with paths that the model can copy.
    """

    return (
        "Zahlen und Zitate nie frei formulieren, sondern referenzieren: "
        "{{ev:ID}} fuer den Primaerwert oder als Fakt-Zitation, "
        "{{ev:ID.feld}} fuer ein Feld. Jede Zeile der Evidenzoberflaeche "
        "traegt ihren Pfad, also abschreiben statt raten: rows[i], "
        "periods[i], tables.<rel>[i], values.<feld>[i], jeweils ab 0. Flache "
        "Ergebnisse wie query_count haben keinen Container, dort gilt "
        "{{ev:ID.total}} direkt. Unaufloesbare Referenzen werden als "
        "'[Beleg fehlt]' sichtbar."
    )


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def _index_evidence(
    evidence_bundle: Any,
    facts: Sequence[Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], List[str]]:
    """Gibt (items_by_id, facts_by_id, bundle_surface_lines) zurueck."""

    items_by_id: Dict[str, Dict[str, Any]] = {}
    bundle_surface: List[str] = []
    bundle = _as_mapping(evidence_bundle) if evidence_bundle is not None else {}
    for line in bundle.get("grounding_surface") or []:
        if str(line or "").strip():
            bundle_surface.append(str(line))
    for raw_item in bundle.get("items") or []:
        item = _as_mapping(raw_item)
        item_id = str(item.get("id") or "").strip()
        if item_id:
            items_by_id[item_id] = item
    facts_by_id: Dict[str, Dict[str, Any]] = {}
    for raw_fact in facts or ():
        fact = _as_mapping(raw_fact)
        fact_id = str(fact.get("id") or "").strip()
        if fact_id:
            facts_by_id[fact_id] = fact
    return items_by_id, facts_by_id, bundle_surface


def _evidence_surface_text(
    items_by_id: Dict[str, Dict[str, Any]],
    facts_by_id: Dict[str, Dict[str, Any]],
    bundle_surface: Sequence[str],
) -> str:
    lines: List[str] = list(bundle_surface)
    for item in items_by_id.values():
        for line in item.get("grounding_surface") or []:
            if str(line or "").strip():
                lines.append(str(line))
    for fact in facts_by_id.values():
        statement = str(fact.get("statement") or "").strip()
        if statement:
            lines.append(statement)
        for quote in fact.get("grounding_quotes") or []:
            if str(quote or "").strip():
                lines.append(str(quote))
    return "\n".join(lines)


def _match_known_id(ref: str, known_ids: Sequence[str]) -> str:
    """Laengster ID-Praefix, an einer Pfadgrenze ('.' oder '[') endend."""

    best = ""
    for known in known_ids:
        if not known or len(known) < len(best):
            continue
        if ref == known or (
            ref.startswith(known)
            and len(ref) > len(known)
            and ref[len(known)] in ".["
        ):
            best = known
    return best


def _parse_path(path: str) -> List[Tuple[str, Any]] | None:
    segments: List[Tuple[str, Any]] = []
    pos = 0
    while pos < len(path):
        match = _PATH_TOKEN_PATTERN.match(path, pos)
        if match is None:
            return None
        if match.group(1) is not None:
            segments.append(("key", match.group(1)))
        else:
            segments.append(("idx", int(match.group(2))))
        pos = match.end()
    return segments


def _navigate(root: Any, segments: Sequence[Tuple[str, Any]]) -> Tuple[bool, Any]:
    current = root
    for kind, key in segments:
        if kind == "key":
            if not isinstance(current, dict) or key not in current:
                return False, None
            current = current[key]
        else:
            if not isinstance(current, (list, tuple)) or not (
                0 <= key < len(current)
            ):
                return False, None
            current = current[key]
    if current is None:
        return False, None
    return True, current


def _normalise_cell_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _format_number(value: Any) -> str | None:
    """Zahlformatierung, fuer Ganzzahlen byte-identisch zum Markdown-Builder
    (grounding_markdown._analysis_provenance_lines._number: Tausenderpunkt).

    In an English answer (candyconc/answer_language.py) the comma groups: an
    English reader takes "49.536" for 49.5.
    """

    grenze = "," if is_english() else "."
    if isinstance(value, bool):
        return yes_no(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", grenze)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 10**15:
            return f"{int(value):,}".replace(",", grenze)
        return str(value)
    return None


def _format_scalar(value: Any) -> str:
    number = _format_number(value)
    if number is not None:
        return number
    if isinstance(value, str):
        return _normalise_cell_text(value)
    return _compact_text(value, 60)


def _looks_like_kwic_row(value: Dict[str, Any]) -> bool:
    return ("kw" in value or "word" in value) and (
        "left" in value or "right" in value
    )


def format_evidence_value(
    value: Any,
    *,
    source_id: str = "",
    row_index: int | None = None,
) -> str:
    """Deterministische, nutzerlesbare Formatierung eines Evidenz-Werts."""

    number = _format_number(value)
    if number is not None:
        return number
    if isinstance(value, str):
        return _normalise_cell_text(value)
    if isinstance(value, dict):
        if _looks_like_kwic_row(value):
            text = " ".join(
                part
                for part in (
                    _normalise_cell_text(value.get("left")),
                    _normalise_cell_text(value.get("kw") or value.get("word")),
                    _normalise_cell_text(value.get("right")),
                )
                if part
            )
            quote = _compact_text(text, 200)
            if source_id and row_index is not None:
                return f"„{quote}“ ({source_id}, Zeile {row_index})"
            if source_id:
                return f"„{quote}“ ({source_id})"
            return f"„{quote}“"
        rendered = ", ".join(
            f"{key}={_format_scalar(item_value)}"
            for key, item_value in value.items()
            if item_value not in (None, "", [], {})
        )
        return _compact_text(rendered, 220)
    if isinstance(value, (list, tuple)):
        rendered = ", ".join(_format_scalar(entry) for entry in value[:20])
        return _compact_text(rendered, 220)
    return _compact_text(value, 220)


def _digitless(value: str) -> str:
    """Schattenform eines eingesetzten Werts: gleiche Laenge, keine Ziffern.

    Nur Ziffern werden ersetzt, Whitespace und Interpunktion bleiben, damit
    alle nachgelagerten Bereinigungs-Regexe auf Real- und Schattentext
    identisch matchen und die Offsets beider Strings synchron bleiben.
    """

    return re.sub(r"\d", "x", value)


# Gruppierungszeichen (Tausenderpunkt, ASCII-/schmales/geschuetztes Leerzeichen,
# Komma) einer Zahl, damit "18.761" und "18 761" dieselbe Ziffernfolge liefern.
_GROUPING_CHARS = re.compile(r"[.,\s]")
_TRAILING_NUMBER = re.compile(r"[\d.,\s]+$")

# Schliessende Zeichen, die zwischen dem bereits genannten Wert und dem Marker
# stehen koennen ("nach `score_key = logdice` {{ev:...}}", "„32“ {{ev:...}}",
# R7/A2). H8 (hold_assoz_merkel, "Treffer: 98, 98"): auch Satzzeichen
# (Komma, Semikolon, Doppelpunkt) trennen Wert und Marker ("98, {{ev:...}}").
# Sie werden fuer den Doppelungs-Vergleich zusammen mit Whitespace vom
# Tail-Ende gestrippt; die Wortgrenzen-Pruefung auf dem gestrippten Tail
# bleibt unveraendert ("...xlogdice`" dedupliziert weiterhin NICHT, und
# "12, {{ev:...}}" mit Wert 98 dedupliziert nicht, der Tail endet auf 12).
_TAIL_CLOSING_CHARS = "`'\"“”‘’«»‹›)]},;:"
_TAIL_STRIP_CHARS = _TAIL_CLOSING_CHARS + " \t\r\n\u00a0\u202f"


def _grouping_stripped(value: str) -> str:
    return _GROUPING_CHARS.sub("", value)


def _value_already_stated(prefix: str, value: str) -> bool:
    """Steht ``value`` bereits unmittelbar vor dem Marker im Modelltext?

    Der kanonische Antwortstil schreibt den Wert und setzt den Marker DIREKT
    dahinter (``"212 Treffer {{ev:ev1.total}}"``, prompt_layout). Ein erneutes
    Einsetzen wuerde den Wert verdoppeln (``"683 683"``, ``"18.761 18 761"``,
    ``"test, train test, train"``). Ist der Wert schon da, rendert der Marker
    als Zitation statt als zweite Kopie. Vergleich ist gruppierungs-tolerant,
    damit unterschiedliche Tausendertrennung nicht auseinanderlaeuft, und
    casefold-tolerant, damit Schreibvarianten wie "logDice" vs. "logdice"
    nicht verdoppeln (H6/B5). Schliessende Zeichen zwischen Wert und Marker
    (Backtick, Anfuehrungszeichen, Klammern, seit H8 auch Komma, Semikolon
    und Doppelpunkt) werden vor dem Vergleich vom Tail-Ende gestrippt, damit
    auch "nach `score_key = logdice`", "„32“" und "Treffer: 98," als bereits
    genannt erkannt werden (R7/A2, H8 "98, 98"); die Wortgrenzen-Pruefung
    auf dem gestrippten Tail bleibt bestehen ("12, {{ev:...}}" mit Wert 98
    dedupliziert nicht).
    """

    tail = prefix.rstrip().rstrip(_TAIL_STRIP_CHARS)
    stated = value.strip()
    if not tail or not stated:
        return False
    # Text-/Listenwerte (z.B. "test, train") exakt am Wortende vergleichen,
    # casefold-tolerant, aber weiterhin mit Wortgrenzen-Pruefung.
    tail_cf = tail.casefold()
    stated_cf = stated.casefold()
    if tail_cf == stated_cf or (
        tail_cf.endswith(stated_cf)
        and not tail_cf[len(tail_cf) - len(stated_cf) - 1].isalnum()
    ):
        return True
    # Zahlen gruppierungs-tolerant: nur wenn der Wert eine reine Ziffernfolge
    # ist, sonst greift der Textpfad oben (keine False Positives auf Teilzahlen).
    normalised = _grouping_stripped(stated)
    if normalised.isdigit():
        trailing = _TRAILING_NUMBER.search(tail)
        if trailing and _grouping_stripped(trailing.group(0)) == normalised:
            return True
    # Auch wenn der exakte Vergleich scheitert: hat der Modelltext denselben
    # Wert GERUNDET geschrieben, ist er bereits genannt.
    #
    # Der Pfad muss auch nach der Ziffernpruefung erreichbar sein. Ein
    # Dezimalwert wie 4362.29273365558 sieht nach _grouping_stripped wie
    # eine reine Ziffernfolge aus, weil der Punkt im Deutschen gruppiert.
    # Die erste Fassung stellte die Rundungspruefung deshalb hinter ein
    # "if not normalised.isdigit()" und erreichte sie nie.
    return _ist_gerundete_wiedergabe(tail, stated)


def _ist_gerundete_wiedergabe(tail: str, wert: str) -> bool:
    """Hat der Modelltext denselben Wert nur GERUNDET geschrieben?

    LIVE am 2026-09-01. Das Modell schrieb "4362,3", die Evidenz traegt
    4362.29273365558. Der Vergleich war exakt, erkannte die Rundung nicht
    als bereits genannt, und die Antwort las sich

        „sondern" in KI-Fassungen 4362,3 4362.29273365558 pmw

    Ein Wert, zweimal, einmal lesbar und einmal roh. Die Regel im Prompt
    ("Marker DIREKT hinter den Wert") war eingehalten, nur die Pruefung
    dahinter kannte keine Rundung.

    GEPRUEFT WIRD DIE RUNDUNG SELBST, nicht die Naehe: der Evidenzwert
    wird auf so viele Nachkommastellen gerundet, wie der Modelltext
    schreibt, und muss dann exakt uebereinstimmen. Damit passiert eine
    FALSCHE Zahl weiterhin nicht: wer 4400 schreibt, bekommt den echten
    Wert danebengesetzt, und die Abweichung wird sichtbar. Genau dafuer
    ist die Wache da.
    """
    letzte = _TRAILING_NUMBER.search(tail)
    if not letzte:
        return False
    geschrieben = letzte.group(0).strip().strip(",;:")
    if not geschrieben:
        return False
    try:
        roh = float(str(wert).replace(",", "."))
    except (TypeError, ValueError):
        return False
    # BEIDE LESARTEN, statt eine zu raten. "4362,3" ist deutsch drei Zehntel,
    # "18.761" ist deutsch achtzehntausend und englisch achtzehn Komma sieben.
    # Wer sich fuer eine Konvention entscheidet, liegt bei der anderen falsch,
    # und die Antwort traegt beide: Modelltext deutsch, Evidenzwert englisch.
    for lesart in _zahllesarten(geschrieben):
        gezeigt, stellen = lesart
        if stellen <= 6 and round(roh, stellen) == gezeigt:
            return True
    return False


#: An English grouped number: 174,284 or 1,592.3.
_ENGLISCH_GRUPPIERT = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def _englisches_zahlwort(real: str, start: int, raw_token: str) -> "tuple[str, str] | None":
    """(written, canonical) for a number in English answer text, else None.

    English probe of 2026-09-27, run b1: "174,284" and "180,221" were listed
    as unsupported because the check read the comma as a decimal comma, and
    "log_ratio .85" gave the number 85. In English the comma groups
    thousands, and a dot without a digit before it starts a value below 1.
    """
    if _ENGLISCH_GRUPPIERT.fullmatch(raw_token):
        return raw_token, _normalize_number_token(raw_token.replace(",", ""))
    if (
        raw_token.isdigit()
        and start >= 1
        and real[start - 1] == "."
        and (start < 2 or not real[start - 2].isdigit())
    ):
        sign = real[start - 2] if start >= 2 and real[start - 2] in "+-" else ""
        return sign + "." + raw_token, _normalize_number_token(sign + "0." + raw_token)
    return None


def _zahllesarten(geschrieben: str) -> list[tuple[float, int]]:
    """Wert und Nachkommastellen je moeglicher Schreibung.

    Liefert (Wert, Stellen) fuer jede plausible Lesart. Eine unlesbare
    Schreibung liefert nichts, und nichts heisst: keine Uebereinstimmung.
    """
    heraus: list[tuple[float, int]] = []
    kandidaten: list[str] = []
    if is_english() and _ENGLISCH_GRUPPIERT.fullmatch(geschrieben):
        # English answer: the comma groups, the dot separates decimals
        # ("1,592.3", "174,284"). The German reading made 1.5923 of it.
        kandidaten.append(geschrieben.replace(",", ""))
    elif "," in geschrieben:
        # Komma trennt die Stellen, Punkte gruppieren.
        kandidaten.append(geschrieben.replace(".", "").replace(",", "."))
    elif is_english():
        # Without a comma a dot in English text is the decimal separator.
        kandidaten.append(geschrieben)
    else:
        # Ohne Komma ist ein Punkt entweder Gruppierung oder Dezimaltrenner.
        kandidaten.append(geschrieben.replace(".", ""))
        kandidaten.append(geschrieben)
    for kandidat in kandidaten:
        try:
            wert = float(kandidat)
        except (TypeError, ValueError):
            continue
        _, _, nachkomma = kandidat.partition(".")
        heraus.append((wert, len(nachkomma)))
    return heraus


def _eindeutige_kennung(ref_body: str, item_ids: Sequence[str]) -> Tuple[str, str]:
    """Resolve an alternative marker spelling when it identifies exactly one item.

    Evidence sequence numbers are unique across tools within a turn.
    Match IDs case-insensitively or by their sequence number, requiring one result.
    """
    teile = re.match(r"([^.\[]+)(.*)", str(ref_body or ""), re.S)
    if teile is None:
        return "", ref_body
    basis, pfad = teile.group(1).strip(), teile.group(2)
    gefaltet = basis.casefold()
    kandidaten = {
        kennung for kennung in item_ids
        if kennung.casefold() in (gefaltet, "e_" + gefaltet)
    }
    if not kandidaten and basis.isdigit():
        muster = re.compile(r"E_[A-Za-z][A-Za-z_]*?_" + basis)
        kandidaten = {kennung for kennung in item_ids if muster.fullmatch(kennung)}
    if len(kandidaten) != 1:
        return "", ref_body
    kennung = next(iter(kandidaten))
    return kennung, kennung + pfad


class _MarkerOutcome:
    __slots__ = ("status", "value", "source_id", "reason")

    def __init__(
        self,
        status: str,
        value: str = "",
        source_id: str = "",
        reason: str = "",
    ) -> None:
        self.status = status  # "value" | "citation" | "missing"
        self.value = value
        self.source_id = source_id
        self.reason = reason


def _resolve_marker(
    ref_body: str,
    items_by_id: Dict[str, Dict[str, Any]],
    facts_by_id: Dict[str, Dict[str, Any]],
) -> _MarkerOutcome:
    known_ids = list(items_by_id) + list(facts_by_id)
    target_id = _match_known_id(ref_body, known_ids)
    if not target_id and not ref_body.startswith("E_"):
        # Kandidat 4, Frage 6: {{ev:query_count_49}} ohne Praefix meint
        # eindeutig E_query_count_49 (test_evidence_marker_without_prefix).
        target_id = _match_known_id("E_" + ref_body, known_ids)
        ref_body = "E_" + ref_body if target_id else ref_body
    if not target_id:
        target_id, ref_body = _eindeutige_kennung(ref_body, list(items_by_id))
    if not target_id:
        return _MarkerOutcome("missing", reason="unbekannte Evidenz-ID")
    path = ref_body[len(target_id):]
    is_item = target_id in items_by_id
    target = items_by_id.get(target_id) or facts_by_id.get(target_id) or {}
    if not path:
        if is_item:
            raw_surface = target.get("raw_surface")
            if isinstance(raw_surface, dict):
                for key in _PRIMARY_SCALAR_KEYS:
                    if raw_surface.get(key) is not None:
                        return _MarkerOutcome(
                            "value",
                            value=format_evidence_value(
                                raw_surface[key],
                                source_id=target_id,
                            ),
                            source_id=target_id,
                        )
        # Fakt-Zitation oder Item ohne Primaerwert: Zitations-Semantik.
        return _MarkerOutcome("citation", source_id=target_id)
    segments = _parse_path(path)
    if segments is None:
        return _MarkerOutcome(
            "missing",
            source_id=target_id,
            reason=f"ungueltiger Referenz-Pfad '{path}'",
        )
    roots: List[Any]
    if is_item:
        from candyconc.candyconc_copilot.view_row_selection import zeilen_nach_pfad

        roots = [
            target,
            # Eine verteilte Auswahl nennt je Zeile ihren Pfad: rows[i] ist die i-te
            # Zeile des Werkzeugergebnisses, nicht die i-te der Sicht (view_row_selection).
            zeilen_nach_pfad(target.get("raw_surface")),
            target.get("fact_surface"),
            target.get("result_scope"),
        ]
    else:
        roots = [target]
    row_index: int | None = None
    for kind, key in segments:
        if kind == "idx":
            row_index = key
    for root in roots:
        if not isinstance(root, dict):
            continue
        found, value = _navigate(root, segments)
        if found:
            return _MarkerOutcome(
                "value",
                value=format_evidence_value(
                    value,
                    source_id=target_id,
                    row_index=row_index,
                ),
                source_id=target_id,
            )
    return _MarkerOutcome(
        "missing",
        source_id=target_id,
        reason="Pfad nicht in der Evidenz",
    )


def _substitute_markers(
    text: str,
    items_by_id: Dict[str, Dict[str, Any]],
    facts_by_id: Dict[str, Dict[str, Any]],
    resolved: List[Dict[str, str]],
    unresolved: List[str],
    messages: List[str],
) -> Tuple[str, str]:
    real_parts: List[str] = []
    shadow_parts: List[str] = []
    last = 0
    for match in EVIDENCE_REFERENCE_PATTERN.finditer(text):
        prefix = text[last : match.start()]
        real_parts.append(prefix)
        shadow_parts.append(prefix)
        marker = match.group(0)
        outcome = _resolve_marker(
            match.group(1).strip(),
            items_by_id,
            facts_by_id,
        )
        if outcome.status == "value":
            resolved.append(
                {
                    "ref": marker,
                    "value": outcome.value,
                    "source_id": outcome.source_id,
                    "kind": "value",
                }
            )
            # Hat der GERENDERTE Text den Wert direkt vor dem Marker schon
            # genannt, rendert der Marker als Zitation statt als zweite Kopie
            # (sonst "683 683" / "18.761 18 761" / "test, train test, train").
            # Verglichen wird das Ende von ''.join(real_parts), damit auch ein
            # zuvor vom Renderer EINGESETZTER Wert zaehlt ("{{ev:ev1.total}}
            # {{ev:ev2.total}}" mit gleichem Wert wurde sonst "40 40", H6/B5).
            rendered_tail = "".join(real_parts)[
                -(len(outcome.value) + 64):
            ]
            if _value_already_stated(rendered_tail, outcome.value):
                # Das Trennzeichen zum Marker faellt mit weg, damit kein
                # doppeltes Leerzeichen zurueckbleibt. Real und Schatten
                # werden identisch getrimmt, die Offsets bleiben synchron.
                trimmed = prefix.rstrip()
                real_parts[-1] = trimmed + _ENTFERNT
                shadow_parts[-1] = trimmed + _ENTFERNT
            else:
                real_parts.append(outcome.value)
                shadow_parts.append(_digitless(outcome.value))
        elif outcome.status == "citation":
            resolved.append(
                {
                    "ref": marker,
                    "value": "",
                    "source_id": outcome.source_id,
                    "kind": "citation",
                }
            )
            real_parts.append(_ENTFERNT)
            shadow_parts.append(_ENTFERNT)
        else:
            unresolved.append(marker)
            messages.append(
                f"Referenz {marker} konnte nicht aufgeloest werden"
                f" ({outcome.reason})."
            )
            real_parts.append(MISSING_EVIDENCE_PLACEHOLDER)
            shadow_parts.append(MISSING_EVIDENCE_PLACEHOLDER)
        last = match.end()
    real_parts.append(text[last:])
    shadow_parts.append(text[last:])
    return "".join(real_parts), "".join(shadow_parts)


def _normalise_cited_id(token: str) -> str:
    token = token.strip().lower()
    if not token.startswith("f"):
        token = f"f{token}"
    return token


def _strip_legacy_citations(
    real: str,
    shadow: str,
    items_by_id: Dict[str, Dict[str, Any]],
    facts_by_id: Dict[str, Dict[str, Any]],
    resolved: List[Dict[str, str]],
    unresolved: List[str],
    messages: List[str],
) -> Tuple[str, str]:
    """Entfernt Klartext-Fakt-Zitationen byte-identisch zum Legacy-Stripper.

    Die Matches werden auf dem Schattentext gesucht: eingesetzte Werte sind
    dort ziffernlos, daher kann das ``f\\d{3}``-Muster nie in einen vom
    Renderer eingesetzten Beleg hineingreifen.
    """

    matches = list(_INTERNAL_FACT_REFERENCE_PATTERN.finditer(shadow))
    if not matches:
        return real, shadow
    real_parts: List[str] = []
    shadow_parts: List[str] = []
    last = 0
    for match in matches:
        real_parts.append(real[last : match.start()])
        shadow_parts.append(shadow[last : match.start()])
        citation_text = real[match.start() : match.end()].strip()
        for token in _CITED_ID_PATTERN.findall(citation_text):
            cited_id = _normalise_cited_id(token)
            if cited_id in facts_by_id or cited_id in items_by_id:
                resolved.append(
                    {
                        "ref": citation_text,
                        "value": "",
                        "source_id": cited_id,
                        "kind": "citation",
                    }
                )
            else:
                unresolved.append(cited_id)
                messages.append(
                    f"Zitierte Fakt-ID {cited_id} existiert nicht in der"
                    " Evidenz."
                )
        real_parts.append(_ENTFERNT)
        shadow_parts.append(_ENTFERNT)
        last = match.end()
    real_parts.append(real[last:])
    shadow_parts.append(shadow[last:])
    return "".join(real_parts), "".join(shadow_parts)


def _sub_both(
    real: str,
    shadow: str,
    pattern: re.Pattern[str],
    group_replacement: int | None = None,
) -> Tuple[str, str]:
    """Wendet dieselben Ersetzungen positionsgleich auf beide Strings an.

    Die Matches werden auf dem Schattentext gesucht; die Ersetzung ist leer
    oder eine ziffernfreie Capture-Gruppe (in beiden Strings identisch), die
    Offsets bleiben daher synchron.
    """

    matches = list(pattern.finditer(shadow))
    if not matches:
        return real, shadow
    real_parts: List[str] = []
    shadow_parts: List[str] = []
    last = 0
    for match in matches:
        real_parts.append(real[last : match.start()])
        shadow_parts.append(shadow[last : match.start()])
        if group_replacement is not None:
            replacement = match.group(group_replacement) or ""
            real_parts.append(replacement)
            shadow_parts.append(replacement)
        last = match.end()
    real_parts.append(real[last:])
    shadow_parts.append(shadow[last:])
    return "".join(real_parts), "".join(shadow_parts)


def _sub_an_entfernung(
    real: str,
    shadow: str,
    pattern: re.Pattern[str],
    group_replacement: int | None = None,
) -> Tuple[str, str]:
    """Wie ``_sub_both``, aber nur Treffer, die eine Entfernungsmarke beruehren.

    Ein Treffer ohne Marke ist Text des Modells oder Korpustext und bleibt
    unveraendert. Ein entfernter Treffer hinterlaesst selbst eine Marke, damit
    der naechste Schritt ("Wert ( ) ." -> "Wert .") die Stelle noch kennt.
    """
    real_parts: List[str] = []
    shadow_parts: List[str] = []
    last = 0
    for match in pattern.finditer(shadow):
        davor = shadow[match.start() - 1 : match.start()] if match.start() else ""
        danach = shadow[match.end() : match.end() + 1]
        if _ENTFERNT not in match.group(0) and _ENTFERNT not in davor + danach:
            continue
        real_parts.append(real[last : match.start()])
        shadow_parts.append(shadow[last : match.start()])
        ersatz = _ENTFERNT
        if group_replacement is not None:
            ersatz = match.group(group_replacement) or ""
        real_parts.append(ersatz)
        shadow_parts.append(ersatz)
        last = match.end()
    real_parts.append(real[last:])
    shadow_parts.append(shadow[last:])
    return "".join(real_parts), "".join(shadow_parts)


def _cleanup_both(real: str, shadow: str) -> Tuple[str, str]:
    # Nur an den Stellen, an denen eine Marke oder Zitation entfernt wurde
    # (siehe _ENTFERNT). Der uebrige Text bleibt byte-gleich.
    real, shadow = _sub_an_entfernung(real, shadow, _DANGLING_DASH_AN_ENTFERNUNG)
    real, shadow = _sub_an_entfernung(real, shadow, _EMPTY_PARENS_AN_ENTFERNUNG)
    real, shadow = _sub_an_entfernung(
        real, shadow, _SPACE_BEFORE_PUNCT_AN_ENTFERNUNG, 1)
    real = real.replace(_ENTFERNT, "")
    shadow = shadow.replace(_ENTFERNT, "")
    lead = len(real) - len(real.lstrip())
    trail = len(real) - len(real.rstrip())
    end = len(real) - trail
    return real[lead:end], shadow[lead:end]


def _is_harmless_year(
    raw_token: str,
    real: str,
    start: int,
    end: int,
    has_date_metadata: bool,
) -> bool:
    if not has_date_metadata:
        return False
    if _YEAR_TOKEN_PATTERN.fullmatch(raw_token) is None:
        return False
    prefix = real[max(0, start - 24) : start]
    if _TEMPORAL_CUE_PATTERN.search(prefix):
        return True
    if _YEAR_RANGE_BEFORE_PATTERN.search(prefix):
        return True
    return _YEAR_RANGE_AFTER_PATTERN.match(real[end : end + 12]) is not None


#: Ein Belegchip, wie ``deutungs_synthese._verankere`` ihn setzt.
_BELEG_CHIP_PATTERN = re.compile(r"\[\[beleg:[^\]\n]*\]\]")


def _bare_number_findings(
    real: str,
    shadow: str,
    surface: str,
    allowed_numbers: set,
) -> List[Dict[str, str]]:
    # Evidence chip IDs are references, not numbers asserted by the answer.
    # Mask them at equal length in the shadow text to preserve offsets.
    shadow = _BELEG_CHIP_PATTERN.sub(lambda m: _digitless(m.group(0)), shadow)
    ordinal_spans = [
        match.span()
        for match in _MARKDOWN_LIST_ORDINAL_PATTERN.finditer(shadow)
    ]
    has_date_metadata = _DATE_METADATA_PATTERN.search(surface) is not None
    findings: List[Dict[str, str]] = []
    for match in _SIGNED_NUMBER_PATTERN.finditer(shadow):
        start, end = match.span()
        if any(start >= a and end <= b for a, b in ordinal_spans):
            continue
        raw_token = real[start:end]
        englisch = _englisches_zahlwort(real, start, raw_token) if is_english() else None
        if englisch is not None:
            raw_token, token = englisch
        else:
            token = _normalize_number_token(
                raw_token,
                integer_grouping=(not is_english() and "." in raw_token and "," not in raw_token)
                or _number_has_integer_grouping_context(real, match),
            )
        places = next((places for value, places in _zahllesarten(raw_token) if value == float(token)), 0)
        is_percent = _PERCENT_SUFFIX_PATTERN.match(real, end) is not None
        if is_percent:
            supported = _percent_token_is_supported(token, surface, decimal_places=places)
        else:
            supported = _numeric_token_is_supported(token, allowed_numbers, decimal_places=places)
        if supported:
            continue
        if _is_harmless_year(raw_token, real, start, end, has_date_metadata):
            continue
        context = " ".join(
            real[max(0, start - 48) : min(len(real), end + 48)].split()
        )
        finding = {"number": raw_token, "context": context}
        if is_percent:
            finding["unit"] = "percent"
        findings.append(finding)
    return findings


_TOKEN_DENOMINATOR_KEYS = (
    "denominator_tokens",
    "corpus_tokens",
    "token_count",
    "n_tokens",
)


def _unique_token_denominator_from_items(
    items_by_id: Dict[str, Dict[str, Any]],
) -> int | None:
    """Der EINE strukturelle Tokennenner aller Evidenz-Items, sonst None."""

    values: set[int] = set()
    for item in items_by_id.values():
        raw_surface = item.get("raw_surface")
        if not isinstance(raw_surface, dict):
            continue
        for key in _TOKEN_DENOMINATOR_KEYS:
            value = raw_surface.get(key)
            if value in (None, ""):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                values.add(parsed)
    if len(values) != 1:
        return None
    return values.pop()


def _pmw_row_counts_from_items(
    items_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, int]:
    """Casefold-Label -> f aus sichtbaren Evidenzzeilen (rows/tables).

    Konfligierende f-Werte fuer dasselbe Label werden verworfen (nicht
    eindeutig bestimmbar -> die Label-Zahl-Zahl-pmw-Form bleibt stumm).
    """

    counts: Dict[str, int] = {}
    conflicts: set[str] = set()

    def _note(label: Any, f_value: Any) -> None:
        key = str(label or "").strip().casefold()
        if not key:
            return
        try:
            parsed = int(f_value)
        except (TypeError, ValueError):
            return
        if key in counts and counts[key] != parsed:
            conflicts.add(key)
            return
        counts[key] = parsed

    def _scan_rows(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = row.get("word") if row.get("word") not in (None, "") else row.get("kw")
            if label in (None, "") or row.get("f") in (None, ""):
                continue
            _note(label, row.get("f"))

    for item in items_by_id.values():
        raw_surface = item.get("raw_surface")
        if not isinstance(raw_surface, dict):
            continue
        _scan_rows(raw_surface.get("rows"))
        tables = raw_surface.get("tables")
        if isinstance(tables, dict):
            for table_rows in tables.values():
                _scan_rows(table_rows)
    for key in conflicts:
        counts.pop(key, None)
    return counts


def resolve_references(
    text: str,
    evidence_bundle: Any = None,
    facts: Sequence[Any] = (),
    *,
    detect_bare_numbers: bool = True,
) -> Dict[str, Any]:
    """Loest Evidenz-Referenzen im Modelltext deterministisch auf.

    Ergebnis (API-Kontrakt):
        text          aufgeloester, bereinigter Text
        resolved      [{ref, value, source_id, kind: "value"|"citation"}]
        unresolved    [Marker bzw. zitierte IDs ohne Beleg]
        messages      menschenlesbare Meldungen zu unresolved
        bare_numbers  [{number, context}] ungebundene Zahlen (potentielle
                      Fabrikation; gebundene und harmlose Zahlen sind still)
        pmw_findings  [{fragment, f, pmw, expected_pmw, token_count}]
                      f/pmw-Paare derselben Entitaet, die dem eindeutigen
                      Tokennenner der Evidenz arithmetisch widersprechen
                      (H9/V3: die Zahl ist einzeln belegt, aber mit der
                      falschen Zeile verheiratet — Set-Membership allein
                      sieht das nicht). Jeder Befund erscheint zusaetzlich
                      in ``bare_numbers``, damit die bestehende
                      Fabrikations-Politik greift.

    Der Renderer entscheidet keine Politik: bare_numbers/unresolved sind
    Befunde, deren Behandlung (hart/beratend) der Severity-Split der
    Verifikationsschicht festlegt.
    """

    raw_text = str(text or "")
    items_by_id, facts_by_id, bundle_surface = _index_evidence(
        evidence_bundle,
        facts,
    )
    resolved: List[Dict[str, str]] = []
    unresolved: List[str] = []
    messages: List[str] = []
    real, shadow = _substitute_markers(
        raw_text,
        items_by_id,
        facts_by_id,
        resolved,
        unresolved,
        messages,
    )
    real, shadow = _strip_legacy_citations(
        real,
        shadow,
        items_by_id,
        facts_by_id,
        resolved,
        unresolved,
        messages,
    )
    real, shadow = _cleanup_both(real, shadow)
    bare_numbers: List[Dict[str, str]] = []
    pmw_findings: List[Dict[str, Any]] = []
    if detect_bare_numbers:
        surface = _evidence_surface_text(
            items_by_id,
            facts_by_id,
            bundle_surface,
        )
        allowed_numbers = set(_extract_numeric_tokens(surface, signed=True))
        bare_numbers = _bare_number_findings(
            real,
            shadow,
            surface,
            allowed_numbers,
        )
        # H9/V3 (a): ein f/pmw-Paar derselben Entitaet wird IMMER gegen die
        # selbst gerechnete Normalisierung geprueft (pmw = f/token_count*1e6),
        # statt die zweite Modellzahl allein per Set-Membership zu binden —
        # genau so entstand "Flüchtlinge 30 498.3 pmw" (f der einen, pmw der
        # Nachbarzeile). Nur bei eindeutigem Tokennenner, konservativ.
        token_count = _unique_token_denominator_from_items(items_by_id)
        if token_count is None:
            token_count = _unique_token_denominator([surface])
        if token_count is not None:
            pmw_findings = _pmw_pair_findings(
                real,
                token_count,
                row_counts=_pmw_row_counts_from_items(items_by_id),
            )
            flagged = {
                (entry.get("number"), entry.get("context"))
                for entry in bare_numbers
            }
            for finding in pmw_findings:
                messages.append(
                    "pmw-Widerspruch: '"
                    + str(finding["fragment"])
                    + f"', f={finding['f']} bei {finding['token_count']} "
                    f"Tokens ergibt {finding['expected_pmw']} pmw, "
                    f"nicht {finding['pmw']}."
                )
                key = (str(finding["pmw"]), str(finding["fragment"]))
                if key in flagged:
                    continue
                flagged.add(key)
                bare_numbers.append(
                    {
                        "number": str(finding["pmw"]),
                        "context": str(finding["fragment"]),
                        "reason": "pmw_inconsistent_with_count",
                    }
                )
    return {
        "text": real,
        "resolved": resolved,
        "unresolved": unresolved,
        "messages": messages,
        "bare_numbers": bare_numbers,
        "pmw_findings": pmw_findings,
    }
