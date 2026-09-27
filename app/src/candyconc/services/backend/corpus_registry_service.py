from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from candyconc.core.index_format import IndexManifest
from candyconc.domain.corpus import CorpusRegistry, corpus_summary, resolve_corpus_path
from candyconc.i18n import lt
from candyconc.services.backend.corpus_import_outcome import read_import_outcome

CorpusStatus = Literal["ready", "missing", "incomplete", "corrupt"]

# POSIX NAME_MAX: a single path component over 255 bytes makes the kernel raise
# OSError(ENAMETOOLONG) from stat/exists. We reject such names up front (as the
# sibling traversal/absolute checks do) so the lifecycle routes return a clean
# 400 instead of an unguarded 500 from ``inspect_corpus_status`` (CORPUS-LIFECYCLE-01).
_MAX_CORPUS_NAME_BYTES = 255


def _reject_overlong_corpus_name(name: str) -> None:
    if len(str(name).encode("utf-8", "surrogatepass")) > _MAX_CORPUS_NAME_BYTES:
        raise ValueError(lt("Ungültiger Korpusname", "Invalid corpus name"))


@dataclass(frozen=True)
class CorpusRef:
    """Resolved corpus reference used by catalogue/lifecycle routes."""

    name: str
    path: Path
    source: str
    active: bool = False

    @property
    def display_name(self) -> str:
        """Name to show: the directory name, also for the pinned ``default`` corpus.

        ``name`` stays the identifier the routes accept (``default`` for the
        corpus pinned with CANDYCONC_INDEX_PATH or the configuration).
        """
        return self.path.name or self.name


@dataclass(frozen=True)
class CorpusManifestStatus:
    """Cheap release-facing status without opening the full index."""

    status: CorpusStatus
    reason: str = ""


def inspect_corpus_status(path: Path) -> CorpusManifestStatus:
    """Classify an index directory without constructing ``CorpusIndex``."""
    index_path = Path(path).expanduser().resolve(strict=False)
    if not index_path.exists() or not index_path.is_dir():
        return CorpusManifestStatus("missing", "directory missing")
    if not (index_path / "meta.bin").exists():
        return CorpusManifestStatus("incomplete", "missing meta.bin")
    try:
        manifest = IndexManifest.load(index_path)
    except Exception as exc:
        return CorpusManifestStatus("corrupt", str(exc))
    if not bool(getattr(manifest, "complete", True)):
        return CorpusManifestStatus("incomplete", "manifest complete=false")
    return CorpusManifestStatus("ready", "")


class CorpusRegistryService:
    """Authoritative read/write facade for configured corpus references.

    This service intentionally does not delete files. It only registers,
    activates, unregisters, and reports status. Destructive filesystem deletion
    remains a separate, more constrained operation.
    """

    def __init__(self, corpus_dir: Path, default_path: Path | None = None) -> None:
        self.corpus_dir = Path(corpus_dir).expanduser().resolve(strict=False)
        self.default_path = (
            Path(default_path).expanduser().resolve(strict=False)
            if default_path is not None
            else None
        )

    def _registry(self) -> CorpusRegistry:
        return CorpusRegistry.load()

    def _entry(self, ref: CorpusRef) -> dict[str, Any]:
        status = inspect_corpus_status(ref.path)
        base: dict[str, Any] = {
            "name": ref.name,
            "display_name": ref.display_name,
            "path": str(ref.path),
            "status": status.status,
            "status_reason": status.reason,
            "source": ref.source,
            "active": bool(ref.active),
            "token_count": 0,
            "doc_count": 0,
            "import_mode": "",
            "paired": False,
            "pair_axes": [],
            "is_legacy": False,
            "language": None,
            "annotation_pipeline": None,
            "capabilities": {},
            "partial_input": False,
            "rejected_rows": 0,
            "warning_count": 0,
            "import_warnings": [],
        }
        if status.status != "ready":
            return base
        try:
            summary = corpus_summary(ref.path, name=ref.name)
        except Exception as exc:
            base["status"] = "corrupt"
            base["status_reason"] = str(exc)
            return base
        summary.update(
            {
                "display_name": ref.display_name,
                "status": "ready",
                "status_reason": "",
                "source": ref.source,
                "active": bool(ref.active),
            }
        )
        outcome = read_import_outcome(ref.path)
        if outcome is not None:
            summary.update(
                {
                    "partial_input": bool(outcome["partial_input"]),
                    "rejected_rows": int(outcome["rejected_rows"]),
                    "warning_count": int(outcome["warning_count"]),
                    "import_warnings": list(outcome["import_warnings"]),
                }
            )
        else:
            summary.update(
                {
                    "partial_input": False,
                    "rejected_rows": 0,
                    "warning_count": 0,
                    "import_warnings": [],
                }
            )
        return summary

    def _iter_refs(self) -> list[CorpusRef]:
        reg = self._registry()
        refs: list[CorpusRef] = []
        if self.default_path is not None:
            refs.append(
                CorpusRef(
                    "default",
                    self.default_path,
                    "default",
                    active=reg.active == str(self.default_path),
                )
            )
        for raw in reg.indices:
            path = Path(raw).expanduser().resolve(strict=False)
            refs.append(CorpusRef(path.name, path, "registry", active=raw == reg.active))
        if self.corpus_dir.is_dir():
            for child in sorted(self.corpus_dir.iterdir()):
                # Dot-prefixed entries (e.g. the '.imports' staging area where
                # in-flight import jobs build their not-yet-published index) are
                # internal scratch, not corpora; surfacing them in the catalog
                # leaks a 0-token 'incomplete' entry that 409s on activation
                # (CORPUS-LIFECYCLE-02).
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    refs.append(CorpusRef(child.name, child.resolve(strict=False), "managed"))
        return refs

    def list_corpora(self) -> list[dict[str, Any]]:
        merged: dict[str, CorpusRef] = {}
        active_by_path: set[str] = set()
        for ref in self._iter_refs():
            key = str(ref.path)
            if ref.active:
                active_by_path.add(key)
            existing = merged.get(key)
            if existing is None or existing.source != "default":
                merged[key] = ref
        entries = []
        for key, ref in merged.items():
            active = ref.active or key in active_by_path
            entry = self._entry(CorpusRef(ref.name, ref.path, ref.source, active=active))
            reason = str(entry.get("status_reason") or "")
            if (
                entry.get("status") == "corrupt"
                and "Manifest" in reason
                and "version" in reason
                and "supported" in reason
            ):
                continue
            entries.append(entry)
        entries.sort(key=lambda item: (item.get("name") != "default", str(item.get("name", ""))))
        return entries

    def _is_active_path(self, path: Path) -> bool:
        """Return whether ``path`` is the registry's active corpus.

        Single source of truth shared with ``list_corpora``/``_iter_refs`` so the
        ``active`` flag is identical across /corpora and /corpora/{name}/capabilities
        (finding 28). Compares both the raw and resolved path strings because the
        registry may store either an as-configured or a resolved path.
        """
        active = str(self._registry().active or "")
        if not active:
            return False
        resolved = str(Path(path).expanduser().resolve(strict=False))
        return active == str(path) or active == resolved

    def inspect(self, name: str) -> dict[str, Any]:
        wanted = str(name or "default").strip()
        _reject_overlong_corpus_name(wanted)
        if not wanted or wanted.lower() == "default":
            if self.default_path is None:
                raise FileNotFoundError(lt("Kein Standard-Korpus konfiguriert", "No default corpus configured"))
            return self._entry(
                CorpusRef(
                    "default",
                    self.default_path,
                    "default",
                    active=self._is_active_path(self.default_path),
                )
            )

        managed_name, managed_path = resolve_corpus_path(self.corpus_dir, wanted)
        registry_matches = [ref for ref in self._iter_refs() if ref.name == wanted]
        candidates = list(registry_matches)
        if managed_name:
            candidates.append(
                CorpusRef(
                    managed_name,
                    managed_path,
                    "managed",
                    active=self._is_active_path(managed_path),
                )
            )
        if not candidates:
            raise FileNotFoundError(lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}").format(name=wanted))
        chosen = candidates[0]
        # Re-derive ``active`` from the single source of truth: a registry match
        # may already carry it, but a managed-only candidate (or a stale ref)
        # must not default to False when this IS the active corpus.
        active = chosen.active or self._is_active_path(chosen.path)
        return self._entry(
            CorpusRef(chosen.name, chosen.path, chosen.source, active=active)
        )

    @staticmethod
    def _require_partial_import_acknowledgement(
        entry: dict[str, Any],
        *,
        acknowledge_partial_input: bool,
    ) -> None:
        if entry.get("partial_input") and not acknowledge_partial_input:
            raise RuntimeError(
                lt(
                    "Dieser Korpus stammt aus einem Teilimport. Prüfe Reject-/Build-Report "
                    "und bestätige die Aktivierung ausdrücklich.",
                    "This corpus comes from a partial import. Check the rejected rows report "
                    "and the build report, then confirm the activation explicitly.",
                )
            )

    def register(
        self,
        path: Path,
        *,
        activate: bool = False,
        acknowledge_partial_input: bool = False,
    ) -> dict[str, Any]:
        corpus_path = Path(path).expanduser().resolve(strict=False)
        if not corpus_path.is_dir():
            raise FileNotFoundError(lt("Korpusverzeichnis nicht gefunden: {path}", "Corpus directory not found: {path}").format(path=corpus_path))
        entry = self._entry(CorpusRef(corpus_path.name, corpus_path, "registry"))
        if activate and entry.get("status") != "ready":
            raise RuntimeError(lt("Nur bereite Korpora können aktiviert werden", "Only ready corpora can be activated"))
        if activate:
            self._require_partial_import_acknowledgement(
                entry,
                acknowledge_partial_input=acknowledge_partial_input,
            )
        reg = self._registry()
        reg.register(corpus_path, activate=activate)
        reg = self._registry()
        return self._entry(
            CorpusRef(
                corpus_path.name,
                corpus_path,
                "registry",
                active=reg.active == str(corpus_path),
            )
        )

    def activate(
        self,
        name: str,
        *,
        acknowledge_partial_input: bool = False,
    ) -> dict[str, Any]:
        entry = self.inspect(name)
        if entry.get("status") != "ready":
            raise RuntimeError(lt("Nur bereite Korpora können aktiviert werden", "Only ready corpora can be activated"))
        self._require_partial_import_acknowledgement(
            entry,
            acknowledge_partial_input=acknowledge_partial_input,
        )
        path = Path(str(entry["path"])).expanduser().resolve(strict=False)
        reg = self._registry()
        reg.register(path, activate=True)
        return self._entry(CorpusRef(str(entry["name"]), path, str(entry.get("source") or "registry"), active=True))

    def unregister(self, name: str) -> dict[str, str]:
        wanted = str(name or "").strip()
        if not wanted or wanted.lower() == "default":
            raise RuntimeError(lt("Der Standard-Korpus kann nicht unregistert werden", "The default corpus cannot be unregistered"))
        reg = self._registry()
        matches = [Path(raw).expanduser().resolve(strict=False) for raw in reg.indices if Path(raw).name == wanted]
        if not matches:
            raise FileNotFoundError(lt("Registrierter Korpus nicht gefunden: {name}", "Registered corpus not found: {name}").format(name=wanted))
        path = matches[0]
        reg.unregister(path)
        return {"status": "ok", "path": str(path)}


__all__ = [
    "CorpusManifestStatus",
    "CorpusRef",
    "CorpusRegistryService",
    "CorpusStatus",
    "inspect_corpus_status",
    "_reject_overlong_corpus_name",
]
