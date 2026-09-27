# -*- coding: utf-8 -*-
"""Token counts in the context window of a node.

Purpose: the publication being replicated evaluates the CONTEXT of a node
against the REST of the corpus. That is a different analysis from docset
against docset (the target is a set of positions, not of documents) and
also different from ``collocate_stats``, where the pair event space applies
and a token in the window of several anchors counts several times. On such
a table ``b = corpus frequency - a`` would be meaningless. Here every
position belongs to the table exactly once, so that ``a``, ``b``, ``n1``
and ``n2`` share the same counting scheme.

THE CONVENTION: ``coverage_sweep_arrays`` returns HALF-OPEN segments
``[start, end)``, and according to ``CoverageSegment`` they are already
DISJOINT. Reading ``ends`` as inclusive takes one token too many per
segment, and merging would also bridge the gap the sweep leaves AT THE
NODE POSITION (``_fast_count.pyx`` lays out ``[l, s)`` on the left and
``[e, r)`` on the right, the node ``[s, e)`` deliberately stays outside).

On a 56,000-token test index, node ``[word="die"]``, window +-5, within
sentences: the true position set has 8,289 elements, the inclusive reading
reports 10,005, i.e. 20.7 percent too many, 857 of them node positions.
``die`` then ranks first with log_ratio 8.81 instead of rank 293 with 0.11.
In addition the surplus token at every right segment edge reads across the
sentence boundary although ``within_sentence=True`` is set.

Hence: no merging (there is nothing to merge), half-open reading, and
disjointness is CHECKED instead of assumed.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

#: Wieviele Token-IDs gesammelt werden, bevor einmal gezaehlt wird. Die
#: Vorfassung rief ``np.bincount`` mit ``minlength=vocab+1`` JE Segment auf
#: und legte damit je Segment ein Array in Vokabulargroesse an. Am
#: 273M-Index gingen dadurch 99,5 Prozent der Laufzeit in das Zaehlen und
#: ein haeufiger Knoten war unbenutzbar.
_ZAEHL_BLOCK = 4_000_000


def _sweep_segmente(
    backend: Any,
    query: str,
    *,
    window_left: int,
    window_right: int,
    within_sentence: bool,
    docset_mask: Any,
    gesamt: int,
) -> Tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """``(starts, ends, Knotentreffer, Ankerpositionen)``, halboffen und disjunkt."""
    from candyconc.core.cql_engine import search_cql_match_arrays_backend
    from candyconc.core.coverage_sweep import coverage_sweep_arrays

    treffer = search_cql_match_arrays_backend(
        backend, query, limit=2_000_000_000, docset_mask=docset_mask
    )
    anker = np.asarray(
        treffer[0] if isinstance(treffer, (tuple, list)) else treffer,
        dtype=np.int64,
    )
    if anker.size == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64), 0, anker
    seg_s, seg_e, _w = coverage_sweep_arrays(
        anchors=anker,
        spans=np.ones_like(anker),
        window_left=int(window_left),
        window_right=int(window_right),
        boundaries=backend.boundaries,
        within_sentence=bool(within_sentence),
        total_tokens=int(gesamt),
        pair_semantics=False,
    )
    s = np.asarray(seg_s, dtype=np.int64)
    e = np.asarray(seg_e, dtype=np.int64)
    if s.size and not bool(np.all(s[1:] >= e[:-1])):
        # Der Vertrag von CoverageSegment sagt "disjoint". Wenn er je bricht,
        # ist n1 keine Positionsmenge mehr, und das darf nicht still passieren.
        raise RuntimeError(
            "coverage_sweep_arrays lieferte überlappende Segmente: n1 wäre "
            "dann keine Positionszahl. Bitte melden."
        )
    return s, e, int(anker.size), anker


def _vereinige(s: np.ndarray, e: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Halboffene Intervalle zu einer disjunkten, sortierten Menge verschmelzen.

    Vektorisiert ueber das laufende Maximum der Enden. Beruehrende Intervalle
    (``a <= laufendes Ende``) verschmelzen mit, denn fuer eine POSITIONSMENGE
    ist [5,10) vereinigt [10,11) genau [5,11).
    """
    if s.size == 0:
        return s, e
    ordn = np.argsort(s, kind="stable")
    s2 = s[ordn]
    e2 = e[ordn]
    lauf = np.maximum.accumulate(e2)
    neu = np.empty(s2.size, dtype=bool)
    neu[0] = True
    neu[1:] = s2[1:] > lauf[:-1]
    anfaenge = np.flatnonzero(neu)
    return s2[neu], np.maximum.reduceat(e2, anfaenge)


def context_token_counts(
    backend: Any,
    query: str,
    *,
    window_left: int = 5,
    window_right: int = 5,
    within_sentence: bool = True,
    docset_mask: Any = None,
    attribute: str = "word",
    knoten_im_kontext: bool = False,
) -> Tuple[Dict[str, int], int, int, int]:
    """``(Haeufigkeiten, Positionen, Knotentreffer, ohne_Label)``.

    ``Positionen`` ist die Groesse der Fenstermenge und gleich
    ``coverage_sweep.total_context_mass_arrays`` auf denselben Segmenten.
    Der Knoten selbst gehoert NICHT dazu, solange ``knoten_im_kontext``
    falsch ist.

    ``knoten_im_kontext`` nimmt die Knotenpositionen mit in die
    Positionsmenge. Das ist keine Spielerei, sondern eine Konvention, in
    der sich Publikationen unterscheiden: Heinrich/Evert 2024 (Operationalising
    the Hermeneutic Grouping Process in Corpus-assisted Discourse Studies,
    CPSS 2024, Wien, 33-44, https://aclanthology.org/2024.cpss-1.3/) setzen
    ``node_removed_from_context = false`` und argumentieren ausdruecklich
    gegen das Entfernen (contra Evert 2004). Ohne die Option ist ihre
    Tabelle nicht reproduzierbar. Gemessen am AfD-19-Teilkorpus: 869
    Knoten, davon liegen 47 ohnehin im Fenster eines anderen Knotens,
    R1 steigt von 12.330 auf 13.199 gegen publizierte 13.344.

    Die Knotenspanne ist EIN Token breit, wie im Sweep daneben
    (``spans=np.ones_like``). Bei mehrwortigen Treffern zaehlt also nur die
    Anfangsposition. Wer das aendert, muss beide Stellen aendern.

    ``ohne_Label`` are positions whose token has lexicon id 0 in the chosen
    attribute, i.e. NO value. A parliamentary corpus of 273 million tokens
    has 2,236 of them in the lemma (``empty_gold_values`` in the import
    report: ``lemma total_tokens`` 273,547,857 against ``token_count``
    273,550,093). They occupy a position but contribute to no type. Hence
    ``sum(Haeufigkeiten) + ohne_Label == Positionen`` holds, not
    ``sum(Haeufigkeiten) == Positionen``. Confusing the two computes ``a/n1``
    against a denominator that is too large.
    """
    from candyconc.core.fast_index_native import strings_for_ids

    attribut = str(attribute or "word").strip().lower()
    if attribut not in {"word", "lemma"}:
        raise ValueError("attribute muss word oder lemma sein")
    lexikon = getattr(backend.lexicons, attribut, None)
    if lexikon is None or int(getattr(lexikon, "vocab_size", 0)) <= 0:
        raise ValueError(f"{attribut}-Lexikon fehlt. Bitte Index neu bauen.")

    # The corpus size is the TOKEN COUNT. boundaries.document._positions.max()
    # + 1 would be the START of the last document: 56,172 instead of 56,191
    # on a small test index, 2,406 positions missing on a 273M-token index,
    # and a window in the last document would be cut off.
    gesamt = int(backend.token_store.token_count)

    s, e, knotentreffer, anker = _sweep_segmente(
        backend, query,
        window_left=window_left, window_right=window_right,
        within_sentence=within_sentence, docset_mask=docset_mask,
        gesamt=gesamt,
    )
    if bool(knoten_im_kontext) and anker.size:
        s, e = _vereinige(
            np.concatenate([s, anker]),
            np.concatenate([e, anker + 1]),
        )
    if s.size == 0:
        return {}, 0, knotentreffer, 0

    n1 = int((e - s).sum())
    holen = (
        backend.token_store.get_word_ids_range
        if attribut == "word"
        else backend.token_store.get_lemma_ids_range
    )
    breite = int(lexikon.vocab_size) + 1
    zaehler = np.zeros(breite, dtype=np.int64)
    puffer: list[np.ndarray] = []
    offen = 0

    def _leeren() -> None:
        nonlocal puffer, offen
        if not puffer:
            return
        ids = np.concatenate(puffer) if len(puffer) > 1 else puffer[0]
        zaehler[:] += np.bincount(ids, minlength=breite)[:breite]
        puffer = []
        offen = 0

    for links, rechts in zip(s.tolist(), e.tolist()):
        if rechts <= links:
            continue
        ids = np.asarray(holen(int(links), int(rechts)), dtype=np.int64)
        if ids.size == 0:
            continue
        puffer.append(ids)
        offen += int(ids.size)
        if offen >= _ZAEHL_BLOCK:
            _leeren()
    _leeren()

    ohne_label = int(zaehler[0])
    belegt = np.nonzero(zaehler)[0]
    belegt = belegt[belegt > 0]
    if belegt.size == 0:
        return {}, int(n1), knotentreffer, ohne_label
    woerter = strings_for_ids(
        lexikon.offsets, lexikon.strings_view,
        belegt.astype(np.uint32, copy=False), True,
    )
    haeufigkeiten = {
        str(w): int(zaehler[i]) for w, i in zip(woerter, belegt.tolist())
    }
    return haeufigkeiten, int(n1), knotentreffer, ohne_label


def _analysierbare_korpusmasse(lexikon: Any, ist_analysetoken: Any, roh: int) -> int:
    """Die Korpusmasse OHNE die Token, die der Zaehler nicht zaehlt.

    Ein Durchgang ueber das Lexikon, gemessen 1,32 Sekunden bei 1,8
    Millionen Typen. Das Ergebnis wird am Lexikonobjekt gemerkt, weil es
    sich innerhalb eines Prozesses nicht aendert: der Index ist
    unveraenderlich geoeffnet.

    Faellt die Ermittlung aus, bleibt die rohe Masse. Eine leicht zu
    grosse Referenzmasse ist der kleinere Fehler gegenueber einem
    Werkzeug, das gar nicht antwortet.
    """
    gemerkt = getattr(lexikon, "_analysierbare_masse", None)
    if isinstance(gemerkt, int) and gemerkt > 0:
        return gemerkt
    try:
        from candyconc.core.fast_index_native import strings_for_ids

        anzahl = int(getattr(lexikon, "vocab_size", 0) or 0)
        if anzahl <= 0:
            return roh
        ids = np.arange(1, anzahl + 1, dtype=np.uint32)
        woerter = strings_for_ids(
            lexikon.offsets, lexikon.strings_view, ids, True
        )
        freqs = lexikon.get_freqs_for_ids(ids.astype(np.int64))
        masse = int(sum(
            int(c) for w, c in zip(woerter, freqs) if ist_analysetoken(w)
        ))
    except Exception:
        return roh
    if masse <= 0:
        return roh
    try:
        setattr(lexikon, "_analysierbare_masse", masse)
    except Exception:
        pass
    return masse


def build_context_keyness_frames(
    backend: Any,
    query: str,
    *,
    window: int = 5,
    attribute: str = "word",
    ist_analysetoken: Any = None,
) -> Tuple[Dict[str, int], Dict[str, int], int, int, Dict[str, Any]]:
    """Die vollstaendige Token-Tabelle Kontext gegen REST des Korpus.

    Referenz ist das Korpus OHNE das Kontextfenster, nicht das ganze
    Korpus: sonst steckte das Ziel in seiner eigenen Referenz.
    """
    haeufigkeiten, positionen, knotentreffer, ohne_label = context_token_counts(
        backend, query,
        window_left=int(window), window_right=int(window),
        within_sentence=True, attribute=attribute,
    )
    # Der Nenner der Tabelle ist die ZAEHLBARE Masse: Positionen ohne
    # Lexikonwert besetzen ein Fenster, tragen aber zu keinem Typ bei, und
    # gehoerten sie in n1, waere a/n1 systematisch zu klein.
    n1 = int(positionen) - int(ohne_label)
    if n1 <= 0:
        raise ValueError(
            f"Kein Kontextfenster für {query!r}: der Knoten kommt nicht vor."
        )
    lexikon = getattr(backend.lexicons, str(attribute), None)
    if lexikon is None:
        raise ValueError(f"{attribute}-Lexikon fehlt.")
    korpus_gesamt = int(lexikon.total_tokens)
    n1_roh, korpus_roh = int(n1), korpus_gesamt
    if ist_analysetoken is not None:
        haeufigkeiten = {
            w: c for w, c in haeufigkeiten.items() if ist_analysetoken(w)
        }
        # THE DENOMINATOR BELONGS TO THE FILTERED NUMERATOR, here too.
        #
        # The numerator is filtered two lines above, so n1 and korpus_gesamt
        # must not be the RAW masses. The neighbouring comment gives the same
        # reason for the unlabelled positions ("gehoerten sie in n1, waere
        # a/n1 systematisch zu klein"), and it holds unchanged for filtered
        # tokens.
        #
        # On a corpus of 142 million tokens 80.7 percent of the tokens are
        # analysable, and computing that costs 1.32 seconds over 1.8 million
        # types.
        n1 = sum(int(c) for c in haeufigkeiten.values())
        if n1 <= 0:
            raise ValueError(
                f"Kein analysierbares Kontextfenster für {query!r}: der "
                "Kontext besteht nur aus Satzzeichen und Markern."
            )
        korpus_gesamt = _analysierbare_korpusmasse(
            lexikon, ist_analysetoken, korpus_gesamt
        )
    referenz: Dict[str, int] = {}
    for wort, im_kontext in haeufigkeiten.items():
        wid = int(lexikon.get_id(wort))
        if wid <= 0:
            continue
        korpusfreq = int(
            lexikon.get_freqs_for_ids(np.array([wid], dtype=np.int64))[0]
        )
        if im_kontext > korpusfreq:
            # Bei korrektem halboffenem Lesen unmoeglich. Wenn es doch
            # eintritt, ist die Tabelle gemischt und darf nicht still auf 0
            # geklemmt werden, wie es die Vorfassung tat.
            raise ValueError(
                f"{wort!r}: {im_kontext} im Kontext, aber Korpusfrequenz "
                f"{korpusfreq}. Die Tabelle ist nicht mehr eine."
            )
        referenz[wort] = korpusfreq - im_kontext
    diagnose = {
        "target_tokens": int(n1),
        "target_tokens_roh": int(n1_roh),
        "reference_tokens_roh": max(0, korpus_roh - int(n1_roh)),
        "context_positions": int(positionen),
        "unlabelled_positions": int(ohne_label),
        "reference_tokens": max(0, korpus_gesamt - int(n1)),
        "reference_kind": "rest_des_korpus_ohne_kontext",
        "node_hits": int(knotentreffer),
        "context_window": int(window),
        "attribute": str(attribute),
    }
    return (
        haeufigkeiten, referenz, int(n1),
        max(0, korpus_gesamt - int(n1)), diagnose,
    )
