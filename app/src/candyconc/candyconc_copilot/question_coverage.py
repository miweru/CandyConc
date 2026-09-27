# -*- coding: utf-8 -*-
"""Was die Frage nennt und was der Lauf gerechnet hat.

Am 2026-08-30 auf dem echten Produktpfad gemessen. Die Frage lautete
woertlich: "Rechne mir vor, was ich bei Fenster 1, 5 und 10 jeweils gewinne
und was ich verliere." Gerechnet wurden Fenster 1 und 5. Fenster 10 nie.
Die Antwort nannte trotzdem selbstbewusst zwei Fenster und verschwieg, dass
ein Drittel der Frage unbeantwortet blieb.

Das ist eine Behauptung jenseits der Evidenz, und zwar die stille Sorte:
nicht eine falsche Zahl, sondern eine Deckung, die es nicht gibt.

WARUM HIER MELDEN UND NICHT NACHRECHNEN LASSEN. Der Baum hat die andere
Naht bereits: ``response_requirements`` zerlegt die Frage in Pflichten und
laesst ``_accepted_claims_complete`` scheitern, wenn eine fehlt. Zwei
Regex-Alternativen wuerden sie fuer diesen Fall scharf schalten. Gemessen
kostet das aber einen zusaetzlichen strukturierten Modellaufruf je Turn und
eine Neusynthese der ganzen Antwort je unerfuellter Pflicht, zuletzt sieben
Mal zu je rund 360 Sekunden. Bei einem Modell, das den Grossteil seiner
Zeit im Reasoning verbringt, ist eine Antwortpflicht keine Meldung, sondern
eine Neuschreib-Schleife.

Wer bereit ist, den Aufruf und die Schleife zu bezahlen, bekommt die
bessere Antwort. Wer das nicht ist, bekommt hier wenigstens die wahre.

NICHT fensterspezifisch geschnitten. Dieselbe Luecke besteht fuer
``min_freq``, ``top_n`` und jede andere Groesse, die eine Frage aufzaehlt.
Das Feld ist deshalb ein Parameter, ``window`` nur der erste Fall.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Mapping, Sequence

from candyconc.answer_language import choose as _t
from .evidence_access import feld as _feld, flaeche as _flaeche

#: How the English sentence names the field.
_FELDNAME_EN: Mapping[str, str] = {
    "window": "window",
    "min_freq": "minimum frequency",
    "top_n": "top N",
}

#: Feldname im Werkzeug -> wie eine Frage die Groesse auf Deutsch nennt.
#: Ein Feld ohne Eintrag wird nicht geprueft, und das ist Absicht: eine
#: Wache, die Wortmuster raet, meldet Luecken, die niemand gefragt hat.
FELDNAMEN: Mapping[str, tuple[str, ...]] = {
    "window": ("Fenster", "Fenstergroesse", "Fenstergröße"),
    "min_freq": ("Mindestfrequenz", "min_freq"),
    "top_n": ("Top-N", "top_n"),
}


def genannte_werte(feld: str, frage: str) -> List[int]:
    """Die ganzen Zahlen, die die Frage zu diesem Feld aufzaehlt.

    Erkannt wird eine Aufzaehlung direkt hinter dem Feldnamen, also
    "Fenster 1, 5 und 10" ebenso wie "bei Fenster 5". Was weiter weg im
    Satz steht, wird NICHT eingesammelt: eine Zahl drei Nebensaetze
    spaeter hat mit dem Feld nichts zu tun, und eine Wache, die das
    behauptet, meldet Luecken, die es nicht gibt.
    """
    namen = FELDNAMEN.get(feld)
    if not namen or not frage:
        return []
    gefunden: List[int] = []
    for name in namen:
        muster = re.compile(
            re.escape(name) + r"\s+((?:\d+\s*(?:,|;|/|und|oder|bis|sowie)?\s*)+)",
            re.IGNORECASE,
        )
        for treffer in muster.finditer(str(frage)):
            for zahl in re.findall(r"\d+", treffer.group(1)):
                wert = int(zahl)
                if wert not in gefunden:
                    gefunden.append(wert)
    return gefunden


def gerechnete_werte(feld: str, evidenz: Sequence[Any]) -> List[int]:
    """Die Werte, mit denen wirklich gerechnet wurde.

    Quelle ist ``raw_surface``, also das, was das Werkzeug ZURUECKGEMELDET
    hat, nicht was das Modell angefordert hatte. Ein Werkzeug darf einen
    Wert kalibrieren oder abweisen, und dann gilt der gerechnete.
    ``query`` dient nur als Rueckfall, wenn die Oberflaeche den Wert nicht
    fuehrt.
    """
    werte: List[int] = []

    def merken(roh: Any) -> None:
        try:
            wert = int(roh)
        except (TypeError, ValueError):
            return
        if wert not in werte:
            werte.append(wert)

    for eintrag in evidenz or ():
        flaeche = _flaeche(eintrag)
        if flaeche is not None and feld in flaeche:
            merken(flaeche.get(feld))
            continue
        rohe_frage = _feld(eintrag, "query", "")
        if not rohe_frage:
            continue
        try:
            argumente = json.loads(rohe_frage)
        except (TypeError, ValueError):
            continue
        if isinstance(argumente, Mapping) and feld in argumente:
            merken(argumente.get(feld))
    return werte


def luecke(feld: str, frage: str, evidenz: Sequence[Any]) -> List[int]:
    """Die genannten Werte, zu denen nichts gerechnet wurde."""
    genannt = genannte_werte(feld, frage)
    if not genannt:
        return []
    gerechnet = set(gerechnete_werte(feld, evidenz))
    if not gerechnet:
        # Nichts gerechnet heisst nicht Luecke, sondern anderer Analyseweg.
        # Eine Frage, die Fenster nennt, kann ueber ein Docset oder eine
        # Frequenzliste beantwortet werden, ohne dass ein Fenster vorkommt.
        return []
    return [w for w in genannt if w not in gerechnet]


def luecken_satz(feld: str, frage: str, evidenz: Sequence[Any]) -> str:
    """Ein Satz fuer die Antwort, oder leer.

    Er nennt beide Seiten, damit die Leserin die Luecke nachrechnen kann,
    statt sie glauben zu muessen.
    """
    fehlend = luecke(feld, frage, evidenz)
    if not fehlend:
        return ""
    name = _t(FELDNAMEN[feld][0], _FELDNAME_EN.get(feld, feld))
    gerechnet = gerechnete_werte(feld, evidenz)
    fehlt = ", ".join(str(w) for w in fehlend)
    lief = ", ".join(str(w) for w in gerechnet)
    return _t(
        "Nicht gemessen: nach {n} {f} wurde gefragt, gerechnet wurde "
        "mit {n} {l}. Die Aussage deckt den fehlenden Teil nicht ab.",
        "Not measured: the question asked for {n} {f}, the run computed "
        "{n} {l}. The statement does not cover the missing part.",
    ).format(n=name, f=fehlt, l=lief)


def alle_luecken_saetze(frage: str, evidenz: Sequence[Any]) -> List[str]:
    """Ueber alle bekannten Felder, in fester Reihenfolge."""
    saetze = []
    for feld in FELDNAMEN:
        satz = luecken_satz(feld, frage, evidenz)
        if satz:
            saetze.append(satz)
    return saetze
