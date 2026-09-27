# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True

import os
import numpy as np
cimport numpy as np
from libc.limits cimport LLONG_MAX
from libc.math cimport log
from libc.stdlib cimport malloc, free
from cython.parallel cimport parallel, prange, threadid
from cpython.dict cimport PyDict_Next
from cpython.mem cimport PyMem_Malloc, PyMem_Free
from cpython.object cimport PyObject
from cpython.object cimport PyObject_RichCompareBool, Py_EQ


ENABLE_PARALLEL_DENSE_COUNTS = os.getenv("CANDYCONC_ENABLE_PARALLEL_DENSE_COUNTS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


cdef void _svb_decode_block(
    const unsigned char* data,
    unsigned long long data_len,
    unsigned int n,
    unsigned int* out,
) noexcept nogil:
    cdef unsigned int groups = (n + 3) // 4
    cdef const unsigned char* controls = data
    cdef const unsigned char* p = data + groups
    cdef unsigned int o = 0
    cdef unsigned int g
    cdef unsigned int i
    cdef unsigned int l
    cdef unsigned int v
    cdef unsigned char ctrl
    for g in range(groups):
        ctrl = controls[g]
        for i in range(4):
            if o >= n:
                break
            l = ((ctrl >> (2 * i)) & 3) + 1
            v = 0
            if p + l > data + data_len:
                l = <unsigned int>(data + data_len - p)
            if l >= 1:
                v |= <unsigned int>p[0]
            if l >= 2:
                v |= (<unsigned int>p[1] << 8)
            if l >= 3:
                v |= (<unsigned int>p[2] << 16)
            if l >= 4:
                v |= (<unsigned int>p[3] << 24)
            p += l
            out[o] = v
            o += 1


cdef inline Py_ssize_t _first_end_after_u32(
    const unsigned int[:] ends,
    Py_ssize_t n,
    unsigned long long target,
) noexcept nogil:
    cdef Py_ssize_t lo = 0
    cdef Py_ssize_t hi = n
    cdef Py_ssize_t mid
    while lo < hi:
        mid = lo + ((hi - lo) >> 1)
        if ends[mid] <= target:
            lo = mid + 1
        else:
            hi = mid
    return lo


cdef void _count_block_dense_local(
    const unsigned int[:] starts,
    const unsigned int[:] ends,
    const unsigned int[:] weights,
    Py_ssize_t n_seg,
    unsigned long long block_start,
    unsigned long long block_end,
    unsigned int* buf,
    np.uint64_t* counts_ptr,
    unsigned int vocab_size,
) noexcept nogil:
    cdef Py_ssize_t seg_idx = _first_end_after_u32(ends, n_seg, block_start)
    cdef Py_ssize_t t
    cdef unsigned int seg_start
    cdef unsigned int seg_end
    cdef unsigned int seg_weight
    cdef unsigned int rel_start
    cdef unsigned int rel_end
    cdef unsigned int pos
    cdef unsigned int tid

    if seg_idx >= n_seg or starts[seg_idx] >= block_end:
        return
    t = seg_idx
    while t < n_seg and starts[t] < block_end:
        seg_start = starts[t]
        if seg_start < block_start:
            seg_start = <unsigned int>block_start
        seg_end = ends[t]
        if seg_end > block_end:
            seg_end = <unsigned int>block_end
        if seg_start < seg_end:
            seg_weight = weights[t]
            rel_start = <unsigned int>(seg_start - block_start)
            rel_end = <unsigned int>(seg_end - block_start)
            for pos in range(rel_start, rel_end):
                tid = buf[pos]
                if tid != 0 and tid <= vocab_size:
                    counts_ptr[tid] += seg_weight
        t += 1


cdef void _count_block_dual_local(
    const unsigned int[:] starts_a,
    const unsigned int[:] ends_a,
    const unsigned int[:] weights_a,
    Py_ssize_t na,
    const unsigned int[:] starts_b,
    const unsigned int[:] ends_b,
    const unsigned int[:] weights_b,
    Py_ssize_t nb,
    unsigned long long block_start,
    unsigned long long block_end,
    unsigned int* buf,
    np.uint64_t* counts_a_ptr,
    np.uint64_t* counts_b_ptr,
    unsigned int vocab_size,
) noexcept nogil:
    cdef Py_ssize_t seg_idx_a = _first_end_after_u32(ends_a, na, block_start)
    cdef Py_ssize_t seg_idx_b = _first_end_after_u32(ends_b, nb, block_start)
    cdef Py_ssize_t t
    cdef unsigned int seg_start
    cdef unsigned int seg_end
    cdef unsigned int seg_weight
    cdef unsigned int rel_start
    cdef unsigned int rel_end
    cdef unsigned int pos
    cdef unsigned int tid

    if (seg_idx_a >= na or starts_a[seg_idx_a] >= block_end) and (seg_idx_b >= nb or starts_b[seg_idx_b] >= block_end):
        return

    t = seg_idx_a
    while t < na and starts_a[t] < block_end:
        seg_start = starts_a[t]
        if seg_start < block_start:
            seg_start = <unsigned int>block_start
        seg_end = ends_a[t]
        if seg_end > block_end:
            seg_end = <unsigned int>block_end
        if seg_start < seg_end:
            seg_weight = weights_a[t]
            rel_start = <unsigned int>(seg_start - block_start)
            rel_end = <unsigned int>(seg_end - block_start)
            for pos in range(rel_start, rel_end):
                tid = buf[pos]
                if tid != 0 and tid <= vocab_size:
                    counts_a_ptr[tid] += seg_weight
        t += 1

    t = seg_idx_b
    while t < nb and starts_b[t] < block_end:
        seg_start = starts_b[t]
        if seg_start < block_start:
            seg_start = <unsigned int>block_start
        seg_end = ends_b[t]
        if seg_end > block_end:
            seg_end = <unsigned int>block_end
        if seg_start < seg_end:
            seg_weight = weights_b[t]
            rel_start = <unsigned int>(seg_start - block_start)
            rel_end = <unsigned int>(seg_end - block_start)
            for pos in range(rel_start, rel_end):
                tid = buf[pos]
                if tid != 0 and tid <= vocab_size:
                    counts_b_ptr[tid] += seg_weight
        t += 1


def count_segments_cy(
    np.ndarray[np.uint32_t, ndim=1] word_ids,
    np.ndarray[np.uint32_t, ndim=1] seg_starts,
    np.ndarray[np.uint32_t, ndim=1] seg_ends,
    np.ndarray[np.uint32_t, ndim=1] seg_weights,
    object stoplist=None,
):
    cdef dict counts = {}
    cdef object stopset = stoplist if stoplist else None
    cdef Py_ssize_t i, n_seg
    cdef Py_ssize_t pos
    cdef unsigned int tid
    cdef unsigned int start
    cdef unsigned int end
    cdef unsigned int weight
    cdef Py_ssize_t n_tokens = word_ids.shape[0]

    n_seg = seg_starts.shape[0]
    for i in range(n_seg):
        start = seg_starts[i]
        end = seg_ends[i]
        if end > n_tokens:
            end = n_tokens
        if start >= end:
            continue
        weight = seg_weights[i]
        for pos in range(start, end):
            tid = word_ids[pos]
            if tid == 0:
                continue
            if stopset is not None and tid in stopset:
                continue
            counts[tid] = counts.get(tid, 0) + weight

    return counts


def count_segments_svb(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.uint32_t, ndim=1] seg_starts,
    np.ndarray[np.uint32_t, ndim=1] seg_ends,
    np.ndarray[np.uint32_t, ndim=1] seg_weights,
    object stoplist=None,
):
    cdef dict counts = {}
    cdef object stopset = stoplist if stoplist else None
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t i, n_seg
    cdef unsigned int start
    cdef unsigned int end
    cdef unsigned int weight
    cdef unsigned int pos
    cdef unsigned int tid
    cdef unsigned long long block_idx
    cdef unsigned long long block_start
    cdef unsigned int block_len
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf

    n_seg = seg_starts.shape[0]
    for i in range(n_seg):
        start = seg_starts[i]
        end = seg_ends[i]
        if start >= end:
            continue
        if end > token_count:
            end = <unsigned int>token_count
        weight = seg_weights[i]
        pos = start
        while pos < end:
            block_idx = pos // block_size
            block_start = block_idx * block_size
            start_off = offsets[block_idx]
            end_off = offsets[block_idx + 1]
            block_len = block_size
            if (block_idx + 1) * block_size > token_count:
                block_len = <unsigned int>(token_count - block_idx * block_size)
            _svb_decode_block(&blob[start_off], end_off - start_off, block_len, &buf_view[0])
            while pos < end and pos < block_start + block_len:
                tid = buf_view[pos - block_start]
                if tid != 0:
                    if stopset is None or tid not in stopset:
                        counts[tid] = counts.get(tid, 0) + weight
                pos += 1
    return counts


def count_segments_svb_dense(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.uint32_t, ndim=1] seg_starts,
    np.ndarray[np.uint32_t, ndim=1] seg_ends,
    np.ndarray[np.uint32_t, ndim=1] seg_weights,
    unsigned int vocab_size,
    object stoplist=None,
):
    cdef object stopset = stoplist if stoplist else None
    cdef bint only_zero_stop = stopset is None or (len(stopset) == 1 and 0 in stopset)
    cdef const unsigned char[:] blob = data
    cdef const unsigned int[:] starts = seg_starts
    cdef const unsigned int[:] ends = seg_ends
    cdef const unsigned int[:] weights = seg_weights
    cdef Py_ssize_t n_seg = starts.shape[0]
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t t
    cdef Py_ssize_t thread_idx
    cdef unsigned long long block_count
    cdef unsigned long long parallel_bytes
    cdef unsigned int pos
    cdef unsigned int tid
    cdef unsigned long long block_idx
    cdef unsigned long long block_start
    cdef unsigned long long block_end
    cdef unsigned int block_len
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned int seg_start
    cdef unsigned int seg_end
    cdef unsigned int seg_weight
    cdef unsigned int rel_start
    cdef unsigned int rel_end
    cdef bint need_block
    cdef int max_threads = 4
    cdef np.ndarray[np.uint64_t, ndim=1] counts = np.zeros(vocab_size + 1, dtype=np.uint64)
    cdef np.uint64_t[:] counts_view = counts
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf
    cdef np.ndarray[np.uint64_t, ndim=2] counts_threads
    cdef np.uint64_t[:, :] counts_threads_view
    cdef np.ndarray[np.uint8_t, ndim=1] malloc_failed
    cdef np.uint8_t[:] malloc_failed_view
    cdef unsigned int* local_buf

    if n_seg == 0:
        return counts

    block_count = (token_count + block_size - 1) // block_size
    parallel_bytes = <unsigned long long>max_threads * (<unsigned long long>vocab_size + 1) * sizeof(np.uint64_t)
    if (
        ENABLE_PARALLEL_DENSE_COUNTS
        and
        only_zero_stop
        and n_seg >= 1024
        and block_count >= <unsigned long long>(max_threads * 8)
        and parallel_bytes <= <unsigned long long>(256 * 1024 * 1024)
    ):
        counts_threads = np.zeros((max_threads, vocab_size + 1), dtype=np.uint64)
        malloc_failed = np.zeros(max_threads, dtype=np.uint8)
        counts_threads_view = counts_threads
        malloc_failed_view = malloc_failed
        with nogil, parallel(num_threads=max_threads):
            thread_idx = threadid()
            local_buf = <unsigned int*>malloc(block_size * sizeof(unsigned int))
            if local_buf == NULL:
                malloc_failed_view[thread_idx] = 1
            else:
                for block_idx in prange(block_count, schedule="static"):
                    block_start = block_idx * block_size
                    block_end = block_start + block_size
                    if block_end > token_count:
                        block_end = token_count
                    start_off = offsets[block_idx]
                    end_off = offsets[block_idx + 1]
                    block_len = block_size
                    if (block_idx + 1) * block_size > token_count:
                        block_len = <unsigned int>(token_count - block_idx * block_size)
                    _svb_decode_block(&blob[start_off], end_off - start_off, block_len, local_buf)
                    _count_block_dense_local(
                        starts,
                        ends,
                        weights,
                        n_seg,
                        block_start,
                        block_end,
                        local_buf,
                        &counts_threads_view[thread_idx, 0],
                        vocab_size,
                    )
                free(local_buf)
        if np.any(malloc_failed):
            raise MemoryError("Lokaler OpenMP-Puffer fuer count_segments_svb_dense konnte nicht alloziert werden")
        for thread_idx in range(max_threads):
            for tid in range(1, vocab_size + 1):
                counts_view[tid] += counts_threads_view[thread_idx, tid]
        return counts

    for block_idx in range(block_count):
        block_start = block_idx * block_size
        block_end = block_start + block_size
        if block_end > token_count:
            block_end = token_count

        while i < n_seg and ends[i] <= block_start:
            i += 1
        if i >= n_seg:
            break

        need_block = starts[i] < block_end
        if not need_block:
            continue

        start_off = offsets[block_idx]
        end_off = offsets[block_idx + 1]
        block_len = block_size
        if (block_idx + 1) * block_size > token_count:
            block_len = <unsigned int>(token_count - block_idx * block_size)
        _svb_decode_block(&blob[start_off], end_off - start_off, block_len, &buf_view[0])

        t = i
        while t < n_seg and starts[t] < block_end:
            seg_start = starts[t]
            if seg_start < block_start:
                seg_start = <unsigned int>block_start
            seg_end = ends[t]
            if seg_end > block_end:
                seg_end = <unsigned int>block_end
            if seg_start < seg_end:
                seg_weight = weights[t]
                rel_start = <unsigned int>(seg_start - block_start)
                rel_end = <unsigned int>(seg_end - block_start)
                for pos in range(rel_start, rel_end):
                    tid = buf_view[pos]
                    if tid == 0 or tid > vocab_size:
                        continue
                    if not only_zero_stop and stopset is not None and tid in stopset:
                        continue
                    counts_view[tid] += seg_weight
            if ends[t] <= block_end:
                t += 1
            else:
                break
        i = t
    return counts


def count_segments_svb_dual(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.uint32_t, ndim=1] seg_starts_a,
    np.ndarray[np.uint32_t, ndim=1] seg_ends_a,
    np.ndarray[np.uint32_t, ndim=1] seg_weights_a,
    np.ndarray[np.uint32_t, ndim=1] seg_starts_b,
    np.ndarray[np.uint32_t, ndim=1] seg_ends_b,
    np.ndarray[np.uint32_t, ndim=1] seg_weights_b,
    object stoplist=None,
):
    cdef dict counts_a = {}
    cdef dict counts_b = {}
    cdef object stopset = stoplist if stoplist else None
    cdef const unsigned char[:] blob = data
    cdef const unsigned int[:] starts_a = seg_starts_a
    cdef const unsigned int[:] ends_a = seg_ends_a
    cdef const unsigned int[:] weights_a = seg_weights_a
    cdef const unsigned int[:] starts_b = seg_starts_b
    cdef const unsigned int[:] ends_b = seg_ends_b
    cdef const unsigned int[:] weights_b = seg_weights_b
    cdef Py_ssize_t na = starts_a.shape[0]
    cdef Py_ssize_t nb = starts_b.shape[0]
    cdef Py_ssize_t ia = 0
    cdef Py_ssize_t ib = 0
    cdef Py_ssize_t ta
    cdef Py_ssize_t tb
    cdef unsigned long long block_idx
    cdef unsigned long long block_count
    cdef unsigned long long block_start
    cdef unsigned long long block_end
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned int block_len
    cdef unsigned int seg_start
    cdef unsigned int seg_end
    cdef unsigned int seg_weight
    cdef unsigned int rel_start
    cdef unsigned int rel_end
    cdef unsigned int pos
    cdef unsigned int tid
    cdef bint need_block
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf

    if na == 0 and nb == 0:
        return counts_a, counts_b

    block_count = (token_count + block_size - 1) // block_size
    for block_idx in range(block_count):
        block_start = block_idx * block_size
        block_end = block_start + block_size
        if block_end > token_count:
            block_end = token_count

        while ia < na and ends_a[ia] <= block_start:
            ia += 1
        while ib < nb and ends_b[ib] <= block_start:
            ib += 1

        need_block = False
        if ia < na and starts_a[ia] < block_end:
            need_block = True
        elif ib < nb and starts_b[ib] < block_end:
            need_block = True
        if not need_block:
            continue

        start_off = offsets[block_idx]
        end_off = offsets[block_idx + 1]
        block_len = block_size
        if (block_idx + 1) * block_size > token_count:
            block_len = <unsigned int>(token_count - block_idx * block_size)
        _svb_decode_block(&blob[start_off], end_off - start_off, block_len, &buf_view[0])

        ta = ia
        while ta < na and starts_a[ta] < block_end:
            seg_start = starts_a[ta]
            if seg_start < block_start:
                seg_start = <unsigned int>block_start
            seg_end = ends_a[ta]
            if seg_end > block_end:
                seg_end = <unsigned int>block_end
            if seg_start < seg_end:
                seg_weight = weights_a[ta]
                rel_start = <unsigned int>(seg_start - block_start)
                rel_end = <unsigned int>(seg_end - block_start)
                for pos in range(rel_start, rel_end):
                    tid = buf_view[pos]
                    if tid != 0:
                        if stopset is None or tid not in stopset:
                            counts_a[tid] = counts_a.get(tid, 0) + seg_weight
            if ends_a[ta] <= block_end:
                ta += 1
            else:
                break
        ia = ta

        tb = ib
        while tb < nb and starts_b[tb] < block_end:
            seg_start = starts_b[tb]
            if seg_start < block_start:
                seg_start = <unsigned int>block_start
            seg_end = ends_b[tb]
            if seg_end > block_end:
                seg_end = <unsigned int>block_end
            if seg_start < seg_end:
                seg_weight = weights_b[tb]
                rel_start = <unsigned int>(seg_start - block_start)
                rel_end = <unsigned int>(seg_end - block_start)
                for pos in range(rel_start, rel_end):
                    tid = buf_view[pos]
                    if tid != 0:
                        if stopset is None or tid not in stopset:
                            counts_b[tid] = counts_b.get(tid, 0) + seg_weight
            if ends_b[tb] <= block_end:
                tb += 1
            else:
                break
        ib = tb

    return counts_a, counts_b


def count_segments_svb_dual_dense(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.uint32_t, ndim=1] seg_starts_a,
    np.ndarray[np.uint32_t, ndim=1] seg_ends_a,
    np.ndarray[np.uint32_t, ndim=1] seg_weights_a,
    np.ndarray[np.uint32_t, ndim=1] seg_starts_b,
    np.ndarray[np.uint32_t, ndim=1] seg_ends_b,
    np.ndarray[np.uint32_t, ndim=1] seg_weights_b,
    unsigned int vocab_size,
    object stoplist=None,
):
    cdef object stopset = stoplist if stoplist else None
    cdef bint only_zero_stop = stopset is None or (len(stopset) == 1 and 0 in stopset)
    cdef const unsigned char[:] blob = data
    cdef const unsigned int[:] starts_a = seg_starts_a
    cdef const unsigned int[:] ends_a = seg_ends_a
    cdef const unsigned int[:] weights_a = seg_weights_a
    cdef const unsigned int[:] starts_b = seg_starts_b
    cdef const unsigned int[:] ends_b = seg_ends_b
    cdef const unsigned int[:] weights_b = seg_weights_b
    cdef Py_ssize_t na = starts_a.shape[0]
    cdef Py_ssize_t nb = starts_b.shape[0]
    cdef Py_ssize_t ia = 0
    cdef Py_ssize_t ib = 0
    cdef Py_ssize_t ta
    cdef Py_ssize_t tb
    cdef Py_ssize_t touched_n = 0
    cdef Py_ssize_t thread_idx
    cdef unsigned long long block_idx
    cdef unsigned long long block_count
    cdef unsigned long long block_start
    cdef unsigned long long block_end
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned long long parallel_bytes
    cdef unsigned int block_len
    cdef unsigned int seg_start
    cdef unsigned int seg_end
    cdef unsigned int seg_weight
    cdef unsigned int rel_start
    cdef unsigned int rel_end
    cdef unsigned int pos
    cdef unsigned int tid
    cdef bint need_block
    cdef int max_threads = 4
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf
    cdef np.ndarray[np.uint64_t, ndim=1] counts_a = np.zeros(vocab_size + 1, dtype=np.uint64)
    cdef np.ndarray[np.uint64_t, ndim=1] counts_b = np.zeros(vocab_size + 1, dtype=np.uint64)
    cdef np.ndarray[np.uint8_t, ndim=1] seen = np.zeros(vocab_size + 1, dtype=np.uint8)
    cdef np.ndarray[np.uint32_t, ndim=1] touched = np.empty(vocab_size + 1, dtype=np.uint32)
    cdef np.uint64_t[:] counts_a_view = counts_a
    cdef np.uint64_t[:] counts_b_view = counts_b
    cdef np.uint8_t[:] seen_view = seen
    cdef np.uint32_t[:] touched_view = touched
    cdef np.ndarray[np.uint32_t, ndim=1] ids
    cdef np.ndarray[np.uint64_t, ndim=1] vals_a
    cdef np.ndarray[np.uint64_t, ndim=1] vals_b
    cdef np.ndarray[np.uint64_t, ndim=2] counts_a_threads
    cdef np.ndarray[np.uint64_t, ndim=2] counts_b_threads
    cdef np.uint64_t[:, :] counts_a_threads_view
    cdef np.uint64_t[:, :] counts_b_threads_view
    cdef np.ndarray[np.uint8_t, ndim=1] malloc_failed
    cdef np.uint8_t[:] malloc_failed_view
    cdef unsigned int* local_buf
    cdef np.ndarray order

    if na == 0 and nb == 0:
        ids = np.zeros(0, dtype=np.uint32)
        vals_a = np.zeros(0, dtype=np.uint64)
        vals_b = np.zeros(0, dtype=np.uint64)
        return ids, vals_a, vals_b

    block_count = (token_count + block_size - 1) // block_size
    parallel_bytes = <unsigned long long>max_threads * (<unsigned long long>vocab_size + 1) * sizeof(np.uint64_t) * 2
    if (
        ENABLE_PARALLEL_DENSE_COUNTS
        and
        only_zero_stop
        and (na + nb) >= 2048
        and block_count >= <unsigned long long>(max_threads * 8)
        and parallel_bytes <= <unsigned long long>(256 * 1024 * 1024)
    ):
        counts_a_threads = np.zeros((max_threads, vocab_size + 1), dtype=np.uint64)
        counts_b_threads = np.zeros((max_threads, vocab_size + 1), dtype=np.uint64)
        malloc_failed = np.zeros(max_threads, dtype=np.uint8)
        counts_a_threads_view = counts_a_threads
        counts_b_threads_view = counts_b_threads
        malloc_failed_view = malloc_failed
        with nogil, parallel(num_threads=max_threads):
            thread_idx = threadid()
            local_buf = <unsigned int*>malloc(block_size * sizeof(unsigned int))
            if local_buf == NULL:
                malloc_failed_view[thread_idx] = 1
            else:
                for block_idx in prange(block_count, schedule="static"):
                    block_start = block_idx * block_size
                    block_end = block_start + block_size
                    if block_end > token_count:
                        block_end = token_count
                    start_off = offsets[block_idx]
                    end_off = offsets[block_idx + 1]
                    block_len = block_size
                    if (block_idx + 1) * block_size > token_count:
                        block_len = <unsigned int>(token_count - block_idx * block_size)
                    _svb_decode_block(&blob[start_off], end_off - start_off, block_len, local_buf)
                    _count_block_dual_local(
                        starts_a,
                        ends_a,
                        weights_a,
                        na,
                        starts_b,
                        ends_b,
                        weights_b,
                        nb,
                        block_start,
                        block_end,
                        local_buf,
                        &counts_a_threads_view[thread_idx, 0],
                        &counts_b_threads_view[thread_idx, 0],
                        vocab_size,
                    )
                free(local_buf)
        if np.any(malloc_failed):
            raise MemoryError("Lokaler OpenMP-Puffer fuer count_segments_svb_dual_dense konnte nicht alloziert werden")
        for thread_idx in range(max_threads):
            for tid in range(1, vocab_size + 1):
                counts_a_view[tid] += counts_a_threads_view[thread_idx, tid]
                counts_b_view[tid] += counts_b_threads_view[thread_idx, tid]
        touched_n = 0
        for tid in range(1, vocab_size + 1):
            if counts_a_view[tid] != 0 or counts_b_view[tid] != 0:
                touched_n += 1
        if touched_n == 0:
            ids = np.zeros(0, dtype=np.uint32)
            vals_a = np.zeros(0, dtype=np.uint64)
            vals_b = np.zeros(0, dtype=np.uint64)
            return ids, vals_a, vals_b
        ids = np.empty(touched_n, dtype=np.uint32)
        vals_a = np.empty(touched_n, dtype=np.uint64)
        vals_b = np.empty(touched_n, dtype=np.uint64)
        touched_n = 0
        for tid in range(1, vocab_size + 1):
            if counts_a_view[tid] != 0 or counts_b_view[tid] != 0:
                ids[touched_n] = tid
                vals_a[touched_n] = counts_a_view[tid]
                vals_b[touched_n] = counts_b_view[tid]
                touched_n += 1
        return ids, vals_a, vals_b

    for block_idx in range(block_count):
        block_start = block_idx * block_size
        block_end = block_start + block_size
        if block_end > token_count:
            block_end = token_count

        while ia < na and ends_a[ia] <= block_start:
            ia += 1
        while ib < nb and ends_b[ib] <= block_start:
            ib += 1

        need_block = False
        if ia < na and starts_a[ia] < block_end:
            need_block = True
        elif ib < nb and starts_b[ib] < block_end:
            need_block = True
        if not need_block:
            continue

        start_off = offsets[block_idx]
        end_off = offsets[block_idx + 1]
        block_len = block_size
        if (block_idx + 1) * block_size > token_count:
            block_len = <unsigned int>(token_count - block_idx * block_size)
        _svb_decode_block(&blob[start_off], end_off - start_off, block_len, &buf_view[0])

        ta = ia
        while ta < na and starts_a[ta] < block_end:
            seg_start = starts_a[ta]
            if seg_start < block_start:
                seg_start = <unsigned int>block_start
            seg_end = ends_a[ta]
            if seg_end > block_end:
                seg_end = <unsigned int>block_end
            if seg_start < seg_end:
                seg_weight = weights_a[ta]
                rel_start = <unsigned int>(seg_start - block_start)
                rel_end = <unsigned int>(seg_end - block_start)
                for pos in range(rel_start, rel_end):
                    tid = buf_view[pos]
                    if tid == 0 or tid > vocab_size:
                        continue
                    if not only_zero_stop and stopset is not None and tid in stopset:
                        continue
                    if seen_view[tid] == 0:
                        seen_view[tid] = 1
                        touched_view[touched_n] = tid
                        touched_n += 1
                    counts_a_view[tid] += seg_weight
            if ends_a[ta] <= block_end:
                ta += 1
            else:
                break
        ia = ta

        tb = ib
        while tb < nb and starts_b[tb] < block_end:
            seg_start = starts_b[tb]
            if seg_start < block_start:
                seg_start = <unsigned int>block_start
            seg_end = ends_b[tb]
            if seg_end > block_end:
                seg_end = <unsigned int>block_end
            if seg_start < seg_end:
                seg_weight = weights_b[tb]
                rel_start = <unsigned int>(seg_start - block_start)
                rel_end = <unsigned int>(seg_end - block_start)
                for pos in range(rel_start, rel_end):
                    tid = buf_view[pos]
                    if tid == 0 or tid > vocab_size:
                        continue
                    if not only_zero_stop and stopset is not None and tid in stopset:
                        continue
                    if seen_view[tid] == 0:
                        seen_view[tid] = 1
                        touched_view[touched_n] = tid
                        touched_n += 1
                    counts_b_view[tid] += seg_weight
            if ends_b[tb] <= block_end:
                tb += 1
            else:
                break
        ib = tb

    if touched_n == 0:
        ids = np.zeros(0, dtype=np.uint32)
        vals_a = np.zeros(0, dtype=np.uint64)
        vals_b = np.zeros(0, dtype=np.uint64)
        return ids, vals_a, vals_b

    ids = touched[:touched_n].copy()
    if touched_n > 1:
        order = np.argsort(ids, kind="mergesort")
        ids = ids[order]
    vals_a = counts_a[ids].copy()
    vals_b = counts_b[ids].copy()
    return ids, vals_a, vals_b


def gather_u64_to_f64(
    np.ndarray[np.uint64_t, ndim=1] src,
    np.ndarray[np.uint32_t, ndim=1] ids,
):
    cdef Py_ssize_t n = ids.shape[0]
    cdef np.ndarray[np.float64_t, ndim=1] out = np.empty(n, dtype=np.float64)
    cdef np.float64_t[:] out_view = out
    cdef np.uint64_t[:] src_view = src
    cdef np.uint32_t[:] ids_view = ids
    cdef Py_ssize_t i

    if n >= 131072:
        with nogil:
            for i in prange(n, schedule="static"):
                out_view[i] = <double>src_view[ids_view[i]]
    else:
        for i in range(n):
            out_view[i] = <double>src_view[ids_view[i]]
    return out


def subtract_and_compact_dual_counts_u64(
    np.ndarray[np.uint32_t, ndim=1] union_ids,
    np.ndarray[np.uint64_t, ndim=1] counts_a,
    np.ndarray[np.uint64_t, ndim=1] counts_b,
    np.ndarray[np.uint32_t, ndim=1] anchor_ids,
    np.ndarray[np.uint64_t, ndim=1] anchor_counts_a,
    np.ndarray[np.uint64_t, ndim=1] anchor_counts_b,
):
    cdef Py_ssize_t n = union_ids.shape[0]
    cdef Py_ssize_t m = anchor_ids.shape[0]
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t out_n = 0
    cdef np.ndarray[np.uint32_t, ndim=1] out_ids = np.empty(n, dtype=np.uint32)
    cdef np.ndarray[np.uint64_t, ndim=1] out_a = np.empty(n, dtype=np.uint64)
    cdef np.ndarray[np.uint64_t, ndim=1] out_b = np.empty(n, dtype=np.uint64)
    cdef np.uint32_t[:] union_ids_view = union_ids
    cdef np.uint64_t[:] counts_a_view = counts_a
    cdef np.uint64_t[:] counts_b_view = counts_b
    cdef np.uint32_t[:] anchor_ids_view = anchor_ids
    cdef np.uint64_t[:] anchor_a_view = anchor_counts_a
    cdef np.uint64_t[:] anchor_b_view = anchor_counts_b
    cdef np.uint32_t[:] out_ids_view = out_ids
    cdef np.uint64_t[:] out_a_view = out_a
    cdef np.uint64_t[:] out_b_view = out_b
    cdef np.uint64_t a_val
    cdef np.uint64_t b_val
    cdef np.uint64_t sub_a
    cdef np.uint64_t sub_b
    cdef np.uint32_t cur_id

    if n == 0:
        return (
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.uint64),
            np.zeros(0, dtype=np.uint64),
        )
    if m == 0:
        return union_ids.copy(), counts_a.copy(), counts_b.copy()

    while i < n:
        cur_id = union_ids_view[i]
        while j < m and anchor_ids_view[j] < cur_id:
            j += 1
        a_val = counts_a_view[i]
        b_val = counts_b_view[i]
        if j < m and anchor_ids_view[j] == cur_id:
            sub_a = anchor_a_view[j]
            sub_b = anchor_b_view[j]
            if sub_a >= a_val:
                a_val = 0
            else:
                a_val -= sub_a
            if sub_b >= b_val:
                b_val = 0
            else:
                b_val -= sub_b
        if a_val != 0 or b_val != 0:
            out_ids_view[out_n] = cur_id
            out_a_view[out_n] = a_val
            out_b_view[out_n] = b_val
            out_n += 1
        i += 1

    return (
        out_ids[:out_n].copy(),
        out_a[:out_n].copy(),
        out_b[:out_n].copy(),
    )


cdef tuple _dict_to_sorted_arrays(dict counts):
    cdef Py_ssize_t n = len(counts)
    cdef np.ndarray[np.uint32_t, ndim=1] ids = np.empty(n, dtype=np.uint32)
    cdef np.ndarray[np.float64_t, ndim=1] values = np.empty(n, dtype=np.float64)
    cdef np.uint32_t[:] ids_view = ids
    cdef np.float64_t[:] values_view = values
    cdef Py_ssize_t pos = 0
    cdef Py_ssize_t i = 0
    cdef PyObject* key_obj = NULL
    cdef PyObject* value_obj = NULL
    cdef np.ndarray order

    while PyDict_Next(counts, &pos, &key_obj, &value_obj):
        ids_view[i] = <np.uint32_t>(<object>key_obj)
        values_view[i] = float(<object>value_obj)
        i += 1

    if n <= 1:
        return ids, values

    order = np.argsort(ids, kind="mergesort")
    return ids[order], values[order]


def build_dual_basis_arrays(
    dict counts_a,
    dict counts_b,
    dict freqs_a,
    dict freqs_b,
):
    cdef np.ndarray[np.uint32_t, ndim=1] ids_a
    cdef np.ndarray[np.uint32_t, ndim=1] ids_b
    cdef np.ndarray[np.float64_t, ndim=1] vals_a
    cdef np.ndarray[np.float64_t, ndim=1] vals_b
    cdef np.ndarray[np.uint32_t, ndim=1] out_ids
    cdef np.ndarray[np.float64_t, ndim=1] out_obs_a
    cdef np.ndarray[np.float64_t, ndim=1] out_obs_b
    cdef np.ndarray[np.float64_t, ndim=1] out_freq_a
    cdef np.ndarray[np.float64_t, ndim=1] out_freq_b
    cdef np.uint32_t[:] ids_a_view
    cdef np.uint32_t[:] ids_b_view
    cdef np.float64_t[:] vals_a_view
    cdef np.float64_t[:] vals_b_view
    cdef np.uint32_t[:] out_ids_view
    cdef np.float64_t[:] out_obs_a_view
    cdef np.float64_t[:] out_obs_b_view
    cdef np.float64_t[:] out_freq_a_view
    cdef np.float64_t[:] out_freq_b_view
    cdef Py_ssize_t na
    cdef Py_ssize_t nb
    cdef Py_ssize_t ia = 0
    cdef Py_ssize_t ib = 0
    cdef Py_ssize_t out_idx = 0
    cdef np.uint32_t tid

    ids_a, vals_a = _dict_to_sorted_arrays(counts_a)
    ids_b, vals_b = _dict_to_sorted_arrays(counts_b)
    na = ids_a.shape[0]
    nb = ids_b.shape[0]
    if na == 0 and nb == 0:
        empty_u32 = np.zeros(0, dtype=np.uint32)
        empty_f64 = np.zeros(0, dtype=np.float64)
        return empty_u32, empty_f64, empty_f64, empty_f64, empty_f64

    out_ids = np.empty(na + nb, dtype=np.uint32)
    out_obs_a = np.zeros(na + nb, dtype=np.float64)
    out_obs_b = np.zeros(na + nb, dtype=np.float64)
    out_freq_a = np.zeros(na + nb, dtype=np.float64)
    out_freq_b = np.zeros(na + nb, dtype=np.float64)
    ids_a_view = ids_a
    ids_b_view = ids_b
    vals_a_view = vals_a
    vals_b_view = vals_b
    out_ids_view = out_ids
    out_obs_a_view = out_obs_a
    out_obs_b_view = out_obs_b
    out_freq_a_view = out_freq_a
    out_freq_b_view = out_freq_b

    while ia < na and ib < nb:
        if ids_a_view[ia] == ids_b_view[ib]:
            tid = ids_a_view[ia]
            out_ids_view[out_idx] = tid
            out_obs_a_view[out_idx] = vals_a_view[ia]
            out_obs_b_view[out_idx] = vals_b_view[ib]
            out_freq_a_view[out_idx] = float(freqs_a.get(int(tid), 0.0))
            out_freq_b_view[out_idx] = float(freqs_b.get(int(tid), 0.0))
            ia += 1
            ib += 1
        elif ids_a_view[ia] < ids_b_view[ib]:
            tid = ids_a_view[ia]
            out_ids_view[out_idx] = tid
            out_obs_a_view[out_idx] = vals_a_view[ia]
            out_freq_a_view[out_idx] = float(freqs_a.get(int(tid), 0.0))
            out_freq_b_view[out_idx] = float(freqs_b.get(int(tid), 0.0))
            ia += 1
        else:
            tid = ids_b_view[ib]
            out_ids_view[out_idx] = tid
            out_obs_b_view[out_idx] = vals_b_view[ib]
            out_freq_a_view[out_idx] = float(freqs_a.get(int(tid), 0.0))
            out_freq_b_view[out_idx] = float(freqs_b.get(int(tid), 0.0))
            ib += 1
        out_idx += 1

    while ia < na:
        tid = ids_a_view[ia]
        out_ids_view[out_idx] = tid
        out_obs_a_view[out_idx] = vals_a_view[ia]
        out_freq_a_view[out_idx] = float(freqs_a.get(int(tid), 0.0))
        out_freq_b_view[out_idx] = float(freqs_b.get(int(tid), 0.0))
        ia += 1
        out_idx += 1

    while ib < nb:
        tid = ids_b_view[ib]
        out_ids_view[out_idx] = tid
        out_obs_b_view[out_idx] = vals_b_view[ib]
        out_freq_a_view[out_idx] = float(freqs_a.get(int(tid), 0.0))
        out_freq_b_view[out_idx] = float(freqs_b.get(int(tid), 0.0))
        ib += 1
        out_idx += 1

    return (
        out_ids[:out_idx].copy(),
        out_obs_a[:out_idx].copy(),
        out_obs_b[:out_idx].copy(),
        out_freq_a[:out_idx].copy(),
        out_freq_b[:out_idx].copy(),
    )


def count_segments_svb_pos(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.uint32_t, ndim=1] pos_ids,
    np.ndarray[np.uint32_t, ndim=1] seg_starts,
    np.ndarray[np.uint32_t, ndim=1] seg_ends,
    np.ndarray[np.uint32_t, ndim=1] seg_weights,
    np.ndarray[np.uint8_t, ndim=1] pos_allow,
    object stoplist=None,
):
    cdef dict counts = {}
    cdef object stopset = stoplist if stoplist else None
    cdef const unsigned char[:] blob = data
    cdef const unsigned int[:] pos_view = pos_ids
    cdef const unsigned int[:] starts_view = seg_starts
    cdef const unsigned int[:] ends_view = seg_ends
    cdef const unsigned int[:] weights_view = seg_weights
    cdef const unsigned char[:] allow = pos_allow
    cdef unsigned int allow_len = allow.shape[0]
    cdef Py_ssize_t i, n_seg
    cdef unsigned int start
    cdef unsigned int end
    cdef unsigned int weight
    cdef unsigned int pos
    cdef unsigned int tid
    cdef unsigned int pos_id
    cdef unsigned long long block_idx
    cdef unsigned long long block_start
    cdef unsigned int block_len
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf

    n_seg = starts_view.shape[0]
    for i in range(n_seg):
        start = starts_view[i]
        end = ends_view[i]
        if start >= end:
            continue
        if end > token_count:
            end = <unsigned int>token_count
        weight = weights_view[i]
        pos = start
        while pos < end:
            block_idx = pos // block_size
            block_start = block_idx * block_size
            start_off = offsets[block_idx]
            end_off = offsets[block_idx + 1]
            block_len = block_size
            if (block_idx + 1) * block_size > token_count:
                block_len = <unsigned int>(token_count - block_idx * block_size)
            _svb_decode_block(&blob[start_off], end_off - start_off, block_len, &buf_view[0])
            while pos < end and pos < block_start + block_len:
                pos_id = pos_view[pos]
                if pos_id < allow_len and allow[pos_id] != 0:
                    tid = buf_view[pos - block_start]
                    if tid != 0:
                        if stopset is None or tid not in stopset:
                            counts[tid] = counts.get(tid, 0) + weight
                pos += 1
    return counts


def count_ngrams_svb(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.uint32_t, ndim=1] doc_starts,
    np.ndarray[np.uint32_t, ndim=1] doc_ends,
    unsigned int min_n,
    unsigned int max_n,
):
    cdef dict counts = {}
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t i, n_docs
    cdef unsigned int start
    cdef unsigned int end
    cdef unsigned int doc_len
    cdef unsigned long long pos
    cdef unsigned long long block_idx
    cdef unsigned long long block_start
    cdef unsigned int block_len
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned int out_pos
    cdef unsigned int n
    cdef unsigned int j
    cdef unsigned int k
    cdef unsigned int tid
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf
    cdef np.ndarray[np.uint32_t, ndim=1] doc_buf
    cdef unsigned int[:] doc_view
    cdef object key
    cdef bint valid

    if min_n < 1:
        min_n = 1
    if max_n < min_n:
        max_n = min_n

    n_docs = doc_starts.shape[0]
    for i in range(n_docs):
        start = doc_starts[i]
        end = doc_ends[i]
        if start >= end:
            continue
        if end > token_count:
            end = <unsigned int>token_count
        doc_len = end - start
        if doc_len == 0:
            continue
        doc_buf = np.empty(doc_len, dtype=np.uint32)
        doc_view = doc_buf
        pos = start
        out_pos = 0
        while pos < end:
            block_idx = pos // block_size
            block_start = block_idx * block_size
            start_off = offsets[block_idx]
            end_off = offsets[block_idx + 1]
            block_len = block_size
            if (block_idx + 1) * block_size > token_count:
                block_len = <unsigned int>(token_count - block_idx * block_size)
            _svb_decode_block(&blob[start_off], end_off - start_off, block_len, &buf_view[0])
            while pos < end and pos < block_start + block_len:
                doc_view[out_pos] = buf_view[pos - block_start]
                out_pos += 1
                pos += 1

        for n in range(min_n, max_n + 1):
            if doc_len < n:
                continue
            for j in range(0, doc_len - n + 1):
                valid = True
                for k in range(n):
                    tid = doc_view[j + k]
                    if tid == 0:
                        valid = False
                        break
                if not valid:
                    continue
                key = tuple(doc_view[j:j + n])
                counts[key] = counts.get(key, 0) + 1

    return counts


def count_block_top_svb(
    np.ndarray[np.uint64_t, ndim=1] block_offsets,
    np.ndarray[np.uint32_t, ndim=1] block_ids,
    np.ndarray[np.uint32_t, ndim=1] block_cnts,
    np.ndarray[np.uint32_t, ndim=1] block_totals,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.uint64_t, ndim=1] svb_offsets,
    object svb_data,
    unsigned int svb_block_size,
    np.ndarray[np.uint32_t, ndim=1] seg_starts,
    np.ndarray[np.uint32_t, ndim=1] seg_ends,
    np.ndarray[np.uint32_t, ndim=1] seg_weights,
    object stoplist=None,
    unsigned int top_n=0,
):
    cdef dict counts = {}
    cdef object stopset = stoplist if stoplist else None
    cdef Py_ssize_t n_seg = seg_starts.shape[0]
    cdef Py_ssize_t i, j
    cdef unsigned long long s
    cdef unsigned long long e
    cdef unsigned long long w
    cdef unsigned long long b_first
    cdef unsigned long long b_last
    cdef unsigned long long left_end
    cdef unsigned long long right_start
    cdef unsigned long long off_a
    cdef unsigned long long off_b
    cdef unsigned long long block_len
    cdef unsigned long long other_mass = 0
    cdef unsigned long long sum_top
    cdef unsigned int tid
    cdef unsigned int cnt
    cdef Py_ssize_t totals_len = block_totals.shape[0]
    cdef list partial_starts = []
    cdef list partial_ends = []
    cdef list partial_weights = []

    for i in range(n_seg):
        s = seg_starts[i]
        e = seg_ends[i]
        if e <= s:
            continue
        w = seg_weights[i]
        b_first = (s + block_size - 1) // block_size
        b_last = e // block_size
        if b_first >= b_last:
            partial_starts.append(int(s))
            partial_ends.append(int(e))
            partial_weights.append(int(w))
            continue
        left_end = b_first * block_size
        if s < left_end:
            partial_starts.append(int(s))
            partial_ends.append(int(left_end))
            partial_weights.append(int(w))
        right_start = b_last * block_size
        if right_start < e:
            partial_starts.append(int(right_start))
            partial_ends.append(int(e))
            partial_weights.append(int(w))
        for b in range(b_first, b_last):
            off_a = block_offsets[b]
            off_b = block_offsets[b + 1]
            if b < totals_len:
                block_len = block_totals[b]
            else:
                block_len = min((b + 1) * block_size, token_count) - b * block_size
            if off_b <= off_a:
                other_mass += block_len * w
                continue
            sum_top = 0
            for j in range(off_a, off_b):
                sum_top += block_cnts[j]
            other_mass += (block_len - sum_top) * w
            for j in range(off_a, off_b):
                tid = block_ids[j]
                if tid == 0:
                    continue
                if stopset is not None and tid in stopset:
                    continue
                cnt = block_cnts[j]
                counts[tid] = counts.get(tid, 0) + cnt * w

    if partial_starts:
        p_starts = np.asarray(partial_starts, dtype=np.uint32)
        p_ends = np.asarray(partial_ends, dtype=np.uint32)
        p_weights = np.asarray(partial_weights, dtype=np.uint32)
        partial = count_segments_svb(
            svb_offsets,
            svb_data,
            svb_block_size,
            token_count,
            p_starts,
            p_ends,
            p_weights,
            stopset,
        )
        for tid, val in partial.items():
            counts[tid] = counts.get(tid, 0) + int(val)

    if other_mass > 0 and counts:
        values = list(counts.values())
        if top_n and len(values) > top_n:
            import heapq
            min_top = heapq.nlargest(top_n, values)[-1]
        else:
            min_top = min(values)
        if min_top <= other_mass:
            raise RuntimeError("Block-Top Kandidaten unsicher. Bitte Index neu bauen oder top_n anpassen.")

    return counts


def keyness_scores(
    np.ndarray[np.uint64_t, ndim=1] counts_t,
    np.ndarray[np.uint64_t, ndim=1] counts_r,
    unsigned long long total_t,
    unsigned long long total_r,
):
    cdef Py_ssize_t n = counts_t.shape[0]
    if counts_r.shape[0] != n:
        raise ValueError("counts_t und counts_r muessen gleich lang sein")
    cdef np.ndarray[np.float64_t, ndim=1] mi2 = np.empty(n, dtype=np.float64)
    cdef np.ndarray[np.float64_t, ndim=1] ll = np.empty(n, dtype=np.float64)
    cdef Py_ssize_t i
    cdef double a
    cdef double b
    cdef double c
    cdef double d
    cdef double total = <double>(total_t + total_r)
    cdef double exp
    cdef double e1
    cdef double e2
    cdef double e3
    cdef double e4
    cdef double term

    for i in range(n):
        a = <double>counts_t[i]
        b = <double>counts_r[i]
        if total != 0.0:
            exp = <double>total_t * (a + b) / total
        else:
            exp = 0.0
        if exp != 0.0:
            mi2[i] = ((a - exp) * (a - exp)) / exp
        else:
            mi2[i] = 0.0
        c = <double>total_t - a
        d = <double>total_r - b
        if total != 0.0:
            e1 = <double>total_t * (a + b) / total
            e2 = <double>total_r * (a + b) / total
            e3 = <double>total_t * (c + d) / total
            e4 = <double>total_r * (c + d) / total
        else:
            e1 = 0.0
            e2 = 0.0
            e3 = 0.0
            e4 = 0.0
        term = 0.0
        if a != 0.0 and e1 != 0.0:
            term += a * log(a / e1)
        if b != 0.0 and e2 != 0.0:
            term += b * log(b / e2)
        if c != 0.0 and e3 != 0.0:
            term += c * log(c / e3)
        if d != 0.0 and e4 != 0.0:
            term += d * log(d / e4)
        ll[i] = 2.0 * term
    return mi2, ll


def match_arrays_from_positions(np.ndarray[np.uint32_t, ndim=1] positions):
    cdef Py_ssize_t n = positions.shape[0]
    cdef np.ndarray[np.uint32_t, ndim=1] anchors = np.empty(n, dtype=np.uint32)
    cdef np.ndarray[np.uint32_t, ndim=1] starts = np.empty(n, dtype=np.uint32)
    cdef np.ndarray[np.uint32_t, ndim=1] ends = np.empty(n, dtype=np.uint32)
    cdef np.uint32_t[:] pos_view = positions
    cdef np.uint32_t[:] anchor_view = anchors
    cdef np.uint32_t[:] start_view = starts
    cdef np.uint32_t[:] end_view = ends
    cdef Py_ssize_t i
    for i in range(n):
        anchor_view[i] = pos_view[i]
        start_view[i] = pos_view[i]
        end_view[i] = pos_view[i] + 1
    return anchors, starts, ends


cdef inline Py_ssize_t _doc_index_from_bounds_u32(
    const np.uint32_t[:] bounds,
    Py_ssize_t n_bounds,
    np.uint32_t pos,
) noexcept nogil:
    cdef Py_ssize_t lo = 0
    cdef Py_ssize_t hi = n_bounds
    cdef Py_ssize_t mid
    if n_bounds <= 0:
        return -1
    while lo < hi:
        mid = lo + ((hi - lo) >> 1)
        if bounds[mid] <= pos:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def filter_sorted_positions_by_docset_mask_u32(
    const np.uint32_t[:] positions,
    const np.uint32_t[:] doc_bounds,
    const np.uint8_t[:] docset_mask,
):
    # Inputs are read-only views: ``positions``/``doc_bounds`` may be backed by a
    # read-only mmap (zero-copy index arrays) and the metadata ``docset_mask`` can
    # be a read-only buffer too. Declaring them ``const`` memoryviews accepts those
    # buffers zero-copy instead of demanding a writable buffer (which raised
    # "buffer source array is read-only" and 500'd every metadata-filtered query).
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t n_docs = doc_bounds.shape[0]
    cdef const np.uint32_t[:] pos_view = positions
    cdef const np.uint32_t[:] bounds_view = doc_bounds
    cdef const np.uint8_t[:] mask_view = docset_mask
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t i
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t doc_idx = 0
    cdef Py_ssize_t cur_doc_idx
    cdef np.uint32_t pos
    cdef bint monotonic = True

    if n == 0:
        return np.zeros(0, dtype=np.uint32)
    if n_docs == 0:
        raise ValueError("doc_bounds darf nicht leer sein")
    if docset_mask.shape[0] < n_docs:
        raise ValueError("docset_mask ist kuerzer als doc_bounds")

    out = np.empty(n, dtype=np.uint32)
    out_view = out
    for i in range(1, n):
        if pos_view[i] < pos_view[i - 1]:
            monotonic = False
            break
    for i in range(n):
        pos = pos_view[i]
        if monotonic:
            while doc_idx + 1 < n_docs and pos >= bounds_view[doc_idx + 1]:
                doc_idx += 1
            cur_doc_idx = doc_idx
        else:
            cur_doc_idx = _doc_index_from_bounds_u32(bounds_view, n_docs, pos)
            if cur_doc_idx < 0:
                continue
        if mask_view[cur_doc_idx] != 0:
            out_view[k] = pos
            k += 1
    if k == n:
        # Everything matched. Returning ``None`` lets the Python wrapper hand back
        # the caller's original array object zero-copy (the kernel only holds a
        # read-only view, not the ndarray object itself).
        return None
    if k == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:k]


def filter_sorted_positions_and_values_i64_by_docset_mask_u32(
    const np.uint32_t[:] positions,
    const np.int64_t[:] values,
    const np.uint32_t[:] doc_bounds,
    const np.uint8_t[:] docset_mask,
):
    # Read-only views: any of these may be backed by a read-only mmap. ``const``
    # memoryviews accept those buffers zero-copy (see the sibling
    # ``filter_sorted_positions_by_docset_mask_u32`` for the rationale).
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t n_docs = doc_bounds.shape[0]
    cdef const np.uint32_t[:] pos_view = positions
    cdef const np.int64_t[:] val_view = values
    cdef const np.uint32_t[:] bounds_view = doc_bounds
    cdef const np.uint8_t[:] mask_view = docset_mask
    cdef np.ndarray[np.uint32_t, ndim=1] out_pos
    cdef np.ndarray[np.int64_t, ndim=1] out_vals
    cdef np.uint32_t[:] out_pos_view
    cdef np.int64_t[:] out_val_view
    cdef Py_ssize_t i
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t doc_idx = 0
    cdef Py_ssize_t cur_doc_idx
    cdef np.uint32_t pos
    cdef bint monotonic = True

    if values.shape[0] != n:
        raise ValueError("values muessen gleich lang wie positions sein")
    if n == 0:
        return (
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.int64),
        )
    if n_docs == 0:
        raise ValueError("doc_bounds darf nicht leer sein")
    if docset_mask.shape[0] < n_docs:
        raise ValueError("docset_mask ist kuerzer als doc_bounds")

    out_pos = np.empty(n, dtype=np.uint32)
    out_vals = np.empty(n, dtype=np.int64)
    out_pos_view = out_pos
    out_val_view = out_vals
    for i in range(1, n):
        if pos_view[i] < pos_view[i - 1]:
            monotonic = False
            break
    for i in range(n):
        pos = pos_view[i]
        if monotonic:
            while doc_idx + 1 < n_docs and pos >= bounds_view[doc_idx + 1]:
                doc_idx += 1
            cur_doc_idx = doc_idx
        else:
            cur_doc_idx = _doc_index_from_bounds_u32(bounds_view, n_docs, pos)
            if cur_doc_idx < 0:
                continue
        if mask_view[cur_doc_idx] != 0:
            out_pos_view[k] = pos
            out_val_view[k] = val_view[i]
            k += 1
    if k == n:
        # Everything matched: ``None`` signals the wrapper to return the caller's
        # original ``positions``/``values`` objects zero-copy.
        return None
    if k == 0:
        return (
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.int64),
        )
    return out_pos[:k], out_vals[:k]


def unique_doc_ids_from_sorted_positions_u32(
    const np.uint32_t[:] positions,
    const np.uint32_t[:] doc_bounds,
):
    # Read-only views so mmap-backed index arrays pass zero-copy.
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t n_docs = doc_bounds.shape[0]
    cdef const np.uint32_t[:] pos_view = positions
    cdef const np.uint32_t[:] bounds_view = doc_bounds
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef np.ndarray[np.uint8_t, ndim=1] seen
    cdef np.uint8_t[:] seen_view
    cdef Py_ssize_t i
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t doc_idx = 0
    cdef Py_ssize_t cur_doc_idx
    cdef Py_ssize_t last_doc = -1
    cdef np.uint32_t pos
    cdef bint monotonic = True

    if n == 0:
        return np.zeros(0, dtype=np.uint32)
    if n_docs == 0:
        raise ValueError("doc_bounds darf nicht leer sein")

    out = np.empty(n if n < n_docs else n_docs, dtype=np.uint32)
    out_view = out
    for i in range(1, n):
        if pos_view[i] < pos_view[i - 1]:
            monotonic = False
            break
    if monotonic:
        for i in range(n):
            pos = pos_view[i]
            while doc_idx + 1 < n_docs and pos >= bounds_view[doc_idx + 1]:
                doc_idx += 1
            if doc_idx != last_doc:
                out_view[k] = <np.uint32_t>doc_idx
                k += 1
                last_doc = doc_idx
    else:
        seen = np.zeros(n_docs, dtype=np.uint8)
        seen_view = seen
        for i in range(n):
            cur_doc_idx = _doc_index_from_bounds_u32(bounds_view, n_docs, pos_view[i])
            if cur_doc_idx >= 0 and seen_view[cur_doc_idx] == 0:
                seen_view[cur_doc_idx] = 1
                out_view[k] = <np.uint32_t>cur_doc_idx
                k += 1
    return out[:k]


def map_positions_to_doc_ids_i64(
    const np.uint32_t[:] positions,
    const np.uint32_t[:] doc_bounds,
):
    # Read-only views so mmap-backed index arrays pass zero-copy.
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t n_docs = doc_bounds.shape[0]
    cdef const np.uint32_t[:] pos_view = positions
    cdef const np.uint32_t[:] bounds_view = doc_bounds
    cdef np.ndarray[np.int64_t, ndim=1] out
    cdef np.int64_t[:] out_view
    cdef Py_ssize_t i
    cdef Py_ssize_t doc_idx = 0
    cdef Py_ssize_t cur_doc_idx
    cdef bint monotonic = True

    if n == 0:
        return np.zeros(0, dtype=np.int64)
    if n_docs == 0:
        raise ValueError("doc_bounds darf nicht leer sein")

    out = np.empty(n, dtype=np.int64)
    out_view = out
    for i in range(1, n):
        if pos_view[i] < pos_view[i - 1]:
            monotonic = False
            break

    if monotonic:
        for i in range(n):
            while doc_idx + 1 < n_docs and pos_view[i] >= bounds_view[doc_idx + 1]:
                doc_idx += 1
            out_view[i] = doc_idx
    else:
        for i in range(n):
            cur_doc_idx = _doc_index_from_bounds_u32(bounds_view, n_docs, pos_view[i])
            out_view[i] = cur_doc_idx
    return out


def map_positions_to_doc_ids_i32(
    const np.uint32_t[:] positions,
    const np.uint32_t[:] doc_bounds,
):
    # Read-only views so mmap-backed index arrays pass zero-copy.
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t n_docs = doc_bounds.shape[0]
    cdef const np.uint32_t[:] pos_view = positions
    cdef const np.uint32_t[:] bounds_view = doc_bounds
    cdef np.ndarray[np.int32_t, ndim=1] out
    cdef np.int32_t[:] out_view
    cdef Py_ssize_t i
    cdef Py_ssize_t doc_idx = 0
    cdef Py_ssize_t cur_doc_idx
    cdef bint monotonic = True

    if n == 0:
        return np.zeros(0, dtype=np.int32)
    if n_docs == 0:
        raise ValueError("doc_bounds darf nicht leer sein")

    out = np.empty(n, dtype=np.int32)
    out_view = out
    for i in range(1, n):
        if pos_view[i] < pos_view[i - 1]:
            monotonic = False
            break

    if monotonic:
        for i in range(n):
            while doc_idx + 1 < n_docs and pos_view[i] >= bounds_view[doc_idx + 1]:
                doc_idx += 1
            out_view[i] = <np.int32_t> doc_idx
    else:
        for i in range(n):
            cur_doc_idx = _doc_index_from_bounds_u32(bounds_view, n_docs, pos_view[i])
            out_view[i] = <np.int32_t> cur_doc_idx
    return out


def position_to_doc_id_i64(
    np.uint32_t position,
    const np.uint32_t[:] doc_bounds,
):
    # Read-only view so mmap-backed doc_bounds passes zero-copy.
    cdef Py_ssize_t n_docs = doc_bounds.shape[0]
    cdef const np.uint32_t[:] bounds_view = doc_bounds
    if n_docs == 0:
        raise ValueError("doc_bounds darf nicht leer sein")
    return <long long>_doc_index_from_bounds_u32(bounds_view, n_docs, position)


def intersect_sorted_limit(
    np.ndarray[np.uint32_t, ndim=1] a,
    np.ndarray[np.uint32_t, ndim=1] b,
    unsigned int limit,
):
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    if limit == 0 or na == 0 or nb == 0:
        return np.zeros(0, dtype=np.uint32)
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t max_out = na if na < nb else nb
    if limit < max_out:
        max_out = limit
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(max_out, dtype=np.uint32)
    cdef np.uint32_t[:] av = a
    cdef np.uint32_t[:] bv = b
    cdef np.uint32_t[:] ov = out
    while i < na and j < nb:
        if av[i] == bv[j]:
            ov[k] = av[i]
            k += 1
            if k >= max_out:
                break
            i += 1
            j += 1
        elif av[i] < bv[j]:
            i += 1
        else:
            j += 1
    if k == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:k]


def union_sorted_limit(
    np.ndarray[np.uint32_t, ndim=1] a,
    np.ndarray[np.uint32_t, ndim=1] b,
    unsigned int limit,
):
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    if limit == 0:
        return np.zeros(0, dtype=np.uint32)
    if na == 0:
        return b[:limit].astype(np.uint32, copy=False)
    if nb == 0:
        return a[:limit].astype(np.uint32, copy=False)
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t max_out = na + nb
    if limit < max_out:
        max_out = limit
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(max_out, dtype=np.uint32)
    cdef np.uint32_t[:] av = a
    cdef np.uint32_t[:] bv = b
    cdef np.uint32_t[:] ov = out
    cdef bint has_last = False
    cdef np.uint32_t last = 0
    cdef np.uint32_t v
    while (i < na or j < nb) and k < max_out:
        if j >= nb or (i < na and av[i] <= bv[j]):
            v = av[i]
            i += 1
        else:
            v = bv[j]
            j += 1
        if not has_last or v != last:
            ov[k] = v
            k += 1
            last = v
            has_last = True
    if k == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:k]


def levenshtein_tokens_fast(list a, list b):
    cdef Py_ssize_t n = len(a)
    cdef Py_ssize_t m = len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    cdef Py_ssize_t *prev = <Py_ssize_t *> PyMem_Malloc((m + 1) * sizeof(Py_ssize_t))
    cdef Py_ssize_t *curr = <Py_ssize_t *> PyMem_Malloc((m + 1) * sizeof(Py_ssize_t))
    if prev == NULL or curr == NULL:
        if prev != NULL:
            PyMem_Free(prev)
        if curr != NULL:
            PyMem_Free(curr)
        raise MemoryError("Failed to allocate Levenshtein buffers")
    cdef Py_ssize_t i, j
    cdef Py_ssize_t del_cost, ins_cost, sub_cost, best
    cdef int cost
    try:
        for j in range(m + 1):
            prev[j] = j
        for i in range(1, n + 1):
            curr[0] = i
            for j in range(1, m + 1):
                cost = 0 if PyObject_RichCompareBool(a[i - 1], b[j - 1], Py_EQ) else 1
                del_cost = prev[j] + 1
                ins_cost = curr[j - 1] + 1
                sub_cost = prev[j - 1] + cost
                best = del_cost
                if ins_cost < best:
                    best = ins_cost
                if sub_cost < best:
                    best = sub_cost
                curr[j] = best
            prev, curr = curr, prev
        return int(prev[m])
    finally:
        PyMem_Free(prev)
        PyMem_Free(curr)


def co_kwic_offset_map(
    np.ndarray[np.int64_t, ndim=1] term_positions,
    list coll_positions_list,
    list left_indices_list,
    list right_indices_list,
):
    cdef Py_ssize_t n_terms = term_positions.shape[0]
    cdef list out_lists = [None] * n_terms
    cdef dict out = {}
    cdef Py_ssize_t i, j, c
    cdef long long term
    cdef list lst
    for i in range(n_terms):
        term = term_positions[i]
        lst = []
        out_lists[i] = lst
        out[int(term)] = lst

    cdef Py_ssize_t n_coll = len(coll_positions_list)
    cdef np.ndarray[np.int64_t, ndim=1] left_idx
    cdef np.ndarray[np.int64_t, ndim=1] right_idx
    cdef long long[:] left_view
    cdef long long[:] right_view
    cdef np.ndarray[np.uint32_t, ndim=1] coll_pos_u32
    cdef np.ndarray[np.int64_t, ndim=1] coll_pos_i64
    cdef unsigned int[:] coll_u32_view
    cdef long long[:] coll_i64_view
    cdef bint use_u32
    cdef long long[:] term_view = term_positions
    cdef Py_ssize_t start_i, end_i
    for c in range(n_coll):
        left_idx = np.asarray(left_indices_list[c], dtype=np.int64)
        right_idx = np.asarray(right_indices_list[c], dtype=np.int64)
        if left_idx.shape[0] != n_terms or right_idx.shape[0] != n_terms:
            raise ValueError("left/right indices length mismatch")
        coll_pos_obj = coll_positions_list[c]
        use_u32 = False
        if isinstance(coll_pos_obj, np.ndarray) and coll_pos_obj.dtype == np.uint32:
            coll_pos_u32 = coll_pos_obj
            coll_u32_view = coll_pos_u32
            use_u32 = True
        else:
            coll_pos_i64 = np.asarray(coll_pos_obj, dtype=np.int64)
            coll_i64_view = coll_pos_i64
        left_view = left_idx
        right_view = right_idx
        for i in range(n_terms):
            start_i = <Py_ssize_t>left_view[i]
            end_i = <Py_ssize_t>right_view[i]
            if end_i <= start_i:
                continue
            term = term_view[i]
            lst = out_lists[i]
            for j in range(start_i, end_i):
                if use_u32:
                    lst.append(<long long>coll_u32_view[j] - term)
                else:
                    lst.append(coll_i64_view[j] - term)
    return out


cdef Py_ssize_t _count_constant_span_segments(
    const np.int64_t[:] left_starts,
    const np.int64_t[:] left_ends,
    const np.int64_t[:] right_starts,
    const np.int64_t[:] right_ends,
) noexcept nogil:
    cdef Py_ssize_t i_ls = 0
    cdef Py_ssize_t i_le = 0
    cdef Py_ssize_t i_rs = 0
    cdef Py_ssize_t i_re = 0
    cdef Py_ssize_t n_ls = left_starts.shape[0]
    cdef Py_ssize_t n_le = left_ends.shape[0]
    cdef Py_ssize_t n_rs = right_starts.shape[0]
    cdef Py_ssize_t n_re = right_ends.shape[0]
    cdef long long prev_pos = 0
    cdef long long next_pos
    cdef long long coverage = 0
    cdef bint started = False
    cdef Py_ssize_t seg_count = 0

    while i_ls < n_ls or i_le < n_le or i_rs < n_rs or i_re < n_re:
        next_pos = LLONG_MAX
        if i_ls < n_ls and left_starts[i_ls] < next_pos:
            next_pos = left_starts[i_ls]
        if i_rs < n_rs and right_starts[i_rs] < next_pos:
            next_pos = right_starts[i_rs]
        if i_le < n_le and left_ends[i_le] < next_pos:
            next_pos = left_ends[i_le]
        if i_re < n_re and right_ends[i_re] < next_pos:
            next_pos = right_ends[i_re]
        if started and next_pos > prev_pos and coverage > 0:
            seg_count += 1
        while i_ls < n_ls and left_starts[i_ls] == next_pos:
            coverage += 1
            i_ls += 1
        while i_rs < n_rs and right_starts[i_rs] == next_pos:
            coverage += 1
            i_rs += 1
        while i_le < n_le and left_ends[i_le] == next_pos:
            coverage -= 1
            i_le += 1
        while i_re < n_re and right_ends[i_re] == next_pos:
            coverage -= 1
            i_re += 1
        prev_pos = next_pos
        started = True
    return seg_count


cdef void _fill_constant_span_segments(
    const np.int64_t[:] left_starts,
    const np.int64_t[:] left_ends,
    const np.int64_t[:] right_starts,
    const np.int64_t[:] right_ends,
    np.uint32_t[:] seg_starts,
    np.uint32_t[:] seg_ends,
    np.uint32_t[:] seg_weights,
    bint pair_semantics,
) noexcept nogil:
    cdef Py_ssize_t i_ls = 0
    cdef Py_ssize_t i_le = 0
    cdef Py_ssize_t i_rs = 0
    cdef Py_ssize_t i_re = 0
    cdef Py_ssize_t n_ls = left_starts.shape[0]
    cdef Py_ssize_t n_le = left_ends.shape[0]
    cdef Py_ssize_t n_rs = right_starts.shape[0]
    cdef Py_ssize_t n_re = right_ends.shape[0]
    cdef Py_ssize_t out_idx = 0
    cdef long long prev_pos = 0
    cdef long long next_pos
    cdef long long coverage = 0
    cdef bint started = False

    while i_ls < n_ls or i_le < n_le or i_rs < n_rs or i_re < n_re:
        next_pos = LLONG_MAX
        if i_ls < n_ls and left_starts[i_ls] < next_pos:
            next_pos = left_starts[i_ls]
        if i_rs < n_rs and right_starts[i_rs] < next_pos:
            next_pos = right_starts[i_rs]
        if i_le < n_le and left_ends[i_le] < next_pos:
            next_pos = left_ends[i_le]
        if i_re < n_re and right_ends[i_re] < next_pos:
            next_pos = right_ends[i_re]
        if started and next_pos > prev_pos and coverage > 0:
            seg_starts[out_idx] = <np.uint32_t>prev_pos
            seg_ends[out_idx] = <np.uint32_t>next_pos
            if pair_semantics:
                seg_weights[out_idx] = <np.uint32_t>coverage
            else:
                seg_weights[out_idx] = 1
            out_idx += 1
        while i_ls < n_ls and left_starts[i_ls] == next_pos:
            coverage += 1
            i_ls += 1
        while i_rs < n_rs and right_starts[i_rs] == next_pos:
            coverage += 1
            i_rs += 1
        while i_le < n_le and left_ends[i_le] == next_pos:
            coverage -= 1
            i_le += 1
        while i_re < n_re and right_ends[i_re] == next_pos:
            coverage -= 1
            i_re += 1
        prev_pos = next_pos
        started = True


cdef void _merge_sorted_i64(
    const np.int64_t[:] left,
    const np.int64_t[:] right,
    np.int64_t[:] out,
) noexcept nogil:
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t o = 0
    cdef Py_ssize_t n_left = left.shape[0]
    cdef Py_ssize_t n_right = right.shape[0]

    while i < n_left and j < n_right:
        if left[i] <= right[j]:
            out[o] = left[i]
            i += 1
        else:
            out[o] = right[j]
            j += 1
        o += 1
    while i < n_left:
        out[o] = left[i]
        i += 1
        o += 1
    while j < n_right:
        out[o] = right[j]
        j += 1
        o += 1


cdef Py_ssize_t _count_start_end_segments(
    const np.int64_t[:] starts,
    const np.int64_t[:] ends,
) noexcept nogil:
    cdef Py_ssize_t i_s = 0
    cdef Py_ssize_t i_e = 0
    cdef Py_ssize_t n_s = starts.shape[0]
    cdef Py_ssize_t n_e = ends.shape[0]
    cdef Py_ssize_t seg_count = 0
    cdef long long prev_pos = 0
    cdef long long next_pos
    cdef long long coverage = 0
    cdef bint started = False

    while i_s < n_s or i_e < n_e:
        next_pos = LLONG_MAX
        if i_s < n_s and starts[i_s] < next_pos:
            next_pos = starts[i_s]
        if i_e < n_e and ends[i_e] < next_pos:
            next_pos = ends[i_e]
        if started and next_pos > prev_pos and coverage > 0:
            seg_count += 1
        while i_s < n_s and starts[i_s] == next_pos:
            coverage += 1
            i_s += 1
        while i_e < n_e and ends[i_e] == next_pos:
            coverage -= 1
            i_e += 1
        prev_pos = next_pos
        started = True
    return seg_count


cdef void _fill_start_end_segments(
    const np.int64_t[:] starts,
    const np.int64_t[:] ends,
    np.uint32_t[:] seg_starts,
    np.uint32_t[:] seg_ends,
    np.uint32_t[:] seg_weights,
    bint pair_semantics,
) noexcept nogil:
    cdef Py_ssize_t i_s = 0
    cdef Py_ssize_t i_e = 0
    cdef Py_ssize_t n_s = starts.shape[0]
    cdef Py_ssize_t n_e = ends.shape[0]
    cdef Py_ssize_t out_idx = 0
    cdef long long prev_pos = 0
    cdef long long next_pos
    cdef long long coverage = 0
    cdef bint started = False

    while i_s < n_s or i_e < n_e:
        next_pos = LLONG_MAX
        if i_s < n_s and starts[i_s] < next_pos:
            next_pos = starts[i_s]
        if i_e < n_e and ends[i_e] < next_pos:
            next_pos = ends[i_e]
        if started and next_pos > prev_pos and coverage > 0:
            seg_starts[out_idx] = <np.uint32_t>prev_pos
            seg_ends[out_idx] = <np.uint32_t>next_pos
            if pair_semantics:
                seg_weights[out_idx] = <np.uint32_t>coverage
            else:
                seg_weights[out_idx] = 1
            out_idx += 1
        while i_s < n_s and starts[i_s] == next_pos:
            coverage += 1
            i_s += 1
        while i_e < n_e and ends[i_e] == next_pos:
            coverage -= 1
            i_e += 1
        prev_pos = next_pos
        started = True


def coverage_sweep_arrays_cy(
    const np.int64_t[:] anchors,
    const np.int64_t[:] spans,
    int window_left,
    int window_right,
    const np.uint32_t[:] sentence_bounds,
    bint within_sentence,
    bint pair_semantics,
    unsigned long long total_tokens,
):
    if total_tokens == 0:
        raise RuntimeError("total_tokens fehlt fuer coverage_sweep")
    cdef Py_ssize_t n = anchors.shape[0]
    if n == 0:
        return (
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.uint32),
        )
    if spans.shape[0] != n:
        raise ValueError("anchors und spans muessen gleich lang sein")

    cdef np.ndarray[np.int64_t, ndim=1] start = np.empty(n, dtype=np.int64)
    cdef np.ndarray[np.int64_t, ndim=1] end = np.empty(n, dtype=np.int64)
    cdef np.ndarray[np.int64_t, ndim=1] left_start = np.empty(n, dtype=np.int64)
    cdef np.ndarray[np.int64_t, ndim=1] right_end = np.empty(n, dtype=np.int64)
    cdef const np.int64_t[:] anchor_view = anchors
    cdef const np.int64_t[:] span_view = spans
    cdef np.int64_t[:] start_view = start
    cdef np.int64_t[:] end_view = end
    cdef np.int64_t[:] left_view = left_start
    cdef np.int64_t[:] right_view = right_end

    cdef Py_ssize_t i
    cdef Py_ssize_t seg_count = 0
    cdef long long a
    cdef long long s
    cdef long long e
    cdef long long l
    cdef long long r
    cdef long long bound_start
    cdef long long bound_end
    cdef const np.uint32_t[:] sent_view
    cdef Py_ssize_t sent_len = 0
    cdef Py_ssize_t sent_idx = 0
    cdef Py_ssize_t left_idx = 0
    cdef Py_ssize_t right_idx = 0
    cdef bint uniform_span = True
    cdef bint right_starts_sorted = True
    cdef bint right_ends_sorted = True
    cdef bint have_right_start = False
    cdef bint have_right_end = False
    cdef long long first_span = span_view[0]
    cdef long long prev_right_start = 0
    cdef long long prev_right_end = 0
    cdef np.ndarray[np.int64_t, ndim=1] left_starts
    cdef np.ndarray[np.int64_t, ndim=1] left_ends
    cdef np.ndarray[np.int64_t, ndim=1] right_starts
    cdef np.ndarray[np.int64_t, ndim=1] right_ends
    cdef np.ndarray[np.int64_t, ndim=1] start_events
    cdef np.ndarray[np.int64_t, ndim=1] end_events
    cdef np.int64_t[:] left_starts_view
    cdef np.int64_t[:] left_ends_view
    cdef np.int64_t[:] right_starts_view
    cdef np.int64_t[:] right_ends_view
    cdef np.int64_t[:] start_events_view
    cdef np.int64_t[:] end_events_view
    cdef np.ndarray[np.uint32_t, ndim=1] seg_starts
    cdef np.ndarray[np.uint32_t, ndim=1] seg_ends
    cdef np.ndarray[np.uint32_t, ndim=1] seg_weights
    cdef np.uint32_t[:] seg_s_view
    cdef np.uint32_t[:] seg_e_view
    cdef np.uint32_t[:] seg_w_view
    if within_sentence:
        if sentence_bounds.shape[0] == 0:
            raise RuntimeError("Sentence Boundaries fehlen fuer within_sentence")
        sent_view = sentence_bounds
        sent_len = sent_view.shape[0]

    cdef Py_ssize_t left_count = 0
    cdef Py_ssize_t right_count = 0

    for i in range(n):
        a = anchor_view[i]
        s = a
        if span_view[i] != first_span:
            uniform_span = False
        e = a + span_view[i]
        l = a - window_left
        r = a + span_view[i] + window_right
        if within_sentence:
            while sent_idx < sent_len and sent_view[sent_idx] <= a:
                sent_idx += 1
            if sent_idx == 0:
                bound_start = 0
            else:
                bound_start = sent_view[sent_idx - 1]
            if sent_idx < sent_len:
                bound_end = sent_view[sent_idx]
            else:
                bound_end = <long long>total_tokens
            if l < bound_start:
                l = bound_start
            if r > bound_end:
                r = bound_end
        if l < 0:
            l = 0
        if r > <long long>total_tokens:
            r = <long long>total_tokens
        start_view[i] = s
        end_view[i] = e
        left_view[i] = l
        right_view[i] = r
        if l < s:
            left_count += 1
        if e < r:
            right_count += 1
            if have_right_start and e < prev_right_start:
                right_starts_sorted = False
            prev_right_start = e
            have_right_start = True
            if have_right_end and r < prev_right_end:
                right_ends_sorted = False
            prev_right_end = r
            have_right_end = True

    if left_count == 0 and right_count == 0:
        return (
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.uint32),
        )

    if uniform_span:
        left_starts = np.empty(left_count, dtype=np.int64)
        left_ends = np.empty(left_count, dtype=np.int64)
        right_starts = np.empty(right_count, dtype=np.int64)
        right_ends = np.empty(right_count, dtype=np.int64)
        left_starts_view = left_starts
        left_ends_view = left_ends
        right_starts_view = right_starts
        right_ends_view = right_ends
        left_idx = 0
        right_idx = 0
        for i in range(n):
            s = start_view[i]
            e = end_view[i]
            l = left_view[i]
            r = right_view[i]
            if l < s:
                left_starts_view[left_idx] = l
                left_ends_view[left_idx] = s
                left_idx += 1
            if e < r:
                right_starts_view[right_idx] = e
                right_ends_view[right_idx] = r
                right_idx += 1
        seg_count = _count_constant_span_segments(
            left_starts_view,
            left_ends_view,
            right_starts_view,
            right_ends_view,
        )
        if seg_count == 0:
            return (
                np.zeros(0, dtype=np.uint32),
                np.zeros(0, dtype=np.uint32),
                np.zeros(0, dtype=np.uint32),
            )
        seg_starts = np.empty(seg_count, dtype=np.uint32)
        seg_ends = np.empty(seg_count, dtype=np.uint32)
        seg_weights = np.empty(seg_count, dtype=np.uint32)
        seg_s_view = seg_starts
        seg_e_view = seg_ends
        seg_w_view = seg_weights
        _fill_constant_span_segments(
            left_starts_view,
            left_ends_view,
            right_starts_view,
            right_ends_view,
            seg_s_view,
            seg_e_view,
            seg_w_view,
            pair_semantics,
        )
        return seg_starts, seg_ends, seg_weights

    left_starts = np.empty(left_count, dtype=np.int64)
    left_ends = np.empty(left_count, dtype=np.int64)
    right_starts = np.empty(right_count, dtype=np.int64)
    right_ends = np.empty(right_count, dtype=np.int64)
    left_starts_view = left_starts
    left_ends_view = left_ends
    right_starts_view = right_starts
    right_ends_view = right_ends
    left_idx = 0
    right_idx = 0
    for i in range(n):
        s = start_view[i]
        e = end_view[i]
        l = left_view[i]
        r = right_view[i]
        if l < s:
            left_starts_view[left_idx] = l
            left_ends_view[left_idx] = s
            left_idx += 1
        if e < r:
            right_starts_view[right_idx] = e
            right_ends_view[right_idx] = r
            right_idx += 1

    start_events = np.empty(left_count + right_count, dtype=np.int64)
    end_events = np.empty(left_count + right_count, dtype=np.int64)
    start_events_view = start_events
    end_events_view = end_events
    if right_count == 0:
        start_events = left_starts.copy()
        end_events = left_ends.copy()
        start_events_view = start_events
        end_events_view = end_events
    else:
        if right_starts_sorted:
            _merge_sorted_i64(left_starts_view, right_starts_view, start_events_view)
        else:
            start_events[:left_count] = left_starts
            start_events[left_count:] = right_starts
            start_events.sort()
            start_events_view = start_events
        if right_ends_sorted:
            _merge_sorted_i64(left_ends_view, right_ends_view, end_events_view)
        else:
            end_events[:left_count] = left_ends
            end_events[left_count:] = right_ends
            end_events.sort()
            end_events_view = end_events

    seg_count = _count_start_end_segments(start_events_view, end_events_view)

    if seg_count == 0:
        return (
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.uint32),
            np.zeros(0, dtype=np.uint32),
        )

    seg_starts = np.empty(seg_count, dtype=np.uint32)
    seg_ends = np.empty(seg_count, dtype=np.uint32)
    seg_weights = np.empty(seg_count, dtype=np.uint32)
    seg_s_view = seg_starts
    seg_e_view = seg_ends
    seg_w_view = seg_weights
    _fill_start_end_segments(
        start_events_view,
        end_events_view,
        seg_s_view,
        seg_e_view,
        seg_w_view,
        pair_semantics,
    )

    return seg_starts, seg_ends, seg_weights
