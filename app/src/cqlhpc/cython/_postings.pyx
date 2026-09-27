# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False, nonecheck=False, cdivision=True

from cpython.mem cimport PyMem_Malloc, PyMem_Free

import numpy as np
cimport numpy as cnp

ctypedef cnp.int32_t int32_t
ctypedef cnp.int64_t int64_t


cdef inline void heap_swap(int32_t* hv, int32_t* hi, Py_ssize_t a, Py_ssize_t b) noexcept nogil:
    cdef int32_t tv = hv[a]
    cdef int32_t ti = hi[a]
    hv[a] = hv[b]
    hi[a] = hi[b]
    hv[b] = tv
    hi[b] = ti


cdef inline void heap_sift_up(int32_t* hv, int32_t* hi, Py_ssize_t idx) noexcept nogil:
    cdef Py_ssize_t parent
    while idx > 0:
        parent = (idx - 1) >> 1
        if hv[parent] <= hv[idx]:
            break
        heap_swap(hv, hi, parent, idx)
        idx = parent


cdef inline void heap_sift_down(int32_t* hv, int32_t* hi, Py_ssize_t size, Py_ssize_t idx) noexcept nogil:
    cdef Py_ssize_t left, right, smallest
    while True:
        left = (idx << 1) + 1
        right = left + 1
        smallest = idx
        if left < size and hv[left] < hv[smallest]:
            smallest = left
        if right < size and hv[right] < hv[smallest]:
            smallest = right
        if smallest == idx:
            break
        heap_swap(hv, hi, idx, smallest)
        idx = smallest


cdef inline void heap_push(int32_t* hv, int32_t* hi, Py_ssize_t* size, int32_t v, int32_t src) noexcept nogil:
    cdef Py_ssize_t i = size[0]
    hv[i] = v
    hi[i] = src
    size[0] = i + 1
    heap_sift_up(hv, hi, i)


cdef inline void heap_pop(int32_t* hv, int32_t* hi, Py_ssize_t* size, int32_t* out_v, int32_t* out_src) noexcept nogil:
    cdef Py_ssize_t n = size[0]
    out_v[0] = hv[0]
    out_src[0] = hi[0]
    n -= 1
    if n > 0:
        hv[0] = hv[n]
        hi[0] = hi[n]
        heap_sift_down(hv, hi, n, 0)
    size[0] = n


def intersect_shifted(cnp.ndarray[int32_t, ndim=1] a, cnp.ndarray[int32_t, ndim=1] b, int shift):
    """Return positions p in a such that p+shift is present in b."""
    cdef Py_ssize_t ia = 0
    cdef Py_ssize_t ib = 0
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]

    if na == 0 or nb == 0:
        return np.empty((0,), dtype=np.int32)

    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((na,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef int32_t va
    cdef int32_t vb

    while ia < na and ib < nb:
        va = a[ia] + shift
        vb = b[ib]
        if va == vb:
            out[k] = a[ia]
            k += 1
            ia += 1
            ib += 1
        elif va < vb:
            ia += 1
        else:
            ib += 1

    return out[:k]


cdef inline bint _binary_search_i32(int32_t* arr, Py_ssize_t n, int32_t target) noexcept nogil:
    cdef Py_ssize_t lo = 0
    cdef Py_ssize_t hi = n
    cdef Py_ssize_t mid
    cdef int32_t v
    while lo < hi:
        mid = (lo + hi) >> 1
        v = arr[mid]
        if v < target:
            lo = mid + 1
        else:
            hi = mid
    return lo < n and arr[lo] == target


cdef inline Py_ssize_t _lower_bound_i32_from(int32_t* arr, Py_ssize_t lo, Py_ssize_t hi, int32_t target) noexcept nogil:
    cdef Py_ssize_t mid
    cdef int32_t v
    while lo < hi:
        mid = (lo + hi) >> 1
        v = arr[mid]
        if v < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def intersect_sorted_unique(cnp.ndarray[int32_t, ndim=1] a, cnp.ndarray[int32_t, ndim=1] b):
    """Intersect two sorted unique int32 arrays."""
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    cdef cnp.ndarray[int32_t, ndim=1] out
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t lo
    cdef Py_ssize_t hi
    cdef Py_ssize_t probe
    cdef Py_ssize_t step
    cdef Py_ssize_t k = 0
    cdef int32_t va
    cdef int32_t vb
    cdef int32_t* aptr
    cdef int32_t* bptr
    cdef bint use_gallop
    cdef cnp.ndarray[int32_t, ndim=1] small
    cdef cnp.ndarray[int32_t, ndim=1] large
    cdef Py_ssize_t ns
    cdef Py_ssize_t nl

    if na == 0 or nb == 0:
        return np.empty((0,), dtype=np.int32)
    if a[na - 1] < b[0] or b[nb - 1] < a[0]:
        return np.empty((0,), dtype=np.int32)

    use_gallop = na * 8 < nb or nb * 8 < na
    if use_gallop:
        if na <= nb:
            small = a
            large = b
        else:
            small = b
            large = a
        ns = small.shape[0]
        nl = large.shape[0]
        out = np.empty((ns,), dtype=np.int32)
        aptr = <int32_t*> small.data
        bptr = <int32_t*> large.data
        lo = 0
        for i in range(ns):
            va = aptr[i]
            if lo >= nl:
                break
            if bptr[lo] < va:
                step = 1
                probe = lo + step
                while probe < nl and bptr[probe] < va:
                    step <<= 1
                    probe = lo + step
                hi = nl if probe >= nl else probe + 1
                lo = _lower_bound_i32_from(bptr, lo + 1, hi, va)
            if lo >= nl:
                break
            if bptr[lo] == va:
                out[k] = va
                k += 1
                lo += 1
        return out[:k]

    out = np.empty((na if na <= nb else nb,), dtype=np.int32)
    aptr = <int32_t*> a.data
    bptr = <int32_t*> b.data
    while i < na and j < nb:
        va = aptr[i]
        vb = bptr[j]
        if va == vb:
            out[k] = va
            k += 1
            i += 1
            j += 1
        elif va < vb:
            i += 1
        else:
            j += 1
    return out[:k]


def intersect_shifted_gallop(cnp.ndarray[int32_t, ndim=1] a, cnp.ndarray[int32_t, ndim=1] b, int shift):
    """Binary-search intersection: for each p in a, test (p+shift) in b."""
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    if na == 0 or nb == 0:
        return np.empty((0,), dtype=np.int32)
    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((na,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t i
    cdef int32_t target
    cdef int32_t* bptr = <int32_t*> b.data
    for i in range(na):
        target = a[i] + shift
        if _binary_search_i32(bptr, nb, target):
            out[k] = a[i]
            k += 1
    return out[:k]


def intersect_shifted_many(
    cnp.ndarray[int32_t, ndim=1] anchor,
    list others,
    list shifts,
):
    """Return positions p in anchor such that p+shift_i is present in each others[i]."""
    cdef Py_ssize_t m = len(others)
    if m == 0:
        return anchor.copy()
    if m != len(shifts):
        raise ValueError("others/shifts length mismatch")

    cdef int32_t** ptrs = <int32_t**> PyMem_Malloc(m * sizeof(int32_t*))
    cdef Py_ssize_t* lens = <Py_ssize_t*> PyMem_Malloc(m * sizeof(Py_ssize_t))
    cdef Py_ssize_t* idxs = <Py_ssize_t*> PyMem_Malloc(m * sizeof(Py_ssize_t))
    cdef int32_t* sh = <int32_t*> PyMem_Malloc(m * sizeof(int32_t))
    if ptrs == NULL or lens == NULL or idxs == NULL or sh == NULL:
        if ptrs != NULL: PyMem_Free(ptrs)
        if lens != NULL: PyMem_Free(lens)
        if idxs != NULL: PyMem_Free(idxs)
        if sh != NULL: PyMem_Free(sh)
        raise MemoryError()

    cdef Py_ssize_t i
    cdef cnp.ndarray[int32_t, ndim=1] arr
    for i in range(m):
        arr = others[i]
        if arr is None:
            lens[i] = 0
            idxs[i] = 0
            ptrs[i] = NULL
            sh[i] = <int32_t> shifts[i]
            continue
        lens[i] = arr.shape[0]
        idxs[i] = 0
        ptrs[i] = <int32_t*> arr.data
        sh[i] = <int32_t> shifts[i]

    cdef Py_ssize_t na = anchor.shape[0]
    if na == 0:
        PyMem_Free(ptrs)
        PyMem_Free(lens)
        PyMem_Free(idxs)
        PyMem_Free(sh)
        return np.empty((0,), dtype=np.int32)

    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((na,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t ia
    cdef int32_t a
    cdef int32_t target
    cdef int32_t v
    cdef Py_ssize_t idx
    cdef Py_ssize_t ln
    cdef bint ok

    for ia in range(na):
        a = anchor[ia]
        ok = True
        for i in range(m):
            ln = lens[i]
            if ln == 0:
                ok = False
                break
            target = a + sh[i]
            idx = idxs[i]
            while idx < ln and ptrs[i][idx] < target:
                idx += 1
            if idx >= ln:
                ok = False
                break
            v = ptrs[i][idx]
            idxs[i] = idx
            if v != target:
                ok = False
                break
        if ok:
            out[k] = a
            k += 1

    PyMem_Free(ptrs)
    PyMem_Free(lens)
    PyMem_Free(idxs)
    PyMem_Free(sh)
    return out[:k]


def positions_to_bitset(cnp.ndarray[int32_t, ndim=1] positions, Py_ssize_t n_tokens):
    """Build a compact bitset (uint8) for membership over token positions."""
    cdef Py_ssize_t n_bytes = (n_tokens + 7) >> 3
    cdef cnp.ndarray[cnp.uint8_t, ndim=1] out = np.zeros((n_bytes,), dtype=np.uint8)
    cdef Py_ssize_t i
    cdef Py_ssize_t n = positions.shape[0]
    cdef int32_t p
    cdef Py_ssize_t b
    cdef int32_t bit
    for i in range(n):
        p = positions[i]
        if p < 0 or p >= n_tokens:
            continue
        b = p >> 3
        bit = 1 << (p & 7)
        out[b] |= <cnp.uint8_t> bit
    return out


def postings_to_bitset(
    cnp.ndarray[int64_t, ndim=1] offsets,
    cnp.ndarray[int32_t, ndim=1] positions,
    cnp.ndarray[int32_t, ndim=1] type_ids,
    Py_ssize_t n_tokens,
):
    """Build bitset from postings lists referenced by type_ids."""
    cdef Py_ssize_t n_bytes = (n_tokens + 7) >> 3
    cdef cnp.ndarray[cnp.uint8_t, ndim=1] out = np.zeros((n_bytes,), dtype=np.uint8)
    cdef Py_ssize_t m = type_ids.shape[0]
    cdef Py_ssize_t i
    cdef int32_t tid
    cdef int64_t s
    cdef int64_t e
    cdef int32_t p
    cdef Py_ssize_t b
    cdef int32_t bit
    for i in range(m):
        tid = type_ids[i]
        if tid <= 0:
            continue
        s = offsets[tid]
        e = offsets[tid + 1]
        while s < e:
            p = positions[s]
            if p >= 0 and p < n_tokens:
                b = p >> 3
                bit = 1 << (p & 7)
                out[b] |= <cnp.uint8_t> bit
            s += 1
    return out


def filter_positions_by_bitset(
    cnp.ndarray[int32_t, ndim=1] anchor,
    cnp.ndarray[cnp.uint8_t, ndim=1] bitset,
    int shift,
    Py_ssize_t n_tokens,
):
    """Filter anchor positions by membership in bitset at p+shift."""
    cdef Py_ssize_t n = anchor.shape[0]
    if n == 0:
        return np.empty((0,), dtype=np.int32)
    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((n,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t i
    cdef int32_t p
    cdef Py_ssize_t q
    cdef Py_ssize_t b
    cdef int32_t bit
    for i in range(n):
        p = anchor[i]
        q = p + shift
        if q < 0 or q >= n_tokens:
            continue
        b = q >> 3
        bit = 1 << (q & 7)
        if bitset[b] & bit:
            out[k] = p
            k += 1
    return out[:k]


def filter_positions_by_bitset_no_bounds(
    cnp.ndarray[int32_t, ndim=1] anchor,
    cnp.ndarray[cnp.uint8_t, ndim=1] bitset,
    int shift,
):
    """Filter anchor positions by membership in bitset at p+shift.

    Preconditions:
    - all q = p + shift are gueltige Tokenpositionen
    - anchor is sorted int32
    """
    cdef Py_ssize_t n = anchor.shape[0]
    if n == 0:
        return np.empty((0,), dtype=np.int32)
    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((n,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t i
    cdef int32_t p
    cdef Py_ssize_t q
    cdef Py_ssize_t b
    cdef int32_t bit
    for i in range(n):
        p = anchor[i]
        q = p + shift
        b = q >> 3
        bit = 1 << (q & 7)
        if bitset[b] & bit:
            out[k] = p
            k += 1
    return out[:k]


cdef inline bint _bitset_contains(cnp.uint8_t* bitset, Py_ssize_t pos) noexcept nogil:
    return (bitset[pos >> 3] & <cnp.uint8_t>(1 << (pos & 7))) != 0


def bounded_repeat_sentence_matches(
    cnp.ndarray[int32_t, ndim=1] anchor,
    cnp.ndarray[cnp.uint8_t, ndim=1] middle_bitset,
    cnp.ndarray[cnp.uint8_t, ndim=1] right_bitset,
    int min_rep,
    int max_rep,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
    int max_matches,
    bint include_sids=True,
):
    cdef Py_ssize_t na = anchor.shape[0]
    cdef Py_ssize_t nsent = sent_ends.shape[0]
    cdef Py_ssize_t cap
    cdef cnp.ndarray[int32_t, ndim=1] out_starts
    cdef cnp.ndarray[int32_t, ndim=1] out_ends
    cdef cnp.ndarray[int32_t, ndim=1] out_sids
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t sid = 0
    cdef Py_ssize_t k = 0
    cdef int32_t prev_end = 0
    cdef int32_t cur_end
    cdef int32_t p
    cdef int32_t accepted_until
    cdef int max_mid
    cdef int rep
    cdef int best_rep
    cdef cnp.uint8_t* middle_ptr
    cdef cnp.uint8_t* right_ptr

    if na == 0 or nsent == 0 or max_rep < min_rep:
        return (
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
        )

    cap = na
    if max_matches > 0 and max_matches < cap:
        cap = max_matches
    out_starts = np.empty((cap,), dtype=np.int32)
    out_ends = np.empty((cap,), dtype=np.int32)
    if include_sids:
        out_sids = np.empty((cap,), dtype=np.int32)
    else:
        out_sids = np.empty((0,), dtype=np.int32)
    cur_end = sent_ends[0]
    middle_ptr = <cnp.uint8_t*> middle_bitset.data
    right_ptr = <cnp.uint8_t*> right_bitset.data

    while sid < nsent and i < na:
        while sid < nsent and anchor[i] >= cur_end:
            prev_end = cur_end
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break

        accepted_until = prev_end
        while i < na and anchor[i] < cur_end:
            p = anchor[i]
            i += 1
            if p < accepted_until:
                continue
            max_mid = cur_end - p - 2
            if max_mid < min_rep:
                continue
            if max_mid > max_rep:
                max_mid = max_rep
            best_rep = -1
            if min_rep == 0 and _bitset_contains(right_ptr, p + 1):
                best_rep = 0
            rep = 1
            while rep <= max_mid:
                if not _bitset_contains(middle_ptr, p + rep):
                    break
                if rep >= min_rep and _bitset_contains(right_ptr, p + rep + 1):
                    best_rep = rep
                rep += 1
            if best_rep >= 0:
                out_starts[k] = p
                out_ends[k] = p + best_rep + 2
                if include_sids:
                    out_sids[k] = <int32_t> sid
                accepted_until = out_ends[k]
                k += 1
                if k >= cap:
                    return out_starts[:k], out_ends[:k], out_sids[:k]

        prev_end = cur_end
        sid += 1
        if sid < nsent:
            cur_end = sent_ends[sid]

    return out_starts[:k], out_ends[:k], out_sids[:k]


def unbounded_repeat_sentence_matches(
    cnp.ndarray[int32_t, ndim=1] anchor,
    cnp.ndarray[cnp.uint8_t, ndim=1] right_bitset,
    int min_count,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
    int max_matches,
    bint include_sids=True,
):
    cdef Py_ssize_t na = anchor.shape[0]
    cdef Py_ssize_t nsent = sent_ends.shape[0]
    cdef Py_ssize_t cap
    cdef cnp.ndarray[int32_t, ndim=1] out_starts
    cdef cnp.ndarray[int32_t, ndim=1] out_ends
    cdef cnp.ndarray[int32_t, ndim=1] out_sids
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t sid = 0
    cdef Py_ssize_t k = 0
    cdef int32_t prev_end = 0
    cdef int32_t cur_end
    cdef int32_t p
    cdef int32_t run_start
    cdef int32_t run_end
    cdef int32_t accepted_until
    cdef int run_len
    cdef cnp.uint8_t* right_ptr

    if na == 0 or nsent == 0 or min_count <= 0:
        return (
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
        )

    cap = na
    if max_matches > 0 and max_matches < cap:
        cap = max_matches
    out_starts = np.empty((cap,), dtype=np.int32)
    out_ends = np.empty((cap,), dtype=np.int32)
    if include_sids:
        out_sids = np.empty((cap,), dtype=np.int32)
    else:
        out_sids = np.empty((0,), dtype=np.int32)
    cur_end = sent_ends[0]
    right_ptr = <cnp.uint8_t*> right_bitset.data

    while sid < nsent and i < na:
        while sid < nsent and anchor[i] >= cur_end:
            prev_end = cur_end
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break

        accepted_until = prev_end
        while i < na and anchor[i] < cur_end:
            p = anchor[i]
            if p < accepted_until:
                i += 1
                continue
            run_start = p
            run_end = p
            i += 1
            while i < na and anchor[i] < cur_end and anchor[i] == run_end + 1:
                run_end = anchor[i]
                i += 1
            run_len = run_end - run_start + 1
            if run_len >= min_count and run_end + 1 < cur_end and _bitset_contains(right_ptr, run_end + 1):
                out_starts[k] = run_start
                out_ends[k] = run_end + 2
                if include_sids:
                    out_sids[k] = <int32_t> sid
                accepted_until = out_ends[k]
                k += 1
                if k >= cap:
                    return out_starts[:k], out_ends[:k], out_sids[:k]

        prev_end = cur_end
        sid += 1
        if sid < nsent:
            cur_end = sent_ends[sid]

    return out_starts[:k], out_ends[:k], out_sids[:k]


def bounded_repeat_sentence_matches_from_right(
    cnp.ndarray[int32_t, ndim=1] right,
    cnp.ndarray[cnp.uint8_t, ndim=1] left_bitset,
    cnp.ndarray[cnp.uint8_t, ndim=1] middle_bitset,
    int min_rep,
    int max_rep,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
    int max_matches,
    bint include_sids=True,
):
    cdef Py_ssize_t nr = right.shape[0]
    cdef Py_ssize_t nsent = sent_ends.shape[0]
    cdef Py_ssize_t cap
    cdef cnp.ndarray[int32_t, ndim=1] out_starts
    cdef cnp.ndarray[int32_t, ndim=1] out_ends
    cdef cnp.ndarray[int32_t, ndim=1] out_sids
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t sid = 0
    cdef Py_ssize_t k = 0
    cdef int32_t prev_end = 0
    cdef int32_t cur_end
    cdef int32_t r
    cdef int32_t accepted_until
    cdef int max_mid
    cdef int rep
    cdef int best_rep
    cdef cnp.uint8_t* left_ptr
    cdef cnp.uint8_t* middle_ptr

    if nr == 0 or nsent == 0 or max_rep < min_rep:
        return (
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
        )

    cap = nr
    if max_matches > 0 and max_matches < cap:
        cap = max_matches
    out_starts = np.empty((cap,), dtype=np.int32)
    out_ends = np.empty((cap,), dtype=np.int32)
    if include_sids:
        out_sids = np.empty((cap,), dtype=np.int32)
    else:
        out_sids = np.empty((0,), dtype=np.int32)
    cur_end = sent_ends[0]
    left_ptr = <cnp.uint8_t*> left_bitset.data
    middle_ptr = <cnp.uint8_t*> middle_bitset.data

    while sid < nsent and i < nr:
        while sid < nsent and right[i] >= cur_end:
            prev_end = cur_end
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break

        accepted_until = prev_end
        while i < nr and right[i] < cur_end:
            r = right[i]
            i += 1
            if r < accepted_until:
                continue
            max_mid = r - prev_end - 1
            if max_mid < min_rep:
                continue
            if max_mid > max_rep:
                max_mid = max_rep
            best_rep = -1
            if min_rep == 0 and _bitset_contains(left_ptr, r - 1):
                best_rep = 0
            rep = 1
            while rep <= max_mid:
                if not _bitset_contains(middle_ptr, r - rep):
                    break
                if _bitset_contains(left_ptr, r - rep - 1):
                    best_rep = rep
                rep += 1
            if best_rep >= 0:
                out_starts[k] = r - best_rep - 1
                out_ends[k] = r + 1
                if include_sids:
                    out_sids[k] = <int32_t>sid
                accepted_until = out_ends[k]
                k += 1
                if k >= cap:
                    return out_starts[:k], out_ends[:k], out_sids[:k]

        prev_end = cur_end
        sid += 1
        if sid < nsent:
            cur_end = sent_ends[sid]

    return out_starts[:k], out_ends[:k], out_sids[:k]


def unbounded_repeat_sentence_matches_from_right(
    cnp.ndarray[int32_t, ndim=1] right,
    cnp.ndarray[cnp.uint8_t, ndim=1] left_bitset,
    int min_count,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
    int max_matches,
    bint include_sids=True,
):
    cdef Py_ssize_t nr = right.shape[0]
    cdef Py_ssize_t nsent = sent_ends.shape[0]
    cdef Py_ssize_t cap
    cdef cnp.ndarray[int32_t, ndim=1] out_starts
    cdef cnp.ndarray[int32_t, ndim=1] out_ends
    cdef cnp.ndarray[int32_t, ndim=1] out_sids
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t sid = 0
    cdef Py_ssize_t k = 0
    cdef int32_t prev_end = 0
    cdef int32_t cur_end
    cdef int32_t r
    cdef int32_t run_start
    cdef int32_t run_end
    cdef int32_t accepted_until
    cdef int run_len
    cdef cnp.uint8_t* left_ptr

    if nr == 0 or nsent == 0 or min_count <= 0:
        return (
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
        )

    cap = nr
    if max_matches > 0 and max_matches < cap:
        cap = max_matches
    out_starts = np.empty((cap,), dtype=np.int32)
    out_ends = np.empty((cap,), dtype=np.int32)
    if include_sids:
        out_sids = np.empty((cap,), dtype=np.int32)
    else:
        out_sids = np.empty((0,), dtype=np.int32)
    cur_end = sent_ends[0]
    left_ptr = <cnp.uint8_t*> left_bitset.data

    while sid < nsent and i < nr:
        while sid < nsent and right[i] >= cur_end:
            prev_end = cur_end
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break

        accepted_until = prev_end
        while i < nr and right[i] < cur_end:
            r = right[i]
            i += 1
            if r < accepted_until:
                continue
            if r - prev_end < min_count:
                continue
            run_end = r - 1
            if not _bitset_contains(left_ptr, run_end):
                continue
            run_start = run_end
            while run_start > prev_end and _bitset_contains(left_ptr, run_start - 1):
                run_start -= 1
            run_len = run_end - run_start + 1
            if run_len >= min_count:
                out_starts[k] = run_start
                out_ends[k] = r + 1
                if include_sids:
                    out_sids[k] = <int32_t>sid
                accepted_until = out_ends[k]
                k += 1
                if k >= cap:
                    return out_starts[:k], out_ends[:k], out_sids[:k]

        prev_end = cur_end
        sid += 1
        if sid < nsent:
            cur_end = sent_ends[sid]

    return out_starts[:k], out_ends[:k], out_sids[:k]


def bounded_repeat_sentence_ids(
    cnp.ndarray[int32_t, ndim=1] anchor,
    cnp.ndarray[cnp.uint8_t, ndim=1] middle_bitset,
    cnp.ndarray[cnp.uint8_t, ndim=1] right_bitset,
    int min_rep,
    int max_rep,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
):
    cdef Py_ssize_t na = anchor.shape[0]
    cdef Py_ssize_t nsent = sent_ends.shape[0]
    cdef cnp.ndarray[int32_t, ndim=1] out
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t sid = 0
    cdef Py_ssize_t k = 0
    cdef int32_t prev_end = 0
    cdef int32_t cur_end
    cdef int32_t p
    cdef int max_mid
    cdef int rep
    cdef bint matched
    cdef cnp.uint8_t* middle_ptr
    cdef cnp.uint8_t* right_ptr

    if na == 0 or nsent == 0 or max_rep < min_rep:
        return np.empty((0,), dtype=np.int32)

    out = np.empty((nsent,), dtype=np.int32)
    cur_end = sent_ends[0]
    middle_ptr = <cnp.uint8_t*> middle_bitset.data
    right_ptr = <cnp.uint8_t*> right_bitset.data

    while sid < nsent and i < na:
        while sid < nsent and anchor[i] >= cur_end:
            prev_end = cur_end
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break

        matched = False
        while i < na and anchor[i] < cur_end:
            p = anchor[i]
            i += 1
            max_mid = cur_end - p - 2
            if max_mid < min_rep:
                continue
            if max_mid > max_rep:
                max_mid = max_rep
            if min_rep == 0 and _bitset_contains(right_ptr, p + 1):
                matched = True
            else:
                rep = 1
                while rep <= max_mid:
                    if not _bitset_contains(middle_ptr, p + rep):
                        break
                    if rep >= min_rep and _bitset_contains(right_ptr, p + rep + 1):
                        matched = True
                        break
                    rep += 1
            if matched:
                out[k] = <int32_t>sid
                k += 1
                while i < na and anchor[i] < cur_end:
                    i += 1
                break

        prev_end = cur_end
        sid += 1
        if sid < nsent:
            cur_end = sent_ends[sid]

    return out[:k]


def merge_postings_many(
    cnp.ndarray[int64_t, ndim=1] offsets,
    cnp.ndarray[int32_t, ndim=1] positions,
    cnp.ndarray[int32_t, ndim=1] type_ids,
):
    """Union-merge multiple postings lists.

    offsets: len(V+1)
    positions: concatenated postings
    type_ids: list of type ids to union

    Returns a sorted unique int32 array.
    """
    cdef Py_ssize_t m = type_ids.shape[0]
    if m == 0:
        return np.empty((0,), dtype=np.int32)

    cdef int64_t* ptr = <int64_t*> PyMem_Malloc(m * sizeof(int64_t))
    cdef int64_t* end = <int64_t*> PyMem_Malloc(m * sizeof(int64_t))
    cdef int32_t* hv = <int32_t*> PyMem_Malloc(m * sizeof(int32_t))
    cdef int32_t* hi = <int32_t*> PyMem_Malloc(m * sizeof(int32_t))
    if ptr == NULL or end == NULL or hv == NULL or hi == NULL:
        if ptr != NULL: PyMem_Free(ptr)
        if end != NULL: PyMem_Free(end)
        if hv != NULL: PyMem_Free(hv)
        if hi != NULL: PyMem_Free(hi)
        raise MemoryError()

    cdef Py_ssize_t i
    cdef int32_t tid
    cdef int64_t s
    cdef int64_t e
    cdef Py_ssize_t heap_size = 0
    cdef Py_ssize_t total = 0

    # init pointers + heap
    for i in range(m):
        tid = type_ids[i]
        s = offsets[tid]
        e = offsets[tid + 1]
        ptr[i] = s
        end[i] = e
        total += <Py_ssize_t>(e - s)
        if s < e:
            heap_push(hv, hi, &heap_size, positions[s], <int32_t>i)

    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((total,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef int32_t last = <int32_t>-2147483648
    cdef int32_t v
    cdef int32_t src

    cdef int32_t tmp_v
    cdef int32_t tmp_src

    while heap_size > 0:
        heap_pop(hv, hi, &heap_size, &tmp_v, &tmp_src)
        v = tmp_v
        src = tmp_src
        if k == 0 or v != last:
            out[k] = v
            k += 1
            last = v
        ptr[src] += 1
        if ptr[src] < end[src]:
            heap_push(hv, hi, &heap_size, positions[ptr[src]], src)

    PyMem_Free(ptr)
    PyMem_Free(end)
    PyMem_Free(hv)
    PyMem_Free(hi)

    return out[:k]


def sentence_ids_for_positions(
    cnp.ndarray[int32_t, ndim=1] positions,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
):
    """Map sorted token positions to sorted unique sentence IDs.

    Assumes: sent_ends are increasing, positions are increasing.
    """
    cdef Py_ssize_t npos = positions.shape[0]
    if npos == 0:
        return np.empty((0,), dtype=np.int32)

    cdef Py_ssize_t nsent = sent_ends.shape[0]
    if nsent == 0:
        return np.empty((0,), dtype=np.int32)

    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((npos,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t sid = 0
    cdef int32_t cur_end = sent_ends[0]
    cdef int32_t p

    for i in range(npos):
        p = positions[i]
        while sid < nsent and p >= cur_end:
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break
        if k == 0 or out[k - 1] != sid:
            out[k] = <int32_t>sid
            k += 1

    return out[:k]


def filter_positions_to_sentence_ids(
    cnp.ndarray[int32_t, ndim=1] positions,
    cnp.ndarray[int32_t, ndim=1] sent_ids,
    cnp.ndarray[int32_t, ndim=1] sent_starts,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
):
    """Filter sorted positions down to the selected sorted unique sentence IDs."""
    cdef Py_ssize_t npos = positions.shape[0]
    cdef Py_ssize_t nsids = sent_ids.shape[0]
    cdef cnp.ndarray[int32_t, ndim=1] out
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j
    cdef Py_ssize_t total = 0
    cdef Py_ssize_t k = 0
    cdef int32_t start_pos
    cdef int32_t end_pos

    if npos == 0 or nsids == 0:
        return np.empty((0,), dtype=np.int32)

    for j in range(nsids):
        start_pos = sent_starts[sent_ids[j]]
        end_pos = sent_ends[sent_ids[j]]
        while i < npos and positions[i] < start_pos:
            i += 1
        while i < npos and positions[i] < end_pos:
            total += 1
            i += 1

    if total <= 0:
        return np.empty((0,), dtype=np.int32)
    if total == npos and nsids == sent_ends.shape[0]:
        return positions

    out = np.empty((total,), dtype=np.int32)
    i = 0
    for j in range(nsids):
        start_pos = sent_starts[sent_ids[j]]
        end_pos = sent_ends[sent_ids[j]]
        while i < npos and positions[i] < start_pos:
            i += 1
        while i < npos and positions[i] < end_pos:
            out[k] = positions[i]
            k += 1
            i += 1
    return out if k == total else out[:k]


def sentence_ids_for_min_shift_same_sentence(
    cnp.ndarray[int32_t, ndim=1] anchor,
    cnp.ndarray[int32_t, ndim=1] other,
    int min_shift,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
):
    cdef Py_ssize_t na = anchor.shape[0]
    cdef Py_ssize_t nb = other.shape[0]
    cdef Py_ssize_t nsent = sent_ends.shape[0]
    cdef cnp.ndarray[int32_t, ndim=1] out
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t ai0
    cdef Py_ssize_t bj0
    cdef Py_ssize_t sid = 0
    cdef Py_ssize_t k = 0
    cdef int32_t prev_end = 0
    cdef int32_t cur_end
    cdef int32_t next_pos

    if na == 0 or nb == 0 or nsent == 0:
        return np.empty((0,), dtype=np.int32)

    out = np.empty((nsent,), dtype=np.int32)
    cur_end = sent_ends[0]

    while sid < nsent and i < na and j < nb:
        next_pos = anchor[i]
        if other[j] < next_pos:
            next_pos = other[j]
        while sid < nsent and next_pos >= cur_end:
            prev_end = cur_end
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break

        ai0 = i
        while i < na and anchor[i] < cur_end:
            i += 1
        bj0 = j
        while j < nb and other[j] < cur_end:
            j += 1
        if i > ai0 and j > bj0:
            if other[j - 1] - anchor[ai0] >= min_shift:
                out[k] = <int32_t>sid
                k += 1

        prev_end = cur_end
        sid += 1
        if sid < nsent:
            cur_end = sent_ends[sid]

    return out[:k]


def sentence_ids_for_shifted_range(
    cnp.ndarray[int32_t, ndim=1] anchor,
    cnp.ndarray[int32_t, ndim=1] other,
    int min_shift,
    int max_shift,
    cnp.ndarray[int32_t, ndim=1] sent_ends,
):
    cdef Py_ssize_t na = anchor.shape[0]
    cdef Py_ssize_t nb = other.shape[0]
    cdef Py_ssize_t nsent = sent_ends.shape[0]
    cdef cnp.ndarray[int32_t, ndim=1] out
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t ai0
    cdef Py_ssize_t ai1
    cdef Py_ssize_t bj0
    cdef Py_ssize_t bj1
    cdef Py_ssize_t sid = 0
    cdef Py_ssize_t k = 0
    cdef int32_t a
    cdef int32_t lower
    cdef int32_t upper
    cdef int32_t cur_end
    cdef int32_t next_pos
    cdef Py_ssize_t ii
    cdef Py_ssize_t jj
    cdef Py_ssize_t alen
    cdef Py_ssize_t blen

    if na == 0 or nb == 0 or nsent == 0:
        return np.empty((0,), dtype=np.int32)
    if min_shift > max_shift:
        return np.empty((0,), dtype=np.int32)

    out = np.empty((nsent,), dtype=np.int32)
    cur_end = sent_ends[0]

    while sid < nsent and i < na and j < nb:
        next_pos = anchor[i]
        if other[j] < next_pos:
            next_pos = other[j]
        while sid < nsent and next_pos >= cur_end:
            sid += 1
            if sid < nsent:
                cur_end = sent_ends[sid]
        if sid >= nsent:
            break

        ai0 = i
        while i < na and anchor[i] < cur_end:
            i += 1
        ai1 = i

        bj0 = j
        while j < nb and other[j] < cur_end:
            j += 1
        bj1 = j

        if ai1 > ai0 and bj1 > bj0:
            if other[bj1 - 1] >= anchor[ai0] + min_shift and other[bj0] <= anchor[ai1 - 1] + max_shift:
                alen = ai1 - ai0
                blen = bj1 - bj0
                if alen <= blen:
                    ii = ai0
                    jj = bj0
                    while ii < ai1 and jj < bj1:
                        a = anchor[ii]
                        lower = a + min_shift
                        upper = a + max_shift
                        while jj < bj1 and other[jj] < lower:
                            jj += 1
                        if jj >= bj1:
                            break
                        if other[jj] <= upper:
                            out[k] = <int32_t>sid
                            k += 1
                            break
                        ii += 1
                else:
                    ii = ai0
                    jj = bj0
                    while ii < ai1 and jj < bj1:
                        a = other[jj]
                        lower = a - max_shift
                        upper = a - min_shift
                        while ii < ai1 and anchor[ii] < lower:
                            ii += 1
                        if ii >= ai1:
                            break
                        if anchor[ii] <= upper:
                            out[k] = <int32_t>sid
                            k += 1
                            break
                        jj += 1

        sid += 1
        if sid < nsent:
            cur_end = sent_ends[sid]

    return out[:k]


def union_positions_many(arrays):
    """Union-merge multiple sorted int32 arrays.

    arrays: Python list/tuple of int32 ndarrays (sorted, unique).
    Returns a sorted unique int32 array.
    """
    cdef Py_ssize_t m = len(arrays)
    if m == 0:
        return np.empty((0,), dtype=np.int32)
    if m == 1:
        return np.asarray(arrays[0], dtype=np.int32)

    cdef int32_t** ptrs = <int32_t**> PyMem_Malloc(m * sizeof(int32_t*))
    cdef Py_ssize_t* lens = <Py_ssize_t*> PyMem_Malloc(m * sizeof(Py_ssize_t))
    cdef Py_ssize_t* idxs = <Py_ssize_t*> PyMem_Malloc(m * sizeof(Py_ssize_t))
    cdef int32_t* hv = <int32_t*> PyMem_Malloc(m * sizeof(int32_t))
    cdef int32_t* hi = <int32_t*> PyMem_Malloc(m * sizeof(int32_t))
    if ptrs == NULL or lens == NULL or idxs == NULL or hv == NULL or hi == NULL:
        if ptrs != NULL: PyMem_Free(ptrs)
        if lens != NULL: PyMem_Free(lens)
        if idxs != NULL: PyMem_Free(idxs)
        if hv != NULL: PyMem_Free(hv)
        if hi != NULL: PyMem_Free(hi)
        raise MemoryError()

    cdef Py_ssize_t i
    cdef Py_ssize_t total = 0
    cdef Py_ssize_t heap_size = 0

    cdef cnp.ndarray[int32_t, ndim=1] arr

    for i in range(m):
        arr = arrays[i]
        if arr is None:
            lens[i] = 0
            idxs[i] = 0
            ptrs[i] = NULL
            continue
        lens[i] = arr.shape[0]
        idxs[i] = 0
        if lens[i] == 0:
            ptrs[i] = NULL
            continue
        ptrs[i] = <int32_t*> arr.data
        total += lens[i]
        heap_push(hv, hi, &heap_size, ptrs[i][0], <int32_t>i)

    if total == 0:
        PyMem_Free(ptrs)
        PyMem_Free(lens)
        PyMem_Free(idxs)
        PyMem_Free(hv)
        PyMem_Free(hi)
        return np.empty((0,), dtype=np.int32)

    cdef cnp.ndarray[int32_t, ndim=1] out = np.empty((total,), dtype=np.int32)
    cdef Py_ssize_t k = 0
    cdef int32_t last = <int32_t>-2147483648
    cdef int32_t v
    cdef int32_t src
    cdef int32_t tmp_v
    cdef int32_t tmp_src

    while heap_size > 0:
        heap_pop(hv, hi, &heap_size, &tmp_v, &tmp_src)
        v = tmp_v
        src = tmp_src
        if k == 0 or v != last:
            out[k] = v
            k += 1
            last = v
        idxs[src] += 1
        if idxs[src] < lens[src]:
            heap_push(hv, hi, &heap_size, ptrs[src][idxs[src]], src)

    PyMem_Free(ptrs)
    PyMem_Free(lens)
    PyMem_Free(idxs)
    PyMem_Free(hv)
    PyMem_Free(hi)

    return out[:k].copy()
