# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False, nonecheck=False, cdivision=True

from cpython.mem cimport PyMem_Malloc, PyMem_Free
from libc.string cimport memcpy

import numpy as np
cimport numpy as cnp

ctypedef cnp.int32_t int32_t
ctypedef cnp.int64_t int64_t
ctypedef cnp.uint8_t uint8_t
ctypedef cnp.uint64_t uint64_t

cdef extern from *:
    int __builtin_ctzll(unsigned long long) nogil


cdef inline int ctz64(uint64_t x) nogil:
    return __builtin_ctzll(<unsigned long long>x)


cdef inline bint bitset_empty(uint64_t* bits, int words) noexcept nogil:
    cdef int i
    for i in range(words):
        if bits[i] != 0:
            return False
    return True


cdef inline bint bitset_intersects(uint64_t* a, uint64_t[:] b, int words) noexcept nogil:
    cdef int i
    for i in range(words):
        if a[i] & b[i]:
            return True
    return False


cdef inline void bitset_copy(uint64_t* dst, uint64_t[:] src, int words) noexcept nogil:
    cdef int i
    for i in range(words):
        dst[i] = src[i]


cdef inline void bitset_clear(uint64_t* dst, int words) noexcept nogil:
    cdef int i
    for i in range(words):
        dst[i] = 0


cdef inline void bitset_or_inplace(uint64_t* dst, uint64_t[:, :] src, Py_ssize_t row, int words) noexcept nogil:
    cdef int i
    for i in range(words):
        dst[i] |= src[row, i]


cdef inline bint contains_sorted(int32_t[:] values, int off, int ln, int32_t x) nogil:
    cdef int i
    if ln == 1:
        return values[off] == x
    if ln <= 8:
        for i in range(ln):
            if values[off + i] == x:
                return True
        return False
    # binary search
    cdef int lo = 0
    cdef int hi = ln
    cdef int mid
    cdef int32_t v
    while lo < hi:
        mid = (lo + hi) >> 1
        v = values[off + mid]
        if v < x:
            lo = mid + 1
        else:
            hi = mid
    return lo < ln and values[off + lo] == x


cdef inline bint cond_matches_value(
    int op,
    int off,
    int ln,
    int32_t[:] values,
    int32_t tv,
) noexcept nogil:
    if op == 0:
        return tv == values[off]
    if op == 1:
        return tv != values[off]
    if op == 2:
        return contains_sorted(values, off, ln, tv)
    return False


cdef inline void fill_pm_single(
    uint8_t[:] pm,
    int out_off,
    int32_t[:] arr,
    int base_pos,
    int length,
    int op,
    int off,
    int ln,
    int32_t[:] values,
) noexcept nogil:
    cdef int j
    cdef int pos
    cdef int32_t v0 = 0
    if op == 0 and ln == 1:
        v0 = values[off]
        for j in range(length):
            pos = base_pos + j
            pm[out_off + j] = 1 if arr[pos] == v0 else 0
        return
    if op == 1 and ln == 1:
        v0 = values[off]
        for j in range(length):
            pos = base_pos + j
            pm[out_off + j] = 1 if arr[pos] != v0 else 0
        return
    for j in range(length):
        pos = base_pos + j
        pm[out_off + j] = 1 if cond_matches_value(op, off, ln, values, arr[pos]) else 0


cdef inline int32_t token_attr_value(
    int ai,
    int pos,
    int32_t[:] lemma,
    int32_t[:] pos_arr,
    int32_t[:] word,
) noexcept nogil:
    if ai == 0:
        return lemma[pos]
    if ai == 1:
        return pos_arr[pos]
    return word[pos]


cdef inline void fill_pm_double(
    uint8_t[:] pm,
    int out_off,
    int32_t[:] lemma,
    int32_t[:] pos_arr,
    int32_t[:] word,
    int base_pos,
    int length,
    int ai0,
    int op0,
    int off0,
    int ln0,
    int ai1,
    int op1,
    int off1,
    int ln1,
    int32_t[:] values,
) noexcept nogil:
    cdef int j
    cdef int pos
    cdef int32_t tv0
    cdef int32_t tv1
    for j in range(length):
        pos = base_pos + j
        tv0 = token_attr_value(ai0, pos, lemma, pos_arr, word)
        if not cond_matches_value(op0, off0, ln0, values, tv0):
            pm[out_off + j] = 0
            continue
        if ai1 == ai0:
            tv1 = tv0
        else:
            tv1 = token_attr_value(ai1, pos, lemma, pos_arr, word)
        pm[out_off + j] = 1 if cond_matches_value(op1, off1, ln1, values, tv1) else 0


cdef inline void fill_pm_triple(
    uint8_t[:] pm,
    int out_off,
    int32_t[:] lemma,
    int32_t[:] pos_arr,
    int32_t[:] word,
    int base_pos,
    int length,
    int ai0,
    int op0,
    int off0,
    int ln0,
    int ai1,
    int op1,
    int off1,
    int ln1,
    int ai2,
    int op2,
    int off2,
    int ln2,
    int32_t[:] values,
) noexcept nogil:
    cdef int j
    cdef int pos
    cdef int32_t tv0
    cdef int32_t tv1
    cdef int32_t tv2
    for j in range(length):
        pos = base_pos + j
        tv0 = token_attr_value(ai0, pos, lemma, pos_arr, word)
        if not cond_matches_value(op0, off0, ln0, values, tv0):
            pm[out_off + j] = 0
            continue
        if ai1 == ai0:
            tv1 = tv0
        else:
            tv1 = token_attr_value(ai1, pos, lemma, pos_arr, word)
        if not cond_matches_value(op1, off1, ln1, values, tv1):
            pm[out_off + j] = 0
            continue
        if ai2 == ai0:
            tv2 = tv0
        elif ai2 == ai1:
            tv2 = tv1
        else:
            tv2 = token_attr_value(ai2, pos, lemma, pos_arr, word)
        pm[out_off + j] = 1 if cond_matches_value(op2, off2, ln2, values, tv2) else 0


cdef inline bint pred_match_at(
    int pid,
    int pos,
    int32_t[:] lemma,
    int32_t[:] pos_arr,
    int32_t[:] word,
    int32_t[:] pred_cond_off,
    uint8_t[:] cond_attr,
    uint8_t[:] cond_op,
    int32_t[:] cond_val_off,
    int32_t[:] cond_val_len,
    int32_t[:] values,
) nogil:
    cdef int c0 = pred_cond_off[pid]
    cdef int c1 = pred_cond_off[pid + 1]
    cdef int ci
    cdef int ai
    cdef int op
    cdef int off
    cdef int ln
    cdef int32_t tv

    for ci in range(c0, c1):
        ai = cond_attr[ci]
        op = cond_op[ci]
        off = cond_val_off[ci]
        ln = cond_val_len[ci]
        tv = token_attr_value(ai, pos, lemma, pos_arr, word)
        if not cond_matches_value(op, off, ln, values, tv):
            return False

    return True


def nfa_find_matches(
    cnp.ndarray[int32_t, ndim=1] lemma,
    cnp.ndarray[int32_t, ndim=1] pos_arr,
    cnp.ndarray[int32_t, ndim=1] word,
    int start,
    int end,
    cnp.ndarray[uint64_t, ndim=1] start_bits,
    cnp.ndarray[uint64_t, ndim=1] accept_bits,
    cnp.ndarray[int32_t, ndim=1] state_edge_off,
    cnp.ndarray[int32_t, ndim=1] edge_pred,
    cnp.ndarray[uint64_t, ndim=2] edge_tgt,
    cnp.ndarray[int32_t, ndim=1] start_pred_ids,
    cnp.ndarray[int32_t, ndim=1] pred_cond_off,
    cnp.ndarray[uint8_t, ndim=1] cond_attr,
    cnp.ndarray[uint8_t, ndim=1] cond_op,
    cnp.ndarray[int32_t, ndim=1] cond_val_off,
    cnp.ndarray[int32_t, ndim=1] cond_val_len,
    cnp.ndarray[int32_t, ndim=1] values,
    int max_matches,
):
    """Find leftmost-longest non-overlapping matches of a compiled NFA.

    Returns a Python list of (start,end) spans in global token coordinates.
    """

    # memoryviews (fast, nogil-friendly)
    cdef int32_t[:] lemma_v = lemma
    cdef int32_t[:] pos_v = pos_arr
    cdef int32_t[:] word_v = word

    cdef uint64_t[:] start_bits_v = start_bits
    cdef uint64_t[:] accept_bits_v = accept_bits

    cdef int32_t[:] state_edge_off_v = state_edge_off
    cdef int32_t[:] edge_pred_v = edge_pred
    cdef uint64_t[:, :] edge_tgt_v = edge_tgt

    cdef int32_t[:] start_pred_ids_v = start_pred_ids

    cdef int32_t[:] pred_cond_off_v = pred_cond_off
    cdef uint8_t[:] cond_attr_v = cond_attr
    cdef uint8_t[:] cond_op_v = cond_op
    cdef int32_t[:] cond_val_off_v = cond_val_off
    cdef int32_t[:] cond_val_len_v = cond_val_len
    cdef int32_t[:] values_v = values

    cdef int n_states = state_edge_off_v.shape[0] - 1
    cdef int n_preds = pred_cond_off_v.shape[0] - 1
    cdef int words = start_bits_v.shape[0]

    cdef int sent_len = end - start
    if sent_len <= 0 or max_matches <= 0:
        return []

    # precompute predicate matches: pm[pid, j] flattened
    cdef cnp.ndarray[uint8_t, ndim=1] pm = np.empty((n_preds * sent_len,), dtype=np.uint8)
    cdef uint8_t[:] pm_v = pm

    cdef int pid
    cdef int j
    cdef int pos
    cdef int c0
    cdef int c1
    cdef int ai
    cdef int op
    cdef int off
    cdef int ln
    cdef int ai1
    cdef int op1
    cdef int off1
    cdef int ln1
    cdef int ai2
    cdef int op2
    cdef int off2
    cdef int ln2

    with nogil:
        for pid in range(n_preds):
            c0 = pred_cond_off_v[pid]
            c1 = pred_cond_off_v[pid + 1]
            if c1 == c0 + 1:
                ai = cond_attr_v[c0]
                op = cond_op_v[c0]
                off = cond_val_off_v[c0]
                ln = cond_val_len_v[c0]
                if ai == 0:
                    fill_pm_single(pm_v, pid * sent_len, lemma_v, start, sent_len, op, off, ln, values_v)
                elif ai == 1:
                    fill_pm_single(pm_v, pid * sent_len, pos_v, start, sent_len, op, off, ln, values_v)
                else:
                    fill_pm_single(pm_v, pid * sent_len, word_v, start, sent_len, op, off, ln, values_v)
            elif c1 == c0 + 2:
                ai = cond_attr_v[c0]
                op = cond_op_v[c0]
                off = cond_val_off_v[c0]
                ln = cond_val_len_v[c0]
                ai1 = cond_attr_v[c0 + 1]
                op1 = cond_op_v[c0 + 1]
                off1 = cond_val_off_v[c0 + 1]
                ln1 = cond_val_len_v[c0 + 1]
                fill_pm_double(
                    pm_v,
                    pid * sent_len,
                    lemma_v,
                    pos_v,
                    word_v,
                    start,
                    sent_len,
                    ai,
                    op,
                    off,
                    ln,
                    ai1,
                    op1,
                    off1,
                    ln1,
                    values_v,
                )
            elif c1 == c0 + 3:
                ai = cond_attr_v[c0]
                op = cond_op_v[c0]
                off = cond_val_off_v[c0]
                ln = cond_val_len_v[c0]
                ai1 = cond_attr_v[c0 + 1]
                op1 = cond_op_v[c0 + 1]
                off1 = cond_val_off_v[c0 + 1]
                ln1 = cond_val_len_v[c0 + 1]
                ai2 = cond_attr_v[c0 + 2]
                op2 = cond_op_v[c0 + 2]
                off2 = cond_val_off_v[c0 + 2]
                ln2 = cond_val_len_v[c0 + 2]
                fill_pm_triple(
                    pm_v,
                    pid * sent_len,
                    lemma_v,
                    pos_v,
                    word_v,
                    start,
                    sent_len,
                    ai,
                    op,
                    off,
                    ln,
                    ai1,
                    op1,
                    off1,
                    ln1,
                    ai2,
                    op2,
                    off2,
                    ln2,
                    values_v,
                )
            else:
                for j in range(sent_len):
                    pos = start + j
                    pm_v[pid * sent_len + j] = 1 if pred_match_at(
                        pid,
                        pos,
                        lemma_v,
                        pos_v,
                        word_v,
                        pred_cond_off_v,
                        cond_attr_v,
                        cond_op_v,
                        cond_val_off_v,
                        cond_val_len_v,
                        values_v,
                    ) else 0

    cdef cnp.ndarray[uint8_t, ndim=1] start_ok = np.empty((sent_len,), dtype=np.uint8)
    cdef uint8_t[:] start_ok_v = start_ok
    cdef bint ok
    cdef int w
    cdef int n_start_preds = start_pred_ids_v.shape[0]
    if n_start_preds > 0:
        with nogil:
            for j in range(sent_len):
                ok = False
                for w in range(n_start_preds):
                    pid = start_pred_ids_v[w]
                    if pm_v[pid * sent_len + j]:
                        ok = True
                        break
                start_ok_v[j] = 1 if ok else 0
    else:
        start_ok.fill(1)

    # bitset working buffers
    cdef uint64_t* active = <uint64_t*> PyMem_Malloc(words * sizeof(uint64_t))
    cdef uint64_t* nxt = <uint64_t*> PyMem_Malloc(words * sizeof(uint64_t))
    if active == NULL or nxt == NULL:
        if active != NULL:
            PyMem_Free(active)
        if nxt != NULL:
            PyMem_Free(nxt)
        raise MemoryError()

    cdef list out = []
    cdef int i = 0
    cdef int last_accept
    cdef int32_t state
    cdef Py_ssize_t e0, e1, ei
    cdef int32_t ep
    cdef uint64_t x
    cdef int b

    try:
        while i < sent_len and len(out) < max_matches:
            # Quick skip: if none of the start predicates match at this token, skip.
            if not start_ok_v[i]:
                i += 1
                continue

            # match from i
            with nogil:
                bitset_copy(active, start_bits_v, words)
            last_accept = -1
            j = i
            while j < sent_len:
                with nogil:
                    if bitset_empty(active, words):
                        break
                    bitset_clear(nxt, words)

                    # iterate active states
                    for w in range(words):
                        x = active[w]
                        while x:
                            b = ctz64(x)
                            state = <int32_t>(w * 64 + b)
                            x &= x - 1  # clear lowest set bit
                            if state >= n_states:
                                continue
                            e0 = state_edge_off_v[state]
                            e1 = state_edge_off_v[state + 1]
                            for ei in range(e0, e1):
                                ep = edge_pred_v[ei]
                                if pm_v[ep * sent_len + j]:
                                    bitset_or_inplace(nxt, edge_tgt_v, ei, words)

                    # advance
                    for w in range(words):
                        active[w] = nxt[w]

                    if bitset_intersects(active, accept_bits_v, words):
                        # record accepting end (exclusive)
                        last_accept = j + 1

                j += 1

            if last_accept != -1:
                out.append((start + i, start + last_accept))
                i = last_accept
            else:
                i += 1
    finally:
        PyMem_Free(active)
        PyMem_Free(nxt)

    return out


def nfa_find_matches_many(
    cnp.ndarray[int32_t, ndim=1] lemma,
    cnp.ndarray[int32_t, ndim=1] pos_arr,
    cnp.ndarray[int32_t, ndim=1] word,
    cnp.ndarray[int32_t, ndim=1] sentence_starts,
    cnp.ndarray[int32_t, ndim=1] sentence_ends,
    cnp.ndarray[uint64_t, ndim=1] start_bits,
    cnp.ndarray[uint64_t, ndim=1] accept_bits,
    cnp.ndarray[int32_t, ndim=1] state_edge_off,
    cnp.ndarray[int32_t, ndim=1] edge_pred,
    cnp.ndarray[uint64_t, ndim=2] edge_tgt,
    cnp.ndarray[int32_t, ndim=1] start_pred_ids,
    cnp.ndarray[int32_t, ndim=1] pred_cond_off,
    cnp.ndarray[uint8_t, ndim=1] cond_attr,
    cnp.ndarray[uint8_t, ndim=1] cond_op,
    cnp.ndarray[int32_t, ndim=1] cond_val_off,
    cnp.ndarray[int32_t, ndim=1] cond_val_len,
    cnp.ndarray[int32_t, ndim=1] values,
    int max_matches,
    int base_offset=0,
    object sentence_offsets=None,
):
    """Find leftmost-longest non-overlapping matches for many sentence spans in one block."""

    cdef int32_t[:] lemma_v = lemma
    cdef int32_t[:] pos_v = pos_arr
    cdef int32_t[:] word_v = word
    cdef int32_t[:] sent_start_v = sentence_starts
    cdef int32_t[:] sent_end_v = sentence_ends
    cdef int32_t[:] sent_offset_v

    cdef uint64_t[:] start_bits_v = start_bits
    cdef uint64_t[:] accept_bits_v = accept_bits

    cdef int32_t[:] state_edge_off_v = state_edge_off
    cdef int32_t[:] edge_pred_v = edge_pred
    cdef uint64_t[:, :] edge_tgt_v = edge_tgt

    cdef int32_t[:] start_pred_ids_v = start_pred_ids

    cdef int32_t[:] pred_cond_off_v = pred_cond_off
    cdef uint8_t[:] cond_attr_v = cond_attr
    cdef uint8_t[:] cond_op_v = cond_op
    cdef int32_t[:] cond_val_off_v = cond_val_off
    cdef int32_t[:] cond_val_len_v = cond_val_len
    cdef int32_t[:] values_v = values

    cdef int n_states = state_edge_off_v.shape[0] - 1
    cdef int n_preds = pred_cond_off_v.shape[0] - 1
    cdef int words = start_bits_v.shape[0]
    cdef int block_len = lemma_v.shape[0]
    if pos_v.shape[0] > block_len:
        block_len = pos_v.shape[0]
    if word_v.shape[0] > block_len:
        block_len = word_v.shape[0]
    cdef int n_sentences = sent_start_v.shape[0]
    cdef int n_start_preds = start_pred_ids_v.shape[0]
    cdef bint use_sentence_offsets = sentence_offsets is not None

    if use_sentence_offsets:
        sent_offset_v = sentence_offsets
        if sent_offset_v.shape[0] != n_sentences:
            raise ValueError("sentence_offsets passt nicht zu sentence_starts")

    if block_len <= 0 or n_sentences <= 0 or max_matches <= 0:
        return []

    cdef cnp.ndarray[uint8_t, ndim=1] pm = np.empty((n_preds * block_len,), dtype=np.uint8)
    cdef uint8_t[:] pm_v = pm

    cdef int pid
    cdef int j
    cdef int pos
    cdef int c0
    cdef int c1
    cdef int ai
    cdef int op
    cdef int off
    cdef int ln
    cdef int ai1
    cdef int op1
    cdef int off1
    cdef int ln1
    cdef int ai2
    cdef int op2
    cdef int off2
    cdef int ln2

    with nogil:
        for pid in range(n_preds):
            c0 = pred_cond_off_v[pid]
            c1 = pred_cond_off_v[pid + 1]
            if c1 == c0 + 1:
                ai = cond_attr_v[c0]
                op = cond_op_v[c0]
                off = cond_val_off_v[c0]
                ln = cond_val_len_v[c0]
                if ai == 0:
                    fill_pm_single(pm_v, pid * block_len, lemma_v, 0, block_len, op, off, ln, values_v)
                elif ai == 1:
                    fill_pm_single(pm_v, pid * block_len, pos_v, 0, block_len, op, off, ln, values_v)
                else:
                    fill_pm_single(pm_v, pid * block_len, word_v, 0, block_len, op, off, ln, values_v)
            elif c1 == c0 + 2:
                ai = cond_attr_v[c0]
                op = cond_op_v[c0]
                off = cond_val_off_v[c0]
                ln = cond_val_len_v[c0]
                ai1 = cond_attr_v[c0 + 1]
                op1 = cond_op_v[c0 + 1]
                off1 = cond_val_off_v[c0 + 1]
                ln1 = cond_val_len_v[c0 + 1]
                fill_pm_double(
                    pm_v,
                    pid * block_len,
                    lemma_v,
                    pos_v,
                    word_v,
                    0,
                    block_len,
                    ai,
                    op,
                    off,
                    ln,
                    ai1,
                    op1,
                    off1,
                    ln1,
                    values_v,
                )
            elif c1 == c0 + 3:
                ai = cond_attr_v[c0]
                op = cond_op_v[c0]
                off = cond_val_off_v[c0]
                ln = cond_val_len_v[c0]
                ai1 = cond_attr_v[c0 + 1]
                op1 = cond_op_v[c0 + 1]
                off1 = cond_val_off_v[c0 + 1]
                ln1 = cond_val_len_v[c0 + 1]
                ai2 = cond_attr_v[c0 + 2]
                op2 = cond_op_v[c0 + 2]
                off2 = cond_val_off_v[c0 + 2]
                ln2 = cond_val_len_v[c0 + 2]
                fill_pm_triple(
                    pm_v,
                    pid * block_len,
                    lemma_v,
                    pos_v,
                    word_v,
                    0,
                    block_len,
                    ai,
                    op,
                    off,
                    ln,
                    ai1,
                    op1,
                    off1,
                    ln1,
                    ai2,
                    op2,
                    off2,
                    ln2,
                    values_v,
                )
            else:
                for j in range(block_len):
                    pm_v[pid * block_len + j] = 1 if pred_match_at(
                        pid,
                        j,
                        lemma_v,
                        pos_v,
                        word_v,
                        pred_cond_off_v,
                        cond_attr_v,
                        cond_op_v,
                        cond_val_off_v,
                        cond_val_len_v,
                        values_v,
                    ) else 0

    cdef cnp.ndarray[uint8_t, ndim=1] start_ok = np.empty((block_len,), dtype=np.uint8)
    cdef uint8_t[:] start_ok_v = start_ok
    cdef bint ok
    cdef int w
    if n_start_preds > 0:
        with nogil:
            for j in range(block_len):
                ok = False
                for w in range(n_start_preds):
                    pid = start_pred_ids_v[w]
                    if pm_v[pid * block_len + j]:
                        ok = True
                        break
                start_ok_v[j] = 1 if ok else 0
    else:
        start_ok.fill(1)

    cdef uint64_t* active = <uint64_t*> PyMem_Malloc(words * sizeof(uint64_t))
    cdef uint64_t* nxt = <uint64_t*> PyMem_Malloc(words * sizeof(uint64_t))
    if active == NULL or nxt == NULL:
        if active != NULL:
            PyMem_Free(active)
        if nxt != NULL:
            PyMem_Free(nxt)
        raise MemoryError()

    cdef list out = []
    cdef list sent_out
    cdef int sent_idx
    cdef int sent_start
    cdef int sent_end
    cdef int i
    cdef int last_accept
    cdef int32_t state
    cdef Py_ssize_t e0, e1, ei
    cdef int32_t ep
    cdef uint64_t x
    cdef int b

    try:
        for sent_idx in range(n_sentences):
            sent_start = sent_start_v[sent_idx]
            sent_end = sent_end_v[sent_idx]
            if sent_start < 0:
                sent_start = 0
            if sent_end > block_len:
                sent_end = block_len
            if sent_end <= sent_start:
                continue

            sent_out = []
            i = sent_start
            while i < sent_end and len(sent_out) < max_matches:
                if not start_ok_v[i]:
                    i += 1
                    continue

                with nogil:
                    bitset_copy(active, start_bits_v, words)
                last_accept = -1
                j = i
                while j < sent_end:
                    with nogil:
                        if bitset_empty(active, words):
                            break
                        bitset_clear(nxt, words)

                        for w in range(words):
                            x = active[w]
                            while x:
                                b = ctz64(x)
                                state = <int32_t>(w * 64 + b)
                                x &= x - 1
                                if state >= n_states:
                                    continue
                                e0 = state_edge_off_v[state]
                                e1 = state_edge_off_v[state + 1]
                                for ei in range(e0, e1):
                                    ep = edge_pred_v[ei]
                                    if pm_v[ep * block_len + j]:
                                        bitset_or_inplace(nxt, edge_tgt_v, ei, words)

                        for w in range(words):
                            active[w] = nxt[w]

                        if bitset_intersects(active, accept_bits_v, words):
                            last_accept = j + 1

                    j += 1

                if last_accept != -1:
                    if use_sentence_offsets:
                        sent_out.append((sent_offset_v[sent_idx] + i, sent_offset_v[sent_idx] + last_accept))
                    else:
                        sent_out.append((base_offset + i, base_offset + last_accept))
                    i = last_accept
                else:
                    i += 1

            if sent_out:
                out.append((sent_idx, sent_out))
    finally:
        PyMem_Free(active)
        PyMem_Free(nxt)

    return out
