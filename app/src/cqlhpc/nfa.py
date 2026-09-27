from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Callable

import numpy as np

from . import config
from .errors import lt
from .ast import Alt, Node, Quant, Seq, Tok, Within, Where
from .corpus import Corpus
from .parser import ParseError
from .predicates import CompiledClause, compile_clause

# Defence-in-depth budget on the lowered NFA size. The parser already rejects
# explosive nested quantifiers via the cheap parse-time expansion estimate, but
# these caps backstop any path that reaches NFA construction with too many
# states/predicates (e.g. a hand-built AST, or a future grammar extension). They
# bound the O(states^2) epsilon-closure + edge materialisation that otherwise
# hangs the worker, and keep the predicate count well inside the int32 edge
# tables. Both are configurable via cqlhpc.config.
DEFAULT_MAX_NFA_PREDS = 2000
DEFAULT_MAX_NFA_STATES = 5000


try:
    from .cython._nfa import nfa_find_matches as _cy_nfa_find_matches  # type: ignore
    from .cython._nfa import nfa_find_matches_many as _cy_nfa_find_matches_many  # type: ignore
except Exception:  # pragma: no cover
    _cy_nfa_find_matches = None
    _cy_nfa_find_matches_many = None


# -------------------- Thompson NFA build (Python) ---------------------------


@dataclass
class _ThompsonNFA:
    start: int
    accept: int
    eps: List[List[int]]
    cons: List[List[Tuple[int, int]]]
    preds: List[CompiledClause]


class _NfaBuilder:
    def __init__(self, corpus: Corpus, *, progress_cb: Callable | None = None):
        self.corpus = corpus
        self._progress_cb = progress_cb
        self.eps: List[List[int]] = []
        self.cons: List[List[Tuple[int, int]]] = []
        self.preds: List[CompiledClause] = []

    def new_state(self) -> int:
        s = len(self.eps)
        self.eps.append([])
        self.cons.append([])
        return s

    def add_eps(self, a: int, b: int) -> None:
        self.eps[a].append(b)

    def add_cons(self, a: int, pid: int, b: int) -> None:
        self.cons[a].append((pid, b))

    def intern_pred(self, tok: Tok) -> int:
        pid = len(self.preds)
        self.preds.append(
            compile_clause(tok.clause, self.corpus, progress_cb=self._progress_cb)
        )
        return pid

    def build(self, node: Node) -> Tuple[int, int]:
        n = node
        # wrappers ignored at this stage; handled by engine (scope/docset)
        if isinstance(n, Within):
            return self.build(n.node)
        if isinstance(n, Where):
            return self.build(n.node)

        if isinstance(n, Tok):
            s = self.new_state()
            e = self.new_state()
            pid = self.intern_pred(n)
            self.add_cons(s, pid, e)
            return s, e

        if isinstance(n, Seq):
            se = [self.build(p) for p in n.parts]
            for (s1, e1), (s2, e2) in zip(se, se[1:]):
                self.add_eps(e1, s2)
            return se[0][0], se[-1][1]

        if isinstance(n, Alt):
            s = self.new_state()
            e = self.new_state()
            for opt in n.options:
                os, oe = self.build(opt)
                self.add_eps(s, os)
                self.add_eps(oe, e)
            return s, e

        if isinstance(n, Quant):
            return self._build_quant(n)

        raise TypeError(f"unsupported node for NFA: {type(n)}")

    def _build_quant(self, q: Quant) -> Tuple[int, int]:
        m, nmax = q.m, q.n
        if nmax is not None and nmax < m:
            s = self.new_state()
            e = self.new_state()
            return s, e

        if m == 0 and nmax == 1:
            # optional
            s = self.new_state()
            e = self.new_state()
            is_, ie = self.build(q.node)
            self.add_eps(s, e)
            self.add_eps(s, is_)
            self.add_eps(ie, e)
            return s, e

        if m == 0 and nmax is None:
            # star
            s = self.new_state()
            e = self.new_state()
            is_, ie = self.build(q.node)
            self.add_eps(s, e)
            self.add_eps(s, is_)
            self.add_eps(ie, is_)
            self.add_eps(ie, e)
            return s, e

        if m == 1 and nmax is None:
            # plus
            s = self.new_state()
            e = self.new_state()
            is_, ie = self.build(q.node)
            self.add_eps(s, is_)
            self.add_eps(ie, is_)
            self.add_eps(ie, e)
            return s, e

        # general bounded {m,n}
        parts: List[Tuple[int, int]] = []
        for _ in range(m):
            parts.append(self.build(q.node))
        if nmax is None:
            parts.append(self._build_quant(Quant(node=q.node, m=0, n=None)))
        else:
            for _ in range(nmax - m):
                parts.append(self._build_quant(Quant(node=q.node, m=0, n=1)))

        if not parts:
            s = self.new_state()
            e = self.new_state()
            self.add_eps(s, e)
            return s, e

        for (s1, e1), (s2, e2) in zip(parts, parts[1:]):
            self.add_eps(e1, s2)
        return parts[0][0], parts[-1][1]


def _build_thompson(
    node: Node, corpus: Corpus, *, progress_cb: Callable | None = None
) -> _ThompsonNFA:
    b = _NfaBuilder(corpus, progress_cb=progress_cb)
    s, e = b.build(node)
    return _ThompsonNFA(start=s, accept=e, eps=b.eps, cons=b.cons, preds=b.preds)


# -------------------- Lowering to epsilon-free, bitset NFA ------------------


@dataclass(frozen=True)
class CompiledNFA:
    n_states: int
    n_preds: int
    words: int

    # bitsets
    start_bits: np.ndarray  # uint64[words]
    accept_bits: np.ndarray # uint64[words]

    # edges
    state_edge_off: np.ndarray  # int32[n_states+1]
    edge_pred: np.ndarray       # int32[n_edges]
    edge_tgt: np.ndarray        # uint64[n_edges, words]

    # predicates
    pred_cond_off: np.ndarray   # int32[n_preds+1]
    cond_attr: np.ndarray       # uint8[n_conds]
    cond_op: np.ndarray         # uint8[n_conds]
    cond_val_off: np.ndarray    # int32[n_conds]
    cond_val_len: np.ndarray    # int32[n_conds]
    values: np.ndarray          # int32[sum]

    start_pred_ids: np.ndarray  # int32[k]

    # No Python fallback; Cython runner is required.


_ATTR_INDEX = {"lemma": 0, "pos": 1, "word": 2}
_OP_CODE = {"=": 0, "!=": 1, "in": 2}


def compile_nfa(
    node: Node, corpus: Corpus, *, progress_cb: Callable | None = None
) -> CompiledNFA:
    th = _build_thompson(node, corpus, progress_cb=progress_cb)
    n_states = len(th.eps)
    n_preds = len(th.preds)

    # DoS budget: enforce *before* the O(states^2) epsilon-closure pass. The
    # parser rejects explosive nested quantifiers up front, so reaching this is
    # rare; when it does we fail fast with a user-facing 400 ("Muster zu
    # komplex") rather than hanging the worker. ParseError subclasses ValueError
    # so the sync /query path and message-based classifiers route it to HTTP 400.
    max_preds = config.get_int("CQLHPC_MAX_NFA_PREDS", DEFAULT_MAX_NFA_PREDS)
    max_states = config.get_int("CQLHPC_MAX_NFA_STATES", DEFAULT_MAX_NFA_STATES)
    if n_preds > max_preds or n_states > max_states:
        raise ParseError(
            lt(
                "Muster zu komplex: das Suchmuster erzeugt einen zu grossen Automaten "
                "({n_states} Zustände, {n_preds} Praedikate; Limit {max_states} "
                "Zustände / {max_preds} Praedikate). Bitte die Wiederholungszahlen "
                "verkleinern.",
                "Pattern too complex: the search pattern creates an automaton that "
                "is too large ({n_states} states, {n_preds} predicates, limit "
                "{max_states} states / {max_preds} predicates). Reduce the "
                "repetition counts.",
            ).format(
                n_states=n_states, n_preds=n_preds, max_states=max_states, max_preds=max_preds
            ),
            0,
            0,
        )

    closures = _epsilon_closures(th.eps)

    # bitset helpers
    words = (n_states + 63) // 64

    start_bits = _mask_to_words(closures[th.start], words)
    # Accepting states are those whose closure contains accept.
    accept_mask = 0
    acc_bit = 1 << th.accept
    for s in range(n_states):
        if closures[s] & acc_bit:
            accept_mask |= 1 << s
    accept_bits = _mask_to_words(accept_mask, words)

    # Build epsilon-free edges: per state s, per predicate pid -> target bitset.
    per_state: List[Dict[int, int]] = [dict() for _ in range(n_states)]
    for s in range(n_states):
        clo = closures[s]
        # iterate u in closure(s)
        for u in _iter_bits(clo):
            for pid, v in th.cons[u]:
                tgt = closures[v]
                cur = per_state[s].get(pid, 0)
                per_state[s][pid] = cur | tgt

    # Flatten edges
    state_edge_off = np.zeros((n_states + 1,), dtype=np.int32)
    n_edges = 0
    for s in range(n_states):
        n_edges += len(per_state[s])
        state_edge_off[s + 1] = n_edges

    edge_pred = np.empty((n_edges,), dtype=np.int32)
    edge_tgt = np.zeros((n_edges, words), dtype=np.uint64)

    k = 0
    for s in range(n_states):
        items = sorted(per_state[s].items(), key=lambda kv: kv[0])
        for pid, mask in items:
            edge_pred[k] = pid
            edge_tgt[k, :] = _mask_to_words(mask, words)
            k += 1

    # start_pred_ids for quick skip
    start_pred_set: Dict[int, None] = {}
    start_mask = closures[th.start]
    for s in _iter_bits(start_mask):
        for pid in per_state[s].keys():
            start_pred_set[pid] = None
    start_pred_ids = np.asarray(sorted(start_pred_set.keys()), dtype=np.int32)

    # lower predicates to arrays
    pred_arrays = _lower_preds(th.preds)

    return CompiledNFA(
        n_states=n_states,
        n_preds=n_preds,
        words=words,
        start_bits=start_bits,
        accept_bits=accept_bits,
        state_edge_off=state_edge_off,
        edge_pred=edge_pred,
        edge_tgt=edge_tgt,
        pred_cond_off=pred_arrays[0],
        cond_attr=pred_arrays[1],
        cond_op=pred_arrays[2],
        cond_val_off=pred_arrays[3],
        cond_val_len=pred_arrays[4],
        values=pred_arrays[5],
        start_pred_ids=start_pred_ids,
    )


def find_nonoverlapping_matches(nfa: CompiledNFA, corpus: Corpus, start: int, end: int, max_matches: int = 10000) -> List[Tuple[int, int]]:
    """Find leftmost-longest non-overlapping matches in [start,end)."""

    if _cy_nfa_find_matches is None:
        raise RuntimeError("CQLHPC NFA Extension fehlt. Bitte Extension bauen.")

    lemma = corpus.attr("lemma")
    pos = corpus.attr("pos")
    word = corpus.attr("word")
    if isinstance(lemma, np.ndarray) and isinstance(pos, np.ndarray) and isinstance(word, np.ndarray):
        return _cy_nfa_find_matches(
            lemma,
            pos,
            word,
            int(start),
            int(end),
            nfa.start_bits,
            nfa.accept_bits,
            nfa.state_edge_off,
            nfa.edge_pred,
            nfa.edge_tgt,
            nfa.start_pred_ids,
            nfa.pred_cond_off,
            nfa.cond_attr,
            nfa.cond_op,
            nfa.cond_val_off,
            nfa.cond_val_len,
            nfa.values,
            int(max_matches),
        )
    span_len = int(end - start)
    if span_len <= 0:
        return []
    lemma_arr = np.asarray(lemma[start:end], dtype=np.int32)
    pos_arr = np.asarray(pos[start:end], dtype=np.int32)
    word_arr = np.asarray(word[start:end], dtype=np.int32)
    if (
        lemma_arr.shape[0] != span_len
        or pos_arr.shape[0] != span_len
        or word_arr.shape[0] != span_len
    ):
        raise RuntimeError("CQLHPC NFA Input ungültig")
    spans = _cy_nfa_find_matches(
        lemma_arr,
        pos_arr,
        word_arr,
        0,
        span_len,
        nfa.start_bits,
        nfa.accept_bits,
        nfa.state_edge_off,
        nfa.edge_pred,
        nfa.edge_tgt,
        nfa.start_pred_ids,
        nfa.pred_cond_off,
        nfa.cond_attr,
        nfa.cond_op,
        nfa.cond_val_off,
        nfa.cond_val_len,
        nfa.values,
        int(max_matches),
    )
    return [(a + start, b + start) for a, b in spans]


# -------------------- helpers ----------------------------------------------


def _epsilon_closures(eps: List[List[int]]) -> List[int]:
    n = len(eps)
    closures = [0] * n
    for s in range(n):
        seen = set()
        stack = [s]
        mask = 0
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            mask |= 1 << x
            for y in eps[x]:
                if y not in seen:
                    stack.append(y)
        closures[s] = mask
    return closures


def _iter_bits(mask: int):
    while mask:
        lsb = mask & -mask
        i = (lsb.bit_length() - 1)
        yield i
        mask ^= lsb


def _mask_to_words(mask: int, words: int) -> np.ndarray:
    out = np.zeros((words,), dtype=np.uint64)
    for w in range(words):
        out[w] = np.uint64(mask & ((1 << 64) - 1))
        mask >>= 64
        if mask == 0:
            break
    return out


def _lower_preds(preds: List[CompiledClause]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Flatten predicate conditions.
    pred_cond_off = np.zeros((len(preds) + 1,), dtype=np.int32)

    cond_attr: List[int] = []
    cond_op: List[int] = []
    cond_val_off: List[int] = []
    cond_val_len: List[int] = []
    values: List[int] = []

    off = 0
    for pid, p in enumerate(preds):
        for attr, op, vals in p.conds:
            ai = _ATTR_INDEX.get(attr)
            if ai is None:
                # Hard restriction for the HPC runner.
                # If you need arbitrary attributes, add an attribute table and extend the Cython code.
                raise ValueError(f"unsupported attribute in NFA predicate: {attr}")
            oc = _OP_CODE.get(op)
            if oc is None:
                raise ValueError(f"unsupported operator in NFA predicate: {op}")
            v = vals.astype(np.int32, copy=False)
            cond_attr.append(ai)
            cond_op.append(oc)
            cond_val_off.append(off)
            cond_val_len.append(int(v.size))
            values.extend(int(x) for x in v)
            off += int(v.size)
        pred_cond_off[pid + 1] = len(cond_attr)

    return (
        pred_cond_off,
        np.asarray(cond_attr, dtype=np.uint8),
        np.asarray(cond_op, dtype=np.uint8),
        np.asarray(cond_val_off, dtype=np.int32),
        np.asarray(cond_val_len, dtype=np.int32),
        np.asarray(values, dtype=np.int32),
    )
