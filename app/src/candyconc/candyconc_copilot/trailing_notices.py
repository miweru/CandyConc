# -*- coding: utf-8 -*-
"""Separate answer content from notices appended by other checks.

Grounding, quotation and recovery checks append separate paragraphs beginning
with "Hinweis: ". Exclude these trailing notices from later content checks
so a notice's count cannot become evidence for a claim in the model's answer.
"""

from __future__ import annotations

import re

from candyconc.answer_language import is_english

#: So beginnt jeder Hinweis, den der Harnisch unter eine Antwort hängt.
HINWEIS_KOPF = "Hinweis: "
#: The same head in an English answer (candyconc/answer_language.py).
HINWEIS_KOPF_EN = "Note: "

_ABSATZGRENZE = re.compile(r"\n[ \t]*\n")


def ohne_schlusshinweise(text: str) -> str:
    """Der Text ohne die Hinweis-Absätze an seinem Ende.

    Nur am Ende: ein Absatz mit „Hinweis:“, hinter dem die Antwort weitergeht,
    gehört zur Antwort. Besteht der Text aus einem einzigen Absatz, bleibt er
    stehen, denn dann gibt es keine Antwort davor.
    """
    rumpf = str(text or "").rstrip()
    koepfe = (HINWEIS_KOPF, HINWEIS_KOPF_EN) if is_english() else (HINWEIS_KOPF,)
    while True:
        grenzen = list(_ABSATZGRENZE.finditer(rumpf))
        if not grenzen or not rumpf[grenzen[-1].end():].lstrip().startswith(koepfe):
            return rumpf
        rumpf = rumpf[: grenzen[-1].start()].rstrip()
