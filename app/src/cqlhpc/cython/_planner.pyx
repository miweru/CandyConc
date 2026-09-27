# cython: boundscheck=False, wraparound=False, cdivision=True, nonecheck=False

from __future__ import annotations

import numpy as np
cimport numpy as cnp


def dp_order(
    int anchor_len,
    cnp.ndarray[cnp.int32_t, ndim=1] clause_len,
    cnp.ndarray[cnp.double_t, ndim=1] clause_sel,
    cnp.ndarray[cnp.uint8_t, ndim=1] has_dense,
    double bitset_build_weight,
    double bitset_filter_weight,
):
    cdef Py_ssize_t n = clause_len.shape[0]
    if n <= 0:
        return np.empty((0,), dtype=np.int32), np.empty((0,), dtype=np.uint8), np.empty((0,), dtype=np.float64), 0.0
    cdef Py_ssize_t total = 1 << n
    cdef double INF = 1e100
    cdef cnp.ndarray[cnp.double_t, ndim=1] dp_cost = np.full((total,), INF, dtype=np.float64)
    cdef cnp.ndarray[cnp.double_t, ndim=1] dp_size = np.zeros((total,), dtype=np.float64)
    cdef cnp.ndarray[cnp.int32_t, ndim=1] back_idx = np.full((total,), -1, dtype=np.int32)
    cdef cnp.ndarray[cnp.uint8_t, ndim=1] back_method = np.zeros((total,), dtype=np.uint8)
    cdef cnp.ndarray[cnp.double_t, ndim=1] back_step_cost = np.zeros((total,), dtype=np.float64)

    dp_cost[0] = 0.0
    dp_size[0] = anchor_len

    cdef Py_ssize_t mask
    cdef Py_ssize_t i
    cdef Py_ssize_t new_mask
    cdef double cur_size
    cdef double merge_cost
    cdef double bit_cost
    cdef double step_cost
    cdef double new_cost
    cdef double new_size
    cdef double sel
    cdef int method
    for mask in range(total):
        if dp_cost[mask] >= INF:
            continue
        cur_size = dp_size[mask]
        for i in range(n):
            if mask & (1 << i):
                continue
            merge_cost = cur_size + clause_len[i]
            if has_dense[i]:
                bit_cost = cur_size * bitset_filter_weight
            else:
                bit_cost = clause_len[i] * bitset_build_weight + cur_size * bitset_filter_weight
            if bit_cost <= merge_cost:
                method = 1
                step_cost = bit_cost
            else:
                method = 0
                step_cost = merge_cost
            new_mask = mask | (1 << i)
            new_cost = dp_cost[mask] + step_cost
            sel = clause_sel[i]
            new_size = cur_size * sel
            if new_size < 0.0:
                new_size = 0.0
            if new_cost < dp_cost[new_mask]:
                dp_cost[new_mask] = new_cost
                dp_size[new_mask] = new_size
                back_idx[new_mask] = <cnp.int32_t> i
                back_method[new_mask] = <cnp.uint8_t> method
                back_step_cost[new_mask] = step_cost

    if dp_cost[total - 1] >= INF:
        return np.empty((0,), dtype=np.int32), np.empty((0,), dtype=np.uint8), np.empty((0,), dtype=np.float64), -1.0

    cdef cnp.ndarray[cnp.int32_t, ndim=1] order = np.empty((n,), dtype=np.int32)
    cdef cnp.ndarray[cnp.uint8_t, ndim=1] methods = np.empty((n,), dtype=np.uint8)
    cdef cnp.ndarray[cnp.double_t, ndim=1] step_costs = np.empty((n,), dtype=np.float64)
    mask = total - 1
    cdef Py_ssize_t pos
    for pos in range(n - 1, -1, -1):
        i = back_idx[mask]
        if i < 0:
            break
        order[pos] = <cnp.int32_t> i
        methods[pos] = back_method[mask]
        step_costs[pos] = back_step_cost[mask]
        mask &= ~(1 << i)

    return order, methods, step_costs, float(dp_cost[total - 1])
