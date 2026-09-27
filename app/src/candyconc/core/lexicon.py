"""
Lexicon and Global Frequencies for Collocation Engine.

Provides:
- Bidirectional ID↔string mapping
- Pre-computed global type frequencies
- Efficient lookup for statistics calculation
"""
from __future__ import annotations

import mmap
import struct
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional, Iterable, List
import numpy as np

from . import index_format

LOGGER = logging.getLogger(__name__)


def _fmix64(x: int) -> int:
    x ^= x >> 33
    x = (x * 0xff51afd7ed558ccd) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    x = (x * 0xc4ceb9fe1a85ec53) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    return x & 0xFFFFFFFFFFFFFFFF


def _hash64(text: str) -> int:
    h = 14695981039346656037
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return _fmix64(h)


class Lexicon:
    """
    Lexicon for a single attribute (word, lemma, pos).
    
    Provides O(1) lookups in both directions and pre-computed
    global frequencies for MI/LLR calculation.
    """
    
    def __init__(self):
        self._offsets: Optional[np.ndarray] = None
        self._freqs_arr: Optional[np.ndarray] = None
        self._strings_view: Optional[memoryview] = None
        self._strings_bytes: Optional[bytes] = None
        self._vocab_size: int = 0
        self._total_tokens: int = 0
        self._path: Optional[Path] = None
        self._hash_entries: Optional[np.ndarray] = None
        self._hash_buckets: Optional[np.ndarray] = None
        self._bucket_bits: int = 0
        self._mm: Optional[mmap.mmap] = None
        self._string_cache: "OrderedDict[int, str]" = OrderedDict()
        self._string_cache_max: int = 65536
        # The copilot runs the read-only tool calls of one round concurrently.
        # One thread can evict an entry between get and move_to_end of
        # another, which raises KeyError and reaches the model as HTTP 500 (7
        # of 11 parallel KWIC queries failed that way).
        #
        # NO LOCK. A threading.Lock around the cache deadlocked: 14 threads
        # waited in get_string for the lock at 0 percent CPU while no thread
        # was inside the critical section (stacks taken with SIGUSR1 and
        # sample). Every single OrderedDict operation is atomic under the
        # GIL, and the only race is the KeyError, which get_string catches.
        self._prefix_top: Optional[Dict[str, np.ndarray]] = None
        self._top_global_ids: Optional[np.ndarray] = None
        self._prefix_len: int = 0
        self._top_k: int = 0
        self._top_global: int = 0

    @staticmethod
    def _madvise(mm: mmap.mmap, advice: int) -> None:
        if hasattr(mm, "madvise"):
            try:
                mm.madvise(advice)
            except (ValueError, OSError):
                LOGGER.exception("madvise fehlgeschlagen für Lexikon mmap")
                raise RuntimeError("madvise fehlgeschlagen für Lexikon mmap")
        
    @classmethod
    def load(cls, path: Path) -> "Lexicon":
        """Load lexicon from binary file."""
        lex = cls()
        lex._path = Path(path)
        if not path.exists():
            raise RuntimeError(f"Lexikon fehlt: {path}. Bitte Index neu bauen.")
        with open(path, "rb") as f:
            header = f.read(index_format.LEXICON_HEADER_SIZE)
            if len(header) != index_format.LEXICON_HEADER_SIZE:
                raise RuntimeError(f"Lexikon Header ungültig: {path}. Bitte Index neu bauen.")
            magic, version, vocab_size, _, total_tokens, strings_len = struct.unpack(
                index_format.LEXICON_HEADER_STRUCT, header
            )
            if magic != index_format.LEXICON_MAGIC or version != index_format.LEXICON_VERSION:
                raise RuntimeError(f"Lexikon Format ungültig: {path}. Bitte Index neu bauen.")
            lex._vocab_size = int(vocab_size)
            lex._total_tokens = int(total_tokens)
            offsets_count = lex._vocab_size + index_format.LEXICON_OFFSETS_EXTRA
            offsets_bytes = offsets_count * 8
            freqs_bytes = offsets_count * 8
            offsets_offset = index_format.LEXICON_HEADER_SIZE
            freqs_offset = offsets_offset + offsets_bytes
            strings_offset = freqs_offset + freqs_bytes
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            lex._mm = mm
            lex._madvise(mm, mmap.MADV_RANDOM)
            # Truncation guard (D2): the strings region (and the offsets/freqs
            # tables that precede it) must fit inside the mapped file. A short
            # file would otherwise raise an opaque numpy/memoryview error or,
            # worse, silently read past the data. Fail closed with an
            # actionable message instead.
            file_size = mm.size()
            strings_end = strings_offset + int(strings_len)
            if strings_offset > file_size or strings_end > file_size:
                raise RuntimeError(
                    "Lexikon Daten unvollständig: "
                    f"{path} (erwartet {strings_end} Bytes, Datei hat {file_size}). "
                    "Bitte Index neu bauen."
                )
            lex._offsets = np.frombuffer(mm, dtype=np.uint64, offset=offsets_offset, count=offsets_count)
            lex._freqs_arr = np.frombuffer(mm, dtype=np.uint64, offset=freqs_offset, count=offsets_count)
            lex._strings_view = memoryview(mm)[strings_offset : strings_offset + int(strings_len)]
            lex._strings_bytes = None
        hash_path = path.with_suffix(".hash.bin")
        bucket_path = path.with_suffix(".bucket.bin")
        if not (hash_path.exists() and bucket_path.exists()):
            raise RuntimeError(f"Lexikon Hash Index fehlt: {path}. Bitte Index neu bauen.")
        with open(bucket_path, "rb") as f:
            header = f.read(16)
            if len(header) != 16:
                raise RuntimeError(f"Lexikon Hash Header ungültig: {bucket_path}. Bitte Index neu bauen.")
            bucket_bits, _, bucket_count = struct.unpack("<IIQ", header)
            bucket_bytes = f.read(8 * (bucket_count + 1))
            lex._hash_buckets = np.frombuffer(bucket_bytes, dtype=np.uint64)
            lex._bucket_bits = int(bucket_bits)
        with open(hash_path, "rb") as f:
            header = f.read(8)
            if len(header) != 8:
                raise RuntimeError(f"Lexikon Hash Header ungültig: {hash_path}. Bitte Index neu bauen.")
            count = struct.unpack("<Q", header)[0]
            entry_bytes = f.read()
            if count == 0:
                lex._hash_entries = np.zeros(
                    0, dtype=[("hash", np.uint64), ("lexid", np.uint32), ("pad", np.uint32)]
                )
            else:
                if not entry_bytes:
                    raise RuntimeError(
                        f"Lexikon Hash Eintraege leer: {hash_path}. Bitte Index neu bauen."
                    )
                lex._hash_entries = np.frombuffer(
                    entry_bytes,
                    dtype=[("hash", np.uint64), ("lexid", np.uint32), ("pad", np.uint32)],
                    count=count,
                )
        lex.load_prefix_top()
        return lex

    @property
    def strings_bytes(self) -> bytes:
        if self._strings_bytes is None:
            if self._strings_view is None:
                return b""
            self._strings_bytes = bytes(self._strings_view)
        return self._strings_bytes
        
    def _string_bounds(self, id_: int) -> tuple[int, int]:
        if self._offsets is None or self._strings_view is None:
            return (0, 0)
        if id_ < 0 or id_ >= len(self._offsets):
            return (0, 0)
        start = int(self._offsets[id_])
        if id_ + 1 < len(self._offsets):
            end = int(self._offsets[id_ + 1])
        else:
            end = len(self._strings_view)
        return (start, end)
            
    def get_id(self, string: str) -> int:
        """Get ID for string, 0 if not found."""
        if self._hash_entries is None or self._hash_buckets is None:
            raise RuntimeError("Lexikon Hash Index fehlt")
        if self._strings_view is None:
            raise RuntimeError("Lexikon Daten fehlen")
        h = _hash64(string)
        bucket = int(h >> (64 - self._bucket_bits)) if self._bucket_bits else 0
        if bucket + 1 >= len(self._hash_buckets):
            return 0
        start = int(self._hash_buckets[bucket])
        end = int(self._hash_buckets[bucket + 1])
        if end <= start:
            return 0
        target = string.encode("utf-8")
        hashes = self._hash_entries["hash"]
        local = np.searchsorted(hashes[start:end], h, side="left")
        pos = start + int(local)
        while pos < end and int(hashes[pos]) == h:
            lexid = int(self._hash_entries["lexid"][pos])
            b_start, b_end = self._string_bounds(lexid)
            if b_end - b_start == len(target):
                if self._strings_view[b_start:b_end] == target:
                    return lexid
            pos += 1
        return 0
        
    def get_string(self, id_: int) -> str:
        """Get string for ID, empty if not found."""
        if self._strings_view is None or self._offsets is None:
            return ""
        if id_ <= 0 or id_ >= len(self._offsets):
            return ""
        cache = self._string_cache
        cached = cache.get(id_)
        if cached is not None:
            try:
                cache.move_to_end(id_)
            except KeyError:
                pass  # eben von einem anderen Thread verdraengt, der Wert gilt
            return cached
        start, end = self._string_bounds(id_)
        if end <= start:
            return ""
        value = self._strings_view[start:end].tobytes().decode("utf-8")
        cache[id_] = value
        if len(cache) > self._string_cache_max:
            try:
                cache.popitem(last=False)
            except KeyError:
                pass  # ein anderer Thread hat schon verdraengt
        return value

    def get_strings_for_ids(self, ids: Iterable[int]) -> List[str]:
        """Get strings for multiple IDs."""
        get_string = self.get_string
        return [get_string(int(i)) for i in ids]
        
    def get_freq(self, id_: int) -> int:
        """Get global frequency for type ID."""
        if self._freqs_arr is None or id_ < 0 or id_ >= len(self._freqs_arr):
            return 0
        return int(self._freqs_arr[id_])

    def get_freqs_for_ids(self, ids: np.ndarray) -> np.ndarray:
        """Get frequencies for multiple IDs."""
        if self._freqs_arr is None:
            return np.zeros(len(ids), dtype=np.int64)
        return self._freqs_arr[ids].astype(np.int64, copy=False)

    def get_freqs_array(self) -> np.ndarray:
        """Get full frequency array."""
        if self._freqs_arr is None:
            return np.zeros(0, dtype=np.uint64)
        return self._freqs_arr
        
    def get_all_freqs(self) -> Dict[int, int]:
        """Get all frequencies as dict (for batch operations)."""
        if self._freqs_arr is None:
            return {}
        return {i: int(v) for i, v in enumerate(self._freqs_arr) if v}

    def load_prefix_top(self, path: Optional[Path] = None) -> None:
        if path is None and self._path is not None:
            path = self._path.with_suffix(".prefix.bin")
        if path is None or not path.exists():
            return
        try:
            with open(path, "rb") as f:
                header = f.read(28)
                if len(header) != 28:
                    return
                magic, version, prefix_len, top_k, top_global, prefix_count, global_count = struct.unpack(
                    "<4sIIIIII", header
                )
                if magic != b"LXP1" or version != 1:
                    return
                self._prefix_len = int(prefix_len)
                self._top_k = int(top_k)
                self._top_global = int(top_global)
                if global_count:
                    data = f.read(int(global_count) * 4)
                    if len(data) == int(global_count) * 4:
                        self._top_global_ids = np.frombuffer(data, dtype=np.uint32).copy()
                prefix_top: Dict[str, np.ndarray] = {}
                for _ in range(int(prefix_count)):
                    meta = f.read(4)
                    if len(meta) != 4:
                        break
                    plen, cnt = struct.unpack("<HH", meta)
                    key = f.read(int(plen))
                    if len(key) != int(plen):
                        break
                    ids_bytes = f.read(int(cnt) * 4)
                    if len(ids_bytes) != int(cnt) * 4:
                        break
                    prefix = key.decode("utf-8", errors="ignore")
                    prefix_top[prefix] = np.frombuffer(ids_bytes, dtype=np.uint32).copy()
                if prefix_top:
                    self._prefix_top = prefix_top
        except Exception:
            return
        
    def close(self) -> None:
        """Release the mmap handle and drop derived views (DT-CORE-LIFECYCLE).

        Best-effort: a memoryview over the mmap must be released before the
        underlying ``mmap`` can be closed, otherwise CPython raises
        ``BufferError``. We drop every view/array that aliases the mapping
        first, then close the handle. Idempotent.
        """
        # Drop views that alias the mmap BEFORE closing it.
        self._strings_view = None
        self._strings_bytes = None
        self._offsets = None
        self._freqs_arr = None
        try:
            self._string_cache.clear()
        except Exception:
            pass
        mm = self._mm
        self._mm = None
        if mm is not None:
            try:
                mm.close()
            except Exception:
                pass

    @property
    def total_tokens(self) -> int:
        """Total tokens in corpus (sum of all frequencies)."""
        return self._total_tokens

    @property
    def vocab_size(self) -> int:
        """Number of unique types."""
        return self._vocab_size

    @property
    def offsets(self) -> np.ndarray:
        if self._offsets is None:
            raise RuntimeError("Lexikon Offset Daten fehlen")
        return self._offsets

    @property
    def strings_view(self) -> memoryview:
        if self._strings_view is None:
            raise RuntimeError("Lexikon String Daten fehlen")
        return self._strings_view

    @property
    def prefix_len(self) -> int:
        return int(self._prefix_len)

    @property
    def top_k(self) -> int:
        return int(self._top_k)

    @property
    def top_global(self) -> int:
        return int(self._top_global)

    @property
    def prefix_top(self) -> Optional[Dict[str, np.ndarray]]:
        return self._prefix_top

    @property
    def top_global_ids(self) -> Optional[np.ndarray]:
        return self._top_global_ids


class LexiconSet:
    """
    Collection of lexicons for all positional attributes.
    """
    
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.word: Optional[Lexicon] = None
        self.lemma: Optional[Lexicon] = None
        self.pos: Optional[Lexicon] = None
        self.morph: Optional[Lexicon] = None
        self.ent: Optional[Lexicon] = None
        self.rel: Optional[Lexicon] = None
        
    def load(self) -> None:
        """Load all lexicons."""
        self.word = Lexicon.load(self.base_path / "word_lexicon.bin")
        self.lemma = Lexicon.load(self.base_path / "lemma_lexicon.bin")
        self.pos = Lexicon.load(self.base_path / "pos_lexicon.bin")
        self.morph = self._try_load("morph_lexicon.bin")
        self.ent = self._try_load("ent_lexicon.bin")
        self.rel = self._try_load("rel_lexicon.bin")

    def _try_load(self, name: str) -> Optional[Lexicon]:
        path = self.base_path / name
        try:
            if path.exists():
                return Lexicon.load(path)
        except Exception:
            return None
        return None
        
    def close(self) -> None:
        """Close every loaded lexicon mmap, best-effort (DT-CORE-LIFECYCLE)."""
        for attr in ("word", "lemma", "pos", "morph", "ent", "rel"):
            lex = getattr(self, attr, None)
            if lex is not None:
                try:
                    lex.close()
                except Exception:
                    pass

    def get_word_string(self, id_: int) -> str:
        """Get word string for ID."""
        return self.word.get_string(id_) if self.word else ""
        
    def get_word_freq(self, id_: int) -> int:
        """Get global frequency for word ID."""
        return self.word.get_freq(id_) if self.word else 0
        
    @property
    def total_tokens(self) -> int:
        """Total tokens in corpus."""
        return self.word.total_tokens if self.word else 0
