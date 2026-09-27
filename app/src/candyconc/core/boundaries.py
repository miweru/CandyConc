"""
Boundary Structures for Collocation Engine.

Provides efficient sentence/document boundary tracking with:
- Running cursor for amortized O(1) lookups
- Monotonic boundary lists for linear merging
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from candyconc.core.index_format import MAX_U32 as _MAX_U32


class BoundaryIndex:
    """
    Monotonic list of boundary positions (sentence or document starts).
    
    Designed for "running cursor" pattern - when iterating matches in order,
    boundary lookups are amortized O(1) by maintaining current boundary index.
    """
    
    def __init__(self, positions: Optional[np.ndarray] = None):
        """
        Initialize with sorted boundary positions.
        
        positions: u32 array of start positions, monotonically increasing
        """
        self._positions = positions if positions is not None else np.array([], dtype=np.uint32)
        self._cursor = 0  # Current boundary index for running access
        
    @classmethod
    def load(cls, path: Path) -> "BoundaryIndex":
        """Load boundaries from binary file."""
        if not path.exists():
            return cls()
        with open(path, "rb") as f:
            count = struct.unpack("<Q", f.read(8))[0]
            # Copy once at load time so later kernels can consume the array
            # without per-call writeability fallbacks.
            positions = np.frombuffer(f.read(count * 4), dtype=np.uint32).copy()
        return cls(positions)
        
    def save(self, path: Path) -> None:
        """Save boundaries to binary file."""
        with open(path, "wb") as f:
            f.write(struct.pack("<Q", len(self._positions)))
            f.write(self._positions.tobytes())
            
    def reset_cursor(self) -> None:
        """Reset running cursor to start."""
        self._cursor = 0
        
    def get_boundary_for_pos(self, pos: int) -> Tuple[int, int]:
        """
        Get [start, end) of the boundary unit containing pos.
        
        Uses running cursor - efficient when called with increasing pos values.
        Returns (boundary_start, next_boundary_start).
        """
        if len(self._positions) == 0:
            # No boundaries = entire corpus is one unit. The sentinel must be
            # larger than any valid token position; MAX_U32 matches the uint32
            # on-disk position storage and never aliases to a negative int32.
            return (0, _MAX_U32)
            
        # Advance cursor if needed
        while (self._cursor < len(self._positions) - 1 and 
               self._positions[self._cursor + 1] <= pos):
            self._cursor += 1
            
        # Handle edge case: pos before first boundary
        if pos < self._positions[0]:
            return (0, int(self._positions[0]))
            
        start = int(self._positions[self._cursor])
        end = int(self._positions[self._cursor + 1]) if self._cursor + 1 < len(self._positions) else _MAX_U32
        
        return (start, end)
        
    def clip_window(self, pos: int, left: int, right: int) -> Tuple[int, int]:
        """
        Clip a window [pos-left, pos+right] to current boundary.
        
        This is the key operation for "within sentence" semantics.
        Returns (clipped_start, clipped_end) as half-open interval.
        """
        boundary_start, boundary_end = self.get_boundary_for_pos(pos)
        window_start = max(pos - left, boundary_start)
        window_end = min(pos + right + 1, boundary_end)  # +1 for half-open
        return (window_start, window_end)
        
    @property
    def count(self) -> int:
        """Number of boundaries."""
        return len(self._positions)


class BoundarySet:
    """
    Collection of boundary indices (sentence, document, and optionally text_type).
    
    For human/AI comparison, supports text_type boundaries to separate:
    - Human-authored texts
    - AI-generated texts (potentially multiple per human text)
    """
    
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.sentence: Optional[BoundaryIndex] = None
        self.document: Optional[BoundaryIndex] = None
        self.text_type: Optional[BoundaryIndex] = None  # For human/AI separation
        self._sentence_document_bounds: Optional[np.ndarray] = None
        
        # Document metadata for human/AI pairing
        self._doc_metadata: dict = {}
        
    def load(self) -> None:
        """Load all boundary indices."""
        self.sentence = BoundaryIndex.load(self.base_path / "sentence_bounds.bin")
        self.document = BoundaryIndex.load(self.base_path / "document_bounds.bin")
        self.text_type = BoundaryIndex.load(self.base_path / "text_type_bounds.bin")
        self._sentence_document_bounds = None
        if (
            self.sentence is not None
            and self.document is not None
            and self.sentence._positions.size > 0
            and self.document._positions.size > 0
        ):
            self._sentence_document_bounds = merge_sorted_unique_u32(
                self.sentence._positions,
                self.document._positions,
            )

        mmap_idx = self.base_path / "doc_metadata.idx.bin"
        mmap_blob = self.base_path / "doc_metadata.mmap"
        if mmap_idx.exists() and mmap_blob.exists():
            from candyconc.core.doc_metadata_store import DocMetadataMMap

            self._doc_metadata = DocMetadataMMap(self.base_path)
        self._validate_doc_metadata()
                
    def reset_cursors(self) -> None:
        """Reset all running cursors."""
        if self.sentence:
            self.sentence.reset_cursor()
        if self.document:
            self.document.reset_cursor()
        if self.text_type:
            self.text_type.reset_cursor()
            
    def clip_to_sentence(self, pos: int, left: int, right: int) -> Tuple[int, int]:
        """Clip window to sentence boundary."""
        if self.sentence:
            return self.sentence.clip_window(pos, left, right)
        return (max(0, pos - left), pos + right + 1)

    def clip_bounds_array(self, within_sentence: bool) -> Optional[np.ndarray]:
        """Return cached clipping bounds for coverage sweeps."""
        doc_bounds = self.document._positions if self.document else None
        if not within_sentence:
            if doc_bounds is None or doc_bounds.size == 0:
                return None
            return doc_bounds
        sent_bounds = self.sentence._positions if self.sentence else None
        if sent_bounds is None or sent_bounds.size == 0:
            return None
        if doc_bounds is None or doc_bounds.size == 0:
            return sent_bounds
        merged = self._sentence_document_bounds
        if merged is None:
            merged = merge_sorted_unique_u32(sent_bounds, doc_bounds)
            self._sentence_document_bounds = merged
        return merged
        
    def get_doc_type(self, doc_idx: int) -> str:
        """
        Get document type (human/AI) for a document index.
        Returns 'human', 'ai', or 'unknown'.
        """
        return self._doc_metadata.get(doc_idx, {}).get("text_type", "unknown")
        
    def get_human_ai_pair(self, doc_idx: int) -> Optional[List[int]]:
        """
        Get paired document indices for human/AI comparison.
        
        If doc_idx is a human text, returns list of AI doc indices.
        If doc_idx is an AI text, returns the human doc index.
        """
        return self._doc_metadata.get(doc_idx, {}).get("paired_with")

    def _validate_doc_metadata(self) -> None:
        if not self._doc_metadata:
            return
        if not self.document:
            return
        doc_count = int(self.document._positions.size)
        if doc_count <= 0:
            return
        min_key = None
        max_key = None
        try:
            from candyconc.core.doc_metadata_store import DocMetadataMMap
        except Exception:  # pragma: no cover - optional dependency
            DocMetadataMMap = None  # type: ignore
        if DocMetadataMMap is not None and isinstance(self._doc_metadata, DocMetadataMMap):
            if len(self._doc_metadata) <= 0:
                return
            min_key = 0
            max_key = len(self._doc_metadata) - 1
        else:
            for key in self._doc_metadata.keys():
                ik = int(key)
                if min_key is None or ik < min_key:
                    min_key = ik
                if max_key is None or ik > max_key:
                    max_key = ik
        if min_key is None or max_key is None:
            return
        if min_key < 0:
            raise RuntimeError("doc_metadata Index ungültig. Bitte Fast Index neu bauen.")
        if 0 not in self._doc_metadata:
            if min_key == 1 and max_key == doc_count:
                raise RuntimeError("doc_metadata ist 1-basiert. Bitte Fast Index neu bauen.")
            if max_key >= doc_count:
                raise RuntimeError("doc_metadata Index überschreitet doc_bounds. Bitte neu bauen.")
        else:
            if max_key >= doc_count:
                raise RuntimeError("doc_metadata Index überschreitet doc_bounds. Bitte neu bauen.")


def merge_sorted_unique_u32(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Merge two sorted uint32 arrays via NumPy's compiled union path."""
    if left.size == 0:
        return left if left.dtype == np.uint32 else left.astype(np.uint32, copy=False)
    if right.size == 0:
        return right if right.dtype == np.uint32 else right.astype(np.uint32, copy=False)
    return np.union1d(
        np.asarray(left, dtype=np.uint32),
        np.asarray(right, dtype=np.uint32),
    ).astype(np.uint32, copy=False)
