from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Optional, Tuple
import numpy as np
import pandas as pd

from .lexicon import Lexicon


_CACHE_SCHEMA_VERSION = 2


class CollocationCache:
    def __init__(self, base_dir: Path, index_name: str):
        self.base_dir = Path(base_dir) / index_name
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _hash_stoplist(self, stoplist_ids: Optional[Iterable[int]]) -> str:
        if not stoplist_ids:
            return "none"
        ids = np.fromiter(sorted(stoplist_ids), dtype=np.uint32)
        digest = hashlib.sha1(ids.tobytes()).hexdigest()
        return digest[:12]

    def make_key(
        self,
        *,
        term_id: int,
        window_left: int,
        window_right: int,
        within_sentence: bool,
        pair_semantics: bool,
        stoplist_ids: Optional[Iterable[int]],
        top_n: Optional[int],
        attr_name: str,
    ) -> str:
        stop_hash = self._hash_stoplist(stoplist_ids)
        top_key = top_n if top_n is not None else 0
        return (
            f"v{_CACHE_SCHEMA_VERSION}_{attr_name}_tid{term_id}_w{window_left}_{window_right}"
            f"_s{int(within_sentence)}_p{int(pair_semantics)}_n{top_key}_x{stop_hash}"
        )

    def _path(self, key: str) -> Path:
        return self.base_dir / f"{key}.npz"

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def load(self, key: str, lexicon: Lexicon) -> Optional[pd.DataFrame]:
        path = self._path(key)
        if not path.exists():
            return None
        data = np.load(path, allow_pickle=False)
        required = {
            "word_id",
            "observed",
            "expected",
            "mi",
            "lmi",
            "npmi",
            "z",
            "chi2_cell",
            "t_score",
            "log_likelihood",
            "dice",
            "rank",
        }
        if not required.issubset(set(data.files)):
            return None
        word_ids = data["word_id"].astype(np.int64, copy=False)
        words = lexicon.get_strings_for_ids(word_ids)
        observed = data["observed"].astype(np.int64, copy=False)
        expected = data["expected"].astype(np.float64, copy=False)
        mi = data["mi"].astype(np.float64, copy=False)
        lmi = data["lmi"].astype(np.float64, copy=False)
        npmi = data["npmi"].astype(np.float64, copy=False)
        z_score = data["z"].astype(np.float64, copy=False)
        return pd.DataFrame({
            "word": words,
            "observed": observed,
            "expected": expected,
            "mi": mi,
            "lmi": lmi,
            "npmi": npmi,
            "z": z_score,
            "chi2_cell": data["chi2_cell"].astype(np.float64, copy=False),
            "t_score": data["t_score"].astype(np.float64, copy=False),
            "log_likelihood": data["log_likelihood"].astype(np.float64, copy=False),
            "dice": data["dice"].astype(np.float64, copy=False),
            "rank": data["rank"].astype(np.int64, copy=False),
        })

    def save(
        self,
        key: str,
        arrays: Tuple[
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
        ],
    ) -> None:
        path = self._path(key)
        (
            word_ids,
            observed,
            expected,
            mi,
            lmi,
            npmi,
            z_score,
            chi2_cell,
            t_score,
            log_likelihood,
            dice,
            ranks,
        ) = arrays
        np.savez_compressed(
            path,
            word_id=word_ids.astype(np.uint32, copy=False),
            observed=observed.astype(np.float64, copy=False),
            expected=expected.astype(np.float64, copy=False),
            mi=mi.astype(np.float64, copy=False),
            lmi=lmi.astype(np.float64, copy=False),
            npmi=npmi.astype(np.float64, copy=False),
            z=z_score.astype(np.float64, copy=False),
            chi2_cell=chi2_cell.astype(np.float64, copy=False),
            t_score=t_score.astype(np.float64, copy=False),
            log_likelihood=log_likelihood.astype(np.float64, copy=False),
            dice=dice.astype(np.float64, copy=False),
            rank=ranks.astype(np.int64, copy=False),
        )
