"""Reusable disk-space preflight for corpus import builds.

The heuristic mirrors the one battle-tested in
``scripts/jobs/build_fast_index_from_parquet.py::_preflight_checks``: the
estimated build footprint is ``input_size * factor`` (plus optional embedding /
word-FAISS surcharges), compared against the free space on the output volume
with a fixed reserve. Everything stays env-tunable with the SAME variables the
parquet builder honours, so operators only learn one set of knobs:

* ``CANDYCONC_BUILD_DISK_FACTOR``      base multiplier (default 2.5)
* ``CANDYCONC_BUILD_DISK_RESERVE_GB``  reserve kept free (default 5)
* ``CANDYCONC_BUILD_ALLOW_LOW_DISK``   ``1`` downgrades the block to a warning

This module is import-light (stdlib only) so both the FastAPI preflight route
and the standalone adapter CLIs can share it.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict

from candyconc.i18n import LocalizedText, lt

DISK_FACTOR_ENV = "CANDYCONC_BUILD_DISK_FACTOR"
DISK_RESERVE_ENV = "CANDYCONC_BUILD_DISK_RESERVE_GB"
ALLOW_LOW_DISK_ENV = "CANDYCONC_BUILD_ALLOW_LOW_DISK"

_DEFAULT_FACTOR = 2.5
_DEFAULT_RESERVE_GB = 5.0
_LOW_ABSOLUTE_BYTES = 5 * 1024**3


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def size_text(num_bytes: int) -> LocalizedText:
    """A size in B, KB, MB, GB or TB (1024 based), one decimal, as a text pair."""
    value = float(max(0, int(num_bytes)))
    unit = "B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            break
        value /= 1024
    en = f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
    return lt(en.replace(".", ","), en)


def allow_low_disk() -> bool:
    return os.environ.get(ALLOW_LOW_DISK_ENV, "0") == "1"


def estimate_build_disk_need(
    input_size_bytes: int,
    *,
    build_embeddings: bool = False,
    build_word_faiss: bool = False,
    build_gemma_embeddings: bool = False,
) -> int:
    """Estimated on-disk build footprint (same factor heuristic as the parquet builder)."""
    base_factor = _env_float(DISK_FACTOR_ENV, _DEFAULT_FACTOR)
    emb_factor = 0.5 if (build_embeddings or build_word_faiss) else 0.0
    gemma_factor = 0.75 if build_gemma_embeddings else 0.0
    return int(max(0, int(input_size_bytes)) * (base_factor + emb_factor + gemma_factor))


def _nearest_existing(path: Path) -> Path | None:
    probe = Path(path).expanduser().resolve(strict=False)
    for candidate in (probe, *probe.parents):
        if candidate.exists():
            return candidate
    return None


def check_disk_space(
    input_size_bytes: int,
    output_path: str | os.PathLike[str],
    *,
    build_embeddings: bool = False,
    build_word_faiss: bool = False,
    build_gemma_embeddings: bool = False,
) -> Dict[str, Any]:
    """Compare estimated need against the free space of ``output_path``'s volume.

    Returns a dict with:

    * ``status``: ``"pass"`` | ``"warn"`` | ``"fail"`` | ``"unknown"``
    * ``blocking``: True only for ``"fail"``
    * ``message``: human-readable summary (German and English text pair)
    * ``disk_free`` / ``disk_required_est`` / ``disk_reserve`` / ``disk_factor``
    * ``probe_path``: the existing directory whose volume was measured
    * ``allow_low_disk``: whether the env override downgraded a block

    Never raises: an unreadable volume yields ``status="unknown"`` (a warning,
    never a block) so the check cannot brick imports on exotic filesystems.
    """
    reserve = int(_env_float(DISK_RESERVE_ENV, _DEFAULT_RESERVE_GB) * 1024**3)
    factor = _env_float(DISK_FACTOR_ENV, _DEFAULT_FACTOR)
    estimated_need = estimate_build_disk_need(
        input_size_bytes,
        build_embeddings=build_embeddings,
        build_word_faiss=build_word_faiss,
        build_gemma_embeddings=build_gemma_embeddings,
    )
    result: Dict[str, Any] = {
        "disk_required_est": estimated_need,
        "disk_reserve": reserve,
        "disk_factor": factor,
        "input_size_bytes": int(max(0, int(input_size_bytes))),
        "allow_low_disk": allow_low_disk(),
    }
    probe = _nearest_existing(Path(output_path))
    if probe is None:
        result.update(
            status="unknown",
            blocking=False,
            message=lt("Freier Speicher konnte nicht ermittelt werden (Zielpfad unauflösbar).", "Free disk space could not be determined (target path cannot be resolved)."),
        )
        return result
    result["probe_path"] = str(probe)
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        result.update(
            status="unknown",
            blocking=False,
            message=lt("Freier Speicher konnte nicht ermittelt werden: {error}", "Free disk space could not be determined: {error}").format(error=exc),
        )
        return result
    free = int(usage.free)
    result["disk_free"] = free
    if free < estimated_need + reserve:
        message = lt(
            "Wenig freier Speicher für den Build: {free} frei, "
            "geschätzter Bedarf {need} plus Reserve {reserve}. "
            "Override: {env}=1.",
            "Low free disk space for the build: {free} free, "
            "estimated need {need} plus a reserve of {reserve}. "
            "Override: {env}=1.",
        ).format(
            free=size_text(free),
            need=size_text(estimated_need),
            reserve=size_text(reserve),
            env=ALLOW_LOW_DISK_ENV,
        )
        if result["allow_low_disk"]:
            result.update(status="warn", blocking=False, message=message)
        else:
            result.update(status="fail", blocking=True, message=message)
        return result
    if free < _LOW_ABSOLUTE_BYTES:
        result.update(
            status="warn",
            blocking=False,
            message=lt("Wenig freier Speicher (<5GB). Der Build kann scheitern.", "Low free disk space (<5GB). The build can fail."),
        )
        return result
    result.update(
        status="pass",
        blocking=False,
        message=lt(
            "Freier Speicher reicht für den geschätzten Bedarf ({free} frei, Bedarf {need}).",
            "Free disk space is sufficient for the estimated need ({free} free, need {need}).",
        ).format(free=size_text(free), need=size_text(estimated_need)),
    )
    return result
