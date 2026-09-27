# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: nonecheck=False

import numpy as np
cimport numpy as np
import time as _time
from libc.math cimport log
from libc.string cimport memcpy
from cpython.unicode cimport PyUnicode_DecodeUTF8, PyUnicode_GET_LENGTH


cdef inline object _id_to_str(unsigned int tid,
                              np.ndarray[np.uint64_t, ndim=1] offsets,
                              const unsigned char[:] blob):
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef unsigned long long start
    cdef unsigned long long end
    cdef const char* ptr
    if tid == 0 or tid >= n_offsets:
        return ""
    start = offsets[tid]
    end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
    if end <= start:
        return ""
    ptr = <const char*>&blob[start]
    return <object>PyUnicode_DecodeUTF8(ptr, <Py_ssize_t>(end - start), NULL)


cdef inline object _id_to_str_cached(
    unsigned int tid,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    object cache,
):
    cdef object cached
    if tid == 0:
        return ""
    if isinstance(cache, list):
        if tid < len(cache):
            cached = cache[tid]
            if cached is not None:
                return cached
            cached = _id_to_str(tid, offsets, blob)
            cache[tid] = cached
            return cached
        return _id_to_str(tid, offsets, blob)
    cached = cache.get(tid)
    if cached is not None:
        return cached
    cached = _id_to_str(tid, offsets, blob)
    if len(cache) < 65536:
        cache[tid] = cached
    return cached


cdef inline object _id_to_str_cached_list(
    unsigned int tid,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    list cache,
):
    cdef object cached
    if tid == 0:
        return ""
    if tid < len(cache):
        cached = cache[tid]
        if cached is not None:
            return cached
        cached = _id_to_str(tid, offsets, blob)
        cache[tid] = cached
        return cached
    return _id_to_str(tid, offsets, blob)


cdef inline object _join_ids_i32_cached(
    np.int32_t[:] ids,
    Py_ssize_t start,
    Py_ssize_t end,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    object cache,
):
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef list parts = []
    for i in range(start, end):
        tid = <unsigned int>ids[i]
        if tid == 0:
            continue
        parts.append(_id_to_str_cached(tid, offsets, blob, cache))
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts)


cdef inline object _join_ids_i32_cached_list(
    np.int32_t[:] ids,
    Py_ssize_t start,
    Py_ssize_t end,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    list cache,
):
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef list parts = []
    for i in range(start, end):
        tid = <unsigned int>ids[i]
        if tid == 0:
            continue
        parts.append(_id_to_str_cached_list(tid, offsets, blob, cache))
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts)


cdef inline list _ids_to_texts_i32_cached(
    np.int32_t[:] ids,
    Py_ssize_t count,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    object cache,
):
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef list texts = [None] * count
    for i in range(count):
        tid = <unsigned int>ids[i]
        if tid == 0:
            texts[i] = ""
        else:
            texts[i] = _id_to_str_cached(tid, offsets, blob, cache)
    return texts


cdef inline list _ids_to_texts_i32_cached_list(
    np.int32_t[:] ids,
    Py_ssize_t count,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    list cache,
):
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef list texts = [None] * count
    for i in range(count):
        tid = <unsigned int>ids[i]
        if tid == 0:
            texts[i] = ""
        else:
            texts[i] = _id_to_str_cached_list(tid, offsets, blob, cache)
    return texts


cdef inline object _join_texts_range(
    list texts,
    Py_ssize_t start,
    Py_ssize_t end,
):
    cdef Py_ssize_t i
    cdef object part
    cdef list parts = []
    for i in range(start, end):
        part = texts[i]
        if part:
            parts.append(part)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts)


cdef inline object _slice_text_range(
    object merged_txt,
    np.int32_t[:] char_starts_view,
    np.int32_t[:] char_ends_view,
    np.int32_t[:] next_nonempty_view,
    np.int32_t[:] prev_nonempty_view,
    Py_ssize_t start,
    Py_ssize_t end,
):
    cdef Py_ssize_t first_idx
    cdef Py_ssize_t last_idx
    if start >= end:
        return ""
    first_idx = next_nonempty_view[start]
    last_idx = prev_nonempty_view[end - 1]
    if first_idx < 0 or last_idx < 0 or first_idx > last_idx:
        return ""
    return merged_txt[char_starts_view[first_idx]:char_ends_view[last_idx]]


cdef inline void _slice_text_offsets(
    np.int32_t[:] char_starts_view,
    np.int32_t[:] char_ends_view,
    np.int32_t[:] next_nonempty_view,
    np.int32_t[:] prev_nonempty_view,
    Py_ssize_t start,
    Py_ssize_t end,
    np.int32_t[:] out_lo,
    np.int32_t[:] out_hi,
    Py_ssize_t row_idx,
):
    cdef Py_ssize_t first_idx
    cdef Py_ssize_t last_idx
    if start >= end:
        out_lo[row_idx] = -1
        out_hi[row_idx] = -1
        return
    first_idx = next_nonempty_view[start]
    last_idx = prev_nonempty_view[end - 1]
    if first_idx < 0 or last_idx < 0 or first_idx > last_idx:
        out_lo[row_idx] = -1
        out_hi[row_idx] = -1
        return
    out_lo[row_idx] = char_starts_view[first_idx]
    out_hi[row_idx] = char_ends_view[last_idx]


cdef class SvbRangeDecoder:
    cdef object _cache_arr
    cdef object _out_arr
    cdef unsigned long long _cache_block
    cdef unsigned int _cache_block_len

    def __cinit__(self):
        self._cache_arr = np.zeros(0, dtype=np.int32)
        self._out_arr = np.zeros(0, dtype=np.int32)
        self._cache_block = 0xffffffffffffffff
        self._cache_block_len = 0

    cdef void _ensure_capacity(self, unsigned int block_size):
        if self._cache_arr.shape[0] < block_size:
            self._cache_arr = np.empty(block_size, dtype=np.int32)

    cdef np.ndarray _ensure_out_capacity(self, Py_ssize_t size):
        if self._out_arr.shape[0] < size:
            self._out_arr = np.empty(size, dtype=np.int32)
        return self._out_arr

    cdef bint _load_block(
        self,
        np.ndarray[np.uint64_t, ndim=1] offsets,
        const unsigned char[:] blob,
        unsigned long long block_idx,
        unsigned int block_size,
        unsigned long long token_count,
    ) except -1:
        cdef unsigned long long start_off
        cdef unsigned long long end_off
        cdef unsigned int block_len = block_size
        cdef np.int32_t[:] cache_view
        self._ensure_capacity(block_size)
        if (block_idx + 1) * block_size > token_count:
            block_len = <unsigned int>(token_count - block_idx * block_size)
        if block_len == 0:
            self._cache_block = block_idx
            self._cache_block_len = 0
            return False
        start_off = offsets[block_idx]
        end_off = offsets[block_idx + 1]
        cache_view = self._cache_arr
        _svb_decode_block(
            &blob[start_off],
            end_off - start_off,
            block_len,
            <unsigned int*>&cache_view[0],
        )
        self._cache_block = block_idx
        self._cache_block_len = block_len
        return True

    def decode_range_i32(
        self,
        np.ndarray[np.uint64_t, ndim=1] offsets,
        object data,
        unsigned int block_size,
        unsigned long long token_count,
        unsigned long long start_pos,
        unsigned long long end_pos,
    ):
        cdef const unsigned char[:] blob = data
        cdef unsigned long long n_blocks = offsets.shape[0] - 1
        cdef unsigned long long start_block
        cdef unsigned long long end_block
        cdef unsigned long long block_idx
        cdef unsigned long long cursor = 0
        cdef unsigned long long block_start
        cdef unsigned int local_start
        cdef unsigned int local_end
        cdef unsigned int take
        cdef np.ndarray[np.int32_t, ndim=1] out
        cdef np.int32_t[:] out_view
        cdef np.int32_t[:] cache_view

        if end_pos <= start_pos or start_pos >= token_count:
            return np.zeros(0, dtype=np.int32)
        if end_pos > token_count:
            end_pos = token_count
        if start_pos >= end_pos or n_blocks == 0:
            return np.zeros(0, dtype=np.int32)

        out = np.empty(end_pos - start_pos, dtype=np.int32)
        out_view = out
        start_block = start_pos // block_size
        end_block = (end_pos - 1) // block_size
        for block_idx in range(start_block, end_block + 1):
            if block_idx >= n_blocks:
                break
            if self._cache_block != block_idx:
                self._load_block(offsets, blob, block_idx, block_size, token_count)
            if self._cache_block_len == 0:
                continue
            block_start = block_idx * block_size
            local_start = 0
            if block_idx == start_block:
                local_start = <unsigned int>(start_pos - block_start)
            local_end = self._cache_block_len
            if block_idx == end_block:
                local_end = <unsigned int>(end_pos - block_start)
            take = local_end - local_start
            if take == 0:
                continue
            cache_view = self._cache_arr
            memcpy(
                &out_view[cursor],
                &cache_view[local_start],
                take * sizeof(np.int32_t),
            )
            cursor += take
        return out

    def decode_ranges_packed_i32(
        self,
        np.ndarray[np.uint64_t, ndim=1] offsets,
        object data,
        unsigned int block_size,
        unsigned long long token_count,
        np.ndarray[np.int32_t, ndim=1] starts,
        np.ndarray[np.int32_t, ndim=1] ends,
    ):
        cdef const unsigned char[:] blob = data
        cdef Py_ssize_t n_ranges = starts.shape[0]
        cdef Py_ssize_t i
        cdef long long total_len = 0
        cdef int start_pos
        cdef int end_pos
        cdef long long span_len
        cdef unsigned long long n_blocks = offsets.shape[0] - 1
        cdef unsigned long long cursor = 0
        cdef unsigned long long pos
        cdef unsigned long long block_idx
        cdef unsigned long long block_start
        cdef unsigned int local_start
        cdef unsigned int take
        cdef np.ndarray[np.int32_t, ndim=1] out
        cdef np.int32_t[:] out_view
        cdef np.int32_t[:] cache_view

        if ends.shape[0] != n_ranges:
            raise ValueError("starts und ends muessen gleich lang sein")
        if n_ranges == 0 or n_blocks == 0:
            return np.zeros(0, dtype=np.int32)

        for i in range(n_ranges):
            start_pos = starts[i]
            end_pos = ends[i]
            if start_pos < 0:
                start_pos = 0
            if end_pos > token_count:
                end_pos = <int>token_count
            if end_pos <= start_pos:
                continue
            span_len = end_pos - start_pos
            total_len += span_len

        if total_len <= 0:
            return np.zeros(0, dtype=np.int32)

        out = np.empty(total_len, dtype=np.int32)
        out_view = out
        for i in range(n_ranges):
            start_pos = starts[i]
            end_pos = ends[i]
            if start_pos < 0:
                start_pos = 0
            if end_pos > token_count:
                end_pos = <int>token_count
            if end_pos <= start_pos:
                continue
            pos = <unsigned long long>start_pos
            while pos < <unsigned long long>end_pos:
                block_idx = pos // block_size
                if block_idx >= n_blocks:
                    break
                if self._cache_block != block_idx:
                    self._load_block(offsets, blob, block_idx, block_size, token_count)
                if self._cache_block_len == 0:
                    break
                block_start = block_idx * block_size
                local_start = <unsigned int>(pos - block_start)
                take = self._cache_block_len - local_start
                if pos + take > <unsigned long long>end_pos:
                    take = <unsigned int>(end_pos - pos)
                if take <= 0:
                    break
                cache_view = self._cache_arr
                memcpy(
                    &out_view[cursor],
                    &cache_view[local_start],
                    take * sizeof(np.int32_t),
                )
                cursor += take
                pos += take
        return out

    def decode_ranges_packed_sorted_i32(
        self,
        np.ndarray[np.uint64_t, ndim=1] offsets,
        object data,
        unsigned int block_size,
        unsigned long long token_count,
        np.ndarray[np.int32_t, ndim=1] starts,
        np.ndarray[np.int32_t, ndim=1] ends,
    ):
        cdef const unsigned char[:] blob = data
        cdef Py_ssize_t n_ranges = starts.shape[0]
        cdef Py_ssize_t i = 0
        cdef long long total_len = 0
        cdef int start_pos
        cdef int end_pos
        cdef unsigned long long cur_start
        cdef unsigned long long cur_end
        cdef unsigned long long n_blocks = offsets.shape[0] - 1
        cdef unsigned long long block_idx
        cdef unsigned long long block_start
        cdef unsigned long long block_end
        cdef unsigned long long cursor = 0
        cdef unsigned int local_start
        cdef unsigned int local_end
        cdef unsigned int take
        cdef np.ndarray[np.int32_t, ndim=1] out
        cdef np.int32_t[:] out_view
        cdef np.int32_t[:] cache_view

        if ends.shape[0] != n_ranges:
            raise ValueError("starts und ends muessen gleich lang sein")
        if n_ranges == 0 or n_blocks == 0:
            return np.zeros(0, dtype=np.int32)

        for i in range(n_ranges):
            start_pos = starts[i]
            end_pos = ends[i]
            if start_pos < 0:
                start_pos = 0
            if end_pos > token_count:
                end_pos = <int>token_count
            if end_pos <= start_pos:
                continue
            total_len += end_pos - start_pos

        if total_len <= 0:
            return np.zeros(0, dtype=np.int32)

        out = np.empty(total_len, dtype=np.int32)
        out_view = out
        i = 0
        while i < n_ranges:
            start_pos = starts[i]
            end_pos = ends[i]
            if start_pos < 0:
                start_pos = 0
            if end_pos > token_count:
                end_pos = <int>token_count
            if end_pos > start_pos:
                cur_start = <unsigned long long>start_pos
                cur_end = <unsigned long long>end_pos
                break
            i += 1

        while i < n_ranges:
            block_idx = cur_start // block_size
            if block_idx >= n_blocks:
                break
            if self._cache_block != block_idx:
                self._load_block(offsets, blob, block_idx, block_size, token_count)
            if self._cache_block_len == 0:
                break
            block_start = block_idx * block_size
            block_end = block_start + self._cache_block_len
            cache_view = self._cache_arr
            while True:
                local_start = <unsigned int>(cur_start - block_start)
                local_end = self._cache_block_len
                if cur_end < block_end:
                    local_end = <unsigned int>(cur_end - block_start)
                take = local_end - local_start
                if take > 0:
                    memcpy(
                        &out_view[cursor],
                        &cache_view[local_start],
                        take * sizeof(np.int32_t),
                    )
                    cursor += take
                if cur_end <= block_end:
                    i += 1
                    while i < n_ranges:
                        start_pos = starts[i]
                        end_pos = ends[i]
                        if start_pos < 0:
                            start_pos = 0
                        if end_pos > token_count:
                            end_pos = <int>token_count
                        if end_pos > start_pos:
                            cur_start = <unsigned long long>start_pos
                            cur_end = <unsigned long long>end_pos
                            break
                        i += 1
                    if i >= n_ranges or cur_start >= block_end:
                        break
                    continue
                cur_start = block_end
                break
        return out

    def decode_ranges_packed_sorted_known_i32(
        self,
        np.ndarray[np.uint64_t, ndim=1] offsets,
        object data,
        unsigned int block_size,
        unsigned long long token_count,
        np.ndarray[np.int32_t, ndim=1] starts,
        np.ndarray[np.int32_t, ndim=1] ends,
        Py_ssize_t total_len,
    ):
        cdef const unsigned char[:] blob = data
        cdef Py_ssize_t n_ranges = starts.shape[0]
        cdef Py_ssize_t i = 0
        cdef unsigned long long cur_start
        cdef unsigned long long cur_end
        cdef unsigned long long n_blocks = offsets.shape[0] - 1
        cdef unsigned long long block_idx
        cdef unsigned long long block_start
        cdef unsigned long long block_end
        cdef unsigned long long cursor = 0
        cdef unsigned int local_start
        cdef unsigned int local_end
        cdef unsigned int take
        cdef np.ndarray[np.int32_t, ndim=1] out
        cdef np.int32_t[:] out_view
        cdef np.int32_t[:] cache_view

        if ends.shape[0] != n_ranges:
            raise ValueError("starts und ends muessen gleich lang sein")
        if n_ranges == 0 or n_blocks == 0 or total_len <= 0:
            return np.zeros(0, dtype=np.int32)

        out = np.empty(total_len, dtype=np.int32)
        out_view = out
        cur_start = <unsigned long long>starts[0]
        cur_end = <unsigned long long>ends[0]

        while i < n_ranges:
            block_idx = cur_start // block_size
            if block_idx >= n_blocks:
                break
            if self._cache_block != block_idx:
                self._load_block(offsets, blob, block_idx, block_size, token_count)
            if self._cache_block_len == 0:
                break
            block_start = block_idx * block_size
            block_end = block_start + self._cache_block_len
            cache_view = self._cache_arr
            while True:
                local_start = <unsigned int>(cur_start - block_start)
                local_end = self._cache_block_len
                if cur_end < block_end:
                    local_end = <unsigned int>(cur_end - block_start)
                take = local_end - local_start
                if take > 0:
                    memcpy(
                        &out_view[cursor],
                        &cache_view[local_start],
                        take * sizeof(np.int32_t),
                    )
                    cursor += take
                if cur_end <= block_end:
                    i += 1
                    if i >= n_ranges:
                        break
                    cur_start = <unsigned long long>starts[i]
                    cur_end = <unsigned long long>ends[i]
                    if cur_start >= block_end:
                        break
                    continue
                cur_start = block_end
                break
        return out

    def decode_ranges_packed_sorted_known_reuse_i32(
        self,
        np.ndarray[np.uint64_t, ndim=1] offsets,
        object data,
        unsigned int block_size,
        unsigned long long token_count,
        np.ndarray[np.int32_t, ndim=1] starts,
        np.ndarray[np.int32_t, ndim=1] ends,
        Py_ssize_t total_len,
    ):
        cdef const unsigned char[:] blob = data
        cdef Py_ssize_t n_ranges = starts.shape[0]
        cdef Py_ssize_t i = 0
        cdef unsigned long long cur_start
        cdef unsigned long long cur_end
        cdef unsigned long long n_blocks = offsets.shape[0] - 1
        cdef unsigned long long block_idx
        cdef unsigned long long block_start
        cdef unsigned long long block_end
        cdef unsigned long long cursor = 0
        cdef unsigned int local_start
        cdef unsigned int local_end
        cdef unsigned int take
        cdef np.ndarray[np.int32_t, ndim=1] out
        cdef np.int32_t[:] out_view
        cdef np.int32_t[:] cache_view

        if ends.shape[0] != n_ranges:
            raise ValueError("starts und ends muessen gleich lang sein")
        if n_ranges == 0 or n_blocks == 0 or total_len <= 0:
            return np.zeros(0, dtype=np.int32)

        out = self._ensure_out_capacity(total_len)
        out_view = out
        cur_start = <unsigned long long>starts[0]
        cur_end = <unsigned long long>ends[0]

        while i < n_ranges:
            block_idx = cur_start // block_size
            if block_idx >= n_blocks:
                break
            if self._cache_block != block_idx:
                self._load_block(offsets, blob, block_idx, block_size, token_count)
            if self._cache_block_len == 0:
                break
            block_start = block_idx * block_size
            block_end = block_start + self._cache_block_len
            cache_view = self._cache_arr
            while True:
                local_start = <unsigned int>(cur_start - block_start)
                local_end = self._cache_block_len
                if cur_end < block_end:
                    local_end = <unsigned int>(cur_end - block_start)
                take = local_end - local_start
                if take > 0:
                    memcpy(
                        &out_view[cursor],
                        &cache_view[local_start],
                        take * sizeof(np.int32_t),
                    )
                    cursor += take
                if cur_end <= block_end:
                    i += 1
                    if i >= n_ranges:
                        break
                    cur_start = <unsigned long long>starts[i]
                    cur_end = <unsigned long long>ends[i]
                    if cur_start >= block_end:
                        break
                    continue
                cur_start = block_end
                break
        return out[:total_len]

    def decode_ranges_packed_sorted_known_slice_i32(
        self,
        np.ndarray[np.uint64_t, ndim=1] offsets,
        object data,
        unsigned int block_size,
        unsigned long long token_count,
        np.ndarray[np.int32_t, ndim=1] starts,
        np.ndarray[np.int32_t, ndim=1] ends,
        Py_ssize_t total_len,
    ):
        cdef const unsigned char[:] blob = data
        cdef Py_ssize_t n_ranges = starts.shape[0]
        cdef Py_ssize_t i
        cdef int start_pos
        cdef int end_pos
        cdef unsigned long long pos
        cdef unsigned long long n_blocks = offsets.shape[0] - 1
        cdef unsigned long long block_idx
        cdef unsigned long long block_start
        cdef unsigned long long block_end
        cdef unsigned long long start_off
        cdef unsigned long long end_off
        cdef unsigned long long cursor = 0
        cdef unsigned int block_len
        cdef unsigned int local_start
        cdef unsigned int local_end
        cdef unsigned int take
        cdef np.ndarray[np.int32_t, ndim=1] out
        cdef np.int32_t[:] out_view

        if ends.shape[0] != n_ranges:
            raise ValueError("starts und ends muessen gleich lang sein")
        if n_ranges == 0 or n_blocks == 0 or total_len <= 0:
            return np.zeros(0, dtype=np.int32)

        out = self._ensure_out_capacity(total_len)
        out_view = out
        for i in range(n_ranges):
            start_pos = starts[i]
            end_pos = ends[i]
            if start_pos < 0:
                start_pos = 0
            if end_pos > token_count:
                end_pos = <int>token_count
            if end_pos <= start_pos:
                continue
            pos = <unsigned long long>start_pos
            while pos < <unsigned long long>end_pos:
                block_idx = pos // block_size
                if block_idx >= n_blocks:
                    break
                start_off = offsets[block_idx]
                end_off = offsets[block_idx + 1]
                block_start = block_idx * block_size
                block_len = block_size
                if (block_idx + 1) * block_size > token_count:
                    block_len = <unsigned int>(token_count - block_start)
                if block_len == 0:
                    break
                block_end = block_start + block_len
                local_start = <unsigned int>(pos - block_start)
                local_end = block_len
                if end_pos < block_end:
                    local_end = <unsigned int>(end_pos - block_start)
                take = local_end - local_start
                if take == 0:
                    break
                _svb_decode_block_slice_i32(
                    &blob[start_off],
                    end_off - start_off,
                    block_len,
                    local_start,
                    local_end,
                    &out_view[cursor],
                )
                cursor += take
                pos += take
        return out[:total_len]


def make_svb_range_decoder():
    return SvbRangeDecoder()


def lexicon_match_regex(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    object pattern,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    cdef object fullmatch = pattern.fullmatch
    cdef object token
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(n_offsets - 1, dtype=np.uint32)
    out_view = out
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for tid in range(1, n_offsets):
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0:
            if (end - start) < min_len_i:
                continue
        if max_len_i >= 0:
            # UTF-8 safety: skip only if bytes length > max_len * 4
            if (end - start) > (max_len_i * 4):
                continue
        token = bytes(blob[start:end]).decode("utf-8")
        if fullmatch(token):
            out_view[out_n] = <np.uint32_t>tid
            out_n += 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


cdef inline bint _blob_startswith(
    const unsigned char[:] blob,
    unsigned long long start,
    unsigned long long end,
    const unsigned char[:] lit,
) nogil:
    cdef Py_ssize_t llen = lit.shape[0]
    cdef Py_ssize_t i
    if llen == 0:
        return True
    if end <= start or <unsigned long long>llen > (end - start):
        return False
    for i in range(llen):
        if blob[start + i] != lit[i]:
            return False
    return True


cdef inline bint _blob_endswith(
    const unsigned char[:] blob,
    unsigned long long start,
    unsigned long long end,
    const unsigned char[:] lit,
) nogil:
    cdef Py_ssize_t llen = lit.shape[0]
    cdef unsigned long long base
    cdef Py_ssize_t i
    if llen == 0:
        return True
    if end <= start or <unsigned long long>llen > (end - start):
        return False
    base = end - <unsigned long long>llen
    for i in range(llen):
        if blob[base + i] != lit[i]:
            return False
    return True


cdef inline bint _blob_contains(
    const unsigned char[:] blob,
    unsigned long long start,
    unsigned long long end,
    const unsigned char[:] lit,
) nogil:
    cdef Py_ssize_t llen = lit.shape[0]
    cdef unsigned long long i
    cdef Py_ssize_t j
    cdef unsigned long long stop
    if llen == 0:
        return True
    if end <= start or <unsigned long long>llen > (end - start):
        return False
    stop = end - <unsigned long long>llen + 1
    for i in range(start, stop):
        if blob[i] != lit[0]:
            continue
        for j in range(1, llen):
            if blob[i + j] != lit[j]:
                break
        else:
            return True
    return False


def lexicon_match_prefix(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    object literal,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef bytes lit_b = literal.encode("utf-8") if isinstance(literal, str) else bytes(literal)
    cdef const unsigned char[:] lit = lit_b
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(n_offsets - 1, dtype=np.uint32)
    out_view = out
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for tid in range(1, n_offsets):
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0 and (end - start) < min_len_i:
            continue
        if max_len_i >= 0 and (end - start) > (max_len_i * 4):
            continue
        if _blob_startswith(blob, start, end, lit):
            out_view[out_n] = <np.uint32_t>tid
            out_n += 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def lexicon_match_suffix(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    object literal,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef bytes lit_b = literal.encode("utf-8") if isinstance(literal, str) else bytes(literal)
    cdef const unsigned char[:] lit = lit_b
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(n_offsets - 1, dtype=np.uint32)
    out_view = out
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for tid in range(1, n_offsets):
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0 and (end - start) < min_len_i:
            continue
        if max_len_i >= 0 and (end - start) > (max_len_i * 4):
            continue
        if _blob_endswith(blob, start, end, lit):
            out_view[out_n] = <np.uint32_t>tid
            out_n += 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def lexicon_match_contains(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    object literal,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef bytes lit_b = literal.encode("utf-8") if isinstance(literal, str) else bytes(literal)
    cdef const unsigned char[:] lit = lit_b
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(n_offsets - 1, dtype=np.uint32)
    out_view = out
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for tid in range(1, n_offsets):
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0 and (end - start) < min_len_i:
            continue
        if max_len_i >= 0 and (end - start) > (max_len_i * 4):
            continue
        if _blob_contains(blob, start, end, lit):
            out_view[out_n] = <np.uint32_t>tid
            out_n += 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def lexicon_match_regex_ids(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
    object pattern,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef list out = []
    cdef object fullmatch = pattern.fullmatch
    cdef object token
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for i in range(ids.shape[0]):
        tid = ids[i]
        if tid == 0 or tid >= n_offsets:
            continue
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0:
            if (end - start) < min_len_i:
                continue
        if max_len_i >= 0:
            if (end - start) > (max_len_i * 4):
                continue
        token = bytes(blob[start:end]).decode("utf-8")
        if fullmatch(token):
            out.append(tid)
    if not out:
        return np.zeros(0, dtype=np.uint32)
    return np.array(out, dtype=np.uint32)


def lexicon_match_prefix_ids(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
    object literal,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef bytes lit_b = literal.encode("utf-8") if isinstance(literal, str) else bytes(literal)
    cdef const unsigned char[:] lit = lit_b
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(ids.shape[0], dtype=np.uint32)
    out_view = out
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for i in range(ids.shape[0]):
        tid = ids[i]
        if tid == 0 or tid >= n_offsets:
            continue
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0 and (end - start) < min_len_i:
            continue
        if max_len_i >= 0 and (end - start) > (max_len_i * 4):
            continue
        if _blob_startswith(blob, start, end, lit):
            out_view[out_n] = tid
            out_n += 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def lexicon_match_suffix_ids(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
    object literal,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef bytes lit_b = literal.encode("utf-8") if isinstance(literal, str) else bytes(literal)
    cdef const unsigned char[:] lit = lit_b
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(ids.shape[0], dtype=np.uint32)
    out_view = out
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for i in range(ids.shape[0]):
        tid = ids[i]
        if tid == 0 or tid >= n_offsets:
            continue
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0 and (end - start) < min_len_i:
            continue
        if max_len_i >= 0 and (end - start) > (max_len_i * 4):
            continue
        if _blob_endswith(blob, start, end, lit):
            out_view[out_n] = tid
            out_n += 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def lexicon_match_contains_ids(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
    object literal,
    object min_len=None,
    object max_len=None,
):
    cdef const unsigned char[:] blob = data
    cdef bytes lit_b = literal.encode("utf-8") if isinstance(literal, str) else bytes(literal)
    cdef const unsigned char[:] lit = lit_b
    cdef Py_ssize_t n_offsets = offsets.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef Py_ssize_t min_len_i = -1
    cdef Py_ssize_t max_len_i = -1
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    if n_offsets <= 1:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(ids.shape[0], dtype=np.uint32)
    out_view = out
    if min_len is not None:
        try:
            min_len_i = int(min_len)
        except Exception:
            min_len_i = -1
    if max_len is not None:
        try:
            max_len_i = int(max_len)
        except Exception:
            max_len_i = -1
    for i in range(ids.shape[0]):
        tid = ids[i]
        if tid == 0 or tid >= n_offsets:
            continue
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < n_offsets else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        if min_len_i >= 0 and (end - start) < min_len_i:
            continue
        if max_len_i >= 0 and (end - start) > (max_len_i * 4):
            continue
        if _blob_contains(blob, start, end, lit):
            out_view[out_n] = tid
            out_n += 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def strings_for_ids(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
    bint skip_zero=True,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t n = ids.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef list out = []
    for i in range(n):
        tid = ids[i]
        if skip_zero and tid == 0:
            continue
        out.append(_id_to_str(tid, offsets, blob))
    return out


def intersect_sorted(
    np.ndarray[np.uint32_t, ndim=1] a,
    np.ndarray[np.uint32_t, ndim=1] b,
):
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    if na == 0 or nb == 0:
        return np.zeros(0, dtype=np.uint32)
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t k = 0
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(min(na, nb), dtype=np.uint32)
    cdef np.uint32_t[:] av = a
    cdef np.uint32_t[:] bv = b
    cdef np.uint32_t[:] ov = out
    while i < na and j < nb:
        if av[i] == bv[j]:
            ov[k] = av[i]
            k += 1
            i += 1
            j += 1
        elif av[i] < bv[j]:
            i += 1
        else:
            j += 1
    if k == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:k]


cdef np.ndarray _union_sorted(
    np.ndarray[np.uint32_t, ndim=1] a,
    np.ndarray[np.uint32_t, ndim=1] b,
):
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    if na == 0:
        return b.astype(np.uint32, copy=False)
    if nb == 0:
        return a.astype(np.uint32, copy=False)
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t k = 0
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(na + nb, dtype=np.uint32)
    cdef np.uint32_t[:] av = a
    cdef np.uint32_t[:] bv = b
    cdef np.uint32_t[:] ov = out
    cdef bint has_last = False
    cdef np.uint32_t last = 0
    cdef np.uint32_t v
    while i < na or j < nb:
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
    return out[:k]


def union_sorted(
    np.ndarray[np.uint32_t, ndim=1] a,
    np.ndarray[np.uint32_t, ndim=1] b,
):
    return _union_sorted(a, b)


def intersect_shifted(
    np.ndarray[np.uint32_t, ndim=1] a,
    np.ndarray[np.uint32_t, ndim=1] b,
    unsigned int shift,
    unsigned long long max_pos,
):
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    if na == 0 or nb == 0:
        return np.zeros(0, dtype=np.uint32)
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t k = 0
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(min(na, nb), dtype=np.uint32)
    cdef np.uint32_t[:] av = a
    cdef np.uint32_t[:] bv = b
    cdef np.uint32_t[:] ov = out
    cdef unsigned int bj
    cdef unsigned long long shifted
    while i < na and j < nb:
        bj = bv[j]
        if bj < shift:
            j += 1
            continue
        shifted = <unsigned long long>(bj - shift)
        if shifted > max_pos:
            break
        if av[i] == <np.uint32_t>shifted:
            ov[k] = av[i]
            k += 1
            i += 1
            j += 1
        elif av[i] < shifted:
            i += 1
        else:
            j += 1
    if k == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:k]


def setdiff_sorted(
    np.ndarray[np.uint32_t, ndim=1] a,
    np.ndarray[np.uint32_t, ndim=1] b,
):
    cdef Py_ssize_t na = a.shape[0]
    cdef Py_ssize_t nb = b.shape[0]
    if na == 0:
        return np.zeros(0, dtype=np.uint32)
    if nb == 0:
        return a.astype(np.uint32, copy=False)
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t j = 0
    cdef Py_ssize_t k = 0
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(na, dtype=np.uint32)
    cdef np.uint32_t[:] av = a
    cdef np.uint32_t[:] bv = b
    cdef np.uint32_t[:] ov = out
    while i < na and j < nb:
        if av[i] == bv[j]:
            i += 1
            j += 1
        elif av[i] < bv[j]:
            ov[k] = av[i]
            k += 1
            i += 1
        else:
            j += 1
    while i < na:
        ov[k] = av[i]
        k += 1
        i += 1
    if k == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:k]


def complement_sorted(
    unsigned long long total_tokens,
    np.ndarray[np.uint32_t, ndim=1] positions,
    long long limit=-1,
):
    cdef Py_ssize_t total = <Py_ssize_t>total_tokens
    if total <= 0:
        return np.zeros(0, dtype=np.uint32)
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t cap
    if limit >= 0:
        cap = <Py_ssize_t>limit
        if cap == 0:
            return np.zeros(0, dtype=np.uint32)
        out = np.empty(cap, dtype=np.uint32)
    else:
        cap = total - n
        if cap <= 0:
            return np.zeros(0, dtype=np.uint32)
        out = np.empty(cap, dtype=np.uint32)
    cdef np.uint32_t[:] pv = positions
    cdef np.uint32_t[:] ov = out
    cdef Py_ssize_t i = 0
    cdef Py_ssize_t k = 0
    cdef Py_ssize_t prev = 0
    cdef Py_ssize_t p
    while i < n:
        p = <Py_ssize_t>pv[i]
        if p > prev:
            while prev < p and k < cap:
                ov[k] = <np.uint32_t>prev
                k += 1
                prev += 1
            if k >= cap:
                return out[:k]
        prev = p + 1
        i += 1
    while prev < total and k < cap:
        ov[k] = <np.uint32_t>prev
        k += 1
        prev += 1
    if k == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:k]


def dependency_arcs_window(
    np.ndarray[np.int64_t, ndim=1] head_ids,
    np.ndarray[np.uint32_t, ndim=1] rel_ids,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned long long start,
    unsigned long long end,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t total = head_ids.shape[0]
    cdef list out = []
    cdef unsigned long long pos
    cdef long long head
    cdef unsigned int rel_id
    if total == 0:
        return out
    if start >= <unsigned long long>total:
        return out
    if end >= <unsigned long long>total:
        end = <unsigned long long>(total - 1)
    for pos in range(start, end + 1):
        head = head_ids[pos]
        if head < <long long>start or head > <long long>end:
            continue
        rel_id = rel_ids[pos]
        out.append((int(pos - start), int(head - start), _id_to_str(rel_id, offsets, blob)))
    return out


def word_sketch_counts(
    np.ndarray[np.uint32_t, ndim=1] positions,
    np.ndarray[np.int64_t, ndim=1] head_ids,
    np.ndarray[np.uint32_t, ndim=1] rel_ids,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
):
    # TODO(native-csr): replace the dense token_count-sized mask with a native
    # dependency CSR/postings index. Until then server.py must keep its token
    # count guard and Python streaming fallback for large corpora/docsets.
    cdef const unsigned char[:] svb = data
    cdef Py_ssize_t n_pos = positions.shape[0]
    cdef Py_ssize_t total = <Py_ssize_t>token_count
    cdef np.ndarray[np.uint8_t, ndim=1] mask = np.zeros(total, dtype=np.uint8)
    cdef np.uint8_t[:] mask_view = mask
    cdef np.uint32_t[:] pos_view = positions
    cdef np.int64_t[:] head_view = head_ids
    cdef np.uint32_t[:] rel_view = rel_ids
    cdef dict dep_counts = {}
    cdef dict head_counts = {}
    cdef dict inner
    cdef dict inner2
    cdef Py_ssize_t i
    cdef unsigned int pos
    cdef long long head
    cdef unsigned int rel_id
    cdef unsigned int word_id

    cdef unsigned long long block_idx
    cdef unsigned long long block_start
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned int block_len
    cdef unsigned int local
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf
    cdef unsigned long long cached_block = 0xffffffffffffffff

    if n_pos == 0:
        return dep_counts, head_counts

    if head_ids.shape[0] != total or rel_ids.shape[0] != total:
        raise ValueError("head_ids oder rel_ids passen nicht zur Tokenanzahl")

    for i in range(n_pos):
        pos = pos_view[i]
        if pos < total:
            mask_view[pos] = 1

    # term as dependent -> count heads
    for i in range(n_pos):
        pos = pos_view[i]
        if pos >= total:
            continue
        head = head_view[pos]
        if head < 0 or head >= token_count:
            continue
        rel_id = rel_view[pos]

        block_idx = (<unsigned long long>head) // block_size
        if block_idx != cached_block:
            start_off = offsets[block_idx]
            end_off = offsets[block_idx + 1]
            block_len = block_size
            if (block_idx + 1) * block_size > token_count:
                block_len = <unsigned int>(token_count - block_idx * block_size)
            _svb_decode_block(&svb[start_off], end_off - start_off, block_len, &buf_view[0])
            cached_block = block_idx
        block_start = block_idx * block_size
        local = <unsigned int>(head - block_start)
        if local >= block_len:
            continue
        word_id = buf_view[local]
        if word_id == 0:
            continue
        inner = dep_counts.get(rel_id)
        if inner is None:
            inner = {}
            dep_counts[rel_id] = inner
        inner[word_id] = inner.get(word_id, 0) + 1

    # term as head -> scan heads for dependents
    cached_block = 0xffffffffffffffff
    block_idx = 0
    block_start = 0
    i = 0
    while i < total:
        block_idx = (<unsigned long long>i) // block_size
        start_off = offsets[block_idx]
        end_off = offsets[block_idx + 1]
        block_len = block_size
        if (block_idx + 1) * block_size > token_count:
            block_len = <unsigned int>(token_count - block_idx * block_size)
        _svb_decode_block(&svb[start_off], end_off - start_off, block_len, &buf_view[0])
        block_start = block_idx * block_size
        for local in range(block_len):
            pos = <unsigned int>(block_start + local)
            head = head_view[pos]
            if head < 0 or head >= token_count:
                continue
            if mask_view[head] == 0:
                continue
            rel_id = rel_view[pos]
            word_id = buf_view[local]
            if word_id == 0:
                continue
            inner2 = head_counts.get(rel_id)
            if inner2 is None:
                inner2 = {}
                head_counts[rel_id] = inner2
            inner2[word_id] = inner2.get(word_id, 0) + 1
        i = block_start + block_len

    return dep_counts, head_counts


cdef inline Py_ssize_t _doc_index(np.ndarray[np.uint32_t, ndim=1] bounds, unsigned int pos):
    cdef Py_ssize_t lo = 0
    cdef Py_ssize_t hi = bounds.shape[0]
    cdef Py_ssize_t mid
    while lo < hi:
        mid = (lo + hi) // 2
        if bounds[mid] <= pos:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


cdef inline unsigned int _read_u16(const unsigned char* p):
    return (<unsigned int>p[0]) | (<unsigned int>p[1] << 8)


cdef inline unsigned int _read_u32(const unsigned char* p):
    return (
        (<unsigned int>p[0])
        | (<unsigned int>p[1] << 8)
        | (<unsigned int>p[2] << 16)
        | (<unsigned int>p[3] << 24)
    )


cdef inline unsigned long long _align8(unsigned long long v):
    return (v + 7) & ~7


cdef inline bint _bin_contains(np.uint32_t[:] arr, Py_ssize_t n, unsigned int val):
    cdef Py_ssize_t lo = 0
    cdef Py_ssize_t hi = n
    cdef Py_ssize_t mid
    cdef unsigned int cur
    while lo < hi:
        mid = (lo + hi) // 2
        cur = arr[mid]
        if cur < val:
            lo = mid + 1
        elif cur > val:
            hi = mid
        else:
            return True
    return False


cdef extern from *:
    int __builtin_ctzll(unsigned long long) nogil


cdef inline Py_ssize_t _u64_heap_push(
    np.uint64_t[:] heap,
    Py_ssize_t size,
    unsigned long long key,
):
    cdef Py_ssize_t idx = size
    cdef Py_ssize_t parent
    while idx > 0:
        parent = (idx - 1) >> 1
        if heap[parent] <= key:
            break
        heap[idx] = heap[parent]
        idx = parent
    heap[idx] = key
    return size + 1


cdef inline unsigned long long _u64_heap_pop(
    np.uint64_t[:] heap,
    Py_ssize_t* size_ptr,
):
    cdef Py_ssize_t size = size_ptr[0]
    cdef unsigned long long out = heap[0]
    cdef unsigned long long tail
    cdef Py_ssize_t idx = 0
    cdef Py_ssize_t child
    cdef Py_ssize_t right
    size -= 1
    size_ptr[0] = size
    if size <= 0:
        return out
    tail = heap[size]
    while True:
        child = (idx << 1) + 1
        if child >= size:
            break
        right = child + 1
        if right < size and heap[right] < heap[child]:
            child = right
        if heap[child] >= tail:
            break
        heap[idx] = heap[child]
        idx = child
    heap[idx] = tail
    return out


cdef void _svb_decode_block(
    const unsigned char* data,
    unsigned long long data_len,
    unsigned int n,
    unsigned int* out,
):
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


cdef void _svb_decode_block_slice_i32(
    const unsigned char* data,
    unsigned long long data_len,
    unsigned int n,
    unsigned int start_idx,
    unsigned int end_idx,
    np.int32_t* out,
):
    cdef unsigned int groups = (n + 3) // 4
    cdef const unsigned char* controls = data
    cdef const unsigned char* p = data + groups
    cdef unsigned int o = 0
    cdef unsigned int w = 0
    cdef unsigned int g
    cdef unsigned int i
    cdef unsigned int start_group
    cdef unsigned int l
    cdef unsigned int v
    cdef unsigned char ctrl
    if start_idx >= end_idx or start_idx >= n:
        return
    if end_idx > n:
        end_idx = n
    start_group = start_idx >> 2
    if start_group > groups:
        start_group = groups
    for g in range(start_group):
        ctrl = controls[g]
        p += (
            ((ctrl & 3) + 1)
            + (((ctrl >> 2) & 3) + 1)
            + (((ctrl >> 4) & 3) + 1)
            + (((ctrl >> 6) & 3) + 1)
        )
    o = start_group << 2
    for g in range(start_group, groups):
        ctrl = controls[g]
        for i in range(4):
            if o >= end_idx:
                return
            if o >= n:
                break
            l = ((ctrl >> (2 * i)) & 3) + 1
            if o < start_idx:
                p += l
                o += 1
                continue
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
            if o >= start_idx:
                out[w] = <np.int32_t>v
                w += 1
            o += 1

def decode_svb_block(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned long long block_idx,
    unsigned int block_size,
    unsigned long long token_count,
):
    cdef const unsigned char[:] blob = data
    cdef unsigned long long n_blocks = offsets.shape[0] - 1
    cdef unsigned long long start
    cdef unsigned long long end
    cdef unsigned int n
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef unsigned int[:] out_view
    if block_idx >= n_blocks:
        return np.zeros(0, dtype=np.uint32)
    start = offsets[block_idx]
    end = offsets[block_idx + 1]
    n = block_size
    if (block_idx + 1) * block_size > token_count:
        n = <unsigned int>(token_count - block_idx * block_size)
    if n == 0:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(n, dtype=np.uint32)
    out_view = out
    _svb_decode_block(&blob[start], end - start, n, &out_view[0])
    return out


def decode_svb_range_i32(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    unsigned long long start_pos,
    unsigned long long end_pos,
):
    cdef const unsigned char[:] blob = data
    cdef unsigned long long n_blocks = offsets.shape[0] - 1
    cdef unsigned long long start_block
    cdef unsigned long long end_block
    cdef unsigned long long block_idx
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned int block_len
    cdef unsigned int local_start
    cdef unsigned int local_end
    cdef unsigned int take
    cdef unsigned long long cursor
    cdef np.ndarray[np.int32_t, ndim=1] out
    cdef np.int32_t[:] out_view

    if end_pos <= start_pos or start_pos >= token_count:
        return np.zeros(0, dtype=np.int32)
    if end_pos > token_count:
        end_pos = token_count
    if start_pos >= end_pos:
        return np.zeros(0, dtype=np.int32)
    if n_blocks == 0:
        return np.zeros(0, dtype=np.int32)

    out = np.empty(end_pos - start_pos, dtype=np.int32)
    out_view = out
    start_block = start_pos // block_size
    end_block = (end_pos - 1) // block_size
    cursor = 0
    for block_idx in range(start_block, end_block + 1):
        if block_idx >= n_blocks:
            break
        start_off = offsets[block_idx]
        end_off = offsets[block_idx + 1]
        block_len = block_size
        if (block_idx + 1) * block_size > token_count:
            block_len = <unsigned int>(token_count - block_idx * block_size)
        if block_len == 0:
            continue
        local_start = 0
        if block_idx == start_block:
            local_start = <unsigned int>(start_pos - block_idx * block_size)
        local_end = block_len
        if block_idx == end_block:
            local_end = <unsigned int>(end_pos - block_idx * block_size)
        take = local_end - local_start
        if take == 0:
            continue
        _svb_decode_block_slice_i32(
            &blob[start_off],
            end_off - start_off,
            block_len,
            local_start,
            local_end,
            &out_view[cursor],
        )
        cursor += take
    return out


def decode_svb_ranges_packed_i32(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    np.ndarray[np.int32_t, ndim=1] starts,
    np.ndarray[np.int32_t, ndim=1] ends,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t n_ranges = starts.shape[0]
    cdef Py_ssize_t i
    cdef long long total_len = 0
    cdef long long span_len
    cdef int start_pos
    cdef int end_pos
    cdef unsigned long long n_blocks = offsets.shape[0] - 1
    cdef unsigned long long block_idx
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned int block_len
    cdef unsigned long long cursor = 0
    cdef unsigned long long pos
    cdef unsigned long long block_start
    cdef unsigned int local_start
    cdef unsigned int take
    cdef unsigned long long cached_block = 0xffffffffffffffff
    cdef unsigned int cached_block_len = 0
    cdef np.ndarray[np.int32_t, ndim=1] out
    cdef np.int32_t[:] out_view
    cdef np.ndarray[np.int32_t, ndim=1] block_buf
    cdef np.int32_t[:] block_view

    if ends.shape[0] != n_ranges:
        raise ValueError("starts und ends muessen gleich lang sein")
    if n_ranges == 0 or n_blocks == 0:
        return np.zeros(0, dtype=np.int32)

    for i in range(n_ranges):
        start_pos = starts[i]
        end_pos = ends[i]
        if start_pos < 0:
            start_pos = 0
        if end_pos > token_count:
            end_pos = <int>token_count
        if end_pos <= start_pos:
            continue
        span_len = end_pos - start_pos
        total_len += span_len

    if total_len <= 0:
        return np.zeros(0, dtype=np.int32)

    out = np.empty(total_len, dtype=np.int32)
    out_view = out
    block_buf = np.empty(block_size, dtype=np.int32)
    block_view = block_buf

    for i in range(n_ranges):
        start_pos = starts[i]
        end_pos = ends[i]
        if start_pos < 0:
            start_pos = 0
        if end_pos > token_count:
            end_pos = <int>token_count
        if end_pos <= start_pos:
            continue
        pos = <unsigned long long>start_pos
        while pos < <unsigned long long>end_pos:
            block_idx = pos // block_size
            if block_idx >= n_blocks:
                break
            block_start = block_idx * block_size
            if cached_block != block_idx:
                start_off = offsets[block_idx]
                end_off = offsets[block_idx + 1]
                block_len = block_size
                if (block_idx + 1) * block_size > token_count:
                    block_len = <unsigned int>(token_count - block_idx * block_size)
                if block_len == 0:
                    cached_block = block_idx
                    cached_block_len = 0
                    break
                _svb_decode_block(
                    &blob[start_off],
                    end_off - start_off,
                    block_len,
                    <unsigned int*>&block_view[0],
                )
                cached_block = block_idx
                cached_block_len = block_len
            if cached_block_len == 0:
                break
            local_start = <unsigned int>(pos - block_start)
            take = cached_block_len - local_start
            if pos + take > <unsigned long long>end_pos:
                take = <unsigned int>(end_pos - pos)
            if take > 0:
                memcpy(
                    &out_view[cursor],
                    &block_view[local_start],
                    take * sizeof(np.int32_t),
                )
                cursor += take
                pos += take
            else:
                break
    return out


def kwic_rows_svb_compact_buffers(
    np.ndarray[np.uint32_t, ndim=1] positions,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    int ctx,
    np.ndarray[np.uint32_t, ndim=1] doc_bounds,
    np.ndarray[np.uint64_t, ndim=1] lex_offsets,
    object lex_blob,
    object text_cache=None,
    bint two_token_pivot_one=False,
    bint return_rows=False,
):
    cdef const unsigned char[:] blob = lex_blob
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t i
    cdef Py_ssize_t j
    cdef Py_ssize_t valid_n = 0
    cdef Py_ssize_t total_len = 0
    cdef Py_ssize_t fused_total_len = 0
    cdef Py_ssize_t merged_n = 0
    cdef Py_ssize_t merged_idx
    cdef Py_ssize_t merged_base
    cdef Py_ssize_t merged_len
    cdef Py_ssize_t rel_base
    cdef Py_ssize_t rel_pivot
    cdef Py_ssize_t next_nonempty_idx
    cdef Py_ssize_t rendered_len
    cdef Py_ssize_t tok_len
    cdef Py_ssize_t last_tok
    cdef Py_ssize_t doc_count = doc_bounds.shape[0]
    cdef Py_ssize_t doc_cursor = 0
    cdef unsigned int pos
    cdef unsigned int prev_pos = 0
    cdef unsigned int left_start
    cdef unsigned int right_end
    cdef unsigned int doc_start
    cdef unsigned int doc_end
    cdef unsigned int tid
    cdef int doc_id
    cdef Py_ssize_t win_doc_cursor = 0
    cdef bint use_list_cache = False
    cdef bint use_packed = n >= 2
    cdef bint use_slice_decode = False
    cdef bint all_nonempty
    cdef object local_cache
    cdef list local_cache_list = []
    cdef object merged_txt
    cdef object tok_txt
    cdef list merged_parts
    cdef list merged_texts
    cdef SvbRangeDecoder decoder
    cdef np.uint32_t[:] doc_bounds_view = doc_bounds
    cdef np.ndarray[np.int32_t, ndim=1] starts = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] ends = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] pivot_offsets = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] merged_starts = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] merged_ends = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] row_merged_idx = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.uint32_t, ndim=1] packed_positions = np.empty(n, dtype=np.uint32)
    cdef np.ndarray[np.int64_t, ndim=1] row_bases = np.empty(n, dtype=np.int64)
    cdef np.ndarray[np.int64_t, ndim=1] merged_bases = np.empty(n, dtype=np.int64)
    cdef np.ndarray[np.int32_t, ndim=1] packed_ids
    cdef np.int32_t[:] starts_view = starts
    cdef np.int32_t[:] ends_view = ends
    cdef np.int32_t[:] pivot_view = pivot_offsets
    cdef np.int32_t[:] merged_starts_view = merged_starts
    cdef np.int32_t[:] merged_ends_view = merged_ends
    cdef np.int32_t[:] row_merged_idx_view = row_merged_idx
    cdef np.uint32_t[:] packed_pos_view = packed_positions
    cdef np.int64_t[:] row_bases_view = row_bases
    cdef np.int64_t[:] merged_bases_view = merged_bases
    cdef np.int32_t[:] packed_ids_view
    cdef np.ndarray[np.int32_t, ndim=1] char_starts
    cdef np.ndarray[np.int32_t, ndim=1] char_ends
    cdef np.ndarray[np.int32_t, ndim=1] next_nonempty
    cdef np.ndarray[np.int32_t, ndim=1] prev_nonempty
    cdef np.ndarray[np.uint8_t, ndim=1] merged_all_nonempty
    cdef np.ndarray[np.int32_t, ndim=1] left_lo = np.empty((1,), dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] left_hi = np.empty((1,), dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] kw_lo = np.empty((1,), dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] kw_hi = np.empty((1,), dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] right_lo = np.empty((1,), dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] right_hi = np.empty((1,), dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] doc_ids = np.empty((1,), dtype=np.int32)
    cdef np.int32_t[:] char_starts_view
    cdef np.int32_t[:] char_ends_view
    cdef np.int32_t[:] next_nonempty_view
    cdef np.int32_t[:] prev_nonempty_view
    cdef np.uint8_t[:] merged_all_nonempty_view
    cdef np.int32_t[:] left_lo_view
    cdef np.int32_t[:] left_hi_view
    cdef np.int32_t[:] kw_lo_view
    cdef np.int32_t[:] kw_hi_view
    cdef np.int32_t[:] right_lo_view
    cdef np.int32_t[:] right_hi_view
    cdef np.int32_t[:] doc_ids_view
    cdef np.int32_t left_lo_i
    cdef np.int32_t left_hi_i
    cdef np.int32_t kw_lo_i
    cdef np.int32_t kw_hi_i
    cdef np.int32_t right_lo_i
    cdef np.int32_t right_hi_i
    cdef list rows
    cdef object left_txt
    cdef object kw_txt
    cdef object right_txt
    if n == 0:
        return None
    if text_cache is None:
        local_cache = {}
    else:
        local_cache = text_cache
    if isinstance(local_cache, list):
        use_list_cache = True
        local_cache_list = local_cache

    prev_pos = positions[0]
    for i in range(1, n):
        pos = positions[i]
        if pos < prev_pos:
            use_packed = False
            break
        prev_pos = pos
    if not use_packed:
        return None

    for i in range(n):
        pos = positions[i]
        if pos >= token_count:
            continue
        left_start = pos - ctx if pos > ctx else 0
        right_end = pos + ctx + 1
        if right_end > token_count:
            right_end = <unsigned int>token_count
        # Clamp the KWIC window to the containing document (D2). Positions are
        # ascending in this packed path, so walk a monotone cursor.
        if doc_count > 0:
            while (win_doc_cursor + 1 < doc_count
                   and doc_bounds_view[win_doc_cursor + 1] <= pos):
                win_doc_cursor += 1
            doc_start = doc_bounds_view[win_doc_cursor]
            if win_doc_cursor + 1 < doc_count:
                doc_end = doc_bounds_view[win_doc_cursor + 1]
            else:
                doc_end = <unsigned int>token_count
            if left_start < doc_start:
                left_start = doc_start
            if right_end > doc_end:
                right_end = doc_end
        starts_view[valid_n] = <np.int32_t>left_start
        ends_view[valid_n] = <np.int32_t>right_end
        pivot_view[valid_n] = <np.int32_t>(pos - left_start)
        packed_pos_view[valid_n] = pos
        total_len += right_end - left_start
        valid_n += 1
    if valid_n == 0 or total_len > 2_000_000:
        return None

    for i in range(valid_n):
        if merged_n == 0 or starts_view[i] > merged_ends_view[merged_n - 1]:
            merged_starts_view[merged_n] = starts_view[i]
            merged_ends_view[merged_n] = ends_view[i]
            merged_bases_view[merged_n] = fused_total_len
            row_merged_idx_view[i] = <np.int32_t>merged_n
            row_bases_view[i] = fused_total_len
            fused_total_len += ends_view[i] - starts_view[i]
            merged_n += 1
        else:
            row_merged_idx_view[i] = <np.int32_t>(merged_n - 1)
            row_bases_view[i] = (
                fused_total_len
                - (merged_ends_view[merged_n - 1] - merged_starts_view[merged_n - 1])
                + (starts_view[i] - merged_starts_view[merged_n - 1])
            )
            if ends_view[i] > merged_ends_view[merged_n - 1]:
                fused_total_len += ends_view[i] - merged_ends_view[merged_n - 1]
                merged_ends_view[merged_n - 1] = ends_view[i]

    if valid_n > 9000 or fused_total_len > 700000:
        return None

    decoder = SvbRangeDecoder()
    use_slice_decode = merged_n * 100 >= valid_n * 95
    if use_slice_decode:
        packed_ids = decoder.decode_ranges_packed_sorted_known_slice_i32(
            offsets,
            data,
            block_size,
            token_count,
            merged_starts[:merged_n],
            merged_ends[:merged_n],
            fused_total_len,
        )
    else:
        packed_ids = decoder.decode_ranges_packed_sorted_known_reuse_i32(
            offsets,
            data,
            block_size,
            token_count,
            merged_starts[:merged_n],
            merged_ends[:merged_n],
            fused_total_len,
        )
    packed_ids_view = packed_ids

    char_starts = np.empty(fused_total_len, dtype=np.int32)
    char_ends = np.empty(fused_total_len, dtype=np.int32)
    next_nonempty = np.empty(fused_total_len, dtype=np.int32)
    prev_nonempty = np.empty(fused_total_len, dtype=np.int32)
    merged_all_nonempty = np.empty(merged_n, dtype=np.uint8)
    char_starts_view = char_starts
    char_ends_view = char_ends
    next_nonempty_view = next_nonempty
    prev_nonempty_view = prev_nonempty
    merged_all_nonempty_view = merged_all_nonempty
    merged_texts = [""] * merged_n
    if return_rows:
        rows = [None] * valid_n
    else:
        left_lo = np.empty(valid_n, dtype=np.int32)
        left_hi = np.empty(valid_n, dtype=np.int32)
        kw_lo = np.empty(valid_n, dtype=np.int32)
        kw_hi = np.empty(valid_n, dtype=np.int32)
        right_lo = np.empty(valid_n, dtype=np.int32)
        right_hi = np.empty(valid_n, dtype=np.int32)
        doc_ids = np.empty(valid_n, dtype=np.int32)
        left_lo_view = left_lo
        left_hi_view = left_hi
        kw_lo_view = kw_lo
        kw_hi_view = kw_hi
        right_lo_view = right_lo
        right_hi_view = right_hi
        doc_ids_view = doc_ids

    for merged_idx in range(merged_n):
        merged_base = merged_bases_view[merged_idx]
        if merged_idx + 1 < merged_n:
            merged_len = merged_bases_view[merged_idx + 1] - merged_base
        else:
            merged_len = fused_total_len - merged_base
        merged_parts = [None] * merged_len
        rendered_len = 0
        last_tok = -1
        all_nonempty = True
        if use_list_cache:
            for j in range(merged_len):
                rel_base = merged_base + j
                tid = <unsigned int>packed_ids_view[rel_base]
                if tid != 0:
                    tok_txt = _id_to_str_cached_list(
                        tid, lex_offsets, blob, local_cache_list
                    )
                else:
                    tok_txt = ""
                if not tok_txt:
                    all_nonempty = False
                    break
                if j > 0:
                    rendered_len += 1
                char_starts_view[rel_base] = <np.int32_t>rendered_len
                tok_len = <Py_ssize_t>PyUnicode_GET_LENGTH(tok_txt)
                rendered_len += tok_len
                char_ends_view[rel_base] = <np.int32_t>rendered_len
                merged_parts[j] = tok_txt
            if not all_nonempty:
                rendered_len = 0
                merged_parts = []
                last_tok = -1
                for j in range(merged_len):
                    rel_base = merged_base + j
                    tid = <unsigned int>packed_ids_view[rel_base]
                    char_starts_view[rel_base] = -1
                    char_ends_view[rel_base] = -1
                    prev_nonempty_view[rel_base] = <np.int32_t>last_tok
                    if tid != 0:
                        tok_txt = _id_to_str_cached_list(
                            tid, lex_offsets, blob, local_cache_list
                        )
                    else:
                        tok_txt = ""
                    if tok_txt:
                        if rendered_len > 0:
                            rendered_len += 1
                        char_starts_view[rel_base] = <np.int32_t>rendered_len
                        rendered_len += <Py_ssize_t>PyUnicode_GET_LENGTH(tok_txt)
                        char_ends_view[rel_base] = <np.int32_t>rendered_len
                        prev_nonempty_view[rel_base] = <np.int32_t>rel_base
                        next_nonempty_view[rel_base] = <np.int32_t>rel_base
                        merged_parts.append(tok_txt)
                        last_tok = rel_base
        else:
            for j in range(merged_len):
                rel_base = merged_base + j
                tid = <unsigned int>packed_ids_view[rel_base]
                if tid != 0:
                    tok_txt = _id_to_str_cached(
                        tid, lex_offsets, blob, local_cache
                    )
                else:
                    tok_txt = ""
                if not tok_txt:
                    all_nonempty = False
                    break
                if j > 0:
                    rendered_len += 1
                char_starts_view[rel_base] = <np.int32_t>rendered_len
                tok_len = <Py_ssize_t>PyUnicode_GET_LENGTH(tok_txt)
                rendered_len += tok_len
                char_ends_view[rel_base] = <np.int32_t>rendered_len
                merged_parts[j] = tok_txt
            if not all_nonempty:
                rendered_len = 0
                merged_parts = []
                last_tok = -1
                for j in range(merged_len):
                    rel_base = merged_base + j
                    tid = <unsigned int>packed_ids_view[rel_base]
                    char_starts_view[rel_base] = -1
                    char_ends_view[rel_base] = -1
                    prev_nonempty_view[rel_base] = <np.int32_t>last_tok
                    if tid != 0:
                        tok_txt = _id_to_str_cached(
                            tid, lex_offsets, blob, local_cache
                        )
                    else:
                        tok_txt = ""
                    if tok_txt:
                        if rendered_len > 0:
                            rendered_len += 1
                        char_starts_view[rel_base] = <np.int32_t>rendered_len
                        rendered_len += <Py_ssize_t>PyUnicode_GET_LENGTH(tok_txt)
                        char_ends_view[rel_base] = <np.int32_t>rendered_len
                        prev_nonempty_view[rel_base] = <np.int32_t>rel_base
                        next_nonempty_view[rel_base] = <np.int32_t>rel_base
                        merged_parts.append(tok_txt)
                        last_tok = rel_base
        if not all_nonempty:
            next_nonempty_idx = -1
            for j in range(merged_len - 1, -1, -1):
                rel_base = merged_base + j
                if char_starts_view[rel_base] >= 0:
                    next_nonempty_idx = rel_base
                next_nonempty_view[rel_base] = <np.int32_t>next_nonempty_idx
            merged_all_nonempty_view[merged_idx] = 0
        else:
            merged_all_nonempty_view[merged_idx] = 1
        if not merged_parts:
            merged_txt = ""
        elif len(merged_parts) == 1:
            merged_txt = merged_parts[0]
        else:
            merged_txt = " ".join(merged_parts)
        merged_texts[merged_idx] = merged_txt

    for i in range(valid_n):
        pos = packed_pos_view[i]
        merged_idx = row_merged_idx_view[i]
        rel_pivot = row_bases_view[i] + pivot_view[i]
        left_lo_i = -1
        left_hi_i = -1
        kw_lo_i = -1
        kw_hi_i = -1
        right_lo_i = -1
        right_hi_i = -1
        if merged_all_nonempty_view[merged_idx] != 0:
            rel_base = row_bases_view[i]
            merged_len = ends_view[i] - starts_view[i]
            rendered_len = rel_base + merged_len
            if two_token_pivot_one:
                if rel_base < rel_pivot + 1:
                    left_lo_i = char_starts_view[rel_base]
                    left_hi_i = char_ends_view[rel_pivot]
                if rel_pivot + 1 < rendered_len:
                    kw_lo_i = char_starts_view[rel_pivot + 1]
                    kw_hi_i = char_ends_view[rel_pivot + 1]
                if rel_pivot + 2 < rendered_len:
                    right_lo_i = char_starts_view[rel_pivot + 2]
                    right_hi_i = char_ends_view[rendered_len - 1]
            else:
                if rel_base < rel_pivot:
                    left_lo_i = char_starts_view[rel_base]
                    left_hi_i = char_ends_view[rel_pivot - 1]
                kw_lo_i = char_starts_view[rel_pivot]
                kw_hi_i = char_ends_view[rel_pivot]
                if rel_pivot + 1 < rendered_len:
                    right_lo_i = char_starts_view[rel_pivot + 1]
                    right_hi_i = char_ends_view[rendered_len - 1]
        elif two_token_pivot_one:
            _slice_text_offsets(
                char_starts_view,
                char_ends_view,
                next_nonempty_view,
                prev_nonempty_view,
                row_bases_view[i],
                rel_pivot + 1,
                left_lo,
                left_hi,
                0,
            )
            left_lo_i = left_lo[0]
            left_hi_i = left_hi[0]
            if rel_pivot + 1 < row_bases_view[i] + (ends_view[i] - starts_view[i]):
                if char_starts_view[rel_pivot + 1] >= 0:
                    kw_lo_i = char_starts_view[rel_pivot + 1]
                    kw_hi_i = char_ends_view[rel_pivot + 1]
            _slice_text_offsets(
                char_starts_view,
                char_ends_view,
                next_nonempty_view,
                prev_nonempty_view,
                rel_pivot + 2,
                row_bases_view[i] + (ends_view[i] - starts_view[i]),
                right_lo,
                right_hi,
                0,
            )
            right_lo_i = right_lo[0]
            right_hi_i = right_hi[0]
        else:
            _slice_text_offsets(
                char_starts_view,
                char_ends_view,
                next_nonempty_view,
                prev_nonempty_view,
                row_bases_view[i],
                rel_pivot,
                left_lo,
                left_hi,
                0,
            )
            left_lo_i = left_lo[0]
            left_hi_i = left_hi[0]
            if char_starts_view[rel_pivot] >= 0:
                kw_lo_i = char_starts_view[rel_pivot]
                kw_hi_i = char_ends_view[rel_pivot]
            _slice_text_offsets(
                char_starts_view,
                char_ends_view,
                next_nonempty_view,
                prev_nonempty_view,
                rel_pivot + 1,
                row_bases_view[i] + (ends_view[i] - starts_view[i]),
                right_lo,
                right_hi,
                0,
            )
            right_lo_i = right_lo[0]
            right_hi_i = right_hi[0]
        if doc_count > 0:
            while doc_cursor + 1 < doc_count and doc_bounds_view[doc_cursor + 1] <= pos:
                doc_cursor += 1
            doc_id = doc_cursor
        else:
            doc_id = -1
        if return_rows:
            if 0 <= merged_idx < merged_n:
                merged_txt = merged_texts[merged_idx]
            else:
                merged_txt = ""
            left_txt = merged_txt[left_lo_i:left_hi_i] if left_lo_i >= 0 else ""
            kw_txt = merged_txt[kw_lo_i:kw_hi_i] if kw_lo_i >= 0 else ""
            right_txt = merged_txt[right_lo_i:right_hi_i] if right_lo_i >= 0 else ""
            if two_token_pivot_one:
                rows[i] = (
                    left_txt,
                    kw_txt,
                    right_txt,
                    int(packed_pos_view[i]) + 1,
                    int(doc_id),
                )
            else:
                rows[i] = (
                    left_txt,
                    kw_txt,
                    right_txt,
                    int(packed_pos_view[i]),
                    int(doc_id),
                )
        else:
            left_lo_view[i] = left_lo_i
            left_hi_view[i] = left_hi_i
            kw_lo_view[i] = kw_lo_i
            kw_hi_view[i] = kw_hi_i
            right_lo_view[i] = right_lo_i
            right_hi_view[i] = right_hi_i
            doc_ids_view[i] = <np.int32_t>doc_id

    if return_rows:
        return rows

    if valid_n == n:
        return {
            "merged_texts": merged_texts,
            "row_merged_idx": row_merged_idx,
            "left_lo": left_lo,
            "left_hi": left_hi,
            "kw_lo": kw_lo,
            "kw_hi": kw_hi,
            "right_lo": right_lo,
            "right_hi": right_hi,
            "positions": packed_positions,
            "doc_ids": doc_ids,
            "two_token_pivot_one_prepared": bool(two_token_pivot_one),
        }
    return {
        "merged_texts": merged_texts,
        "row_merged_idx": row_merged_idx[:valid_n],
        "left_lo": left_lo[:valid_n],
        "left_hi": left_hi[:valid_n],
        "kw_lo": kw_lo[:valid_n],
        "kw_hi": kw_hi[:valid_n],
        "right_lo": right_lo[:valid_n],
        "right_hi": right_hi[:valid_n],
        "positions": packed_positions[:valid_n],
        "doc_ids": doc_ids[:valid_n],
        "two_token_pivot_one_prepared": bool(two_token_pivot_one),
    }


def kwic_compact_buffer_rows(object buffers, bint two_token_pivot_one=False):
    cdef list merged_texts = buffers["merged_texts"] if buffers is not None else []
    cdef np.ndarray[np.uint32_t, ndim=1] positions = buffers["positions"]
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t i
    cdef Py_ssize_t merged_idx
    cdef Py_ssize_t merged_texts_len = len(merged_texts)
    cdef object merged_txt
    cdef object left_txt
    cdef object kw_txt
    cdef object right_txt
    cdef object next_kw
    cdef Py_ssize_t split_at
    cdef bint prepared_two_token = False
    cdef np.ndarray[np.int32_t, ndim=1] row_merged_idx = buffers["row_merged_idx"]
    cdef np.ndarray[np.int32_t, ndim=1] left_lo = buffers["left_lo"]
    cdef np.ndarray[np.int32_t, ndim=1] left_hi = buffers["left_hi"]
    cdef np.ndarray[np.int32_t, ndim=1] kw_lo = buffers["kw_lo"]
    cdef np.ndarray[np.int32_t, ndim=1] kw_hi = buffers["kw_hi"]
    cdef np.ndarray[np.int32_t, ndim=1] right_lo = buffers["right_lo"]
    cdef np.ndarray[np.int32_t, ndim=1] right_hi = buffers["right_hi"]
    cdef np.ndarray[np.int32_t, ndim=1] doc_ids = buffers["doc_ids"]
    cdef np.uint32_t[:] positions_view = positions
    cdef np.int32_t[:] row_merged_idx_view = row_merged_idx
    cdef np.int32_t[:] left_lo_view = left_lo
    cdef np.int32_t[:] left_hi_view = left_hi
    cdef np.int32_t[:] kw_lo_view = kw_lo
    cdef np.int32_t[:] kw_hi_view = kw_hi
    cdef np.int32_t[:] right_lo_view = right_lo
    cdef np.int32_t[:] right_hi_view = right_hi
    cdef np.int32_t[:] doc_ids_view = doc_ids
    cdef list rows

    if n == 0:
        return []
    if buffers is not None:
        prepared_two_token = bool(buffers.get("two_token_pivot_one_prepared", False))

    rows = [None] * n
    for i in range(n):
        merged_idx = row_merged_idx_view[i]
        if 0 <= merged_idx < merged_texts_len:
            merged_txt = merged_texts[merged_idx]
        else:
            merged_txt = ""
        left_txt = merged_txt[left_lo_view[i]:left_hi_view[i]] if left_lo_view[i] >= 0 else ""
        kw_txt = merged_txt[kw_lo_view[i]:kw_hi_view[i]] if kw_lo_view[i] >= 0 else ""
        right_txt = merged_txt[right_lo_view[i]:right_hi_view[i]] if right_lo_view[i] >= 0 else ""
        if two_token_pivot_one and not prepared_two_token:
            if right_txt:
                split_at = right_txt.find(" ")
                if split_at < 0:
                    next_kw = right_txt
                    right_txt = ""
                else:
                    next_kw = right_txt[:split_at]
                    right_txt = right_txt[split_at + 1 :]
                if kw_txt:
                    left_txt = left_txt + " " + kw_txt if left_txt else kw_txt
                kw_txt = next_kw
        if two_token_pivot_one:
            rows[i] = (
                left_txt,
                kw_txt,
                right_txt,
                int(positions_view[i]) + 1,
                int(doc_ids_view[i]),
            )
        else:
            rows[i] = (
                left_txt,
                kw_txt,
                right_txt,
                int(positions_view[i]),
                int(doc_ids_view[i]),
            )
    return rows


def kwic_rows_svb(
    np.ndarray[np.uint32_t, ndim=1] positions,
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int block_size,
    unsigned long long token_count,
    int ctx,
    np.ndarray[np.uint32_t, ndim=1] doc_bounds,
    object doc_paths,
    np.ndarray[np.uint64_t, ndim=1] lex_offsets,
    object lex_blob,
    object text_cache=None,
    bint include_file=True,
    bint compact=False,
    object debug_stats=None,
    bint force_scalar=False,
):
    cdef const unsigned char[:] blob = lex_blob
    cdef const unsigned char[:] svb = data
    cdef np.uint32_t[:] doc_bounds_view = doc_bounds
    cdef Py_ssize_t n = positions.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int pos
    cdef unsigned int prev_pos = 0
    cdef unsigned int left_start
    cdef unsigned int right_end
    cdef unsigned int doc_start
    cdef unsigned int doc_end
    cdef unsigned int tid
    cdef bint has_prev = False
    cdef Py_ssize_t doc_idx
    cdef Py_ssize_t win_doc_idx
    cdef Py_ssize_t win_doc_cursor = 0
    cdef Py_ssize_t doc_count = doc_bounds.shape[0]
    cdef Py_ssize_t doc_cursor = 0
    cdef Py_ssize_t doc_paths_len
    cdef Py_ssize_t last_doc_idx = -2
    cdef Py_ssize_t valid_n = 0
    cdef Py_ssize_t total_len = 0
    cdef Py_ssize_t fused_total_len = 0
    cdef Py_ssize_t packed_cursor = 0
    cdef Py_ssize_t merged_n = 0
    cdef list rows = []
    cdef list left_parts
    cdef list right_parts
    cdef object left_txt
    cdef object right_txt
    cdef object kw_txt
    cdef object file_txt
    cdef object last_file_txt = ""
    cdef object local_cache
    cdef list local_cache_list = []
    cdef Py_ssize_t j
    cdef unsigned long long block_idx
    cdef unsigned long long block_start
    cdef unsigned int block_len = 0
    cdef unsigned long long start_off
    cdef unsigned long long end_off
    cdef unsigned int local
    cdef np.ndarray[np.uint32_t, ndim=1] buf = np.empty(block_size, dtype=np.uint32)
    cdef unsigned int[:] buf_view = buf
    cdef unsigned long long cached_block = 0xffffffffffffffff
    cdef bint use_packed = n >= 32 and not force_scalar
    cdef np.ndarray[np.int32_t, ndim=1] starts = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] ends = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] pivot_offsets = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] merged_starts = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] merged_ends = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] row_merged_idx = np.empty(n, dtype=np.int32)
    cdef np.ndarray[np.uint32_t, ndim=1] packed_positions = np.empty(n, dtype=np.uint32)
    cdef np.ndarray[np.int64_t, ndim=1] row_bases = np.empty(n, dtype=np.int64)
    cdef np.ndarray[np.int64_t, ndim=1] merged_bases = np.empty(n, dtype=np.int64)
    cdef np.ndarray[np.int32_t, ndim=1] packed_ids
    cdef np.int32_t[:] starts_view = starts
    cdef np.int32_t[:] ends_view = ends
    cdef np.int32_t[:] pivot_view = pivot_offsets
    cdef np.int32_t[:] merged_starts_view = merged_starts
    cdef np.int32_t[:] merged_ends_view = merged_ends
    cdef np.int32_t[:] row_merged_idx_view = row_merged_idx
    cdef np.uint32_t[:] packed_pos_view = packed_positions
    cdef np.int64_t[:] row_bases_view = row_bases
    cdef np.int64_t[:] merged_bases_view = merged_bases
    cdef np.int32_t[:] packed_ids_view
    cdef bint use_packed_texts = False
    cdef bint use_list_cache = False
    cdef list row_kw_texts
    cdef Py_ssize_t merged_idx
    cdef Py_ssize_t row_start_idx
    cdef Py_ssize_t row_end_idx
    cdef Py_ssize_t merged_len
    cdef Py_ssize_t row_count
    cdef Py_ssize_t merged_base
    cdef Py_ssize_t rel_base
    cdef Py_ssize_t rel_pivot
    cdef Py_ssize_t right_limit
    cdef Py_ssize_t first_tok
    cdef Py_ssize_t last_tok
    cdef Py_ssize_t rendered_len
    cdef Py_ssize_t rendered_pos
    cdef Py_ssize_t next_nonempty_idx
    cdef np.ndarray[np.int32_t, ndim=1] char_starts
    cdef np.ndarray[np.int32_t, ndim=1] char_ends
    cdef np.ndarray[np.int32_t, ndim=1] next_nonempty
    cdef np.ndarray[np.int32_t, ndim=1] prev_nonempty
    cdef np.int32_t[:] char_starts_view
    cdef np.int32_t[:] char_ends_view
    cdef np.int32_t[:] next_nonempty_view
    cdef np.int32_t[:] prev_nonempty_view
    cdef list merged_parts
    cdef list merged_texts
    cdef object merged_txt
    cdef object tok_txt
    cdef SvbRangeDecoder decoder
    cdef bint need_doc_id = compact and not include_file
    cdef bint compact_no_file = compact and not include_file
    cdef bint use_slice_decode = False
    cdef Py_ssize_t row_idx_out = 0
    cdef Py_ssize_t next_row_idx = 0
    cdef double t_begin = 0.0
    cdef double t_after_windows = 0.0
    cdef double t_after_decode = 0.0
    cdef double t_after_texts = 0.0
    cdef double t_end = 0.0
    if debug_stats is not None:
        t_begin = _time.perf_counter()
    if text_cache is None:
        local_cache = {}
    else:
        local_cache = text_cache
    if isinstance(local_cache, list):
        use_list_cache = True
        local_cache_list = local_cache
    doc_paths_len = len(doc_paths) if doc_paths is not None else 0

    if use_packed:
        prev_pos = positions[0]
        for i in range(1, n):
            pos = positions[i]
            if pos < prev_pos:
                use_packed = False
                break
            prev_pos = pos
        if use_packed:
            for i in range(n):
                pos = positions[i]
                if pos >= token_count:
                    continue
                left_start = pos - ctx if pos > ctx else 0
                right_end = pos + ctx + 1
                if right_end > token_count:
                    right_end = <unsigned int>token_count
                # Clamp the KWIC window to the containing document (D2).
                # Positions are ascending in the packed path, so walk a
                # monotone cursor over doc_bounds.
                if doc_count > 0:
                    while (win_doc_cursor + 1 < doc_count
                           and doc_bounds_view[win_doc_cursor + 1] <= pos):
                        win_doc_cursor += 1
                    doc_start = doc_bounds_view[win_doc_cursor]
                    if win_doc_cursor + 1 < doc_count:
                        doc_end = doc_bounds_view[win_doc_cursor + 1]
                    else:
                        doc_end = <unsigned int>token_count
                    if left_start < doc_start:
                        left_start = doc_start
                    if right_end > doc_end:
                        right_end = doc_end
                starts_view[valid_n] = <np.int32_t>left_start
                ends_view[valid_n] = <np.int32_t>right_end
                pivot_view[valid_n] = <np.int32_t>(pos - left_start)
                packed_pos_view[valid_n] = pos
                total_len += right_end - left_start
                valid_n += 1
            if valid_n == 0:
                return []
            if debug_stats is not None:
                t_after_windows = _time.perf_counter()
            if total_len <= 2_000_000:
                for i in range(valid_n):
                    if merged_n == 0 or starts_view[i] > merged_ends_view[merged_n - 1]:
                        merged_starts_view[merged_n] = starts_view[i]
                        merged_ends_view[merged_n] = ends_view[i]
                        merged_bases_view[merged_n] = fused_total_len
                        row_merged_idx_view[i] = <np.int32_t>merged_n
                        row_bases_view[i] = fused_total_len
                        fused_total_len += ends_view[i] - starts_view[i]
                        merged_n += 1
                    else:
                        row_merged_idx_view[i] = <np.int32_t>(merged_n - 1)
                        row_bases_view[i] = (
                            fused_total_len
                            - (merged_ends_view[merged_n - 1] - merged_starts_view[merged_n - 1])
                            + (starts_view[i] - merged_starts_view[merged_n - 1])
                        )
                        if ends_view[i] > merged_ends_view[merged_n - 1]:
                            fused_total_len += ends_view[i] - merged_ends_view[merged_n - 1]
                            merged_ends_view[merged_n - 1] = ends_view[i]
                decoder = SvbRangeDecoder()
                use_slice_decode = merged_n * 100 >= valid_n * 95
                if use_slice_decode:
                    packed_ids = decoder.decode_ranges_packed_sorted_known_slice_i32(
                        offsets,
                        data,
                        block_size,
                        token_count,
                        merged_starts[:merged_n],
                        merged_ends[:merged_n],
                        fused_total_len,
                    )
                else:
                    packed_ids = decoder.decode_ranges_packed_sorted_known_reuse_i32(
                        offsets,
                        data,
                        block_size,
                        token_count,
                        merged_starts[:merged_n],
                        merged_ends[:merged_n],
                        fused_total_len,
                    )
                packed_ids_view = packed_ids
                if debug_stats is not None:
                    t_after_decode = _time.perf_counter()
                use_packed_texts = valid_n <= 9000 and fused_total_len <= 700000
                if use_packed_texts:
                    row_kw_texts = [""] * valid_n
                    merged_texts = [""] * merged_n
                    char_starts = np.empty(fused_total_len, dtype=np.int32)
                    char_ends = np.empty(fused_total_len, dtype=np.int32)
                    next_nonempty = np.empty(fused_total_len, dtype=np.int32)
                    prev_nonempty = np.empty(fused_total_len, dtype=np.int32)
                    char_starts_view = char_starts
                    char_ends_view = char_ends
                    next_nonempty_view = next_nonempty
                    prev_nonempty_view = prev_nonempty
                    for merged_idx in range(merged_n):
                        merged_base = merged_bases_view[merged_idx]
                        if merged_idx + 1 < merged_n:
                            merged_len = merged_bases_view[merged_idx + 1] - merged_base
                        else:
                            merged_len = fused_total_len - merged_base
                        merged_parts = []
                        rendered_len = 0
                        last_tok = -1
                        for j in range(merged_len):
                            rel_base = merged_base + j
                            char_starts_view[rel_base] = -1
                            char_ends_view[rel_base] = -1
                            prev_nonempty_view[rel_base] = <np.int32_t>last_tok
                            tid = <unsigned int>packed_ids_view[rel_base]
                            if tid != 0:
                                if use_list_cache:
                                    tok_txt = _id_to_str_cached_list(
                                        tid, lex_offsets, blob, local_cache_list
                                    )
                                else:
                                    tok_txt = _id_to_str_cached(
                                        tid, lex_offsets, blob, local_cache
                                    )
                            else:
                                tok_txt = ""
                            while (
                                next_row_idx < valid_n
                                and row_bases_view[next_row_idx] + pivot_view[next_row_idx] == rel_base
                            ):
                                row_kw_texts[next_row_idx] = tok_txt
                                next_row_idx += 1
                            if tok_txt:
                                if rendered_len > 0:
                                    rendered_len += 1
                                char_starts_view[rel_base] = <np.int32_t>rendered_len
                                rendered_len += <Py_ssize_t>PyUnicode_GET_LENGTH(tok_txt)
                                char_ends_view[rel_base] = <np.int32_t>rendered_len
                                prev_nonempty_view[rel_base] = <np.int32_t>rel_base
                                merged_parts.append(tok_txt)
                                last_tok = rel_base
                        next_nonempty_idx = -1
                        for j in range(merged_len - 1, -1, -1):
                            rel_base = merged_base + j
                            if char_starts_view[rel_base] >= 0:
                                next_nonempty_idx = rel_base
                            next_nonempty_view[rel_base] = <np.int32_t>next_nonempty_idx
                        if not merged_parts:
                            merged_txt = ""
                        elif len(merged_parts) == 1:
                            merged_txt = merged_parts[0]
                        else:
                            merged_txt = " ".join(merged_parts)
                        merged_texts[merged_idx] = merged_txt
                if debug_stats is not None:
                    t_after_texts = _time.perf_counter()
                if compact_no_file:
                    rows = [None] * valid_n
                for i in range(valid_n):
                    pos = packed_pos_view[i]
                    packed_cursor = row_bases_view[i]
                    if use_packed_texts:
                        merged_idx = row_merged_idx_view[i]
                        merged_txt = merged_texts[merged_idx]
                        rel_pivot = packed_cursor + pivot_view[i]
                        left_txt = _slice_text_range(
                            merged_txt,
                            char_starts_view,
                            char_ends_view,
                            next_nonempty_view,
                            prev_nonempty_view,
                            packed_cursor,
                            rel_pivot,
                        )
                        kw_txt = row_kw_texts[i]
                        right_txt = _slice_text_range(
                            merged_txt,
                            char_starts_view,
                            char_ends_view,
                            next_nonempty_view,
                            prev_nonempty_view,
                            rel_pivot + 1,
                            packed_cursor + (ends_view[i] - starts_view[i]),
                        )
                    else:
                        if use_list_cache:
                            left_txt = _join_ids_i32_cached_list(
                                packed_ids_view,
                                packed_cursor,
                                packed_cursor + pivot_view[i],
                                lex_offsets,
                                blob,
                                local_cache_list,
                            )
                        else:
                            left_txt = _join_ids_i32_cached(
                                packed_ids_view,
                                packed_cursor,
                                packed_cursor + pivot_view[i],
                                lex_offsets,
                                blob,
                                local_cache,
                            )
                        tid = <unsigned int>packed_ids_view[packed_cursor + pivot_view[i]]
                        if use_list_cache:
                            kw_txt = _id_to_str_cached_list(
                                tid, lex_offsets, blob, local_cache_list
                            )
                            right_txt = _join_ids_i32_cached_list(
                                packed_ids_view,
                                packed_cursor + pivot_view[i] + 1,
                                packed_cursor + (ends_view[i] - starts_view[i]),
                                lex_offsets,
                                blob,
                                local_cache_list,
                            )
                        else:
                            kw_txt = _id_to_str_cached(tid, lex_offsets, blob, local_cache)
                            right_txt = _join_ids_i32_cached(
                                packed_ids_view,
                                packed_cursor + pivot_view[i] + 1,
                                packed_cursor + (ends_view[i] - starts_view[i]),
                                lex_offsets,
                                blob,
                                local_cache,
                            )

                    file_txt = ""
                    if (include_file or need_doc_id) and doc_count > 0:
                        while doc_cursor + 1 < doc_count and doc_bounds_view[doc_cursor + 1] <= pos:
                            doc_cursor += 1
                        if include_file and doc_paths_len > 0:
                            doc_idx = doc_cursor
                            if doc_idx == last_doc_idx:
                                file_txt = last_file_txt
                            elif doc_idx >= 0 and doc_idx < doc_paths_len:
                                file_txt = doc_paths[doc_idx]
                                last_doc_idx = doc_idx
                                last_file_txt = file_txt

                    if compact_no_file:
                        rows[i] = (left_txt, kw_txt, right_txt, int(pos), int(doc_cursor))
                    elif include_file:
                        rows.append({
                            "left": left_txt,
                            "kw": kw_txt,
                            "right": right_txt,
                            "pos": int(pos),
                            "file": file_txt,
                        })
                    else:
                        rows.append({
                            "left": left_txt,
                            "kw": kw_txt,
                            "right": right_txt,
                            "pos": int(pos),
                        })
                if debug_stats is not None:
                    t_end = _time.perf_counter()
                    debug_stats["mode"] = "packed"
                    debug_stats["use_packed_texts"] = bool(use_packed_texts)
                    debug_stats["use_slice_decode"] = bool(use_slice_decode)
                    debug_stats["valid_n"] = int(valid_n)
                    debug_stats["merged_n"] = int(merged_n)
                    debug_stats["total_len"] = int(total_len)
                    debug_stats["fused_total_len"] = int(fused_total_len)
                    debug_stats["window_ms"] = (t_after_windows - t_begin) * 1000.0
                    debug_stats["decode_ms"] = (t_after_decode - t_after_windows) * 1000.0
                    debug_stats["text_ms"] = (t_after_texts - t_after_decode) * 1000.0
                    debug_stats["row_ms"] = (t_end - t_after_texts) * 1000.0
                    debug_stats["total_ms"] = (t_end - t_begin) * 1000.0
                return rows

    if compact_no_file:
        rows = [None] * n
    for i in range(n):
        pos = positions[i]
        if pos >= token_count:
            continue
        left_start = pos - ctx if pos > ctx else 0
        right_end = pos + ctx + 1
        if right_end > token_count:
            right_end = <unsigned int>token_count
        # Clamp the KWIC window to the document containing `pos` so context
        # does not bleed across document boundaries (D2). Positions in the
        # scalar path may be unordered, so resolve the doc via binary search.
        if doc_count > 0:
            win_doc_idx = _doc_index(doc_bounds, pos)
            if win_doc_idx < 0:
                win_doc_idx = 0
            doc_start = doc_bounds_view[win_doc_idx]
            if win_doc_idx + 1 < doc_count:
                doc_end = doc_bounds_view[win_doc_idx + 1]
            else:
                doc_end = <unsigned int>token_count
            if left_start < doc_start:
                left_start = doc_start
            if right_end > doc_end:
                right_end = doc_end

        left_parts = []
        for j in range(left_start, pos):
            block_idx = j // block_size
            if block_idx != cached_block:
                start_off = offsets[block_idx]
                end_off = offsets[block_idx + 1]
                block_len = block_size
                if (block_idx + 1) * block_size > token_count:
                    block_len = <unsigned int>(token_count - block_idx * block_size)
                _svb_decode_block(&svb[start_off], end_off - start_off, block_len, &buf_view[0])
                cached_block = block_idx
            block_start = block_idx * block_size
            local = j - block_start
            tid = buf_view[local]
            if tid != 0:
                left_parts.append(_id_to_str_cached(tid, lex_offsets, blob, local_cache))
        left_txt = " ".join(left_parts)

        block_idx = pos // block_size
        if block_idx != cached_block:
            start_off = offsets[block_idx]
            end_off = offsets[block_idx + 1]
            block_len = block_size
            if (block_idx + 1) * block_size > token_count:
                block_len = <unsigned int>(token_count - block_idx * block_size)
            _svb_decode_block(&svb[start_off], end_off - start_off, block_len, &buf_view[0])
            cached_block = block_idx
        block_start = block_idx * block_size
        local = pos - block_start
        tid = buf_view[local]
        kw_txt = _id_to_str_cached(tid, lex_offsets, blob, local_cache)

        right_parts = []
        for j in range(pos + 1, right_end):
            block_idx = j // block_size
            if block_idx != cached_block:
                start_off = offsets[block_idx]
                end_off = offsets[block_idx + 1]
                block_len = block_size
                if (block_idx + 1) * block_size > token_count:
                    block_len = <unsigned int>(token_count - block_idx * block_size)
                _svb_decode_block(&svb[start_off], end_off - start_off, block_len, &buf_view[0])
                cached_block = block_idx
            block_start = block_idx * block_size
            local = j - block_start
            tid = buf_view[local]
            if tid != 0:
                right_parts.append(_id_to_str_cached(tid, lex_offsets, blob, local_cache))
        right_txt = " ".join(right_parts)

        file_txt = ""
        if (include_file or need_doc_id) and doc_count > 0:
            if has_prev and pos < prev_pos:
                doc_idx = _doc_index(doc_bounds, pos)
                doc_cursor = doc_idx if doc_idx >= 0 else 0
            else:
                while doc_cursor + 1 < doc_count and doc_bounds_view[doc_cursor + 1] <= pos:
                    doc_cursor += 1
                doc_idx = doc_cursor
            if include_file and doc_paths_len > 0:
                if doc_idx == last_doc_idx:
                    file_txt = last_file_txt
                elif doc_idx >= 0 and doc_idx < doc_paths_len:
                    file_txt = doc_paths[doc_idx]
                    last_doc_idx = doc_idx
                    last_file_txt = file_txt
            prev_pos = pos
            has_prev = True

        if compact_no_file:
            rows[row_idx_out] = (left_txt, kw_txt, right_txt, int(pos), int(doc_idx))
            row_idx_out += 1
        elif include_file:
            rows.append({
                "left": left_txt,
                "kw": kw_txt,
                "right": right_txt,
                "pos": int(pos),
                "file": file_txt,
            })
        else:
            rows.append({
                "left": left_txt,
                "kw": kw_txt,
                "right": right_txt,
                "pos": int(pos),
            })
    if compact_no_file and row_idx_out != n:
        if debug_stats is not None:
            t_end = _time.perf_counter()
            debug_stats["mode"] = "scalar"
            debug_stats["valid_n"] = int(row_idx_out)
            debug_stats["total_ms"] = (t_end - t_begin) * 1000.0
        return rows[:row_idx_out]
    if debug_stats is not None:
        t_end = _time.perf_counter()
        debug_stats["mode"] = "scalar"
        debug_stats["valid_n"] = int(n)
        debug_stats["total_ms"] = (t_end - t_begin) * 1000.0
    return rows


cdef np.ndarray _decode_roar_positions_inner(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    unsigned int term_id,
):
    cdef unsigned long long start
    cdef unsigned long long end
    cdef const unsigned char* p
    cdef const unsigned char* e
    cdef const unsigned char* cur
    cdef unsigned int n_cont
    cdef unsigned int i
    cdef unsigned int high16
    cdef unsigned int card
    cdef unsigned int type_id
    cdef unsigned long long total = 0
    cdef unsigned long long idx = 0
    cdef unsigned int w
    cdef unsigned long long x
    cdef unsigned int t
    cdef unsigned int low16
    cdef unsigned long long base
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef unsigned int[:] out_view

    if term_id + 1 >= offsets.shape[0]:
        return np.zeros(0, dtype=np.uint32)
    start = offsets[term_id]
    end = offsets[term_id + 1]
    if end <= start:
        return np.zeros(0, dtype=np.uint32)
    p = &blob[start]
    e = &blob[end]
    if e - p < 4:
        return np.zeros(0, dtype=np.uint32)
    n_cont = _read_u32(p)
    p += 4

    cur = p
    for i in range(n_cont):
        if cur + 8 > e:
            break
        high16 = _read_u16(cur)
        cur += 2
        type_id = cur[0]
        cur += 2
        card = _read_u32(cur)
        cur += 4
        total += card
        if type_id == 0:
            cur += card * 2
        else:
            cur += 8192
        cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]

    if total == 0:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(total, dtype=np.uint32)
    out_view = out
    idx = 0
    cur = p
    for i in range(n_cont):
        if cur + 8 > e:
            break
        high16 = _read_u16(cur)
        cur += 2
        type_id = cur[0]
        cur += 2
        card = _read_u32(cur)
        cur += 4
        base = (<unsigned long long>high16) << 16
        if type_id == 0:
            for w in range(card):
                low16 = _read_u16(cur)
                cur += 2
                out_view[idx] = <unsigned int>(base | low16)
                idx += 1
        else:
            for w in range(1024):
                x = (<const unsigned long long*>cur)[w]
                while x:
                    t = __builtin_ctzll(x)
                    out_view[idx] = <unsigned int>(base | ((w << 6) + t))
                    idx += 1
                    x &= x - 1
            cur += 8192
        cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
    if idx != total:
        out = out[:idx]
    return out


def decode_roar_positions(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int term_id,
):
    cdef const unsigned char[:] blob = data
    return _decode_roar_positions_inner(offsets, blob, term_id)


def roaring_postings_to_bitset(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
    unsigned long long n_tokens,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t n = ids.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef unsigned long long start
    cdef unsigned long long end
    cdef const unsigned char* p
    cdef const unsigned char* e
    cdef const unsigned char* cur
    cdef unsigned int n_cont
    cdef unsigned int j
    cdef unsigned int high16
    cdef unsigned int type_id
    cdef unsigned int card
    cdef unsigned int w
    cdef unsigned int low16
    cdef unsigned int pos
    cdef unsigned long long x
    cdef unsigned int t
    cdef unsigned long long base
    cdef unsigned long long word_idx
    cdef Py_ssize_t n_words = <Py_ssize_t>((n_tokens + 63) >> 6)
    cdef Py_ssize_t n_bytes = <Py_ssize_t>((n_tokens + 7) >> 3)
    cdef np.ndarray[np.uint64_t, ndim=1] out_words = np.zeros(n_words, dtype=np.uint64)
    cdef np.uint64_t[:] out_words_view = out_words
    cdef Py_ssize_t word_base

    for i in range(n):
        tid = ids[i]
        if tid == 0 or tid >= offsets.shape[0]:
            continue
        start = offsets[tid]
        end = offsets[tid + 1] if tid + 1 < offsets.shape[0] else <unsigned long long>blob.shape[0]
        if end <= start:
            continue
        p = &blob[start]
        e = &blob[end]
        if e - p < 4:
            continue
        n_cont = _read_u32(p)
        p += 4
        cur = p
        for j in range(n_cont):
            if cur + 8 > e:
                break
            high16 = _read_u16(cur)
            cur += 2
            type_id = cur[0]
            cur += 2
            card = _read_u32(cur)
            cur += 4
            base = (<unsigned long long>high16) << 16
            if type_id == 0:
                if card != 0:
                    for w in range(card):
                        low16 = _read_u16(cur)
                        cur += 2
                        pos = <unsigned int>(base | low16)
                        if pos < n_tokens:
                            out_words_view[pos >> 6] |= <np.uint64_t>1 << (pos & 63)
            else:
                word_base = <Py_ssize_t>(base >> 6)
                if base + 65536 <= n_tokens and word_base + 1024 <= n_words:
                    for w in range(1024):
                        out_words_view[word_base + w] |= (<const unsigned long long*>cur)[w]
                else:
                    for w in range(1024):
                        x = (<const unsigned long long*>cur)[w]
                        while x:
                            t = __builtin_ctzll(x)
                            pos = <unsigned int>(base | ((w << 6) + t))
                            if pos < n_tokens:
                                out_words_view[pos >> 6] |= <np.uint64_t>1 << (pos & 63)
                            x &= x - 1
                cur += 8192
            cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
    return out_words.view(np.uint8)[:n_bytes]


def bitset_positions_limit(
    np.ndarray[np.uint8_t, ndim=1] bitset,
    unsigned long long n_tokens,
    Py_ssize_t limit,
):
    cdef Py_ssize_t n_bytes = bitset.shape[0]
    cdef np.uint8_t[:] bitset_view = bitset
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t byte_idx
    cdef Py_ssize_t out_n = 0
    cdef unsigned long long x
    cdef unsigned int pos
    cdef unsigned int t

    if limit <= 0 or n_bytes == 0 or n_tokens == 0:
        return np.zeros(0, dtype=np.uint32)
    if <unsigned long long>limit > n_tokens:
        limit = <Py_ssize_t>n_tokens
    out = np.empty(limit, dtype=np.uint32)
    out_view = out
    for byte_idx in range(n_bytes):
        x = <unsigned long long>bitset_view[byte_idx]
        while x:
            t = <unsigned int>__builtin_ctzll(x)
            pos = <unsigned int>((byte_idx << 3) + t)
            if pos < n_tokens:
                out_view[out_n] = pos
                out_n += 1
                if out_n >= limit:
                    return out
            x &= x - 1
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def union_roar_positions(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t n = ids.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int tid
    cdef np.ndarray[np.uint32_t, ndim=1] cur
    cdef list parts = []
    cdef list next_parts
    cdef Py_ssize_t m
    for i in range(n):
        tid = ids[i]
        if tid == 0:
            continue
        cur = _decode_roar_positions_inner(offsets, blob, tid)
        if cur.size == 0:
            continue
        parts.append(cur)
    if not parts:
        return np.zeros(0, dtype=np.uint32)
    if len(parts) == 1:
        return parts[0]
    parts.sort(key=lambda arr: (<np.ndarray>arr).size)
    while len(parts) > 1:
        next_parts = []
        m = len(parts)
        for i in range(0, m, 2):
            if i + 1 >= m:
                next_parts.append(parts[i])
            else:
                next_parts.append(_union_sorted(parts[i], parts[i + 1]))
        if len(next_parts) > 1:
            next_parts.sort(key=lambda arr: (<np.ndarray>arr).size)
        parts = next_parts
    return parts[0]


def dependency_heads(
    np.ndarray[np.uint32_t, ndim=1] rel_positions,
    np.ndarray[np.int64_t, ndim=1] head_ids,
    np.ndarray[np.uint32_t, ndim=1] head_allow=None,
    np.ndarray[np.uint32_t, ndim=1] dep_allow=None,
):
    cdef Py_ssize_t n = rel_positions.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.uint32)
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(n, dtype=np.uint32)
    cdef Py_ssize_t o = 0
    cdef np.uint32_t[:] rel_view = rel_positions
    cdef np.int64_t[:] head_view = head_ids
    cdef np.uint32_t[:] head_allow_view
    cdef np.uint32_t[:] dep_allow_view
    cdef Py_ssize_t head_len = 0
    cdef Py_ssize_t dep_len = 0
    cdef unsigned int dep
    cdef long long head
    cdef Py_ssize_t i

    if head_allow is not None:
        head_allow_view = head_allow
        head_len = head_allow_view.shape[0]
    if dep_allow is not None:
        dep_allow_view = dep_allow
        dep_len = dep_allow_view.shape[0]

    for i in range(n):
        dep = rel_view[i]
        if dep_len and not _bin_contains(dep_allow_view, dep_len, dep):
            continue
        head = head_view[dep]
        if head < 0:
            continue
        if head_len and not _bin_contains(head_allow_view, head_len, <unsigned int>head):
            continue
        out[o] = <unsigned int>head
        o += 1

    if o == 0:
        return np.zeros(0, dtype=np.uint32)
    return np.unique(out[:o])


def doc_search_scores(
    list positions_list,
    np.ndarray[np.uint32_t, ndim=1] doc_bounds,
    unsigned long long token_count,
    object metric,
    np.ndarray[np.uint8_t, ndim=1] meta_mask=None,
):
    cdef Py_ssize_t doc_count
    cdef Py_ssize_t n_terms = len(positions_list)
    cdef Py_ssize_t i
    cdef Py_ssize_t t
    cdef Py_ssize_t hit_count = 0
    cdef Py_ssize_t doc_id
    cdef unsigned int pos
    cdef unsigned int start
    cdef unsigned int end
    cdef double total_docs
    cdef double avg_len = 0.0
    cdef double doc_len
    cdef double score
    cdef double idf
    cdef double tf
    cdef double freq
    cdef double denom
    cdef double k1 = 1.5
    cdef double b = 0.75
    cdef np.ndarray[np.int64_t, ndim=1] doc_lengths
    cdef np.ndarray[np.uint8_t, ndim=1] doc_mask
    cdef np.ndarray[np.int64_t, ndim=1] first_pos
    cdef np.ndarray[np.uint64_t, ndim=2] counts_matrix
    cdef np.uint64_t[:, :] counts_view2d
    cdef list df_list = []
    cdef np.ndarray[np.uint64_t, ndim=1] counts
    cdef np.uint64_t[:] counts_view
    cdef np.uint32_t[:] pos_view
    cdef np.ndarray[np.float64_t, ndim=1] idf_vals
    cdef np.ndarray[np.int64_t, ndim=1] out_doc_ids
    cdef np.ndarray[np.float64_t, ndim=1] out_scores
    cdef np.ndarray[np.int64_t, ndim=1] out_first_pos
    cdef np.uint32_t[:] bounds_view = doc_bounds

    if doc_bounds.shape[0] == 0:
        doc_count = 1
        doc_lengths = np.empty(1, dtype=np.int64)
        doc_lengths[0] = <np.int64_t>token_count
    else:
        doc_count = doc_bounds.shape[0]
        doc_lengths = np.empty(doc_count, dtype=np.int64)
        for i in range(doc_count):
            start = bounds_view[i]
            if i + 1 < doc_count:
                end = bounds_view[i + 1]
            else:
                end = <unsigned int>token_count
            doc_lengths[i] = <np.int64_t>(end - start)

    if meta_mask is not None and meta_mask.shape[0] != doc_count:
        raise ValueError("meta_mask passt nicht zu doc_bounds")

    doc_mask = np.ones(doc_count, dtype=np.uint8)
    first_pos = np.empty(doc_count, dtype=np.int64)
    for i in range(doc_count):
        first_pos[i] = <np.int64_t>token_count

    counts_matrix = np.zeros((n_terms, doc_count), dtype=np.uint64)
    counts_view2d = counts_matrix

    for t in range(n_terms):
        counts_view = counts_view2d[t]
        pos_view = positions_list[t]
        if doc_bounds.shape[0] == 0:
            counts_view[0] = <np.uint64_t>pos_view.shape[0]
            if pos_view.shape[0] > 0:
                pos = pos_view[0]
                if pos < first_pos[0]:
                    first_pos[0] = pos
        else:
            for i in range(pos_view.shape[0]):
                pos = pos_view[i]
                doc_id = _doc_index(doc_bounds, pos)
                if doc_id < 0:
                    doc_id = 0
                elif doc_id >= doc_count:
                    doc_id = doc_count - 1
                counts_view[doc_id] += 1
                if pos < first_pos[doc_id]:
                    first_pos[doc_id] = pos
        for i in range(doc_count):
            if doc_mask[i] != 0 and counts_view[i] == 0:
                doc_mask[i] = 0
        df = 0
        for i in range(doc_count):
            if counts_view[i] != 0:
                df += 1
        df_list.append(df)

    if meta_mask is not None:
        for i in range(doc_count):
            if doc_mask[i] != 0 and meta_mask[i] == 0:
                doc_mask[i] = 0

    for i in range(doc_count):
        if doc_mask[i] != 0:
            hit_count += 1

    out_doc_ids = np.empty(hit_count, dtype=np.int64)
    out_scores = np.empty(hit_count, dtype=np.float64)
    out_first_pos = np.empty(hit_count, dtype=np.int64)

    total_docs = <double>doc_count
    if doc_count > 0:
        avg_len = float(doc_lengths.mean())

    if metric == "bm25":
        idf_vals = np.empty(n_terms, dtype=np.float64)
        for t in range(n_terms):
            idf_vals[t] = log((total_docs - df_list[t] + 0.5) / (df_list[t] + 0.5) + 1.0)
    else:
        if metric == "tf-idf":
            if hit_count > 0:
                idf = log(total_docs / (1.0 + <double>hit_count))
            else:
                idf = 0.0
        else:
            idf = 1.0

    hit_count = 0
    for i in range(doc_count):
        if doc_mask[i] == 0:
            continue
        doc_len = <double>doc_lengths[i]
        if metric == "bm25":
            score = 0.0
            for t in range(n_terms):
                tf = <double>counts_view2d[t, i]
                if tf == 0:
                    continue
                denom = tf + k1 * (1.0 - b + b * (doc_len / avg_len if avg_len else 0.0))
                if denom != 0.0:
                    score += idf_vals[t] * (tf * (k1 + 1.0)) / denom
        else:
            freq = 0.0
            for t in range(n_terms):
                freq += <double>counts_view2d[t, i]
            if metric == "tf-idf":
                tf = (freq / doc_len) if doc_len else 0.0
                score = tf * idf
            else:
                score = freq
        out_doc_ids[hit_count] = i
        if first_pos[i] >= token_count:
            out_first_pos[hit_count] = 0
        else:
            out_first_pos[hit_count] = first_pos[i]
        out_scores[hit_count] = score
        hit_count += 1

    return out_doc_ids, out_scores, out_first_pos


def roar_advance_to(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int term_id,
    unsigned int target,
):
    cdef const unsigned char[:] blob = data
    return _roar_advance_to_inner(offsets, blob, term_id, target)


cdef inline int _roar_advance_to_inner(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    const unsigned char[:] blob,
    unsigned int term_id,
    unsigned int target,
):
    cdef unsigned long long start
    cdef unsigned long long end
    cdef const unsigned char* p
    cdef const unsigned char* e
    cdef const unsigned char* cur
    cdef unsigned int n_cont
    cdef unsigned int i
    cdef unsigned int high16
    cdef unsigned int card
    cdef unsigned int type_id
    cdef unsigned int target_hi = target >> 16
    cdef unsigned int target_lo = target & 0xFFFF
    cdef unsigned long long base
    cdef unsigned int low16
    cdef unsigned int lo
    cdef unsigned int hi
    cdef unsigned int mid
    cdef unsigned int val
    cdef unsigned long long x
    cdef unsigned int w
    cdef unsigned int t

    if term_id + 1 >= offsets.shape[0]:
        return -1
    start = offsets[term_id]
    end = offsets[term_id + 1]
    if end <= start:
        return -1
    p = &blob[start]
    e = &blob[end]
    if e - p < 4:
        return -1
    n_cont = _read_u32(p)
    p += 4
    cur = p
    for i in range(n_cont):
        if cur + 8 > e:
            break
        high16 = _read_u16(cur)
        cur += 2
        type_id = cur[0]
        cur += 2
        card = _read_u32(cur)
        cur += 4
        if high16 < target_hi:
            if type_id == 0:
                cur += card * 2
            else:
                cur += 8192
            cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
            continue
        base = (<unsigned long long>high16) << 16
        if high16 > target_hi:
            if card == 0:
                cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
                continue
            if type_id == 0:
                low16 = _read_u16(cur)
                return <int>(base | low16)
            for w in range(1024):
                x = (<const unsigned long long*>cur)[w]
                if x:
                    t = __builtin_ctzll(x)
                    return <int>(base | ((w << 6) + t))
            cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
            continue
        # high16 == target_hi
        if card == 0:
            cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
            continue
        if type_id == 0:
            lo = 0
            hi = card
            while lo < hi:
                mid = (lo + hi) >> 1
                val = _read_u16(cur + mid * 2)
                if val < target_lo:
                    lo = mid + 1
                else:
                    hi = mid
            if lo < card:
                low16 = _read_u16(cur + lo * 2)
                return <int>(base | low16)
        else:
            w = target_lo >> 6
            t = target_lo & 63
            x = (<const unsigned long long*>cur)[w] & (~((1ULL << t) - 1))
            if x:
                val = __builtin_ctzll(x)
                return <int>(base | ((w << 6) + val))
            for w in range(w + 1, 1024):
                x = (<const unsigned long long*>cur)[w]
                if x:
                    val = __builtin_ctzll(x)
                    return <int>(base | ((w << 6) + val))
        if type_id == 0:
            cur += card * 2
        else:
            cur += 8192
        cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
    return -1


def union_roar_positions_limited(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    np.ndarray[np.uint32_t, ndim=1] ids,
    Py_ssize_t limit,
):
    cdef const unsigned char[:] blob = data
    cdef Py_ssize_t n = ids.shape[0]
    cdef Py_ssize_t i
    cdef Py_ssize_t heap_size = 0
    cdef np.ndarray[np.uint64_t, ndim=1] heap
    cdef np.uint64_t[:] heap_view
    cdef np.ndarray[np.uint32_t, ndim=1] out
    cdef np.uint32_t[:] out_view
    cdef Py_ssize_t out_n = 0
    cdef unsigned int tid
    cdef int pos_i
    cdef unsigned int pos
    cdef unsigned int next_pos
    cdef unsigned long long key
    cdef unsigned int last_pos = 0
    cdef bint have_last = False

    if limit <= 0 or n == 0:
        return np.zeros(0, dtype=np.uint32)
    heap = np.empty(n, dtype=np.uint64)
    heap_view = heap
    for i in range(n):
        tid = ids[i]
        if tid == 0:
            continue
        pos_i = _roar_advance_to_inner(offsets, blob, tid, 0)
        if pos_i >= 0:
            key = (<unsigned long long><unsigned int>pos_i << 32) | <unsigned long long>tid
            heap_size = _u64_heap_push(heap_view, heap_size, key)
    if heap_size == 0:
        return np.zeros(0, dtype=np.uint32)
    out = np.empty(limit, dtype=np.uint32)
    out_view = out
    while heap_size > 0 and out_n < limit:
        key = _u64_heap_pop(heap_view, &heap_size)
        pos = <unsigned int>(key >> 32)
        tid = <unsigned int>(key & 0xFFFFFFFF)
        if not have_last or pos != last_pos:
            out_view[out_n] = pos
            out_n += 1
            last_pos = pos
            have_last = True
            if out_n >= limit:
                break
        pos_i = _roar_advance_to_inner(offsets, blob, tid, pos + 1)
        if pos_i >= 0:
            next_pos = <unsigned int>pos_i
            key = (<unsigned long long>next_pos << 32) | <unsigned long long>tid
            heap_size = _u64_heap_push(heap_view, heap_size, key)
    if out_n == 0:
        return np.zeros(0, dtype=np.uint32)
    return out[:out_n]


def roar_contains(
    np.ndarray[np.uint64_t, ndim=1] offsets,
    object data,
    unsigned int term_id,
    unsigned int target,
):
    cdef const unsigned char[:] blob = data
    cdef unsigned long long start
    cdef unsigned long long end
    cdef const unsigned char* p
    cdef const unsigned char* e
    cdef const unsigned char* cur
    cdef unsigned int n_cont
    cdef unsigned int i
    cdef unsigned int high16
    cdef unsigned int card
    cdef unsigned int type_id
    cdef unsigned int target_hi = target >> 16
    cdef unsigned int target_lo = target & 0xFFFF
    cdef unsigned int lo
    cdef unsigned int hi
    cdef unsigned int mid
    cdef unsigned int val
    cdef unsigned long long x
    cdef unsigned int w

    if term_id + 1 >= offsets.shape[0]:
        return False
    start = offsets[term_id]
    end = offsets[term_id + 1]
    if end <= start:
        return False
    p = &blob[start]
    e = &blob[end]
    if e - p < 4:
        return False
    n_cont = _read_u32(p)
    p += 4
    cur = p
    for i in range(n_cont):
        if cur + 8 > e:
            break
        high16 = _read_u16(cur)
        cur += 2
        type_id = cur[0]
        cur += 2
        card = _read_u32(cur)
        cur += 4
        if high16 < target_hi:
            if type_id == 0:
                cur += card * 2
            else:
                cur += 8192
            cur = &blob[_align8(<unsigned long long>(cur - &blob[0]))]
            continue
        if high16 > target_hi:
            return False
        if card == 0:
            return False
        if type_id == 0:
            lo = 0
            hi = card
            while lo < hi:
                mid = (lo + hi) >> 1
                val = _read_u16(cur + mid * 2)
                if val < target_lo:
                    lo = mid + 1
                else:
                    hi = mid
            if lo < card:
                val = _read_u16(cur + lo * 2)
                return val == target_lo
            return False
        w = target_lo >> 6
        x = (<const unsigned long long*>cur)[w]
        return (x >> (target_lo & 63)) & 1
    return False


def docset_mask_from_ids(
    np.ndarray[np.uint32_t, ndim=1] doc_ids,
    unsigned int doc_count,
):
    cdef np.ndarray[np.uint8_t, ndim=1] out = np.zeros(doc_count, dtype=np.uint8)
    cdef Py_ssize_t n = doc_ids.shape[0]
    cdef Py_ssize_t i
    cdef unsigned int d
    for i in range(n):
        d = doc_ids[i]
        if d < doc_count:
            out[d] = 1
    return out.astype(np.bool_)


def near_positions(
    np.ndarray[np.uint32_t, ndim=1] left,
    np.ndarray[np.uint32_t, ndim=1] right,
    int distance,
):
    cdef Py_ssize_t n_left = left.shape[0]
    cdef Py_ssize_t n_right = right.shape[0]
    if n_left == 0 or n_right == 0:
        return np.zeros(0, dtype=np.uint32)
    cdef np.ndarray[np.uint8_t, ndim=1] left_hit = np.zeros(n_left, dtype=np.uint8)
    cdef np.ndarray[np.uint8_t, ndim=1] right_hit = np.zeros(n_right, dtype=np.uint8)
    cdef Py_ssize_t i
    cdef Py_ssize_t j
    cdef Py_ssize_t r_start = 0
    cdef Py_ssize_t r_end = 0
    cdef Py_ssize_t l_start = 0
    cdef Py_ssize_t l_end = 0
    cdef unsigned int pos
    cdef Py_ssize_t count

    for i in range(n_left):
        pos = left[i]
        while r_start < n_right and right[r_start] + distance < pos:
            r_start += 1
        while r_end < n_right and right[r_end] <= pos + distance:
            r_end += 1
        count = r_end - r_start
        if count > 0:
            if not (count == 1 and right[r_start] == pos):
                left_hit[i] = 1

    for j in range(n_right):
        pos = right[j]
        while l_start < n_left and left[l_start] + distance < pos:
            l_start += 1
        while l_end < n_left and left[l_end] <= pos + distance:
            l_end += 1
        count = l_end - l_start
        if count > 0:
            if not (count == 1 and left[l_start] == pos):
                right_hit[j] = 1

    cdef Py_ssize_t total = 0
    for i in range(n_left):
        if left_hit[i]:
            total += 1
    for j in range(n_right):
        if right_hit[j]:
            total += 1
    if total == 0:
        return np.zeros(0, dtype=np.uint32)
    cdef np.ndarray[np.uint32_t, ndim=1] out = np.empty(total, dtype=np.uint32)
    cdef Py_ssize_t k = 0
    for i in range(n_left):
        if left_hit[i]:
            out[k] = left[i]
            k += 1
    for j in range(n_right):
        if right_hit[j]:
            out[k] = right[j]
            k += 1
    return np.unique(out).astype(np.uint32)
