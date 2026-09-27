# -*- coding: utf-8 -*-
"""Present sampled concordance rows in draw order to the copilot.

The REST view sorts sampled indices for stable display and pagination.
Restore draw order here so a prefix does not favor early corpus sections.
The same seed reproduces the order.

Reorder in the tool before the model view, evidence entries and package
read the result. Their ``rows[i]`` references then identify the same row.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

from candyconc.i18n import lt

#: Was der sample-Block unter ``order`` meldet, wenn die Zeilen in Ziehungsfolge stehen.
IN_ZIEHUNGSFOLGE = lt("gezogen, nicht nach Korpusposition", "draw order, not corpus position")


def ziehungsrang(population: int, gezogen: int, seed: int) -> Optional[np.ndarray]:
    """Für jede Ziehung ihr Platz in der nach Position sortierten Stichprobe.

    Es ist dieselbe Ziehung wie in ``routes.query._sample_position_indices``, nur
    vor dem Sortieren. Ob sie es ist, prüft der Vergleich mit genau dieser
    Funktion. Zieht die REST-Naht einmal anders, gibt es keinen Rang, und die
    Zeilen bleiben, wie sie kamen, ohne Angabe einer Ziehungsfolge.

    ``None`` auch dann, wenn nichts gezogen wurde: umfasst die Stichprobe den
    ganzen Bestand, ist sie eine vollständige Liste.
    """
    from candyconc.services.backend.routes.query import _sample_position_indices

    if gezogen <= 0 or gezogen >= population:
        return None
    ziehung = np.random.default_rng(int(seed)).choice(
        int(population), size=int(gezogen), replace=False
    )
    sortiert = _sample_position_indices(int(population), int(gezogen), int(seed))
    if not np.array_equal(np.sort(ziehung), sortiert):
        return None
    return np.searchsorted(sortiert, ziehung)


def in_ziehungsfolge(
    zeilen: List[Any],
    meta: Mapping[str, Any],
    *,
    limit: int,
    sortiert: bool,
) -> Tuple[List[Any], Dict[str, str]]:
    """Return at most ``limit`` rows with sample-order metadata.

    REST supplies position-sorted rows or the requested explicit sort.
    When the sample exceeds the limit, draw a uniform subset using the same
    seed. Preserve requested sorting, otherwise return draw order. A complete
    unsampled list keeps corpus order and does not receive an order label.
    """
    seed = int(meta.get("seed") or 0)
    if len(zeilen) > limit:
        auswahl = random.Random(seed).sample(range(len(zeilen)), limit)
        if sortiert:
            return [zeilen[i] for i in sorted(auswahl)], {}
        return [zeilen[i] for i in auswahl], {"order": IN_ZIEHUNGSFOLGE}
    if sortiert:
        return list(zeilen), {}
    rang = ziehungsrang(int(meta.get("population") or 0), int(meta.get("drawn") or 0), seed)
    if rang is None or len(rang) != len(zeilen):
        return list(zeilen), {}
    return [zeilen[i] for i in rang.tolist()], {"order": IN_ZIEHUNGSFOLGE}


def liegt_in_ziehungsfolge(ausgabe: Any) -> bool:
    """Stehen die Zeilen dieser Werkzeugausgabe in Ziehungsfolge?

    Dann ist jeder Anfang der Liste selbst gleichverteilt, und ein Schnitt
    hinter den ersten Zeilen zeigt dieselben Zeilen wie die Belegaufzeichnung.
    """
    probe = ausgabe.get("sample") if isinstance(ausgabe, Mapping) else None
    return isinstance(probe, Mapping) and probe.get("order") in (IN_ZIEHUNGSFOLGE.de, IN_ZIEHUNGSFOLGE.en)
