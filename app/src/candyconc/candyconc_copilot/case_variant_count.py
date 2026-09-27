# -*- coding: utf-8 -*-
"""Expose spelling variants omitted by a case-sensitive CQL count.

For word and lemma cells without a flag, repeat the same query with ``%c``.
Report the additional count only when it differs from the original count.
This makes sentence-initial capitalization visible alongside the query result.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

#: Eine Wort- oder Lemmazelle mit einem einzigen Wert und ohne Flag.
_ZELLE = re.compile(r'\[(\s*(?:word|lemma)\s*=\s*"[^"\]]*")\s*\]')


def mit_c(query: str) -> Optional[str]:
    """Dieselbe CQL-Abfrage mit ``%c`` an jeder Zelle ohne Flag, oder None."""
    text = str(query or "")
    kopf, rumpf = (text[:4], text[4:]) if text[:4].lower() == "cql:" else ("", text)
    if "[" not in rumpf:
        return None
    neu = _ZELLE.sub(lambda m: "[" + m.group(1) + "%c]", rumpf)
    return kopf + neu if neu != rumpf else None


# Alternative spellings introduced by the German spelling reform.
# Count both spellings so that a contrast does not depend on spelling period.
_REFORM = (
    (re.compile(r"ß"), "ss"),
    (re.compile(r"ss(?=$|[^aeiouyäöü])"), "ß"),
    (re.compile(r"ntiell"), "nziell"), (re.compile(r"nziell"), "ntiell"),
    (re.compile(r"ntial"), "nzial"), (re.compile(r"nzial"), "ntial"),
)
#: Ein Zellwert, der nur aus einem Wort besteht, wahlweise mit (?i) und .*.
_WORTWERT = re.compile(r'^(\(\?i\))?([A-Za-zÄÖÜäöüß-]+)(\.\*)?$')
_WERTZELLE = re.compile(r'(\[\s*(?:word|lemma)\s*=\s*")([^"\]]*)(")')


def _reformiert(wort: str) -> str:
    for muster, ersatz in _REFORM:
        neu = muster.sub(ersatz, wort)
        if neu != wort:
            return neu
    return wort


def andere_schreibung(query: str) -> Optional[str]:
    """Dieselbe Abfrage in der anderen Schreibung der Reform, oder None."""
    text = str(query or "")
    kopf, rumpf = (text[:4], text[4:]) if text[:4].lower() == "cql:" else ("", text)
    if "[" not in rumpf:
        worte = rumpf.split()
        if not worte or not all(re.fullmatch(r"[A-Za-zÄÖÜäöüß-]+", w) for w in worte):
            return None
        neu = " ".join(_reformiert(w) for w in worte)
        return kopf + neu if neu != " ".join(worte) else None

    def _zelle(m: "re.Match[str]") -> str:
        wert = _WORTWERT.match(m.group(2))
        if not wert:
            return m.group(0)
        return m.group(1) + (wert.group(1) or "") + _reformiert(wert.group(2)) + (wert.group(3) or "") + m.group(3)

    neu = _WERTZELLE.sub(_zelle, rumpf)
    return kopf + neu if neu != rumpf else None


def hinweis(query: str, total: int, zaehle: Callable[[str], int]) -> Dict[str, Any]:
    """``mit_c``, wenn ``%c`` eine andere Zahl ergibt, und ``andere_schreibung``,
    wenn die andere Schreibung der Reform im selben Bereich vorkommt."""
    ergebnis: Dict[str, Any] = {}
    for feld, variante in (("mit_c", mit_c(query)), ("andere_schreibung", andere_schreibung(query))):
        if variante is None:
            continue
        try:
            anders = int(zaehle(variante))
        except Exception:  # eine zu weite Regex-Zelle darf die Zählung nicht kippen
            continue
        if (feld == "mit_c" and anders != int(total)) or (feld == "andere_schreibung" and anders > 0):
            ergebnis[feld] = {"query": variante, "total": anders}
    return ergebnis
