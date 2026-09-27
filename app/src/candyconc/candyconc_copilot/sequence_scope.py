"""Describe the boundary within which a multi-position query is counted.

CQL sequences are sentence-scoped by default. An outer ``within(<doc>, ...)``
selects a document scope for the complete expression. Quoted word sequences
and NEAR queries use their own document-boundary rules.

Add scope information where tool results enter the orchestrator so the
model view, evidence surface and package use the same explanation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable

logger = logging.getLogger(__name__)

#: Werkzeuge, deren Ausgabe eine Zählung zur Abfrage ``query`` enthält.
ZAEHLWERKZEUGE = frozenset({"query_count", "run_cqlf_query"})

#: Punkt, Ausrufe- und Fragezeichen.
SATZSCHLUSSZEICHEN = (".", "!", "?")

IM_SATZ = "Folgen zählen innerhalb eines Satzes."
UEBER_SATZGRENZEN = "Über Satzgrenzen hinweg: within(<doc>, …)."
SATZSCHLUSS = (
    "Wo das Satzschlusszeichen vor der letzten Position den Satz schließt, trifft "
    "diese Folge deshalb nicht. Über die Satzgrenze: within(<doc>, {abfrage})"
)
WORTSUCHE = "Die Wortsuche zählt über Satz- und Dokumentgrenzen hinweg."
# Word sequences and NEAR queries stay within document boundaries through
# CorpusIndex._im_dokument and query_eval._near_im_dokument.
WORTFOLGE = "Die Wortfolge zählt über Satzgrenzen hinweg, nicht über Dokumentgrenzen."

#: Ein gewöhnliches Wort. Eine Zelle, die es trifft, ist ein Platzhalter wie
#: ``[word=".*"]`` und keine Zelle für ein Satzschlusszeichen.
_PROBEWORT = "und"


def _hoechstens(knoten: Any) -> float:
    """Wie viele Tokenpositionen ein Treffer höchstens belegt."""
    from cqlhpc.ast import Alt, Quant, Seq, Where, Within

    if isinstance(knoten, Seq):
        return sum(_hoechstens(teil) for teil in knoten.parts)
    if isinstance(knoten, Alt):
        return max((_hoechstens(teil) for teil in knoten.options), default=0)
    if isinstance(knoten, Quant):
        return float("inf") if knoten.n is None else _hoechstens(knoten.node) * knoten.n
    if isinstance(knoten, (Where, Within)):
        return _hoechstens(knoten.node)
    return 1


def _mindestens(knoten: Any) -> float:
    """Wie viele Tokenpositionen ein Treffer mindestens belegt."""
    from cqlhpc.ast import Alt, Quant, Seq, Where, Within

    if isinstance(knoten, Seq):
        return sum(_mindestens(teil) for teil in knoten.parts)
    if isinstance(knoten, Alt):
        return min((_mindestens(teil) for teil in knoten.options), default=0)
    if isinstance(knoten, Quant):
        return _mindestens(knoten.node) * knoten.m
    if isinstance(knoten, (Where, Within)):
        return _mindestens(knoten.node)
    return 1


def _nimmt(bedingung: Any, form: str) -> bool:
    r"""Trifft die Bedingung ein Token der Form ``form``?

    Wie die Maschine (cqlhpc/predicates.py): ``=`` liest einen Wert mit
    unmaskierten Metazeichen als Muster über das ganze Token, sonst wörtlich,
    ``\.`` also als Punkt. ``in`` vergleicht wörtlich, ``~`` immer als Muster,
    ``%c`` faltet.
    """
    from cqlhpc.predicates import _value_has_regex_metachars

    faltet = "c" in str(getattr(bedingung, "flags", "") or "")

    def woertlich(wert: Any) -> bool:
        klar = re.sub(r"\\(.)", r"\1", str(wert))
        return klar.casefold() == form.casefold() if faltet else klar == form

    def muster(wert: Any) -> bool:
        try:
            return re.fullmatch(("(?i)" if faltet else "") + str(wert), form) is not None
        except re.error:
            return False

    wert = bedingung.value
    if bedingung.op == "in":
        return any(woertlich(teil) for teil in (wert or ()))
    if bedingung.op == "~":
        return muster(wert)
    if bedingung.op in ("=", "!="):
        gleich = muster(wert) if _value_has_regex_metachars(str(wert)) else woertlich(wert)
        return gleich if bedingung.op == "=" else not gleich
    return False


def _satzschlusszelle(knoten: Any) -> bool:
    """Steht der Knoten für ein Satzschlusszeichen und für kein gewöhnliches Wort?"""
    from cqlhpc.ast import Alt, Quant, Tok

    if isinstance(knoten, Quant):
        return knoten.m >= 1 and _satzschlusszelle(knoten.node)
    if isinstance(knoten, Alt):
        return bool(knoten.options) and all(_satzschlusszelle(o) for o in knoten.options)
    if not isinstance(knoten, Tok):
        return False
    bedingungen = [b for b in knoten.clause.conds if b.attr in ("word", "lemma")]
    if not any(b.op in ("=", "in", "~") for b in bedingungen):
        return False

    def nimmt_alle(form: str) -> bool:
        return all(_nimmt(b, form) for b in bedingungen)

    return any(nimmt_alle(z) for z in SATZSCHLUSSZEICHEN) and not nimmt_alle(_PROBEWORT)


def _satzschluss_vor_dem_ende(teile: Iterable[Any]) -> bool:
    """Folgt auf eine Satzschlusszelle noch mindestens eine Pflichtposition?"""
    teile = list(teile)
    return any(
        _satzschlusszelle(teil) and sum(_mindestens(t) for t in teile[i + 1:]) >= 1
        for i, teil in enumerate(teile)
    )


def _wortsuche(form: str) -> str:
    """``WORTSUCHE`` für eine Wortfolge in Anführungszeichen oder NEAR, sonst ""."""
    from candyconc.domain.query_parser import Near, Term, parse_query

    offen = [parse_query(form)]
    while offen:
        knoten = offen.pop()
        if isinstance(knoten, Near) or (isinstance(knoten, Term) and " " in knoten.value):
            return WORTFOLGE
        offen.extend(
            kind
            for kind in (getattr(knoten, f, None) for f in ("node", "left", "right", "head", "dep"))
            if kind is not None
        )
    return ""


def folgenbereich(abfrage: Any, treffer: Any = None) -> str:
    """Die Angabe ``bereich`` zu einer erfolgreichen Zählung von ``abfrage``, oder "".

    Leer bleibt sie für eine einzelne Position und für eine Abfrage, die ihren
    Bereich mit ``within`` außen selbst wählt. Den Satzschluss nennt sie nur bei
    0 Treffern, denn nur dort ist die Satzgrenze die Erklärung, nach der das
    Modell sucht.
    """
    text = str(abfrage or "").strip()
    if not text:
        return ""
    from candyconc.core.cql_macros import normalize_query_input
    from candyconc.utils.text_normalize import normalize_text_basic

    form = normalize_query_input(normalize_text_basic(text))
    if not form.lower().startswith("cql:"):
        return _wortsuche(form)
    from cqlhpc.ast import Seq, Where, Within
    from cqlhpc.normalize import normalize
    from cqlhpc.parser import parse_cql

    innen = normalize(parse_cql(form[4:].strip()))
    while isinstance(innen, (Where, Within)):
        if isinstance(innen, Within):
            return ""
        innen = innen.node
    if _hoechstens(innen) <= 1:
        return ""
    null = isinstance(treffer, int) and not isinstance(treffer, bool) and treffer == 0
    if null and isinstance(innen, Seq) and _satzschluss_vor_dem_ende(innen.parts):
        cql = re.sub(r"(?i)^cql:\s*", "", text)
        return f"{IM_SATZ} {SATZSCHLUSS.format(abfrage=cql)}"
    return f"{IM_SATZ} {UEBER_SATZGRENZEN}"


def mit_folgenbereich(werkzeug: Any, ausgabe: Any) -> Any:
    """Die Ausgabe mit ``bereich`` direkt hinter ``total``, sonst unverändert."""
    if (
        str(werkzeug or "") not in ZAEHLWERKZEUGE
        or not isinstance(ausgabe, dict)
        or str(ausgabe.get("status") or "success") != "success"
        or "bereich" in ausgabe
    ):
        return ausgabe
    try:
        angabe = folgenbereich(ausgabe.get("query"), ausgabe.get("total"))
    except Exception:  # noqa: BLE001 - die Angabe ist eine Zugabe und stürzt keinen Aufruf
        logger.debug("Folgenbereich nicht bestimmbar", exc_info=True)
        return ausgabe
    if not angabe:
        return ausgabe
    angereichert: Dict[str, Any] = {}
    for schluessel, wert in ausgabe.items():
        angereichert[schluessel] = wert
        if schluessel == "total":
            angereichert["bereich"] = angabe
    angereichert.setdefault("bereich", angabe)
    return angereichert
