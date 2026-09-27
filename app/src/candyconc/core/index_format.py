"""Single source of truth for the on-disk Fast Index format.

Both the build-time writers (``scripts/build_fast_index.py`` and the importers
that call into it) and the runtime readers (``candyconc.core.*``) MUST use the
constants and codecs defined here, so that the binary layout of an index is
defined in exactly one place.

Historically the layout was defined twice — once at every ``struct.pack`` write
site and again at every ``struct.unpack`` read site — with hand-matched format
strings, magic bytes and pointer conventions. That duplication is what allowed
the docset pointer-sentinel to drift out of sync (the highest term became
unreachable). Anything format-related belongs here.

Two access *strategies* legitimately coexist and are NOT unified here:

* full-read  — ``read_count_prefixed_array`` loads the whole file into memory.
* mmap       — ``TokenStore`` keeps a zero-copy ``mmap`` view for hot arrays.

Both strategies share the *format* constants below; only the mechanism differs.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Integer-width limits.
#
# Token positions and term ids are stored as 32-bit on disk. ``MAX_I32`` is the
# effective ceiling for any value that passes through the int32 decode path.
# These are the central home for the overflow guards (see release plan R6).
# ---------------------------------------------------------------------------
MAX_U32: int = (1 << 32) - 1
MAX_I32: int = (1 << 31) - 1


def enforce_scaling_limits(
    *,
    token_count: int,
    vocab_size: int = 0,
    context: str = "",
) -> None:
    """Raise ``RuntimeError`` if ``token_count`` or ``vocab_size`` exceeds the
    on-disk integer-width limits.

    ``token_count`` must be < ``MAX_I32`` because the Cython postings engine
    decodes token positions through a signed int32 path at query time. The
    stricter I32 limit (not U32) is intentional: positions are stored as uint32
    on disk but the safe queryable ceiling is ``2**31 - 1``.

    ``vocab_size`` must be < ``MAX_U32`` because term ids are uint32.

    This is the single home for the build-time and corpus-open overflow guards
    (release plan R6). Calling it for any corpus within the safe range is a
    no-op, so it never changes the output of an existing build.
    """
    tag = f" ({context})" if context else ""
    if token_count > MAX_I32:
        raise RuntimeError(
            f"Corpus{tag} hat {token_count:,} Tokens — das überschreitet die "
            f"aktuelle int32-Grenze ({MAX_I32:,}). Baue den Index in kleinere "
            "Teile auf."
        )
    if vocab_size and vocab_size > MAX_U32:
        raise RuntimeError(
            f"Vokabular{tag} hat {vocab_size:,} Eintraege — Limit ist {MAX_U32:,}."
        )


# ---------------------------------------------------------------------------
# Count-prefixed array: a ``<Q`` (little-endian uint64) element count followed
# by the raw little-endian payload. This is the generic on-disk array format
# used for pointer arrays, postings, docsets, block-top sidecars, etc.
# ---------------------------------------------------------------------------
COUNT_HEADER_STRUCT: str = "<Q"
COUNT_HEADER_SIZE: int = struct.calcsize(COUNT_HEADER_STRUCT)  # 8

# ---------------------------------------------------------------------------
# Lexicon binary (``LEX2``):
#   magic, version, vocab_size, reserved, total_tokens, blob_size
# followed by offsets[vocab_size+1] (u64), freqs[vocab_size+1] (u64), blob.
# ---------------------------------------------------------------------------
LEXICON_MAGIC: bytes = b"LEX2"
LEXICON_VERSION: int = 1
LEXICON_HEADER_STRUCT: str = "<4sIIIQQ"
LEXICON_HEADER_SIZE: int = struct.calcsize(LEXICON_HEADER_STRUCT)  # 32

# Prefix-top sidecar (``LXP1``).
PREFIX_TOP_MAGIC: bytes = b"LXP1"
PREFIX_TOP_VERSION: int = 1
PREFIX_TOP_HEADER_STRUCT: str = "<4sIIIIII"
PREFIX_TOP_HEADER_SIZE: int = struct.calcsize(PREFIX_TOP_HEADER_STRUCT)  # 28

# Block-top sidecar (``BTP1``).
BLOCK_TOP_MAGIC: bytes = b"BTP1"
BLOCK_TOP_VERSION: int = 1
BLOCK_TOP_HEADER_STRUCT: str = "<4sIIII"
BLOCK_TOP_HEADER_SIZE: int = struct.calcsize(BLOCK_TOP_HEADER_STRUCT)  # 20

# StreamVByte stream pointer header: n_blocks, block_size, token_count.
SVB_PTR_HEADER_STRUCT: str = "<QII"
SVB_PTR_HEADER_SIZE: int = struct.calcsize(SVB_PTR_HEADER_STRUCT)  # 16

# Per-document metadata blob framing tag (followed by ``<len u32><crc u32>``).
DOC_META_FRAME_MAGIC: bytes = b"JMB1"

# ---------------------------------------------------------------------------
# Postings pointer / sentinel convention.
#
# A postings pointer array over ``vocab_size`` term ids has length
# ``vocab_size + 2``:
#
#   index 0            unused — term ids are 1-based, ``offsets[0] == 0``
#   index 1..vocab     start offset of each term's postings run
#   index vocab + 1    terminal sentinel == total number of postings
#
# The terminal sentinel guarantees ``offsets[tid + 1]`` is valid even for the
# highest term id (``tid == vocab_size``). Omitting it makes the highest term's
# postings unreachable — the exact bug that motivated this module.
# ---------------------------------------------------------------------------
POSTINGS_PTR_EXTRA: int = 2

# The lexicon *string-offset* array uses ``vocab_size + 1``: it only needs a
# terminal to slice the last string's bytes, not a postings sentinel. Kept
# distinct on purpose so the two conventions are never conflated again.
LEXICON_OFFSETS_EXTRA: int = 1


def postings_ptr_len(vocab_size: int) -> int:
    """Required length of a postings/docset pointer array for ``vocab_size`` ids."""
    return int(vocab_size) + POSTINGS_PTR_EXTRA


def write_count_prefixed_array(path: Path, arr: np.ndarray) -> None:
    """Write ``arr`` as a count-prefixed array (``<Q count>`` + raw payload).

    The array's existing dtype is preserved (no implicit cast); callers cast to
    the intended on-disk dtype before writing.
    """
    path = Path(path)
    arr = np.asarray(arr)
    count = int(arr.size)
    with open(path, "wb") as f:
        f.write(struct.pack(COUNT_HEADER_STRUCT, count))
        # Avoid materializing large buffers in memory.
        if count:
            arr.tofile(f)


def read_count_prefixed_array(
    path: Path,
    dtype: np.dtype,
    *,
    label: str = "Index",
    missing_ok: bool = False,
) -> Optional[np.ndarray]:
    """Read a count-prefixed array written by :func:`write_count_prefixed_array`.

    Returns a read-only ``np.frombuffer`` view. With ``missing_ok=True`` a
    missing file yields ``None`` instead of raising. ``label`` only shapes the
    error messages so callers can keep their domain-specific wording.
    """
    path = Path(path)
    if not path.exists():
        if missing_ok:
            return None
        raise RuntimeError(f"{label} Datei fehlt: {path}")
    with open(path, "rb") as f:
        header = f.read(COUNT_HEADER_SIZE)
        if len(header) != COUNT_HEADER_SIZE:
            raise RuntimeError(f"{label} Header ungültig: {path}")
        n = struct.unpack(COUNT_HEADER_STRUCT, header)[0]
        data = f.read()
    need = int(n) * int(np.dtype(dtype).itemsize)
    if len(data) < need:
        raise RuntimeError(f"{label} Daten unvollständig: {path}")
    return np.frombuffer(data, dtype=dtype, count=int(n))


# ---------------------------------------------------------------------------
# Index manifest (R5): the single authoritative capability + provenance
# declaration for a Fast Index directory. Written LAST (atomically) by the
# builder; read once at open time. Legacy indices (no manifest) synthesise a
# version-0 manifest from file presence, so every existing index keeps opening.
# ---------------------------------------------------------------------------
MANIFEST_VERSION: int = 1
MANIFEST_FILENAME: str = "index_manifest.json"

# Revision of the builder that wrote an index, stored as builder_revision.
# Manifests without the field read as 0. Added manifest fields stay optional.
# 0: spaCy morph hashes of 2**63 or larger were stored empty.
# 1: morph values keep the full uint64 hash range.
# 2: prealigned imports record text_type as anchor/version and default the
#    anchor model to its role.
# 3: imports write whitespace_after.bin unless disabled and record the
#    origin of the spacing in the whitespace manifest field.
BUILDER_REVISION: int = 3

# Values of the manifest field ``whitespace``: where the spacing between the
# tokens of the index comes from.
#   text          the spacing of the imported text (whitespace_after.bin)
#   vrt_join      VRT imported with spaCy: the spacing of the text the importer
#                 rebuilt from the VRT tokens (--join-mode), whitespace_after.bin
#   pretokenized  VRT with --annotation-mode adopt: the file holds tokens
#                 without their spacing, no whitespace_after.bin
#   disabled      the import ran with --no-capture-whitespace
# An empty value means the builder did not record it (builder_revision < 3).
WHITESPACE_TEXT = "text"
WHITESPACE_VRT_JOIN = "vrt_join"
WHITESPACE_PRETOKENIZED = "pretokenized"
WHITESPACE_DISABLED = "disabled"

# Import mode of the paired Parquet layout (``target_text``/``input_text``
# rows). VRT files imported with spaCy re-tokenization pass through the same
# builder and record ``vrt``.
PAIRED_PARQUET_IMPORT_MODE: str = "paired-parquet"

# Import mode names written by older builds, mapped to today's name when a
# manifest is read.
LEGACY_IMPORT_MODES: Dict[str, str] = {"aligned-dehat": PAIRED_PARQUET_IMPORT_MODE}


def normalize_import_mode(value: object) -> str:
    """Today's name of an import mode read from a manifest."""
    text = str(value or "")
    return LEGACY_IMPORT_MODES.get(text, text)


def normalize_manifest_payload(data: object) -> object:
    """A raw manifest dict with today's import mode name (other values unchanged)."""
    if isinstance(data, dict) and "import_mode" in data:
        mode = normalize_import_mode(data.get("import_mode"))
        if mode != data.get("import_mode"):
            data = {**data, "import_mode": mode}
    return data

# Capability key -> the artifact whose presence proves the capability.
_CAPABILITY_FILES: Dict[str, str] = {
    "word_lex": "word_lexicon.bin",
    "lemma_lex": "lemma_lexicon.bin",
    "pos_lex": "pos_lexicon.bin",
    "morph_lex": "morph_lexicon.bin",
    "ent_lex": "ent_lexicon.bin",
    "rel_lex": "rel_lexicon.bin",
    "embeddings": "passage_vecs.npy",
    "sentence_bounds": "sentence_bounds.bin",
    "document_bounds": "document_bounds.bin",
    "word_prefix_all": "word_lexicon.prefix_all.bin",
    "word_ngram": "word_lexicon.ngram3.bin",
    # Sentence embeddings keyed by token_start_pos enable embed/hybrid sentence
    # alignment (server.py _align_sentence_lists). Produced by the parquet builder
    # only when --build-sentence-embeddings is set (re-ingest); absent on older
    # indices — same missing_ok semantics as the other optional capabilities above.
    "sentence_embeddings": "sentence_vecs.npy",
    # Optional count-prefixed uint8 sidecar with one whitespace flag per token.
    # Imports write it from builder revision 3 unless --no-capture-whitespace
    # is given. Earlier builders required --capture-whitespace. Missing sidecars
    # use space-joined rendering. Only builders produce this file, so its
    # capability remains manifest-authoritative rather than post-build mutable.
    "whitespace_after": "whitespace_after.bin",
}


@dataclass
class IndexManifest:
    """Capability + provenance descriptor for one Fast Index directory."""

    manifest_version: int = MANIFEST_VERSION
    import_mode: str = "unknown"          # csv | jsonl | plaintext | huggingface | generic | prealigned | paired-parquet | vrt | unknown
    paired: bool = False
    pair_axes: List[str] = field(default_factory=list)
    annotation_source: str = "unknown"    # spacy | native | unknown
    capabilities: Dict[str, bool] = field(default_factory=dict)
    dtypes: Dict[str, str] = field(default_factory=dict)
    build_fingerprint: str = ""
    created_at: str = ""
    complete: bool = True
    # Corpus language as ISO 639 code from the pipeline (spaCy ``nlp.lang``).
    # Empty when the build did not record it: the language is then unknown.
    language: str = ""
    # Pipeline that tokenized and annotated the corpus (``en_core_web_md``,
    # ``blank:en``) and its version. Empty when not recorded.
    annotation_pipeline: str = ""
    annotation_pipeline_version: str = ""
    # Width of the pipeline's static word vectors. 0: none, -1: not recorded.
    pipeline_vectors: int = -1
    builder_revision: int = 0
    # Origin of the spacing between tokens (WHITESPACE_* above). Empty when
    # not recorded.
    whitespace: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, path: Path) -> "IndexManifest":
        data = json.loads(Path(path).read_text("utf-8"))
        ver = int(data.get("manifest_version", 0))
        if ver > MANIFEST_VERSION:
            raise ValueError(
                f"Manifest index_manifest.json version {ver} > supported {MANIFEST_VERSION}; "
                "bitte CandyConc aktualisieren."
            )
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        payload = {k: v for k, v in normalize_manifest_payload(data).items() if k in known}
        capabilities = payload.get("capabilities")
        if isinstance(capabilities, dict):
            # Old manifests used this name for the passage FAISS file. It was
            # neither a word index nor the canonical semantic feature contract.
            capabilities = dict(capabilities)
            capabilities.pop("word_faiss", None)
            payload["capabilities"] = capabilities
        return cls(**payload)

    @classmethod
    def legacy(cls, index_path: Path) -> "IndexManifest":
        """Synthesise a version-0 manifest from on-disk file presence."""
        index_path = Path(index_path)
        caps = {
            cap: (index_path / fname).exists()
            for cap, fname in _CAPABILITY_FILES.items()
        }
        return cls(
            manifest_version=0,
            import_mode="unknown",
            paired=False,
            pair_axes=[],
            annotation_source="unknown",
            capabilities=caps,
            dtypes={},
            build_fingerprint="",
            created_at="",
            complete=True,
        )

    @classmethod
    def load(cls, index_path: Path) -> "IndexManifest":
        """The single runtime entry point: real manifest if present, else legacy."""
        index_path = Path(index_path)
        mpath = index_path / MANIFEST_FILENAME
        if mpath.exists():
            return cls.from_json(mpath)
        return cls.legacy(index_path)


def capabilities_from_files(index_path: Path) -> Dict[str, bool]:
    """Probe capability flags from artifact presence (used by the builder to fill
    a manifest, and by legacy synthesis)."""
    index_path = Path(index_path)
    return {
        cap: (index_path / fname).exists()
        for cap, fname in _CAPABILITY_FILES.items()
    }


# Capability keys whose backing artifact may legitimately appear or disappear
# AFTER the build: the embeddings package installs ``passage_vecs.npy`` /
# ``faiss_passage.index`` / ``sentence_vecs.npy`` into an existing index dir,
# and users can delete them to reclaim space. All other ``_CAPABILITY_FILES``
# keys (lexicons, bounds, prefix/ngram sidecars) are produced only by the
# builder and stay authoritative in the frozen manifest.
_POST_BUILD_CAPABILITY_KEYS: frozenset = frozenset(
    {"embeddings", "sentence_embeddings"}
)


def effective_capabilities(manifest_caps: Dict[str, bool], index_path: Path) -> Dict[str, bool]:
    """Reconcile frozen manifest capabilities with CURRENT artifact presence.

    The manifest is written once at build time (manifest_version=1, FROZEN) and
    is never rewritten, so artifact-backed flags drift when embeddings packages
    are installed or artifacts are deleted post-build. This pure read-side
    helper overlays live file presence for the post-build-mutable keys
    (:data:`_POST_BUILD_CAPABILITY_KEYS`) over a copy of the manifest dict.
    Build-derived flags (lexicons, bounds, and non-capability fields like
    ``paired``/``pair_axes``) are untouched; the manifest on disk is never
    modified. Cost: two ``Path.exists()`` calls.
    """
    index_path = Path(index_path)
    caps = dict(manifest_caps)
    caps.pop("word_faiss", None)
    for cap in _POST_BUILD_CAPABILITY_KEYS:
        caps[cap] = (index_path / _CAPABILITY_FILES[cap]).exists()
    return caps
