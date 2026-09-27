# -*- coding: utf-8 -*-
"""Describe docset composition before interpreting a contrast.

Token totals alone do not distinguish many short documents from a few
long documents. Report register, document length and population size
alongside the selected docset."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np


def source_text_count(counts: Dict[str, Dict[str, int]]) -> int | None:
    """Number of distinct source texts among the docset's documents.

    ``counts`` maps a metadata field to its values with token weights. Among
    the source-text fields (``QUELLTEXTFELDER``: origin_id, origin_doc_id,
    pair_id) the one covering the most tokens wins, ties go to the field with
    more distinct values. In a paired human and AI corpus that is typically
    origin_id: it is set on the human original and on all its versions,
    pair_id only on the versions, and origin_doc_id repeats across sources.

    The axes leave these fields out on purpose (their value distribution is
    noise). The count is not noise: statements such as 60,000 AI versions of
    5,000 source texts, or a hit set of 5,921 matches in 1,100 source texts,
    depend on it.
    """
    from candyconc.candyconc_copilot.recipe_runtime import QUELLTEXTFELDER

    felder = [f for f in counts if f.casefold() in QUELLTEXTFELDER and counts[f]]
    bestes = waehle_quelltextfeld(
        [(f, sum(counts[f].values()), len(counts[f])) for f in felder])
    return len(counts[bestes]) if bestes is not None else None


def waehle_quelltextfeld(kandidaten) -> str | None:
    """Die eine Regel, welches Feld die Quelltexte bestimmt.

    ``kandidaten`` sind ``(feld, token, werte)`` in der Reihenfolge der
    Metadatenfelder: das Feld mit den meisten abgedeckten Token gewinnt, bei
    Gleichstand das mit mehr Werten, bei vollem Gleichstand das erste.
    source_text_count und query_count (hit_spread) teilen sie.
    """
    kandidaten = [k for k in kandidaten if k[2] > 0]
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda k: (k[1], k[2]))[0]


def docset_konfundierer(idx: Any, doc_ids: Any) -> Dict[str, Any] | None:
    """Describe register, document length and population size for a docset.

    Equal token totals can represent 40 long documents or 4000 short ones,
    so document composition matters when interpreting a contrast. Include
    the profile with the docset instead of requiring another tool call.
    Return ``None`` for an empty docset.
    """
    anzahl = int(getattr(doc_ids, "size", len(doc_ids) if doc_ids is not None else 0))
    if anzahl <= 0:
        return None
    try:
        starts, ends, _ = idx._doc_ranges_for_ids(doc_ids)
    except Exception:
        return None
    laengen_roh = np.asarray(ends, dtype=np.int64) - np.asarray(starts, dtype=np.int64)
    laengen = laengen_roh[laengen_roh >= 0]
    if laengen.size == 0:
        return None
    # Aligned to doc_ids, hence usable as a token weight per document. The
    # sum equals idx.docset_token_count(doc_ids) to the token and thus the
    # token_count the answer already reports, so the share stays
    # recomputable from the answer itself without a new field.
    gewichte = np.maximum(laengen_roh, 0)
    tokens_gesamt = int(gewichte.sum())
    profil: Dict[str, Any] = {
        "doc_len": {
            "min": int(laengen.min()),
            "median": round(float(np.median(laengen)), 1),
            "mean": round(float(laengen.mean()), 1),
            "max": int(laengen.max()),
        },
        "axes": {},
    }
    doc_meta = getattr(idx.fast_index, "doc_metadata", None) or {}
    if not doc_meta:
        return profil
    try:
        felder = list(idx.metadata_fields() or [])
    except Exception:
        felder = []
    ids = np.asarray(doc_ids, dtype=np.int64).tolist()
    # Two counts side by side: tokens for the shares, documents for the
    # axis classification, which asks for the NUMBER of values. A document
    # share would contradict every other denominator here, which counts
    # tokens. On a nearly homogeneous 56,000-token social media index 34.15
    # percent of documents correspond to 33.39 percent of tokens. That is
    # little, but tokens are the right unit, and with texts of unequal
    # length the two numbers diverge widely.
    zaehlungen: Dict[str, Dict[str, int]] = {}
    for feld in felder:
        zaehler: Dict[str, int] = {}
        for lauf, doc_id in enumerate(ids):
            meta = doc_meta.get(int(doc_id))
            if not isinstance(meta, dict):
                continue
            wert = meta.get(str(feld))
            if wert is None:
                continue
            gewicht = int(gewichte[lauf]) if lauf < gewichte.size else 0
            werte = wert if isinstance(wert, (list, tuple, set)) else [wert]
            for einzeln in werte:
                text = str(einzeln).strip()
                if text:
                    zaehler[text] = zaehler.get(text, 0) + gewicht
        if zaehler:
            zaehlungen[str(feld)] = zaehler

    # DIESELBE Achsendefinition wie im Turn-Briefing statt einer zweiten.
    # Ohne sie stand in jeder Docset-Antwort fuenfmal eine Dokument-ID-Achse
    # der Form "683 Werte, groesster: quelle:ffb50d2a... (0.1%)". Das
    # ist kein Konfundierer, das ist Rauschen im Kontextfenster.
    from candyconc.candyconc_copilot.recipe_runtime import _classify_meta_axes

    anzahl_quelltexte = source_text_count(zaehlungen)
    if anzahl_quelltexte:
        # Before the axes: whoever truncates the profile line at the end
        # (evidence line at 220 characters, bundle at 1,600) hits the axes
        # first and not the number of source texts. The same axes object is
        # filled further below.
        profil = {"doc_len": profil["doc_len"], "source_texts": anzahl_quelltexte,
                  "axes": profil["axes"]}

    kardinalitaet = {feld: len(w) for feld, w in zaehlungen.items()}
    for eintrag in _classify_meta_axes(list(zaehlungen), kardinalitaet, anzahl):
        art = eintrag.get("kind")
        feld = str(eintrag.get("field"))
        zaehler = zaehlungen.get(feld) or {}
        # "quelltext" belongs here: a field that groups versions of THE SAME
        # text (19,272 values for 250,535 documents in a paired corpus) is no
        # more a profile feature than a document id.
        if not zaehler or art in {"doc_id", "quelltext", "unknown"}:
            continue
        geordnet = sorted(zaehler.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(zaehler) == 1:
            # Diese Form liest grounding_contrast.kontrastseiten_benennen, um
            # aus konstanten Metadatenwerten den NAMEN einer Kontrastseite zu
            # bilden. Wer sie aendert, macht aus benannten Seiten wieder
            # "Seite A" und "Seite B".
            profil["axes"][feld] = f"konstant: {geordnet[0][0]}"
            continue
        # Ein einzelner groesster Wert sagt nichts ueber die Verteilung: 51
        # Prozent und 99 Prozent sehen gleich aus, sind aber verschiedene
        # Korpora. Drei Werte sind der Kompromiss gegen das Kontextfenster,
        # das dieses Modul ausdruecklich schont.
        teile = [
            f"{name} {round(100.0 * masse / float(tokens_gesamt), 1)}%"
            for name, masse in geordnet[:3]
            if tokens_gesamt > 0
        ]
        rest = len(geordnet) - len(teile)
        if rest > 0:
            teile.append(f"+{rest} weitere")
        profil["axes"][feld] = (
            f"{len(zaehler)} Werte, Tokenanteile: " + ", ".join(teile)
        )
    return profil
