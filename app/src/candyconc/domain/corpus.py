from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import RLock


from candyconc.i18n import lt  # noqa: E402
from candyconc.paths import data_dir  # noqa: E402

_REGISTRY_PATH = data_dir() / "corpora.json"
_INVALID_NAME = lt("Ungültiger Korpusname", "Invalid corpus name")
_REGISTRY_LOCK = RLock()


def _canonical_path(path: str | Path) -> str:
    """Return a stable registry path without requiring the target to exist."""
    return str(Path(path).expanduser().resolve(strict=False))


@dataclass
class CorpusRegistry:
    """Helper for persisting available corpus indices."""

    indices: List[str] = field(default_factory=list)
    active: Optional[str] = None

    @classmethod
    def load(cls) -> "CorpusRegistry":
        with _REGISTRY_LOCK:
            if not _REGISTRY_PATH.is_file():
                return cls()
            try:
                data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(lt(
                    "Korpus Registry unlesbar: {path}",
                    "The corpus registry cannot be read: {path}",
                ).format(path=_REGISTRY_PATH)) from exc
            seen: set[str] = set()
            indices: list[str] = []
            for raw in data.get("indices", []):
                if not isinstance(raw, str):
                    continue
                path = _canonical_path(raw)
                if path not in seen:
                    seen.add(path)
                    indices.append(path)
            active = data.get("active") if isinstance(data.get("active"), str) else None
            active = _canonical_path(active) if active else None
            if active not in indices:
                active = None
            return cls(indices=indices, active=active)

    def save(self) -> None:
        with _REGISTRY_LOCK:
            _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"indices": self.indices, "active": self.active}
            tmp = _REGISTRY_PATH.with_name(f"{_REGISTRY_PATH.name}.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, _REGISTRY_PATH)

    def register(self, directory: Path, *, activate: bool = False) -> None:
        path = _canonical_path(directory)
        if path not in self.indices:
            self.indices.append(path)
        # Registration and activation are separate user decisions. In particular,
        # a first registered corpus may be a published partial import whose
        # provenance still requires review before it becomes the working scope.
        if activate:
            self.active = path
        self.save()

    def unregister(self, directory: Path) -> None:
        path = _canonical_path(directory)
        if path in self.indices:
            self.indices.remove(path)
        if self.active == path:
            self.active = self.indices[0] if self.indices else None
        self.save()

    def delete(self, directory: Path) -> None:
        """Remove ``directory`` from the registry, refusing destructive removals.

        Deleting the currently active corpus, or the last remaining registered
        corpus, would leave the server without a single source of truth for the
        active corpus. Both are refused with a ``ValueError`` so the route layer
        can translate them into an honest ``409`` instead of silently picking a
        new active corpus.
        """
        path = _canonical_path(directory)
        if path not in self.indices:
            raise FileNotFoundError(f"Registrierter Korpus nicht gefunden: {path}")
        if self.active == path:
            raise ValueError(lt(
                "Der aktive Korpus kann nicht gelöscht werden",
                "The active corpus cannot be removed",
            ))
        if len(self.indices) <= 1:
            raise ValueError(lt(
                "Der letzte registrierte Korpus kann nicht gelöscht werden",
                "The last registered corpus cannot be removed",
            ))
        self.indices.remove(path)
        self.save()


def has_index(path: Path) -> bool:
    """Return ``True`` if ``path`` is a valid CandyConc corpus index directory."""
    base = Path(path)
    meta_bin = base / "meta.bin"
    if not base.is_dir() or not meta_bin.exists():
        return False
    manifest_path = base / "index_manifest.json"
    if manifest_path.exists():
        try:
            from candyconc.core.index_format import IndexManifest

            manifest = IndexManifest.load(base)
        except Exception:
            return False
        if not bool(getattr(manifest, "complete", True)):
            return False
    return True


def ready_corpora_newest_first(corpora_dir: Path) -> list[Path]:
    """Ready indexes directly below ``corpora_dir``, most recently built first.

    Hidden directories (the import staging area ``.imports``) are skipped.
    """
    try:
        children = [child for child in Path(corpora_dir).iterdir() if child.is_dir()]
    except OSError:
        return []
    ready = [child for child in children if not child.name.startswith(".") and has_index(child)]

    def _built_at(path: Path) -> float:
        for name in ("index_manifest.json", "meta.bin"):
            try:
                return (path / name).stat().st_mtime
            except OSError:
                continue
        return 0.0

    return sorted(ready, key=_built_at, reverse=True)


def _read_token_count(index_dir: Path) -> int:
    """Cheaply read token_count from meta.bin (first 8 bytes, uint64 LE) without
    opening the whole index."""
    meta_bin = Path(index_dir) / "meta.bin"
    try:
        import struct

        with open(meta_bin, "rb") as fh:
            head = fh.read(8)
        if len(head) == 8:
            return int(struct.unpack("<Q", head)[0])
    except Exception:
        pass
    return 0


def _anchor_text_type(manifest: object) -> str:
    """``text_type`` value of the anchor documents of a paired index.

    Paired imports from builder revision 2 write ``anchor``. Older paired
    imports and the human/AI research layout write ``human``.
    """
    from candyconc.core import pairing

    if str(getattr(manifest, "import_mode", "")) == "prealigned" and int(
        getattr(manifest, "builder_revision", 0) or 0
    ) >= 2:
        return pairing.ANCHOR
    return "human"


def _corpus_feature_descriptor(caps: dict, manifest: object, index_dir: Path) -> dict:
    """Build the UI-facing feature descriptor from explicit index evidence.

    ``capabilities`` remains the legacy compatibility map. This descriptor is
    the versioned contract new UI surfaces should consume.
    """
    index_dir = Path(index_dir)

    def has(key: str) -> bool:
        return bool(caps.get(key))

    token_attributes = [
        {
            "id": "word",
            "cql_attribute": "word",
            "label": lt("Wortform", "Word form"),
            "artifacts": ["word_lex"],
            "value_domain": "lexicon",
        }
    ]
    if has("lemma_lex"):
        token_attributes.append({
            "id": "lemma",
            "cql_attribute": "lemma",
            "label": "Lemma",
            "artifacts": ["lemma_lex"],
            "value_domain": "lexicon",
        })
    if has("pos_lex"):
        token_attributes.append({
            "id": "pos",
            "cql_attribute": "pos",
            "label": "POS",
            "artifacts": ["pos_lex"],
            "value_domain": "lexicon",
            "tagset": getattr(manifest, "tagset", None) or None,
        })
    if has("ent_lex"):
        token_attributes.append({
            "id": "ner",
            "cql_attribute": "ner",
            "label": "NER",
            "artifacts": ["ent_lex"],
            "value_domain": "lexicon",
        })
    if has("morph_lex"):
        token_attributes.append({
            "id": "morph",
            "cql_attribute": "morph",
            "label": lt("Morphologie", "Morphology"),
            "artifacts": ["morph_lex"],
            "value_domain": "lexicon",
        })
    if has("rel_lex"):
        token_attributes.append({
            "id": "rel",
            "cql_attribute": "rel",
            "label": lt("Relation", "Dependency relation"),
            "artifacts": ["rel_lex"],
            "value_domain": "lexicon",
        })

    spacy_passage_ready = has("embeddings") and (index_dir / "faiss_passage.index").exists()
    gemma_passage_ready = not (index_dir / ".semantic_commit_in_progress").exists() and all(
        (index_dir / artifact).exists()
        for artifact in (
            "faiss_gemma_doc.index",
            "gemma_doc_vecs.npy",
            "gemma_doc_texts.json",
        )
    )
    # Passage search reads its FAISS index at query time. Without the optional
    # package (extra "semantic") the artifacts on disk cannot be used.
    faiss_missing = not _faiss_importable()
    passage_ready = (spacy_passage_ready or gemma_passage_ready) and not faiss_missing
    # One decision for thesaurus, sim() and copilot: the corpus's word index or
    # the static vectors of its annotation pipeline (core.word_vectors).
    from candyconc.core.word_vectors import resolve_word_vectors

    word_vectors = resolve_word_vectors(index_dir)
    word_similarity_ready = word_vectors.available
    if word_similarity_ready:
        token_attributes.append({
            "id": "sim",
            "cql_attribute": "sim",
            "label": lt("Semantik (ähnliche Wörter)", "Semantic (similar words)"),
            "artifacts": (
                ["faiss_word.index", "word_ids.npy"] if word_vectors.word_index else ["annotation_pipeline"]
            ),
            "value_domain": "semantic_neighbourhood",
        })

    frequency_groups = [
        {"id": "word", "label": lt("Wortform", "Word form"), "artifacts": ["word_lex"]},
    ]
    if has("lemma_lex"):
        frequency_groups.append({"id": "lemma", "label": "Lemma", "artifacts": ["lemma_lex"]})
    if has("pos_lex"):
        frequency_groups.append({"id": "pos", "label": lt("POS-Tag", "POS tag"), "artifacts": ["pos_lex"]})

    paired = bool(getattr(manifest, "paired", False))
    pair_axes = list(getattr(manifest, "pair_axes", []) or [])
    pairing_schema = None
    if paired:
        # Current runtime alignment resolves groups through legacy ref_doc
        # metadata. The descriptor makes that explicit so UI surfaces can show
        # generic labels without implying fully generic axis filtering.
        pairing_schema = {
            "schema_id": "legacy_ref_doc_v1",
            "group_key_field": "ref_doc",
            "anchor_role_field": "text_type",
            "default_anchor_role": _anchor_text_type(manifest),
            "variant_axis_fields": pair_axes,
            "legacy_variant_filter_field": "model",
            "generic_axis_filters": False,
            "legacy_response_fields": {
                "anchor_doc_id": "human_doc_id",
                "comparison_doc_ids": "variant_doc_ids",
                "variant_counts": "models",
            },
        }

    return {
        "schema_version": "corpus-features-v1",
        "token_attributes": token_attributes,
        "frequency_groups": frequency_groups,
        "semantic": {
            "passage_search": bool(passage_ready),
            "word_similarity": bool(word_similarity_ready),
            "sentence_alignment": has("sentence_embeddings"),
            "missing_packages": ["faiss-cpu"] if faiss_missing else [],
        },
        "alignment": {
            "paired": paired,
            "pair_axes": pair_axes,
            "pairing_schema": pairing_schema,
            "parallel_groups": paired,
            "parallel_kwic": paired,
        },
    }


def dependency_label_scheme(index_dir: Path | str) -> str | None:
    """Annotation scheme of the dependency labels (``rel``) of an index.

    ``tiger`` for spaCy's German pipelines, ``clearnlp`` for spaCy's English
    pipelines, ``None`` when the scheme is not known (other pipelines, gold
    annotations adopted from VRT, missing build metadata). Read from the
    manifest (``annotation_source``) and ``index_build_meta.json``
    (``spacy_model``). Word-sketch glosses are chosen by this scheme.
    """
    index_dir = Path(index_dir)
    try:
        from candyconc.core.index_format import IndexManifest

        source = str(IndexManifest.load(index_dir).annotation_source or "")
    except Exception:
        source = ""
    try:
        meta = json.loads((index_dir / "index_build_meta.json").read_text("utf-8"))
    except Exception:
        meta = {}
    if source not in ("spacy", "unknown", "") or str(meta.get("annotation_source") or "spacy") != "spacy":
        return None
    model = str(meta.get("spacy_model") or "").strip().lower()
    if model.startswith("de_"):
        return "tiger"
    if model.startswith("en_"):
        return "clearnlp"
    return None


def _faiss_importable() -> bool:
    """True when the optional ``faiss`` package (extra ``semantic``) is installed."""
    import importlib.util

    try:
        return importlib.util.find_spec("faiss") is not None
    except (ImportError, ValueError):
        return False


def corpus_summary(index_dir: Path, *, name: str | None = None) -> dict:
    """Return a lightweight catalogue entry for one index dir (no full open).

    Reads token_count from meta.bin, doc_count from index_build_meta.json when
    present, and capabilities/paired/pair_axes from the IndexManifest (which is
    cheap: a JSON read, or legacy synthesis from file presence).
    """
    index_dir = Path(index_dir)
    from candyconc.core.index_format import IndexManifest, effective_capabilities
    from candyconc.core.word_vectors import resolve_word_vectors

    manifest = IndexManifest.load(index_dir)
    doc_count = 0
    build_meta = index_dir / "index_build_meta.json"
    if build_meta.exists():
        try:
            doc_count = int(json.loads(build_meta.read_text("utf-8")).get("doc_count", 0))
        except Exception:
            doc_count = 0
    # Overlay mutable artifact presence on manifest flags so the catalogue
    # reflects installed embeddings and FAISS files. Free contrasts work on any
    # corpus, while parallel and alignment features require pairing.
    caps = effective_capabilities(manifest.capabilities, index_dir)
    caps["free_contrast"] = True
    caps["parallel"] = bool(manifest.paired)
    features = _corpus_feature_descriptor(caps, manifest, index_dir)
    corpus_id = str(manifest.build_fingerprint or "").strip()
    if not corpus_id:
        corpus_id = "path:" + hashlib.sha256(str(index_dir.resolve(strict=False)).encode("utf-8")).hexdigest()
    return {
        "name": name or index_dir.name,
        "id": corpus_id,
        "corpus_id": corpus_id,
        "path": str(index_dir),
        "token_count": _read_token_count(index_dir),
        "doc_count": doc_count,
        "import_mode": manifest.import_mode,
        "annotation_source": manifest.annotation_source,
        "paired": bool(manifest.paired),
        "pair_axes": list(manifest.pair_axes),
        "is_legacy": manifest.manifest_version == 0,
        # Corpus language (ISO 639) and annotation pipeline. None: not recorded
        # by the build, shown as unknown rather than guessed from other fields.
        "language": manifest.language or None,
        "annotation_pipeline": _annotation_pipeline(manifest, index_dir),
        "builder_revision": int(manifest.builder_revision),
        "word_vectors": resolve_word_vectors(index_dir).to_dict(),
        "capabilities": caps,
        "features": features,
    }


def _annotation_pipeline(manifest: object, index_dir: Path) -> str | None:
    """Pipeline from the manifest, for older indexes the recorded build model.

    A recorded local directory is not shown (it names a path of the build
    machine and not a pipeline).
    """
    from candyconc.core.word_vectors import corpus_pipeline

    name = str(getattr(manifest, "annotation_pipeline", "") or "") or corpus_pipeline(index_dir) or ""
    if not name or "/" in name or "\\" in name:
        return None
    return name


def list_corpora(corpus_dir: Path, *, extra: tuple[tuple[str, Path], ...] = ()) -> List[dict]:
    """Catalogue all corpora under ``corpus_dir`` plus any ``extra`` (name, path)
    entries (e.g. the env-configured default index that lives outside corpus_dir).

    De-duplicated by resolved path; sorted by name. Each entry is a
    :func:`corpus_summary`. Never raises on a single bad dir — it is skipped.
    """
    seen: set[str] = set()
    out: List[dict] = []

    def _add(path: Path, name: str | None) -> None:
        try:
            p = Path(path).resolve()
        except Exception:
            return
        key = str(p)
        if key in seen or not has_index(p):
            return
        seen.add(key)
        try:
            out.append(corpus_summary(p, name=name))
        except Exception:
            pass

    for nm, pth in extra:
        _add(pth, nm)
    cdir = Path(corpus_dir)
    if cdir.is_dir():
        for child in sorted(cdir.iterdir()):
            if child.is_dir():
                _add(child, child.name)
    out.sort(key=lambda e: e["name"])
    return out


def normalize_corpus_name(name: str) -> str:
    """Return a safe single-segment corpus name."""
    corpus_name = str(name).strip()
    if not corpus_name:
        raise ValueError(_INVALID_NAME)

    posix = PurePosixPath(corpus_name)
    windows = PureWindowsPath(corpus_name)
    if posix.is_absolute() or windows.is_absolute():
        raise ValueError(_INVALID_NAME)
    if "/" in corpus_name or "\\" in corpus_name:
        raise ValueError(_INVALID_NAME)
    if corpus_name in {".", ".."}:
        raise ValueError(_INVALID_NAME)
    if posix.parts != (corpus_name,):
        raise ValueError(_INVALID_NAME)
    return corpus_name


def resolve_corpus_path(base_dir: Path, name: str) -> tuple[str, Path]:
    """Resolve ``name`` under ``base_dir`` and reject traversal/absolute paths."""
    corpus_name = normalize_corpus_name(name)
    corpus_root = Path(base_dir).expanduser().resolve(strict=False)
    corpus_path = (corpus_root / corpus_name).resolve(strict=False)
    try:
        corpus_path.relative_to(corpus_root)
    except ValueError as exc:
        raise ValueError(_INVALID_NAME) from exc
    if corpus_path == corpus_root:
        raise ValueError(_INVALID_NAME)
    return corpus_name, corpus_path


__all__ = [
    "CorpusRegistry",
    "corpus_summary",
    "has_index",
    "list_corpora",
    "normalize_corpus_name",
    "resolve_corpus_path",
]
