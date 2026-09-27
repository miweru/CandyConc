"""Describe how returned concordance rows are distributed across versions.

Read document metadata at each row's position rather than parsing filenames.
Add the distribution before the model view, evidence surface and package are
formed so all three receive the same explanation.

Also list axis values present in the query scope that supply no returned row.
This distinguishes the displayed sample's coverage from the whole subcorpus.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

#: Werkzeuge, deren Zeilen KWIC-Treffer mit Korpusposition ``pos`` sind.
KWIC_WERKZEUGE = frozenset({"run_cqlf_query"})

# Use schema fields from broader registers to narrower sources.
# When all rows share one version-axis value, these fields still describe
# the distribution of the returned concordance rows.
GLIEDERUNGSFELDER = ("register", "source")

#: So viele Werte nennt die Zusatzangabe, der Rest steht als Anzahl da.
GLIEDERUNG_SICHTBAR = 6

_ACHSE_JE_INDEX: Dict[tuple, Optional[str]] = {}


def fassungsachse(idx: Any) -> Optional[str]:
    """Find the metadata axis distinguishing versions of a source text.

    Require a paired corpus or source-text information in the corpus card.
    Select an axis classified as contrastable from the manifest's pair_axes,
    falling back to model. Use the same field cardinalities and document count
    as the turn's corpus card.
    """
    # Nach dem aufgeloesten Indexpfad, nicht nach id(idx): eine Python-ID wird
    # nach der Speicherbereinigung neu vergeben, und der Server wechselt Korpora.
    # In der vollen Suite lieferte der Cache so einem neuen Index die Achse eines
    # alten (None). Ohne Pfad gibt es keinen Cache.
    pfad = str(getattr(idx, "path", "") or "")
    schluessel = (str(Path(pfad).resolve()),) if pfad else None
    if schluessel is not None and schluessel in _ACHSE_JE_INDEX:
        return _ACHSE_JE_INDEX[schluessel]
    achse: Optional[str] = None
    try:
        # Absolut, wie docset_profile: unter dem Aliaspaket candyconc_copilot
        # (Testumgebung) fand der relative Import ein Ersatzmodul ohne diese
        # Funktion, und die Angabe fiel still weg.
        from candyconc.candyconc_copilot.prompts import _read_meta_field_cardinality
        from candyconc.candyconc_copilot.recipe_runtime import corpus_card_from_context

        karte = corpus_card_from_context({
            "corpus_docs": len(idx.fast_index.doc_metadata),
            "corpus_meta_fields": [str(f) for f in idx.metadata_fields()],
            "corpus_meta_field_cardinality": _read_meta_field_cardinality(idx.path),
        })
        manifest = getattr(idx, "manifest", None)
        if karte.get("quelltexte") or bool(getattr(manifest, "paired", False)):
            arten = {
                str(a.get("field")): a.get("kind")
                for a in karte.get("meta_axes") or ()
                if isinstance(a, dict)
            }
            kandidaten = [str(a) for a in getattr(manifest, "pair_axes", None) or ()]
            achse = next(
                (f for f in [*kandidaten, "model"] if arten.get(f) == "axis"), None
            )
    except Exception:  # noqa: BLE001 - ohne Karte keine Angabe, die Ausgabe bleibt
        logger.debug("Fassungsachse nicht bestimmbar", exc_info=True)
        achse = None
    if schluessel is not None:
        _ACHSE_JE_INDEX[schluessel] = achse
    return achse


def werte_im_bereich(ausgabe: Dict[str, Any], idx: Any, achse: str) -> Optional[Set[str]]:
    """Die Werte der Achse, die im Bereich der Abfrage mindestens ein Dokument haben.

    Die Werte und ihre Dokumente führt der Metaindex. Den Bereich nennt
    ``scope`` der Ausgabe: ``corpus`` ist das ganze Korpus, ``docset`` ein
    Docset, eine ``where()``-Einschränkung im Abfragetext oder beides. Die
    Dokumente eines Docsets stehen im Docset-Speicher, die eines ``where()``
    liefert ``meta_filters.where_dokumente``, mit dem auch das Werkzeug seinen
    Scope bildet. Ein Docset aus lauter menschlichen Texten schließt die
    Modelle aus, und ausgeschlossene Werte fehlen nicht.

    ``None`` heißt: der Bereich ist nicht sicher bestimmt, etwa weil das
    Docset nicht mehr im Speicher liegt oder die nachgebildete Dokumentzahl
    von ``scope.doc_count`` abweicht. Dann bleibt die Angabe weg, statt eine
    geratene Liste zu zeigen.
    """
    import numpy as np
    from cqlhpc.ast import MetaCond

    try:
        meta = getattr(idx.fast_index, "meta_index", None)
        feld = (getattr(meta, "fields", None) or {}).get(achse)
        scope = ausgabe.get("scope")
        if feld is None or not feld.has_str or not isinstance(scope, dict):
            return None
        anzahl = int(meta.doc_count)
        maske = None
        if scope.get("level") == "docset":
            from candyconc.core.meta_filters import where_dokumente
            from candyconc.services.backend.docsets import _get_docset

            ids = None
            if scope.get("docset_id"):
                ids = np.asarray(_get_docset(str(scope["docset_id"]))["doc_ids"], dtype=np.int64)
            eng = where_dokumente(idx, ausgabe.get("query"))
            if eng is not None:
                eng = np.asarray(eng, dtype=np.int64)
                ids = eng if ids is None else np.intersect1d(ids, eng)
            if ids is None or len(ids) != int(scope.get("doc_count", -1)):
                return None
            maske = np.zeros(anzahl, dtype=bool)
            maske[ids] = True
        elif scope.get("level") != "corpus":
            return None
        werte: Set[str] = set()
        for wert, _ in feld.sample_str_values(max_scan=sys.maxsize):
            if maske is not None and not bool(
                (feld.mask_for_cond(MetaCond(field=achse, op="=", value=wert), anzahl) & maske).any()
            ):
                continue
            if str(wert).strip():
                werte.add(str(wert).strip())
        return werte
    except Exception:  # noqa: BLE001 - ohne sicheren Bereich keine Liste, die Zählung bleibt
        logger.debug("Werte im Bereich nicht bestimmbar", exc_info=True)
        return None


def zeilen_nach_fassung(ausgabe: Dict[str, Any], idx: Any, achse: str) -> str:
    """``Zeilen nach <achse>: wert n, ...`` ueber alle gelieferten Zeilen.

    Jede Zeile zaehlt mit dem Wert ihres Dokuments, das die Dokumentgrenzen des
    Index zur Position ``pos`` bestimmen. Traegt eine Zeile keine Position,
    entsteht keine Angabe: eine Verteilung ueber einen Teil der Zeilen waere
    eine falsche Zahl.

    Dahinter stehen die Werte ohne Zeile (``werte_im_bereich``), aber nur, wenn
    jeder gezählte Wert unter den Werten des Bereichs ist. Widersprechen sich
    Metaindex und Dokument-Metadaten, wäre auch die Differenz falsch.
    """
    import numpy as np

    zeilen = ausgabe.get("rows")
    if not isinstance(zeilen, list) or not zeilen:
        return ""
    positionen = []
    for zeile in zeilen:
        pos = zeile.get("pos") if isinstance(zeile, dict) else None
        if isinstance(pos, bool) or not isinstance(pos, (int, np.integer)):
            return ""
        positionen.append(int(pos))
    grenzen = idx.fast_index.boundaries.document._positions
    dokumente = np.searchsorted(
        np.asarray(grenzen, dtype=np.int64),
        np.asarray(positionen, dtype=np.int64),
        side="right",
    ) - 1
    metadaten = idx.fast_index.doc_metadata
    zaehlung: Counter = Counter()
    for dokument in dokumente.tolist():
        eintrag = metadaten.get(int(dokument)) if dokument >= 0 else None
        wert = str(eintrag.get(achse) or "").strip() if isinstance(eintrag, dict) else ""
        zaehlung[wert or f"ohne {achse}"] += 1
    teile = ", ".join(
        f"{wert} {anzahl}"
        for wert, anzahl in sorted(zaehlung.items(), key=lambda p: (-p[1], p[0]))
    )
    zeile = f"Zeilen nach {achse}: {teile}"
    moeglich = werte_im_bereich(ausgabe, idx, achse)
    gezaehlt = set(zaehlung) - {f"ohne {achse}"}
    if moeglich is not None and gezaehlt <= moeglich and moeglich - gezaehlt:
        zeile += ". Ohne Zeile: " + ", ".join(sorted(moeglich - gezaehlt))
    # Nur eine Seite der Fassungsachse im Bereich (ein menschliches Docset, ein
    # einzelnes Modell): dann die Häufung nach dem ersten Gliederungsfeld, das
    # über die Zeilen variiert. Mehrseitige Bereiche bleiben, wie sie waren.
    einseitig = len(moeglich) <= 1 if moeglich is not None else len(gezaehlt) <= 1
    if einseitig:
        gliederung = _nach_gliederungsfeld(dokumente.tolist(), metadaten, achse)
        if gliederung:
            zeile += ". " + gliederung
    return zeile


def _nach_gliederungsfeld(dokumente: list, metadaten: Any, achse: str) -> str:
    """``Nach <feld>: wert n, ...`` für das erste Gliederungsfeld mit mehr als einem Wert."""
    for feld in GLIEDERUNGSFELDER:
        if feld == achse:
            continue
        zaehlung: Counter = Counter()
        for dokument in dokumente:
            eintrag = metadaten.get(int(dokument)) if dokument >= 0 else None
            wert = str(eintrag.get(feld) or "").strip() if isinstance(eintrag, dict) else ""
            zaehlung[wert or f"ohne {feld}"] += 1
        if len(set(zaehlung) - {f"ohne {feld}"}) < 2:
            continue
        geordnet = sorted(zaehlung.items(), key=lambda p: (-p[1], p[0]))
        teile = ", ".join(f"{wert} {anzahl}" for wert, anzahl in geordnet[:GLIEDERUNG_SICHTBAR])
        rest = len(geordnet) - GLIEDERUNG_SICHTBAR
        return f"Nach {feld}: {teile}" + (f", +{rest} weitere" if rest > 0 else "")
    return ""


def mit_fassungsverteilung(werkzeug: Any, ausgabe: Any) -> Any:
    """Die Ausgabe mit ``verteilung`` vor ihren Zeilen, sonst unveraendert.

    Die Zeilen stammen vom aktiven Index (``tool_wrappers._get_index``, ein
    anderes Korpus weist run_cqlf_query ab). Nennt der Scope trotzdem ein
    anderes Korpus, gehoeren die Positionen nicht zu diesen Metadaten, und die
    Ausgabe bleibt, wie sie ist.
    """
    if (
        str(werkzeug or "") not in KWIC_WERKZEUGE
        or not isinstance(ausgabe, dict)
        or str(ausgabe.get("status") or "success") != "success"
        or not ausgabe.get("rows")
        or "verteilung" in ausgabe
    ):
        return ausgabe
    try:
        from candyconc.core import query_runtime

        idx = query_runtime._CORPUS_INDEX
        if idx is None:
            return ausgabe
        korpus = str((ausgabe.get("scope") or {}).get("corpus_id") or "").strip()
        namen = {
            Path(str(p)).name
            for p in (getattr(idx, "path", None), getattr(idx.fast_index, "index_path", None))
            if p
        }
        if korpus and korpus != "default" and namen and korpus not in namen:
            return ausgabe
        achse = fassungsachse(idx)
        zeile = zeilen_nach_fassung(ausgabe, idx, achse) if achse else ""
    except Exception:  # noqa: BLE001 - die Angabe ist eine Zugabe und stuerzt keinen Aufruf
        logger.debug("Fassungsverteilung nicht bestimmbar", exc_info=True)
        return ausgabe
    if not zeile:
        return ausgabe
    angereichert: Dict[str, Any] = {}
    for schluessel, wert in ausgabe.items():
        if schluessel == "rows":
            angereichert["verteilung"] = zeile
        angereichert[schluessel] = wert
    return angereichert
