from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .lexicon import Lexicon
from .postings import PostingsIndex


@dataclass
class Corpus:
    """A minimal, but HPC-friendly corpus container.

    All token attributes are stored as contiguous int32 arrays.
    Postings are stored in adjacency-list layout (offsets+positions) per attribute.

    This class is *immutable by convention* once built; treat it as a read-only artifact.
    """

    attrs: Dict[str, np.ndarray]  # attr -> int32 array length N
    lex: Dict[str, Lexicon]      # attr -> Lexicon
    postings: Dict[str, PostingsIndex]  # attr -> postings index

    doc_starts: np.ndarray  # int32
    doc_ends: np.ndarray    # int32
    sent_starts: np.ndarray # int32
    sent_ends: np.ndarray   # int32

    doc_meta: Optional[List[Dict[str, object]]] = None

    _token_to_sent: Optional[np.ndarray] = None
    _token_to_doc: Optional[np.ndarray] = None
    _sent_to_doc: Optional[np.ndarray] = None

    def __post_init__(self):
        lens = {a.shape[0] for a in self.attrs.values()}
        if len(lens) != 1:
            raise ValueError(f"all attrs must have same length, got {lens}")
        if self.doc_starts.shape != self.doc_ends.shape:
            raise ValueError("doc_starts/doc_ends mismatch")
        if self.sent_starts.shape != self.sent_ends.shape:
            raise ValueError("sent_starts/sent_ends mismatch")
        if self.doc_meta is not None and len(self.doc_meta) != int(self.doc_starts.shape[0]):
            raise ValueError("doc_meta length mismatch")

    @property
    def n_tokens(self) -> int:
        return int(next(iter(self.attrs.values())).shape[0])

    def has_attr(self, name: str) -> bool:
        return name in self.attrs

    def attr(self, name: str) -> np.ndarray:
        return self.attrs[name]

    def lexicon(self, name: str) -> Lexicon:
        return self.lex[name]

    def postings_index(self, attr: str) -> PostingsIndex:
        return self.postings[attr]

    def sentence_span(self, sid: int) -> Tuple[int, int]:
        return int(self.sent_starts[sid]), int(self.sent_ends[sid])

    def doc_span(self, did: int) -> Tuple[int, int]:
        return int(self.doc_starts[did]), int(self.doc_ends[did])

    def doc_id_of_position(self, pos: int) -> int:
        if self._token_to_doc is not None and 0 <= pos < self._token_to_doc.shape[0]:
            return int(self._token_to_doc[pos])
        i = int(np.searchsorted(self.doc_starts, pos, side='right') - 1)
        if i < 0:
            return 0
        if i >= int(self.doc_starts.shape[0]):
            return int(self.doc_starts.shape[0]) - 1
        return i

    def token_to_sent(self) -> np.ndarray:
        if self._token_to_sent is None:
            lens = (self.sent_ends - self.sent_starts).astype(np.int64)
            sids = np.arange(self.sent_starts.shape[0], dtype=np.int32)
            arr = np.repeat(sids, lens)
            if arr.shape[0] != self.n_tokens:
                raise RuntimeError("token_to_sent length mismatch")
            self._token_to_sent = arr.astype(np.int32, copy=False)
        return self._token_to_sent

    def token_to_doc(self) -> np.ndarray:
        if self._token_to_doc is None:
            lens = (self.doc_ends - self.doc_starts).astype(np.int64)
            dids = np.arange(self.doc_starts.shape[0], dtype=np.int32)
            arr = np.repeat(dids, lens)
            if arr.shape[0] != self.n_tokens:
                raise RuntimeError("token_to_doc length mismatch")
            self._token_to_doc = arr.astype(np.int32, copy=False)
        return self._token_to_doc

    def sent_to_doc(self) -> np.ndarray:
        if self._sent_to_doc is None:
            if self._token_to_doc is not None and self.sent_starts.size:
                dids = self._token_to_doc[self.sent_starts.astype(np.int64, copy=False)]
                dids = dids.astype(np.int32, copy=False)
            else:
                dids = np.searchsorted(self.doc_starts, self.sent_starts, side='right') - 1
                dids = dids.astype(np.int32, copy=False)
            self._sent_to_doc = dids
        return self._sent_to_doc


def build_postings_from_tokens(tokens: np.ndarray, vocab_size: int) -> PostingsIndex:
    """Build postings offsets/positions for a single attribute.

    tokens: int32 array length N, values in [0,vocab_size)
    """
    # Count occurrences per type
    counts = np.bincount(tokens, minlength=vocab_size).astype(np.int64)
    offsets = np.empty((vocab_size + 1,), dtype=np.int64)
    offsets[0] = 0
    np.cumsum(counts, out=offsets[1:])

    # Fill positions using a stable counting-sort like pass.
    positions = np.empty((tokens.shape[0],), dtype=np.int32)
    write = offsets[:-1].copy()
    for p, tid in enumerate(tokens):
        i = int(tid)
        positions[write[i]] = p
        write[i] += 1

    return PostingsIndex(offsets=offsets, positions=positions)


def build_toy_corpus() -> Corpus:
    """Build a small in-memory corpus used by demos/tests."""

    # A tiny token stream with lemma/pos/word.
    words = [
        "ich", "gehe", "nach", "hause", ".",
        "du", "gehst", "nach", "berlin", ".",
        "wir", "gehen", "heute", "nicht", ".",
        "gehen", "wir", "jetzt", "?",
    ]
    pos = [
        "PPER", "VVFIN", "APPR", "NN", "$.",
        "PPER", "VVFIN", "APPR", "NE", "$.",
        "PPER", "VVFIN", "ADV", "PTKNEG", "$.",
        "VVINF", "PPER", "ADV", "$?",
    ]
    lemma = [
        "ich", "gehen", "nach", "haus", ".",
        "du", "gehen", "nach", "berlin", ".",
        "wir", "gehen", "heute", "nicht", ".",
        "gehen", "wir", "jetzt", "?",
    ]

    def make_lex(vals: Sequence[str]) -> Tuple[Lexicon, np.ndarray]:
        uniq = sorted(set(vals))
        str_to_id = {s: i for i, s in enumerate(uniq)}
        ids = np.asarray([str_to_id[v] for v in vals], dtype=np.int32)
        freqs = np.bincount(ids, minlength=len(uniq)).astype(np.int64)
        lex = Lexicon(id_to_str=uniq, str_to_id=str_to_id, freqs=freqs)
        return lex, ids

    lex_word, ids_word = make_lex(words)
    lex_pos, ids_pos = make_lex(pos)
    lex_lemma, ids_lemma = make_lex(lemma)

    attrs = {
        "word": ids_word,
        "pos": ids_pos,
        "lemma": ids_lemma,
    }
    lex = {
        "word": lex_word,
        "pos": lex_pos,
        "lemma": lex_lemma,
    }
    postings = {
        "word": build_postings_from_tokens(ids_word, len(lex_word.id_to_str)),
        "pos": build_postings_from_tokens(ids_pos, len(lex_pos.id_to_str)),
        "lemma": build_postings_from_tokens(ids_lemma, len(lex_lemma.id_to_str)),
    }

    # Simple doc/sentence segmentation: each '.' or '?' ends a sentence.
    sent_starts = [0]
    sent_ends = []
    for i, w in enumerate(words):
        if w in {".", "?"}:
            sent_ends.append(i + 1)
            if i + 1 < len(words):
                sent_starts.append(i + 1)
    if len(sent_ends) < len(sent_starts):
        sent_ends.append(len(words))

    # One doc.
    doc_starts = np.asarray([0], dtype=np.int32)
    doc_ends = np.asarray([len(words)], dtype=np.int32)

    return Corpus(
        attrs=attrs,
        lex=lex,
        postings=postings,
        doc_starts=doc_starts,
        doc_ends=doc_ends,
        sent_starts=np.asarray(sent_starts, dtype=np.int32),
        sent_ends=np.asarray(sent_ends, dtype=np.int32),
        doc_meta=[{"genre": "toy", "year": 2024}],
    )
