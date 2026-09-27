# -*- coding: utf-8 -*-
"""Use one word-rate denominator across counting tools.

Rates use analysis tokens in the selected scope. Raw token counts remain
available in a separate field. An index without word counts falls back
to raw tokens and identifies that denominator source.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence


def _methode(idx: Any, name: str):
    """Nur eine echte Methode der Klasse zaehlt, kein Attribut eines Mocks."""
    if getattr(type(idx), name, None) is None:
        return None
    methode = getattr(idx, name, None)
    return methode if callable(methode) else None


def nenner(idx: Any, doc_ids: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """``{"woerter", "roh", "quelle"}`` fuer das Korpus oder eine Dokumentmenge."""
    if doc_ids is None:
        roh = int(idx.token_count())
        zaehler = _methode(idx, "word_count")
        if zaehler is not None:
            return {"woerter": int(zaehler()), "roh": roh,
                    "quelle": "corpus_index.word_count"}
        return {"woerter": roh, "roh": roh, "quelle": "corpus_index.token_count"}
    roh = int(idx.docset_token_count(doc_ids))
    zaehler = _methode(idx, "docset_word_count")
    if zaehler is not None:
        return {"woerter": int(zaehler(doc_ids)), "roh": roh,
                "quelle": "corpus_index.docset_word_count"}
    return {"woerter": roh, "roh": roh, "quelle": "corpus_index.docset_token_count"}


def rate_je_million(total: int, woerter: int) -> Optional[float]:
    """Use two significant digits below one, otherwise one decimal place."""
    if woerter <= 0:
        return None
    rate = int(total) * 1_000_000 / woerter
    return round(rate, 1) if rate == 0 or rate >= 1 else float(f"{rate:.2g}")


def ist_wortnenner(raw: Dict[str, Any]) -> bool:
    """Steht in einer Werkzeugausgabe der Wortnenner statt der rohen Tokenzahl?"""
    nenner_ = raw.get("denominator_tokens")
    roh = raw.get("denominator_tokens_raw")
    if "word_count" in str(raw.get("denominator_source") or ""):
        return True
    return roh not in (None, "") and nenner_ not in (None, "") and str(roh) != str(nenner_)


def nenner_der_frequenzliste(idx: Any, doc_ids: Any, group_by: str, corpus_tokens: int) -> Dict[str, Any]:
    """Der Nenner von frequency_list: Analysetoken, bei Wortarten alle Token.

    Die Zeilen einer Wort- oder Lemmaliste sind ohnehin Analysetoken
    (filter_frequency_frame). Wortarten zaehlen dagegen JEDES Token, auch
    Satzzeichen (PUNCT) und Umbrueche, ihr Nenner bleibt die rohe Tokenzahl,
    sonst summierten sich die Anteile ueber 100 Prozent. Ohne lesbare
    Korpusgroesse (corpus_tokens 0) gibt es keinen Nenner."""
    if doc_ids is None:
        bezug = (nenner(idx, None) if corpus_tokens
                 else {"woerter": 0, "roh": 0, "quelle": "corpus_index.token_count"})
    else:
        bezug = nenner(idx, doc_ids)
    if group_by == "pos":
        bezug = {"woerter": bezug["roh"], "roh": bezug["roh"],
                 "quelle": "corpus_index.token_count" if doc_ids is None
                 else "corpus_index.docset_token_count"}
    return bezug
