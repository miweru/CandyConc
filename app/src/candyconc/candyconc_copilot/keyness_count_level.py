"""Keep keyness counts and lexicon labels on the same attribute level.

Word and lemma counts use different ID spaces. Return each count together
with its matching lexicon so a lemma ID cannot be rendered as a word ID.
The same attribute selection applies to corpus and docset comparisons.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict

# Gemeinsamer Ort fuer beide Flaechen: REST und Copilot haengen
# dieselbe Aufschluesselung an, sonst laufen die Geschwister auseinander.
from candyconc.services.tools.keyness import schreibungen_anhaengen

from candyconc.candyconc_copilot.tool_errors import ToolInputError

EBENEN = ("word", "lemma")


def zaehlebene(attribute: Any) -> str:
    """Die validierte Zaehlebene. Ein unbekannter Wert ist ein Fehler."""
    ebene = str(attribute or "word").strip().lower()
    if ebene not in EBENEN:
        raise ToolInputError(
            f"attribute muss 'word' oder 'lemma' sein, nicht {str(attribute)!r}."
        )
    return ebene


def lexikon_fuer(idx: Any, ebene: str) -> Any:
    """Das Lexikon der Zaehlebene, oder ein sprechender Abbruch.

    Ein fehlendes Wort-Lexikon ist ein kaputter Index, ein fehlendes
    Lemma-Lexikon eine Eigenschaft des Korpus. Beide bekommen verschiedene
    Saetze, weil sie verschiedene Abhilfen haben.
    """
    kern = getattr(idx, "fast_index", None)
    lexikon = getattr(getattr(kern, "lexicons", None), ebene, None)
    if lexikon is not None:
        return lexikon
    if ebene == "word":
        raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")
    raise ToolInputError(
        f"attribute={ebene} ist für dieses Korpus nicht verfügbar: es führt "
        f"kein {ebene}-Lexikon. attribute=word bleibt nutzbar."
    )


def counts_docset(
    idx: Any,
    doc_ids: Any,
    *,
    pos: str | None,
    attr: str = "word",
    variants_out: Dict[int, Dict[int, int]] | None = None,
):
    """``idx.frequency_counts_docset`` mit Case-Folding und Zaehlebene.

    Keyness must fold each ``str.casefold`` class (die/Die/DIE) into ONE candidate
    keyed by a globally-stable representative id (C-casefold-counting-01), so the
    copilot's q-values match /analysis/keyness. ``case_fold`` and ``attr`` are only
    passed when the callee accepts them, so a narrow test double still works.

    Nimmt die Zaehlung ``attr`` nicht entgegen, bricht alles ausser ``word`` ab.
    Wortformen liefern, waehrend Lemmata bestellt waren, ist der teuerste
    Ausgang, weil die Zahl plausibel aussieht.
    """
    try:
        parameter = inspect.signature(idx.frequency_counts_docset).parameters
    except (TypeError, ValueError):
        parameter = {}
    zusatz: Dict[str, Any] = {}
    if "case_fold" in parameter:
        zusatz["case_fold"] = True
    if "attr" in parameter:
        zusatz["attr"] = str(attr)
    elif str(attr) != "word":
        raise ToolInputError(
            f"Diese Zählung kennt die Ebene {attr} nicht, sie zählt Wortformen."
        )
    # Welche Schreibung welchen Anteil traegt. Ohne sie liest sich die Zeile
    # als Aussage ueber ihr gedrucktes Etikett, waehrend sie eine Aussage
    # ueber die ganze Faltklasse ist. Ein Testdouble ohne den Parameter
    # bekommt ihn nicht und liefert einfach keine Aufschluesselung.
    if variants_out is not None and "variants_out" in parameter:
        zusatz["variants_out"] = variants_out
    return idx.frequency_counts_docset(doc_ids, pos_prefix=pos, **zusatz)


def frequenzliste(quelle: Any, *, attr: str = "word"):
    """``quelle.frequency_list`` mit Zaehlebene, nach derselben Regel.

    Wie ``counts_docset``: ``attr`` geht nur an eine Zaehlung, die ihn kennt,
    und alles ausser ``word`` bricht sonst ab, statt Wortformen unterzuschieben.
    """
    try:
        parameter = inspect.signature(quelle.frequency_list).parameters
    except (TypeError, ValueError):
        parameter = {}
    if "attr" in parameter:
        return quelle.frequency_list(stopwords=None, attr=str(attr))
    if str(attr) != "word":
        raise ToolInputError(
            f"Diese Frequenzliste kennt die Ebene {attr} nicht, "
            "sie zählt Wortformen."
        )
    return quelle.frequency_list(stopwords=None)


def ganzzahl_mindestens_eins(wert: Any, name: str = "limit") -> int:
    """Eine positive Ganzzahl oder ein ehrlicher Eingabefehler."""
    try:
        k = int(wert)
    except (TypeError, ValueError):
        raise ToolInputError(f"{name} muss eine ganze Zahl >= 1 sein.")
    if k < 1:
        raise ToolInputError(f"{name} muss eine ganze Zahl >= 1 sein.")
    return k


def schreibungs_faltung(
    idx: Any,
    query: str,
    *,
    case_insensitive: bool,
    unscoped: bool,
) -> Dict[str, Dict[str, int]]:
    """Return spelling contributions for a case-insensitive plain-word count.

    Counting uses ``str.lower``, so ``dass``, ``Dass`` and ``DASS`` share a
    class while ``daß`` remains separate. Restrict the breakdown to a single
    plain term without a document scope so its parts and total use the same
    counting population. A class with one spelling needs no extra explanation.
    """
    if not case_insensitive or not unscoped:
        return {}
    term = str(query or "").strip()
    if (not term or term.startswith(("cql:", "["))
            or any(z in term for z in ' \t+*?()|&!:=<>""„““”')):
        return {}
    try:
        ids = idx._casefold_ids(term, attr="word")
        lexikon = getattr(idx.fast_index, "lexicons").word
    except Exception:
        return {}
    if ids is None or len(ids) == 0:
        return {}
    anteile: Dict[str, int] = {}
    for tid in ids:
        form = lexikon.get_string(int(tid))
        if not form:
            continue
        anteile[form] = int(
            idx.term_positions(form, case_insensitive=False).size)
    return {"schreibung_gefaltet": anteile} if len(anteile) > 1 else {}
