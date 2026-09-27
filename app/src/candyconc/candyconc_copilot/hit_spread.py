# -*- coding: utf-8 -*-
"""Report hit coverage and cluster-robust intervals for query counts.

For the whole query and each metadata row, expose ``docs_with_hits``,
``source_texts_with_hits`` and the 95-percent ``per_million_ci`` on the same
analysis-token denominator as the rate. Rows also expose ``share`` and
``share_ci``. Hit counts alone do not identify independent source texts.

For clusters c, estimate R = sum(y_c) / sum(n_c), where y is the hit count
and n is the analysis-token count. The linearized variance is
C/(C-1) * sum((y_c - R*n_c)**2) / sum(n_c)**2. Use R +/- 1.96 SE.
For a row's share, use its hits over the whole query's hits per cluster.
Clusters are source texts, or documents when no source-text field exists.
Compute these deterministic intervals only when the query positions match
``total`` exactly.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .schema_parts import _int, _num, _str

Z95 = 1.959963984540054

#: Antwortschema von query_count, oben und je Zeile von nach.
_INTERVALL = {"type": "array", "items": _num()}
ANTWORTFELDER: Dict[str, Any] = {
    "docs_with_hits": _int(),
    "source_texts_with_hits": _int(),
    "per_million_ci": _INTERVALL,
    "ci_cluster": _str(),
}
ZEILENFELDER: Dict[str, Any] = {
    "docs_with_hits": _int(),
    "source_texts_with_hits": _int(),
    "per_million_ci": _INTERVALL,
    "share": _num(),
    "share_ci": _INTERVALL,
}


def _anfaenge(idx: Any) -> np.ndarray:
    return np.asarray(idx.fast_index.boundaries.document._positions, dtype=np.int64)


def trefferpositionen(idx: Any, query: str, docset_mask: Any, total: int, *, server: Any) -> Optional[np.ndarray]:
    """Die Startpositionen derselben Abfrage, nur wenn ihre Zahl ``total`` ist.

    ``server`` is the backend module, passed in by the caller (the copilot
    package does not import it, see the import contracts in pyproject.toml).
    """
    positionen = np.asarray(
        server._dispersion_positions_for_term(idx, str(query), docset_mask=docset_mask),
        dtype=np.int64,
    )
    if int(positionen.size) != int(total):
        return None
    return np.sort(positionen)


def _codes_je_feld(idx: Any) -> Dict[str, np.ndarray]:
    """Je Quelltextfeld ein Code je Dokument, -1 ohne Wert. Einmal je Prozess."""
    vorhanden = getattr(idx, "_quelltext_codes_cache", None)
    if vorhanden is not None:
        return vorhanden
    from candyconc.candyconc_copilot.recipe_runtime import QUELLTEXTFELDER

    try:
        felder = [f for f in (idx.metadata_fields() or []) if str(f).casefold() in QUELLTEXTFELDER]
    except Exception:
        felder = []
    meta = getattr(idx.fast_index, "doc_metadata", None) or {}
    anzahl = int(_anfaenge(idx).size)
    codes = {f: np.full(anzahl, -1, dtype=np.int64) for f in felder}
    werte: Dict[str, Dict[str, int]] = {f: {} for f in felder}
    if felder:
        for d in range(anzahl):
            m = meta.get(d)
            if not isinstance(m, dict):
                continue
            for f in felder:
                w = m.get(f)
                if w in (None, ""):
                    continue
                zuordnung = werte[f]
                codes[f][d] = zuordnung.setdefault(str(w), len(zuordnung))
    try:
        idx._quelltext_codes_cache = codes
    except Exception:
        pass
    return codes


_WAEHLEN = object()


def clustercodes(idx: Any, ids: np.ndarray, feld: Any = _WAEHLEN) -> tuple[np.ndarray, Optional[str]]:
    """Clustercode je Dokument von ``ids`` und das Quelltextfeld (None: Dokumente).

    Ohne ``feld`` wird es fuer diesen Bereich gewaehlt, nach derselben Regel
    wie docset_profile.source_text_count. Zeilen einer Aufschluesselung
    bekommen das Feld des Ganzen, damit Ganzes und Zeilen gleich clustern."""
    from candyconc.services.tools.docset_profile import waehle_quelltextfeld

    codes = _codes_je_feld(idx)
    ids = np.asarray(ids, dtype=np.int64)
    if feld is _WAEHLEN:
        feld = None
        if codes:
            anfaenge = _anfaenge(idx)
            enden = np.append(anfaenge[1:], int(idx.fast_index.token_store.token_count))
            laengen = (enden - anfaenge)[ids]
            kandidaten = []
            for f, c in codes.items():
                belegt = c[ids] >= 0
                kandidaten.append((f, int(laengen[belegt].sum()),
                                   int(np.unique(c[ids][belegt]).size)))
            feld = waehle_quelltextfeld(kandidaten)
    if feld is None or feld not in codes:
        return ids.copy(), None
    eigene = codes[feld][ids]
    # Ein Dokument ohne Feldwert ist sein eigener Cluster.
    return np.where(eigene >= 0, eigene, -1 - ids), feld


def _verhaeltnis_ci(y: np.ndarray, n: np.ndarray, cluster: int) -> Optional[tuple[float, float, float]]:
    """(R, untere, obere Grenze) des Verhaeltnisschaetzers, linearisierte Clustervarianz."""
    summe_n = float(n.sum())
    if summe_n <= 0 or cluster < 2:
        return None
    r = float(y.sum()) / summe_n
    rest = y - r * n
    varianz = cluster / (cluster - 1) * float((rest * rest).sum()) / (summe_n * summe_n)
    halb = Z95 * math.sqrt(max(varianz, 0.0))
    return r, max(0.0, r - halb), r + halb


def _rate(wert: float) -> float:
    return round(wert, 1) if wert == 0 or wert >= 1 else float(f"{wert:.2g}")


def kennzahlen(
    idx: Any,
    ids: np.ndarray,
    positionen: np.ndarray,
    codes: np.ndarray,
    feld: Optional[str],
) -> Dict[str, Any]:
    """Dokumente und Quelltexte mit Treffer, clusterrobustes Intervall der Rate."""
    ids = np.asarray(ids, dtype=np.int64)
    treffer = treffer_je_dokument(idx, ids, positionen)
    woerter = idx.analysetoken_je_dokument()[ids]
    mit_treffer = treffer > 0
    aus: Dict[str, Any] = {"docs_with_hits": int(mit_treffer.sum())}
    if feld is not None:
        aus["source_texts_with_hits"] = int(np.unique(codes[mit_treffer]).size)
    einzel, invers = np.unique(codes, return_inverse=True)
    y = np.bincount(invers, weights=treffer, minlength=einzel.size)
    n = np.bincount(invers, weights=woerter, minlength=einzel.size)
    ci = _verhaeltnis_ci(y, n, int((n > 0).sum()))
    if ci is not None:
        aus["per_million_ci"] = [_rate(ci[1] * 1e6), _rate(ci[2] * 1e6)]
    return aus


def anteil_je_zeile(
    zeilen_treffer: Sequence[np.ndarray], codes_ganz: np.ndarray, treffer_ganz: np.ndarray,
) -> List[Optional[Dict[str, Any]]]:
    """Anteil jeder Zeile an allen Treffern mit clusterrobustem Intervall.

    ``treffer_ganz`` und jedes Element von ``zeilen_treffer`` sind Treffer je
    Dokument des ganzen Bereichs (gleiche Reihenfolge wie ``codes_ganz``)."""
    einzel, invers = np.unique(codes_ganz, return_inverse=True)
    y = np.bincount(invers, weights=treffer_ganz, minlength=einzel.size)
    gesamt = float(y.sum())
    cluster = int(einzel.size)
    aus: List[Optional[Dict[str, Any]]] = []
    for zeile in zeilen_treffer:
        if gesamt <= 0 or cluster < 2:
            aus.append(None)
            continue
        yz = np.bincount(invers, weights=zeile, minlength=einzel.size)
        p = float(yz.sum()) / gesamt
        rest = yz - p * y
        varianz = cluster / (cluster - 1) * float((rest * rest).sum()) / (gesamt * gesamt)
        halb = Z95 * math.sqrt(max(varianz, 0.0))
        aus.append({"share": round(p, 4),
                    "share_ci": [round(max(0.0, p - halb), 4), round(min(1.0, p + halb), 4)]})
    return aus


def treffer_je_dokument(idx: Any, ids: np.ndarray, positionen: np.ndarray) -> np.ndarray:
    """Treffer je Dokument von ``ids`` (Reihenfolge von ids)."""
    ids = np.asarray(ids, dtype=np.int64)
    dok = np.searchsorted(_anfaenge(idx), positionen, side="right") - 1
    zaehlung = np.bincount(dok, minlength=int(_anfaenge(idx).size))
    return zaehlung[ids].astype(np.int64)


def fuer_zaehlung(
    idx: Any, query: str, docset_mask: Any, total: int, bereich_ids: Optional[np.ndarray],
    *, mit_zeilen: bool = True, server: Any,
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Return whole-query fields and row context, or ``({}, None)``.

    Require word counts and query positions matching ``total`` exactly.
    Use ``mit_zeilen=False`` for a where boundary because breakdown rows omit
    that boundary from their denominators. Log failures without losing the count.
    """
    if getattr(type(idx), "analysetoken_je_dokument", None) is None:
        return {}, None
    try:
        positionen = trefferpositionen(idx, query, docset_mask, total, server=server)
        if positionen is None:
            return {}, None
        if bereich_ids is None:
            bereich_ids = np.arange(int(_anfaenge(idx).size), dtype=np.int64)
        bereich_ids = np.asarray(bereich_ids, dtype=np.int64)
        codes, feld = clustercodes(idx, bereich_ids)
        oben = kennzahlen(idx, bereich_ids, positionen, codes, feld)
        oben["ci_cluster"] = feld or "dokument"
        kontext = {"positionen": positionen, "feld": feld,
                   "bereich_ids": bereich_ids, "codes": codes}
        return oben, (kontext if mit_zeilen else None)
    except Exception:  # pragma: no cover - Schutz der Zaehlung
        import logging

        logging.getLogger(__name__).warning("hit_spread fehlgeschlagen", exc_info=True)
        return {}, None


def kwic_felder(idx: Any, query: str, docset_mask: Any, total: Any,
                bereich_ids: Any, *, server: Any) -> Dict[str, Any]:
    """Report documents and source texts containing the KWIC query's hits.

    Use the exact query positions only when their count equals ``total``.
    This exposes coverage directly instead of estimating it from a variant count.
    """
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        return {}
    oben, _ = fuer_zaehlung(idx, str(query), docset_mask, int(total), bereich_ids,
                             mit_zeilen=False, server=server)
    return {feld: oben[feld] for feld in ("docs_with_hits", "source_texts_with_hits")
            if feld in oben}
