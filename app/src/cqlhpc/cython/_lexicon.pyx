# cython: boundscheck=False, wraparound=False, cdivision=True, nonecheck=False

from __future__ import annotations

import numpy as np
cimport numpy as cnp
from libc.string cimport memcmp
from cpython.unicode cimport PyUnicode_AsUTF8AndSize


cdef inline unsigned long long _fmix64(unsigned long long x):
    x ^= x >> 33
    x = (x * 0xff51afd7ed558ccd) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    x = (x * 0xc4ceb9fe1a85ec53) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    return x & 0xFFFFFFFFFFFFFFFF


cdef inline unsigned long long _hash64_ptr(const unsigned char* s, Py_ssize_t n):
    cdef unsigned long long h = 14695981039346656037
    cdef Py_ssize_t i
    for i in range(n):
        h ^= s[i]
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return _fmix64(h)


cdef inline Py_ssize_t _lower_bound_u64(const unsigned long long* arr, Py_ssize_t lo, Py_ssize_t hi, unsigned long long target):
    cdef Py_ssize_t mid
    while lo < hi:
        mid = (lo + hi) >> 1
        if arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def lookup_id(
    cnp.ndarray[cnp.uint64_t, ndim=1] hash_buckets,
    cnp.ndarray[cnp.uint64_t, ndim=1] hashes,
    cnp.ndarray[cnp.uint32_t, ndim=1] lexids,
    cnp.ndarray[cnp.uint64_t, ndim=1] offsets,
    const unsigned char[:] strings_view,
    int bucket_bits,
    object value,
):
    cdef Py_ssize_t n
    cdef const unsigned char* ptr
    if value is None:
        return 0
    ptr = <const unsigned char*> PyUnicode_AsUTF8AndSize(value, &n)
    if ptr == NULL or n <= 0:
        return 0
    return _lookup_id_ptr(hash_buckets, hashes, lexids, offsets, strings_view, bucket_bits, ptr, n)


cdef inline int _lookup_id_ptr(
    cnp.ndarray[cnp.uint64_t, ndim=1] hash_buckets,
    cnp.ndarray[cnp.uint64_t, ndim=1] hashes,
    cnp.ndarray[cnp.uint32_t, ndim=1] lexids,
    cnp.ndarray[cnp.uint64_t, ndim=1] offsets,
    const unsigned char[:] strings_view,
    int bucket_bits,
    const unsigned char* ptr,
    Py_ssize_t n,
):
    cdef unsigned long long h = _hash64_ptr(ptr, n)
    cdef Py_ssize_t bucket
    cdef Py_ssize_t start
    cdef Py_ssize_t end
    cdef Py_ssize_t pos
    cdef Py_ssize_t off_start
    cdef Py_ssize_t off_end
    cdef Py_ssize_t offsets_len = offsets.shape[0]
    cdef const unsigned long long* hash_ptr = <const unsigned long long*> hashes.data
    cdef const unsigned int* lex_ptr = <const unsigned int*> lexids.data
    cdef const unsigned char* view_ptr
    if strings_view.shape[0] > 0:
        view_ptr = &strings_view[0]
    else:
        view_ptr = <const unsigned char*> NULL
    cdef unsigned int lexid

    if bucket_bits <= 0:
        bucket = 0
    else:
        bucket = h >> (64 - bucket_bits)
    if bucket + 1 >= hash_buckets.shape[0]:
        return 0
    start = <Py_ssize_t> hash_buckets[bucket]
    end = <Py_ssize_t> hash_buckets[bucket + 1]
    if end <= start:
        return 0
    pos = _lower_bound_u64(hash_ptr, start, end, h)
    while pos < end and hash_ptr[pos] == h:
        if pos < 0:
            break
        lexid = lex_ptr[pos]
        if lexid < offsets_len:
            off_start = <Py_ssize_t> offsets[lexid]
            if lexid + 1 < offsets_len:
                off_end = <Py_ssize_t> offsets[lexid + 1]
            else:
                off_end = <Py_ssize_t> strings_view.shape[0]
        else:
            off_start = 0
            off_end = 0
        if off_end - off_start == n and off_end <= strings_view.shape[0]:
            if view_ptr != NULL and memcmp(<const void*> (view_ptr + off_start), <const void*> ptr, n) == 0:
                return <int> lexid
        pos += 1
    return 0


def lookup_ids(
    cnp.ndarray[cnp.uint64_t, ndim=1] hash_buckets,
    cnp.ndarray[cnp.uint64_t, ndim=1] hashes,
    cnp.ndarray[cnp.uint32_t, ndim=1] lexids,
    cnp.ndarray[cnp.uint64_t, ndim=1] offsets,
    const unsigned char[:] strings_view,
    int bucket_bits,
    list values,
):
    cdef Py_ssize_t n = len(values)
    cdef cnp.ndarray[cnp.int32_t, ndim=1] out = np.empty((n,), dtype=np.int32)
    cdef Py_ssize_t i
    cdef Py_ssize_t size
    cdef const unsigned char* ptr
    for i in range(n):
        ptr = <const unsigned char*> PyUnicode_AsUTF8AndSize(values[i], &size)
        if ptr == NULL or size <= 0:
            out[i] = 0
        else:
            out[i] = _lookup_id_ptr(hash_buckets, hashes, lexids, offsets, strings_view, bucket_bits, ptr, size)
    return out
