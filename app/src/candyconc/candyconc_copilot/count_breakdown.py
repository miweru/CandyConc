# -*- coding: utf-8 -*-
"""Break down a query count by a metadata field in one tool call.

Each row uses the same document selection, query counter and word-token
denominator as a separately created docset. This keeps the result independent
of how the model batches tool calls.

The caller supplies ``server``. Its attributes are read at call time so the
copilot package does not import the backend module.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

import numpy as np

from .word_denominator import nenner, rate_je_million

#: Mehr Werte ergeben keine Tabelle, die ein Modell lesen kann (ref_doc hat
#: 19.272). Die Absage nennt die Zahl.
HOECHSTENS_WERTE = 50

#: Das Metadatenfeld, dessen Werte die Herstellungsverfahren trennen (PING:
#: je Generator ein Wert, dazu die Direktueberarbeitung und das Original).
VERFAHRENSFELD = "variant"

#: Felder mit einem Herstellungsverfahren je Wert (``prompting_method`` ist
#: ``variant`` ohne das Original). Nach ihnen steht am Ende der Zeilen eine
#: Zeile für alle Generatoren zusammen.
VERFAHRENSFELDER = (VERFAHRENSFELD, "prompting_method")

#: Etikett dieser Zeile, ``procedures`` nennt ihre Verfahren.
GENERATORZEILE = "Generatoren zusammen"


def _verfahrenscodes(idx: Any) -> Optional[tuple[np.ndarray, List[str]]]:
    """Code des Verfahrens je Dokument (-1 ohne Wert) und die Namen, einmal je Index."""
    vorhanden = getattr(idx, "_verfahren_codes_cache", None)
    if vorhanden is not None:
        return vorhanden or None
    meta = getattr(getattr(idx, "fast_index", None), "doc_metadata", None) or {}
    try:
        anzahl = int(idx.fast_index.boundaries.document._positions.size)
    except Exception:
        anzahl = 0
    codes = np.full(anzahl, -1, dtype=np.int64)
    namen: Dict[str, int] = {}
    for d in range(anzahl):
        m = meta.get(d)
        wert = m.get(VERFAHRENSFELD) if isinstance(m, dict) else None
        if wert not in (None, ""):
            codes[d] = namen.setdefault(str(wert), len(namen))
    ergebnis = (codes, list(namen)) if len(namen) > 1 else ()
    try:
        idx._verfahren_codes_cache = ergebnis
    except Exception:
        pass
    return ergebnis or None


def mischverfahren(zeilen_ids: List[np.ndarray], codes: np.ndarray,
                   namen: List[str]) -> List[Optional[Dict[str, int]]]:
    """Report procedure counts for rows that exceptionally mix procedures.

    When most rows contain one procedure, a row containing several needs a
    breakdown to distinguish a procedure effect from a group effect. Partitions
    whose rows all mix the same procedures do not need this exception notice.
    """
    je_zeile: List[Dict[str, int]] = []
    for ids in zeilen_ids:
        eigene = codes[np.asarray(ids, dtype=np.int64)]
        werte, anzahl = np.unique(eigene[eigene >= 0], return_counts=True)
        je_zeile.append(dict(sorted((namen[int(w)], int(n)) for w, n in zip(werte, anzahl))))
    rein = sum(1 for verfahren in je_zeile if len(verfahren) == 1)
    if rein * 2 <= len(je_zeile):
        return [None] * len(je_zeile)
    return [verfahren if len(verfahren) > 1 else None for verfahren in je_zeile]


def ids_mit_filtern(idx: Any, filters: Optional[Mapping[str, Any]], basis: Optional[np.ndarray],
                    *, server: Any) -> Optional[np.ndarray]:
    """Die Dokumente der Filter, geschnitten mit einem Teilkorpus, falls gesetzt."""
    if not filters:
        return basis
    ids = np.asarray(server._doc_ids_from_meta(idx, dict(filters)), dtype=np.uint32)
    if basis is not None:
        ids = np.intersect1d(ids, np.asarray(basis, dtype=np.uint32), assume_unique=False)
    return ids


def _zaehler(idx: Any, query: str, case_insensitive: bool, server: Any) -> Callable[[np.ndarray], int]:
    from candyconc.core.fast_index_native import docset_mask_from_ids

    n_docs = int(idx.fast_index.boundaries.document._positions.size)

    def zaehle(ids: np.ndarray) -> int:
        maske = docset_mask_from_ids(np.asarray(ids, dtype=np.uint32), n_docs)
        total, _ms, _teil = server._compute_query_count(
            idx, str(query), 0, None, None, maske, case_insensitive=case_insensitive
        )
        return int(total)

    return zaehle


def zeilen(
    idx: Any,
    query: str,
    *,
    nach: Optional[str],
    filters: Optional[Mapping[str, Any]],
    basis: Optional[np.ndarray],
    case_insensitive: bool,
    kontext: Optional[Dict[str, Any]] = None,
    server: Any,
) -> Dict[str, Any]:
    """``{"nach": feld, "rows": [...]}`` je Wert des Feldes, sonst leer."""
    if not nach:
        return {}
    from .tool_errors import ToolInputError

    werte = [w for w in (idx.metadata_values(str(nach), filters=dict(filters or {})) or []) if w not in (None, "")]
    if not werte:
        raise ToolInputError(f"Feld '{nach}' hat im gewählten Bereich keine Werte.")
    if len(werte) > HOECHSTENS_WERTE:
        raise ToolInputError(
            f"Feld '{nach}' hat {len(werte)} Werte, aufgeschlüsselt werden höchstens "
            f"{HOECHSTENS_WERTE}. Mit filters einschränken oder ein Feld mit weniger Werten wählen."
        )
    zaehle = _zaehler(idx, query, case_insensitive, server)
    je_dokument: Optional[np.ndarray] = None
    rows: List[Dict[str, Any]] = []
    masken: List[Optional[np.ndarray]] = []
    zeilen_ids: List[np.ndarray] = []
    for wert in werte:
        ids = ids_mit_filtern(idx, {**dict(filters or {}), str(nach): wert}, basis, server=server)
        if ids is None or ids.size == 0:
            continue
        zeilen_ids.append(ids)
        # Use the value's analysis-token count for rates and dispersion.
        # Keep the raw token count alongside it.
        bezug = nenner(idx, ids)
        token = int(bezug["woerter"])
        try:
            total = zaehle(ids) if je_dokument is None else int(je_dokument[np.asarray(ids, dtype=np.int64)].sum())
        except RuntimeError as exc:
            # Count a single cell through per-document type postings so a broad
            # pattern is handled here without escaping query_count's error translation.
            if "Treffer zu gross" not in str(exc):
                raise
            from candyconc.services.backend.regex_type_count import treffer_je_dokument

            je_dokument = treffer_je_dokument(idx, query, server._linebreak_sentinel_word_id)
            if je_dokument is None:
                raise ToolInputError(
                    f"{exc} Die Aufschlüsselung zählt je Wert über Positionen, dort gilt diese "
                    "Grenze. Ohne nach zählt query_count die Korpuszahl eines solchen Musters "
                    "ohne Grenze, je Wert nur ein engeres Muster."
                ) from exc
            total = int(je_dokument[np.asarray(ids, dtype=np.int64)].sum())
        zeile = {
            "wert": str(wert),
            "total": total,
            "docs": int(ids.size),
            "tokens": token,
            "tokens_raw": int(bezug["roh"]),
            "per_million": rate_je_million(total, token),
        }
        maske = None
        if kontext is not None:
            # Report documents and source texts with hits, plus the rate interval
            # using the same clustering as the whole query.
            from . import hit_spread as _ts

            if int(_ts.treffer_je_dokument(idx, ids, kontext["positionen"]).sum()) == int(total):
                codes, _ = _ts.clustercodes(idx, ids, kontext["feld"])
                zeile.update(_ts.kennzahlen(idx, ids, kontext["positionen"], codes, kontext["feld"]))
                maske = np.isin(kontext["bereich_ids"], np.asarray(ids, dtype=np.int64))
        rows.append(zeile)
        masken.append(maske)
    if kontext is not None and rows and all(m is not None for m in masken):
        from . import hit_spread as _ts

        ganz = _ts.treffer_je_dokument(idx, kontext["bereich_ids"], kontext["positionen"])
        for zeile, anteil in zip(rows, _ts.anteil_je_zeile(
                [ganz * m for m in masken], kontext["codes"], ganz)):
            if anteil:
                zeile.update(anteil)
    verfahrenscodes = _verfahrenscodes(idx) if str(nach) != VERFAHRENSFELD else None
    if verfahrenscodes:
        for zeile, verfahren in zip(rows, mischverfahren(zeilen_ids, *verfahrenscodes)):
            if verfahren:
                zeile["procedures"] = verfahren
    # Die Streuung gilt den Werten des Feldes, die Summenzeile kommt danach.
    ergebnis = {"nach": str(nach), "rows": rows, **streuung(rows)}
    zusammen = generatorzeile(idx, rows, zeilen_ids, kontext) if str(nach) in VERFAHRENSFELDER else None
    if zusammen:
        rows.append(zusammen)
    return ergebnis


def generatorzeile(
    idx: Any,
    rows: List[Dict[str, Any]],
    zeilen_ids: List[np.ndarray],
    kontext: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Combine multiple generator procedures when other procedures are also present.

    Sum hits and token denominators before calculating the rate. The summary
    is not a metadata value, so it has no share and does not affect dispersion.
    """
    teil = [(zeile, ids) for zeile, ids in zip(rows, zeilen_ids)
            if "generator" in str(zeile.get("wert", ""))]
    if len(teil) < 2 or len(teil) == len(rows):
        return None
    ids = np.sort(np.concatenate([np.asarray(i, dtype=np.int64) for _, i in teil]))
    total = sum(int(zeile.get("total") or 0) for zeile, _ in teil)
    token = sum(int(zeile.get("tokens") or 0) for zeile, _ in teil)
    zusammen: Dict[str, Any] = {
        "wert": GENERATORZEILE,
        "total": total,
        "docs": int(ids.size),
        "tokens": token,
        "tokens_raw": sum(int(zeile.get("tokens_raw") or 0) for zeile, _ in teil),
        "per_million": rate_je_million(total, token),
        "procedures": {str(zeile["wert"]): int(zeile.get("docs") or 0) for zeile, _ in teil},
    }
    if kontext is not None:
        from . import hit_spread as _ts

        if int(_ts.treffer_je_dokument(idx, ids, kontext["positionen"]).sum()) == total:
            codes, _ = _ts.clustercodes(idx, ids, kontext["feld"])
            zusammen.update(_ts.kennzahlen(idx, ids, kontext["positionen"], codes, kontext["feld"]))
    return zusammen


def streuung(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute Gries' DP over metadata values and its normalized form.

    DP is 0.5 times the sum of |t_i/T - n_i/N|, with token counts t and hit
    counts n per value (Gries 2008). Normalize by 1 - min(t_i/T)
    (Lijffijt and Gries 2012). Require at least two values and one hit.
    """
    t = [int(z.get("tokens") or 0) for z in rows]
    n = [int(z.get("total") or 0) for z in rows]
    T, N = sum(t), sum(n)
    if len(rows) < 2 or T <= 0 or N <= 0:
        return {}
    dp = 0.5 * sum(abs(ti / T - ni / N) for ti, ni in zip(t, n))
    kleinster = min(ti / T for ti in t)
    aus = {"dp_nach": round(dp, 4)}
    if kleinster < 1:
        aus["dp_norm_nach"] = round(dp / (1 - kleinster), 4)
    # Use the same reference values as dispersion_offsets. Gries' DP depends
    # on the number of hits, so interpreting it against a fixed 0-to-1 scale
    # without its count-dependent reference can misstate concentration.
    from candyconc.analysis_defaults import dispersion_referenzwerte

    referenz = dispersion_referenzwerte(t, N)
    aus["dp_min_nach"] = referenz["dp_min"]
    aus["dp_erwartet_nach"] = referenz["dp_erwartet"]
    return aus
