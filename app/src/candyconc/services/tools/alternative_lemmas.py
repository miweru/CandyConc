# -*- coding: utf-8 -*-
"""What a lemma search silently misses, as a number instead of a warning.

On a TreeTagger-annotated parliamentary corpus of 273 million tokens:

    [lemma="Recht"]    finds 110,210 and misses  24,898
    [lemma="Doktor"]   finds     224 and misses 639,263

825 lemmas are affected. The cause is not an import fault: the gold
annotation follows the TreeTagger convention and writes ambiguous lemmas as
alternatives in ONE field, ``Recht|Rechte``, ``Doktor|Dr.``. A search for
the exact string ``Recht`` does not match these tokens.

WHY NO WARNING. A bare warning would be spec gaming. A sentence like "hits
may be missing" leaves the expert with the same uncertainty as before. This
module delivers the NUMBER instead: how many tokens lie in alternative
lemmas that contain the searched value, and which alternatives they are.

WHY THE SEARCH DOES NOT SIMPLY COUNT THEM. That would silently change the
semantics, with side effects. In a corpus of human and AI texts 269 lemmas
contain a vertical bar, and almost all of them are something else: the
marker ``|lbr|``, Markdown table rows ``|---|---|``, tokenisation remnants
such as ``altkatholisch|er``. Splitting blindly at ``|`` there lets
``[lemma="er"]`` match ``altkatholisch|er`` and turns an undercount into an
overcount. The split therefore applies only where ALL parts are non-empty
and word-like, and the result is REPORTED, not silently included. Whoever
sees both numbers can decide.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

#: Mehr Alternativen als das ist kein Lemma mehr, sondern eine Tabelle.
MAX_TEILE = 4

#: So viele Beispiele nennt der Bericht. Mehr liest niemand.
MAX_BEISPIELE = 5


def ist_alternativlemma(text: str) -> bool:
    """Traegt dieser Lexikoneintrag echte Lemma-Alternativen?

    ``Recht|Rechte`` ja. ``|lbr|`` nein, es hat leere Teile.
    ``|---|---|`` nein, aus demselben Grund und weil kein Teil wortartig
    ist. Ein einzelner Strich ohne Text nein.
    """
    roh = str(text or "")
    if "|" not in roh:
        return False
    teile = roh.split("|")
    if not (2 <= len(teile) <= MAX_TEILE):
        return False
    return all(t.strip() and any(z.isalnum() for z in t) for t in teile)


def teile(text: str) -> List[str]:
    """Die Alternativen eines Eintrags, oder er selbst."""
    if not ist_alternativlemma(text):
        return [str(text or "")]
    return [t.strip() for t in str(text).split("|")]


def unterzaehlung(idx: Any, lemma: str, *, attr: str = "lemma") -> Dict[str, Any]:
    """Wie viele Token eine exakte Lemma-Suche uebersieht.

    Rueckgabe immer mit denselben Feldern, damit ein Aufrufer sie ohne
    Fallunterscheidung rendern kann:

        exakt        Token, deren Lemma genau der gesuchte Wert ist
        zusaetzlich  Token in Alternativlemmata, die den Wert enthalten
        alternativen die betroffenen Lexikoneintraege, hoechstens fuenf

    ``zusaetzlich == 0`` heisst: die Suche uebersieht nichts, und das ist
    eine Auskunft, keine Leerstelle.
    """
    gesucht = str(lemma or "").strip()
    leer: Dict[str, Any] = {
        "exakt": 0, "zusaetzlich": 0, "alternativen": [], "lemma": gesucht,
    }
    if not gesucht:
        return leer
    try:
        import numpy as np

        from candyconc.core.fast_index_native import strings_for_ids

        lex = getattr(idx.fast_index.lexicons, attr, None)
        if lex is None:
            return leer
        anzahl = int(getattr(lex, "vocab_size", 0) or 0)
        if anzahl <= 1:
            return leer
        # Die nutzbaren Ids sind 1 bis vocab_size EINSCHLIESSLICH. Id 0 ist
        # reserviert und liefert nichts. Der erste Anlauf schrieb
        # arange(1, anzahl) und liess damit genau den LETZTEN Eintrag aus.
        # Auf einem Miniaturindex war das der gesuchte, und die Wache
        # meldete null Unterzaehlung bei fuenf uebersehenen Token.
        ids = np.arange(1, anzahl + 1, dtype=np.uint32)
        eintraege = strings_for_ids(lex.offsets, lex.strings_view, ids, True)
    except Exception:
        logger.debug("Alternativlemmata nicht ermittelbar", exc_info=True)
        return leer

    getroffen: List[int] = []
    betroffen: List[str] = []
    exakt_id = None
    for kennung, eintrag in zip(ids, eintraege):
        if eintrag == gesucht:
            exakt_id = int(kennung)
            continue
        if gesucht in teile(eintrag):
            getroffen.append(int(kennung))
            betroffen.append(eintrag)

    zaehler = _token_je_id(idx, attr, getroffen + ([exakt_id] if exakt_id else []))
    return {
        "lemma": gesucht,
        "exakt": int(zaehler.get(exakt_id, 0)) if exakt_id else 0,
        "zusaetzlich": int(sum(zaehler.get(k, 0) for k in getroffen)),
        "alternativen": betroffen[:MAX_BEISPIELE],
    }


def _token_je_id(idx: Any, attr: str, kennungen: List[int]) -> Dict[int, int]:
    """Tokenzahl je Lexikon-Id, ueber den vollen Korpus."""
    if not kennungen:
        return {}
    try:
        import numpy as np

        from candyconc.services.backend import server as _server

        alle = np.arange(
            int(_server._doc_count_for_index(idx)), dtype=np.uint32
        )
        ids, counts = idx.frequency_counts_docset(alle, attr=attr)
    except Exception:
        logger.debug("Tokenzahlen nicht ermittelbar", exc_info=True)
        return {}
    gesucht = set(int(k) for k in kennungen)
    return {
        int(i): int(c) for i, c in zip(ids, counts) if int(i) in gesucht
    }


def satz(bericht: Dict[str, Any]) -> str:
    """Ein Satz fuer die Antwort, oder leer.

    Leer, wenn nichts uebersehen wurde. Ein Satz, der jedes Mal dasteht
    und meistens "nichts" sagt, ist genau die Selbstbeschaeftigung, gegen
    die der Nachtragsdeckel gebaut ist.
    """
    zusaetzlich = int(bericht.get("zusaetzlich") or 0)
    if zusaetzlich <= 0:
        return ""
    beispiele = ", ".join(f"„{a}“" for a in bericht.get("alternativen") or ())
    lemma = bericht.get("lemma") or ""
    teil = f" Betroffen sind {beispiele}." if beispiele else ""
    return (
        f"Die Suche nach lemma=„{lemma}“ trifft {bericht.get('exakt', 0):,} "
        f"Token exakt und übersieht {zusaetzlich:,} weitere, deren Lemma "
        f"den Wert nur als Alternative führt.{teil}"
    ).replace(",", ".")
