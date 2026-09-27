from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path

if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from candyconc.config import get as get_config, set as set_config, APP_CONFIG
from candyconc import model_registry
from candyconc.i18n import lt
from candyconc.services.semantic.availability import (
    semantic_artifacts_available,
    semantic_search_available,
)
from ..task_manager import task_manager
from . import auth
try:  # optional dependency
    import faiss  # type: ignore
except Exception:  # pragma: no cover - faiss missing
    faiss = None  # type: ignore

import numpy as np

logger = logging.getLogger(__name__)


class StartupManager:
    """Manage background services for the backend."""

    def __init__(
        self,
        index,
        realtime_dir: Path,
    ) -> None:
        self.index = index
        self.realtime_dir = Path(realtime_dir)
        self.faiss_index_obj = None
        self.faiss_vecs_mmap = None
        self.passages: list[str] = []
        self.faiss_status = "unavailable"
        self.faiss_status_detail: str | None = None
        self.faiss_build_task: asyncio.Task | None = None
        self.observability = None

    def _set_faiss_status(self, status: str, detail: str | None = None) -> None:
        self.faiss_status = status
        self.faiss_status_detail = detail

    async def _load_faiss(self, index_path: Path, vecs_path: Path, texts_path: Path) -> None:
        start = time.perf_counter()
        logger.info("Loading FAISS index and vectors...")
        emb_enabled = semantic_search_available(index_path.parent)
        faiss_enabled = get_config("ENABLE_FAISS") == "1" or emb_enabled
        if not faiss_enabled:
            self._set_faiss_status(
                "unavailable",
                lt(
                    "FAISS deaktiviert oder semantische Assets fehlen.",
                    "FAISS is disabled or the semantic assets are missing.",
                ),
            )
            duration = time.perf_counter() - start
            logger.info("FAISS load skipped (disabled) in %.2fs", duration)
            return
        if faiss is None:
            self._set_faiss_status(
                "error",
                lt(
                    "FAISS fehlt, aber Embedding Search ist aktiv.",
                    "FAISS is missing, but embedding search is enabled.",
                ),
            )
            logger.error("FAISS fehlt, aber Embedding Search ist aktiv.")
            return
        if not index_path.exists() and semantic_artifacts_available(
            index_path.parent,
            backend="gemma",
            level="doc",
        ):
            self._set_faiss_status("ready", None)
            logger.info("Gemma document index is available; legacy passage index load skipped.")
            return
        if not index_path.exists():
            self._set_faiss_status(
                "error",
                lt(
                    "FAISS Index fehlt. Bitte Index neu bauen.",
                    "The FAISS index is missing. Rebuild the index.",
                ),
            )
            return
        if not vecs_path.exists():
            self._set_faiss_status(
                "error",
                lt(
                    "FAISS Vektoren fehlen. Bitte Index neu bauen.",
                    "The FAISS vectors are missing. Rebuild the index.",
                ),
            )
            return
        if not texts_path.exists():
            self._set_faiss_status(
                "error",
                lt(
                    "Passage Texte fehlen. Bitte Index neu bauen.",
                    "The passage texts are missing. Rebuild the index.",
                ),
            )
            return
        meta_path = index_path.parent / "embedding_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
                spacy_model = meta.get("spacy_model")
                if isinstance(spacy_model, str) and spacy_model:
                    # set_config write-through now mirrors model fields into
                    # os.environ (seam F), so the explicit poke is redundant.
                    set_config("CANDYCONC_EMB_SPACY_MODEL", spacy_model)
            except Exception:
                logger.exception("Failed to load embedding_meta.json")
        try:
            self.faiss_index_obj = model_registry.get_faiss_index(index_path)
        except Exception as exc:
            self._set_faiss_status(
                "error",
                lt(
                    "FAISS Index konnte nicht geladen werden: {error}",
                    "The FAISS index could not be loaded: {error}",
                ).format(error=exc),
            )
            logger.exception("Failed to load FAISS index")
            return
        try:
            nprobe_raw = get_config("CANDYCONC_FAISS_NPROBE", "0")
            nprobe = int(nprobe_raw or 0)
        except Exception:
            nprobe = 0
        if nprobe > 0 and hasattr(self.faiss_index_obj, "nprobe"):
            try:
                nlist = getattr(self.faiss_index_obj, "nlist", None)
                if nlist:
                    nprobe = min(int(nprobe), int(nlist))
                self.faiss_index_obj.nprobe = int(nprobe)
            except Exception:
                pass
        try:
            self.faiss_vecs_mmap = np.load(vecs_path, mmap_mode="r")
            self.passages = json.loads(texts_path.read_text("utf-8"))
        except Exception as exc:
            self._set_faiss_status(
                "error",
                lt(
                    "FAISS Daten konnten nicht geladen werden: {error}",
                    "The FAISS data could not be loaded: {error}",
                ).format(error=exc),
            )
            logger.exception("Failed to init FAISS shared state")
            return
        self._set_faiss_status("ready", None)
        duration = time.perf_counter() - start
        logger.info("FAISS load completed in %.2fs", duration)

    def _check_corpus(self) -> None:
        if self.index.num_tokens() > 0:
            return
        logger.warning(
            "No corpus indexed. Build the Fast Index from Parquet before starting the backend."
        )
        if APP_CONFIG.DRY_RUN:
            return

    def _check_dependencies(self) -> None:
        # All release native extensions must import before the backend starts.
        from candyconc.core.native_extensions import require_native_extensions

        require_native_extensions()

        # Import wrappers after the direct smoke check so runtime symbols are initialized.
        from candyconc.core import fast_index_native  # noqa: F401
        from candyconc.core import counting_kernels  # noqa: F401

        # Embedding dependencies
        emb_enabled = semantic_search_available(getattr(self.index.fast_index, "index_path", None))
        emb_backend = get_config("CANDYCONC_EMB_BACKEND", "spacy").lower()
        if emb_enabled:
            if emb_backend == "none":
                raise RuntimeError("Embedding Backend ist deaktiviert, aber Embedding Search ist aktiv.")
            if emb_backend == "spacy":
                from candyconc.candyconc_copilot.vectorizer import SpaCyEmbeddings

                SpaCyEmbeddings()

        # FAISS dependencies
        if get_config("ENABLE_FAISS") == "1" or emb_enabled:
            if faiss is None:
                self._set_faiss_status(
                    "error",
                    lt(
                        "FAISS fehlt, aber FAISS oder Embedding Search ist aktiviert.",
                        "FAISS is missing, but FAISS or embedding search is enabled.",
                    ),
                )
                logger.error("FAISS fehlt, aber FAISS oder Embedding Search ist aktiviert.")
                return

    async def start(self, index_path: Path, vecs_path: Path, texts_path: Path) -> None:
        start = time.perf_counter()
        logger.info("Starting background services...")
        auth.validate_release_security()
        self._check_dependencies()
        if get_config("CANDYCONC_ENABLE_OTEL", "0") == "1":
            from candyconc.candyconc_copilot.observability import Observability

            self.observability = Observability(service_name="backend")
        else:
            self.observability = None
        await task_manager.start()
        await self._load_faiss(index_path, vecs_path, texts_path)
        self._check_corpus()
        if auth.RBAC_ENABLED and not auth.have_users():
            print(
                "RBAC enabled but no users configured. Use the AdminPanel or POST /users to create an admin."
            )
        duration = time.perf_counter() - start
        logger.info("Background services started in %.2fs", duration)

    async def stop(self) -> None:
        await task_manager.stop()
        await self.reset_faiss_build()

    async def reset_faiss_build(self) -> None:
        if self.faiss_build_task is not None:
            if not self.faiss_build_task.done():
                self.faiss_build_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.faiss_build_task
            self.faiss_build_task = None


async def start_without_corpus() -> None:
    """Start the corpus-independent services for a server without any corpus.

    Runs the same security and native-extension checks as
    :meth:`StartupManager.start` and the task manager, so imports started from
    the interface work. FAISS and the corpus checks follow once a corpus is
    activated (``reload_default_corpus_runtime_state``).
    """
    auth.validate_release_security()
    from candyconc.core.native_extensions import require_native_extensions

    require_native_extensions()
    await task_manager.start()


async def stop_without_corpus() -> None:
    await task_manager.stop()
