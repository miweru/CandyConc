"""Gepaarte Claim-Evidenz-Bindung (H10/G2): term_result_mismatch.

Die historische Zahlenbindung ist Set-Membership: eine Zahl im Claim gilt
als belegt, sobald sie IRGENDWO in der zitierten Evidenz vorkommt. Der
Gutachter-Realfall zeigt die Luecke: "Fuer `der` sind keine Treffer belegt
(total=0)" wurde akzeptiert, obwohl die sichtbare Evidenz fuer 'der' f=917
auswies — die 0 stammte aus einer ANDEREN Abfrage desselben Turns.

Dieses Modul bindet Term und Ergebnis GEPAART: ein Claim, der Term T
explizit mit Ergebnis N verknuepft ("T hat/liefert N Treffer",
"fuer T ... total=N", auch negativ "keine Treffer fuer T"), muss gegen die
Evidenzzeile MIT Term/Query == T aufloesen. Widerspricht die Evidenz fuer T
(anderes Ergebnis), ist das ein direkter, exakt gepruefter
Evidenz-Widerspruch => HARTE Regel (Klasse (d) der Severity-Politik, wie
``metadata_values_are_falsely_absent``, generalisiert auf
query_count-/KWIC-/frequency-Ergebnisse).

Konservativ per Bauart (Muster ``_metadata_values_falsely_absent_fields``):
- Der Term muss im Claim markiert sein (Backticks oder Anfuehrungszeichen)
  und die Zahl muss im SELBEN Satz eindeutig als Ergebnis gelesen werden
  (``total=N`` / "N Treffer" / "keine Treffer").
- Genau EIN gebundener Term im Satz; zwei markierte Terme mit Bindung
  machen die Zuordnung mehrdeutig => kein Befund.
- Die Evidenz fuer T muss EINDEUTIG sein: mehrere verschiedene Ergebnisse
  fuer T (z. B. global vs. docset-lokal) => kein Befund.
- Widersprechen sich die Zahlen im Claim-Satz selbst => kein Befund.
"""

from __future__ import annotations

import re
from typing import Dict, List, Mapping, Sequence, Set, Tuple

from ..grounding_schemas import ObservedFact


# ----------------------------------------------------------------------- #
# Evidenzseite: Term->Ergebnis-Bindungen aus den deterministischen Fakten.
# Die Muster spiegeln die Statement-Renderer in ``grounding_facts``
# (_query_count_facts, _kwic_facts, _frequency_row_facts) wortgetreu.
# ----------------------------------------------------------------------- #
_QUERY_COUNT_STATEMENT_PATTERN = re.compile(
    r"'(?P<term>[^']+)'\s*\(query_count\)\s*ist\s*total=(?P<n>\d+)"
)
_KWIC_TOTAL_STATEMENT_PATTERN = re.compile(
    r"CQLF-Abfrage\s+'(?P<term>[^']+)'\s+hat\s+total=(?P<n>\d+)"
)
_FREQUENCY_ROW_STATEMENT_PATTERN = re.compile(
    r"Frequenzzeile[^.]*?\bzeigt\s+(?:die\s+handleartige\s+Form\s+)?"
    r"'(?P<term>[^']+)'.*?\bmit\s+f=(?P<n>\d+)",
    re.DOTALL,
)
_QUOTE_TOTAL_PATTERN = re.compile(r"^total=(?P<n>\d+)$")
_QUOTE_QUERY_PATTERN = re.compile(r"^query=(?P<term>.+)$")
# Einfache Ein-Token-CQL-Literale ([word="X"], optional cql:-Prefix und
# Casefold-Flag) zusaetzlich unter ihrem Literal registrieren, damit der
# Claim-Term `X` gegen die Query [word="X"] aufloest.
_SIMPLE_CQL_LITERAL_PATTERN = re.compile(
    r'^\s*(?:cql:)?\s*\[\s*(?:word|lemma)\s*=\s*"(?P<literal>[^"]+)"\s*'
    r"(?:%c|%d)?\s*\]\s*$",
    re.IGNORECASE,
)


def _register_binding(
    bindings: Dict[str, Set[int]], term: str, value: int
) -> None:
    term_key = str(term or "").strip()
    if not term_key:
        return
    bindings.setdefault(term_key, set()).add(int(value))
    literal = _SIMPLE_CQL_LITERAL_PATTERN.match(term_key)
    if literal:
        inner = literal.group("literal").strip()
        if inner:
            bindings.setdefault(inner, set()).add(int(value))


def _term_result_bindings(
    facts: Sequence[ObservedFact],
) -> Dict[str, Set[int]]:
    """Alle Term->Ergebnis-Paare, die die Evidenz mit Provenienz ausweist."""

    bindings: Dict[str, Set[int]] = {}
    for fact in facts:
        statement = str(getattr(fact, "statement", "") or "")
        for pattern in (
            _QUERY_COUNT_STATEMENT_PATTERN,
            _KWIC_TOTAL_STATEMENT_PATTERN,
            _FREQUENCY_ROW_STATEMENT_PATTERN,
        ):
            for match in pattern.finditer(statement):
                _register_binding(
                    bindings, match.group("term"), int(match.group("n"))
                )
        # Quote-Provenienz (H10/G2): ein Fakt, dessen Zitate GENAU EIN
        # total= und GENAU EIN query= tragen, bindet dieses Paar.
        totals: List[int] = []
        queries: List[str] = []
        for quote in getattr(fact, "grounding_quotes", None) or []:
            quote_text = str(quote or "").strip()
            total_match = _QUOTE_TOTAL_PATTERN.match(quote_text)
            if total_match:
                totals.append(int(total_match.group("n")))
                continue
            query_match = _QUOTE_QUERY_PATTERN.match(quote_text)
            if query_match:
                queries.append(query_match.group("term").strip())
        if len(totals) == 1 and len(queries) == 1:
            _register_binding(bindings, queries[0], totals[0])
    return bindings


# ----------------------------------------------------------------------- #
# Claim-Seite: markierter Term + Ergebnis-Lexem im selben Satz.
# ----------------------------------------------------------------------- #
_CLAIM_TERM_SPAN_PATTERN = re.compile(
    "|".join(
        (
            r"`(?P<backtick>[^`\n]+)`",
            r"„(?P<lowquote>[^“”\n]+)[“”]",
            r"‚(?P<singlelow>[^‘’\n]+)[‘’]",
            r"'(?P<plain>[^'\n]+)'",
            r"‘(?P<curly>[^’\n]+)’",
        )
    )
)
_CLAIM_TOTAL_EQ_PATTERN = re.compile(r"\btotal\s*=\s*(\d+)")
_CLAIM_N_TREFFER_PATTERN = re.compile(r"\b(\d+)\s+Treffer(?:n|zeilen)?\b", re.IGNORECASE)
_CLAIM_KEINE_TREFFER_PATTERN = re.compile(
    r"\bkeine(?:rlei)?\s+(?:einzigen?\s+)?Treffer\b", re.IGNORECASE
)
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?;:])\s+")


def _claim_marked_terms(sentence: str) -> List[str]:
    """In Backticks/Anfuehrungen markierte Kurz-Terme (<=3 Tokens)."""

    terms: List[str] = []
    for match in _CLAIM_TERM_SPAN_PATTERN.finditer(sentence):
        span = next(
            (value for value in match.groupdict().values() if value), ""
        ).strip()
        if not span or len(span) > 40 or "=" in span:
            continue
        if len(span.split()) > 3:
            # Laengere Anfuehrungs-Spannen sind Zitate (H2-Domaene), keine
            # Term-Marker.
            continue
        terms.append(span)
    return list(dict.fromkeys(terms))


def _claimed_result_values(sentence: str) -> Set[int]:
    values: Set[int] = set()
    for match in _CLAIM_TOTAL_EQ_PATTERN.finditer(sentence):
        values.add(int(match.group(1)))
    for match in _CLAIM_N_TREFFER_PATTERN.finditer(sentence):
        values.add(int(match.group(1)))
    if _CLAIM_KEINE_TREFFER_PATTERN.search(sentence):
        values.add(0)
    return values


def _resolve_binding_values(
    bindings: Mapping[str, Set[int]], term: str
) -> Set[int] | None:
    if term in bindings:
        return bindings[term]
    # Casefold-Fallback nur bei eindeutiger Aufloesung.
    folded = term.casefold()
    candidates = [
        values
        for key, values in bindings.items()
        if key.casefold() == folded
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _claim_term_result_mismatches(
    claim_text: str,
    bindings: Mapping[str, Set[int]],
) -> List[Tuple[str, int, int]]:
    """(Term, behauptetes Ergebnis, Evidenz-Ergebnis) je widerlegtem Satz."""

    if not bindings:
        return []
    mismatches: List[Tuple[str, int, int]] = []
    for sentence in _SENTENCE_SPLIT_PATTERN.split(str(claim_text or "")):
        marked_terms = _claim_marked_terms(sentence)
        if not marked_terms:
            continue
        bound = [
            (term, _resolve_binding_values(bindings, term))
            for term in marked_terms
        ]
        bound = [(term, values) for term, values in bound if values]
        if len(bound) != 1:
            # Kein oder mehr als ein evidenzgebundener Term im Satz:
            # die Paarung waere mehrdeutig, kein Befund.
            continue
        term, evidence_values = bound[0]
        if len(evidence_values) != 1:
            # Mehrere verschiedene Evidenz-Ergebnisse fuer T (z. B. global
            # vs. docset-lokal): nicht eindeutig zuordenbar, kein Befund.
            continue
        claimed = _claimed_result_values(sentence)
        if len(claimed) != 1:
            # Keine oder in sich widerspruechliche Ergebniszahlen im Satz.
            continue
        claimed_value = next(iter(claimed))
        evidence_value = next(iter(evidence_values))
        if claimed_value != evidence_value:
            mismatches.append((term, claimed_value, evidence_value))
    return mismatches


def _vae_rule_term_result_mismatch(_vae_ctx):
    """H10/G2: gepaarte Bindung Term<->Ergebnis gegen die Evidenz fuer T.

    Liest die GESAMTE Faktenlage des Turns (``observed_facts``), nicht nur
    die vom Claim referenzierten Fakten: der Realfall zitiert gerade die
    Evidenz einer ANDEREN Abfrage. Helper werden defensiv aus dem Kontext
    gelesen (Monkeypatch-Seam) und fallen auf die Modul-Globals zurueck.
    """

    bindings_helper = _vae_ctx.get(
        "_term_result_bindings", _term_result_bindings
    )
    mismatch_helper = _vae_ctx.get(
        "_claim_term_result_mismatches", _claim_term_result_mismatches
    )
    claim = _vae_ctx["claim"]
    claim_reasons = _vae_ctx["claim_reasons"]
    all_facts = _vae_ctx.get("observed_facts") or _vae_ctx.get("facts") or []
    bindings = bindings_helper(all_facts)
    mismatches = mismatch_helper(claim.text, bindings)
    if mismatches:
        claim_reasons.append(
            "Der Claim verknüpft Terme mit Ergebniszahlen, die der Evidenz "
            "für genau diese Terme widersprechen: "
            + "; ".join(
                f"'{term}' behauptet {claimed}, Evidenz für '{term}' zeigt "
                f"{evidence}"
                for term, claimed, evidence in mismatches[:3]
            )
            + ". Ergebnisse anderer Abfragen dürfen nicht mit diesem Term "
            "verheiratet werden."
        )
    _vae_l = locals()
    for _vae_n in ("mismatches",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]
