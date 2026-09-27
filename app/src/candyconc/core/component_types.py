# -*- coding: utf-8 -*-
"""Types that contain a searched value as a COMPONENT.

Annotations use the vertical bar for two quite different things, and both
produce the same silent gap.

AMBIGUITY. TreeTagger writes ``Recht|Rechte`` when it could not decide. On
a TreeTagger-annotated parliamentary corpus of 273 million tokens these are
706 types over 1,131,791 tokens. A query for ``[lemma="Recht"]`` returns
110,210 and misses the 24,898 filed under ``Recht|Rechte``, a miss rate of
18.4 percent. For ``Doktor`` it is 224 against 639,263, i.e. 99.96
percent. Over all 825 affected values: 4,108,866 directly reachable,
1,441,982 missed, 25.98 percent.

COMPOUND. Some indexes store UPOS and FEATS together in ``morph``:
``ADV|_``, ``ADV|Degree=Pos``. In one such index 225 of 225 types are pipe
types over 41,632 tokens, and NONE of the 51 components is a type of its
own. ``[morph="ADV"]`` returns nothing, although ``ADV|_`` alone accounts
for 3,991 tokens.

In both cases the engine is CORRECT. ``=`` is a regular expression in CQP,
and the data are reachable:

    [lemma="Recht\\|Rechte"]          -> 24,898
    [lemma="(Recht|Recht\\|Rechte)"]  -> 135,108

What is missing is knowledge of the convention. This module therefore
changes NOTHING about query meaning. Silently widening ``[lemma="Recht"]``
to 135,108 would be worse than the gap: it would break CQP semantics,
invalidate every published anchor, and double count as soon as someone
adds ``[lemma="Rechte"]`` next to it (198 types with two or more
independent components, 312,159 tokens of overlap). Applied to the type
column it would yield 273,860,016 lemma tokens for 273,550,093 corpus
positions, and no denominator built from it would be the corpus any more.

Instead this module answers a factual question: WHICH types contain the
searched value as a component, and how much weight they have. The question
is well defined under both conventions and needs neither a threshold nor a
guess about what the bar means. Whoever wants to interpret the result sees
the type names and decides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np

#: Das Trennzeichen beider Konventionen.
TRENNER = "|"

#: Sentinel-Typen bestehen NUR aus Trennern und einem Kern (``|LBR|``).
#: Sie zerfallen in genau einen nichtleeren Teil und sind damit keine
#: Verbindung zweier Werte. Die Regel faellt aus der Zerlegung, es braucht
#: keine Namensliste: jede kuenftige Marke dieser Form ist mit abgedeckt.
_MIN_TEILE = 2


@dataclass(frozen=True)
class Bestandteile:
    """Was ein Wert an zusammengesetzten Geschwistern hat."""

    wert: str
    attribut: str
    #: ``(Typname, Korpusfrequenz)``, absteigend nach Frequenz.
    typen: Tuple[Tuple[str, int], ...]
    #: Frequenz des Werts als eigenstaendiger Typ, 0 wenn es ihn nicht gibt.
    direkt: int

    @property
    def masse(self) -> int:
        """Tokenmasse der zusammengesetzten Typen."""
        return int(sum(f for _n, f in self.typen))

    @property
    def fehlanteil(self) -> float:
        """Anteil der Masse, den eine Abfrage auf ``wert`` allein verfehlt."""
        gesamt = self.direkt + self.masse
        return (self.masse / gesamt) if gesamt else 0.0

    def __bool__(self) -> bool:
        return bool(self.typen)

    def muster(self) -> str:
        """Ein CQL-Wert, der den Wert UND seine Geschwister trifft.

        Alles wird maskiert, auch der Trenner: das Ergebnis ist eine
        Alternation ueber Literale, kein Muster, das versehentlich mehr
        trifft. Bewusst kein ``.*``-Praefixmuster, denn ``Recht(\\|.*)?``
        traefe auch ``Recht|Rechtsstaat`` und damit einen Wert, den
        niemand gefragt hat.
        """
        namen = [self.wert] if self.direkt else []
        namen.extend(n for n, _f in self.typen)
        return "(%s)" % "|".join(re.escape(n) for n in namen)


def zerlege(name: str) -> List[str]:
    """Die nichtleeren Bestandteile eines Typnamens.

    ``"Recht|Rechte"`` ergibt ``["Recht", "Rechte"]``, ``"|LBR|"`` ergibt
    ``["LBR"]`` und faellt damit unter ``_MIN_TEILE`` heraus.
    """
    return [t for t in str(name).split(TRENNER) if t]


def _ist_verbund(name: str) -> bool:
    return TRENNER in name and len(zerlege(name)) >= _MIN_TEILE


def _tabelle(lexikon: Any) -> Dict[str, List[Tuple[str, int]]]:
    """``Bestandteil -> [(Typname, Frequenz), ...]`` ueber das ganze Lexikon.

    Ein voller Lexikonlauf. Am 273M-Index mit 986.580 Lemmatypen gemessen
    unter einer halben Sekunde, und das Ergebnis haengt am Lexikonobjekt,
    wird also je Prozess einmal gebaut.
    """
    zwischen = getattr(lexikon, "_bestandteil_tabelle", None)
    if zwischen is not None:
        return zwischen
    anzahl = int(getattr(lexikon, "vocab_size", 0))
    tabelle: Dict[str, List[Tuple[str, int]]] = {}
    if anzahl > 1:
        ids = np.arange(1, anzahl, dtype=np.int64)
        namen = lexikon.get_strings_for_ids(ids)
        freqs = np.asarray(lexikon.get_freqs_for_ids(ids), dtype=np.int64)
        for name, freq in zip(namen, freqs.tolist()):
            name = str(name)
            if TRENNER not in name:
                continue
            teile = zerlege(name)
            if len(teile) < _MIN_TEILE:
                continue
            for teil in teile:
                tabelle.setdefault(teil, []).append((name, int(freq)))
    for eintraege in tabelle.values():
        eintraege.sort(key=lambda t: (-t[1], t[0]))
    try:
        setattr(lexikon, "_bestandteil_tabelle", tabelle)
    except Exception:
        # Manche Lexikonobjekte sind geschlossen. Dann wird eben neu
        # gebaut, das ist langsamer und bleibt richtig.
        pass
    return tabelle


def bestandteile_fuer(lexikon: Any, wert: str, *, attribut: str = "") -> Bestandteile:
    """Die zusammengesetzten Typen, die ``wert`` als Bestandteil fuehren.

    Der Wert wird WOERTLICH genommen. Wer ein Muster uebergibt, bekommt
    nichts, und das ist richtig: die Frage ist auf einen Wert gestellt.
    """
    wert = str(wert)
    if not wert or TRENNER in wert:
        # Ein Wert, der selbst einen Trenner traegt, ist bereits ein
        # Verbundtyp. Fuer ihn gibt es keine Geschwister dieser Art.
        return Bestandteile(wert=wert, attribut=attribut, typen=(), direkt=0)
    treffer = tuple(_tabelle(lexikon).get(wert, ()))
    direkt = 0
    hole = getattr(lexikon, "get_id", None)
    if hole is not None:
        kennung = int(hole(wert))
        if kennung > 0:
            direkt = int(
                lexikon.get_freqs_for_ids(np.array([kennung], dtype=np.int64))[0]
            )
    return Bestandteile(
        wert=wert, attribut=attribut, typen=treffer, direkt=direkt
    )


def bericht(befund: Bestandteile, *, hoechstens: int = 5) -> Dict[str, Any]:
    """Der Befund als Datensatz fuer eine Werkzeugantwort.

    Bewusst Zahlen und Typnamen, kein Fliesstext und keine Warnung. Eine
    Warnung waere eine Meinung ueber die Annotation. Das hier ist eine
    Angabe wie ``ohne_Label`` in der Kontextzaehlung: sie steht neben der
    Zahl, damit niemand die Zahl fuer vollstaendig haelt.
    """
    if not befund:
        return {}
    gezeigt = befund.typen[:max(0, int(hoechstens))]
    return {
        "wert": befund.wert,
        "attribut": befund.attribut,
        "direkt": befund.direkt,
        "in_verbundtypen": befund.masse,
        "fehlanteil": round(befund.fehlanteil, 4),
        "verbundtypen": [{"typ": n, "frequenz": f} for n, f in gezeigt],
        "verbundtypen_gesamt": len(befund.typen),
        "muster_mit_verbundtypen": befund.muster(),
    }
