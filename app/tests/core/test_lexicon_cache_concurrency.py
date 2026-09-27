"""The lexicon string cache supports concurrent readers."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from candyconc.core.lexicon import Lexicon

INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not INDEX_PATH or not Path(INDEX_PATH).exists(),
    reason="CANDYCONC_INDEX_PATH must point at a real Fast Index",
)


def test_nebenlaeufige_zugriffe_werfen_nicht_und_liefern_denselben_wert() -> None:
    lex = Lexicon.load(Path(INDEX_PATH) / "word_lexicon.bin")
    kennungen = list(range(1, min(lex.vocab_size, 400)))
    erwartet = {i: lex.get_string(i) for i in kennungen}
    lex._string_cache_max = 8
    lex._string_cache.clear()

    def lies(start: int) -> list:
        fehler = []
        for runde in range(40):
            for i in kennungen[start % 7::7]:
                try:
                    if lex.get_string(i) != erwartet[i]:
                        fehler.append(("falsch", i))
                except Exception as exc:  # noqa: BLE001 - genau das wird geprueft
                    fehler.append((type(exc).__name__, i))
        return fehler

    # Ohne haeufigen Threadwechsel ist das Fenster zwischen get und
    # move_to_end zu klein, und die Probe bestand auch ohne Sperre.
    alt = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            fehler = [f for teil in pool.map(lies, range(32)) for f in teil]
    finally:
        sys.setswitchinterval(alt)
    assert fehler == [], f"{len(fehler)} Fehlzugriffe, zuerst {fehler[:3]}"
