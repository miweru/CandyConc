"""
Coverage-Sweep Algorithm for Collocation Engine.

The core algorithm that replaces "per-hit window scanning" with
efficient linear merging to produce disjoint coverage segments.

Key properties:
- No sorting required (inputs already ordered)
- Handles overlapping windows correctly
- Supports both pair and set semantics
- Boundary clipping before segment generation
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional
import numpy as np

from .boundaries import BoundarySet
from .counting_kernels import coverage_sweep_arrays_fast


@dataclass(slots=True)
class Match:
    """
    Represents a single query match.
    
    start: first token position of match
    end: one past last token (half-open)
    anchor: position used for window calculation (usually start)
    doc_id: document index for filtering/grouping
    """
    start: int
    end: int
    anchor: int
    doc_id: int = 0
    
    @property
    def span(self) -> int:
        """Length of match in tokens."""
        return self.end - self.start


@dataclass(slots=True)  
class CoverageSegment:
    """
    A disjoint segment with constant coverage.
    
    start: first position (inclusive)
    end: one past last position (half-open)
    weight: coverage count (pair semantics) or 1 (set semantics)
    """
    start: int
    end: int
    weight: int
    
    @property
    def length(self) -> int:
        return self.end - self.start


def coverage_sweep_arrays(
    anchors: np.ndarray,
    spans: np.ndarray,
    window_left: int,
    window_right: int,
    boundaries: Optional[BoundarySet] = None,
    within_sentence: bool = False,
    pair_semantics: bool = False,
    total_tokens: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if total_tokens is None:
        raise RuntimeError("total_tokens fehlt für coverage_sweep_arrays")
    sentence_bounds = None
    use_bounds = False
    if boundaries is not None:
        sentence_bounds = boundaries.clip_bounds_array(within_sentence)
        if sentence_bounds is not None and sentence_bounds.size > 0:
            use_bounds = True
    if within_sentence and not use_bounds:
        raise RuntimeError("Sentence Boundaries fehlen für within_sentence")
    return coverage_sweep_arrays_fast(
        anchors,
        spans,
        window_left,
        window_right,
        sentence_bounds,
        use_bounds,
        pair_semantics,
        int(total_tokens),
    )


def coverage_sweep(
    matches: List[Match],
    window_left: int,
    window_right: int,
    boundaries: Optional[BoundarySet] = None,
    within_sentence: bool = False,
    pair_semantics: bool = False,
) -> List[CoverageSegment]:
    """
    Generate disjoint coverage segments from sorted matches.
    
    This is THE core algorithm from the whitepaper (Section 4).
    
    Args:
        matches: Matches sorted by anchor position
        window_left: Left context size
        window_right: Right context size
        boundaries: Boundary set for clipping
        within_sentence: If True, clip windows to sentence bounds
        pair_semantics: If True, weight = overlap count; else weight = 1
        
    Returns:
        List of disjoint CoverageSegments covering all context positions
    """
    if not matches:
        return []

    anchors = np.fromiter((m.anchor for m in matches), dtype=np.int64, count=len(matches))
    spans = np.fromiter((m.span for m in matches), dtype=np.int64, count=len(matches))
    starts, ends, weights = coverage_sweep_arrays(
        anchors,
        spans,
        window_left,
        window_right,
        boundaries=boundaries,
        within_sentence=within_sentence,
        pair_semantics=pair_semantics,
        total_tokens=int(anchors.max() + spans.max() + window_right + 1),
    )
    return [CoverageSegment(int(starts[i]), int(ends[i]), int(weights[i])) for i in range(len(starts))]


def total_context_mass(segments: List[CoverageSegment]) -> int:
    """
    Calculate total context mass u (for cost model).
    
    This is sum of (length * weight) for pair semantics,
    or sum of lengths for set semantics.
    """
    return sum(s.length * s.weight for s in segments)


def total_context_mass_arrays(
    starts: np.ndarray, ends: np.ndarray, weights: np.ndarray
) -> int:
    if starts.size == 0:
        return 0
    return int(np.sum((ends.astype(np.int64) - starts.astype(np.int64)) * weights.astype(np.int64)))


def context_token_count(segments: List[CoverageSegment]) -> int:
    """
    Calculate unique context positions covered.
    """
    return sum(s.length for s in segments)
