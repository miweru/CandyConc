from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from setuptools import Extension, setup

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
#: Relative to the project directory, the working directory of every build.
#: cythonize joins it with the extension sources, and setuptools records the
#: result in SOURCES.txt of the sdist. An absolute path put the build
#: machine's directory (with the user name) there.
CYTHON_BUILD_DIR = Path("build") / "cython"
OPENMP_MODE_ENV = "CANDYCONC_ENABLE_OPENMP"
OPENMP_PREFIX_ENV = "CANDYCONC_OPENMP_PREFIX"
OPENMP_DEFAULT_PREFIXES = (
    Path("/opt/homebrew/opt/libomp"),
    Path("/usr/local/opt/libomp"),
)
OPENMP_SUPPORTED_PLATFORMS = {"darwin"}
OPENMP_DISABLED_MODES = {"0", "false", "no", "off", "disabled"}
OPENMP_AUTO_MODES = {"", "auto"}
OPENMP_REQUIRED_MODES = {"1", "true", "yes", "on", "force", "required"}
OPENMP_MODE_HELP = (
    f"{OPENMP_MODE_ENV}=auto|off|on. "
    "auto uses Homebrew/libomp when detected on macOS, off disables OpenMP, "
    f"and on/force requires libomp. Set {OPENMP_PREFIX_ENV} to override the libomp prefix."
)
LOCAL_ABSOLUTE_PATH_MARKERS = tuple(
    dict.fromkeys(
        marker
        for marker in (
            str(ROOT),
            str(Path.home()),
        )
        if marker and marker != "."
    )
)


@dataclass(frozen=True)
class NativeExtensionSpec:
    name: str
    source: Path
    openmp: bool = False


NATIVE_EXTENSION_SPECS: tuple[NativeExtensionSpec, ...] = (
    NativeExtensionSpec(
        "candyconc.core._fast_count",
        SRC / "candyconc" / "core" / "_fast_count.pyx",
        openmp=True,
    ),
    NativeExtensionSpec(
        "candyconc.core._fast_index",
        SRC / "candyconc" / "core" / "_fast_index.pyx",
    ),
    NativeExtensionSpec(
        "cqlhpc.cython._lexicon",
        SRC / "cqlhpc" / "cython" / "_lexicon.pyx",
    ),
    NativeExtensionSpec(
        "cqlhpc.cython._nfa",
        SRC / "cqlhpc" / "cython" / "_nfa.pyx",
    ),
    NativeExtensionSpec(
        "cqlhpc.cython._planner",
        SRC / "cqlhpc" / "cython" / "_planner.pyx",
    ),
    NativeExtensionSpec(
        "cqlhpc.cython._postings",
        SRC / "cqlhpc" / "cython" / "_postings.pyx",
    ),
)


def _numpy_include() -> str:
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - setup failure path
        raise SystemExit("numpy ist erforderlich für build_ext") from exc
    return str(np.get_include())


def _openmp_mode() -> str:
    raw_mode = os.getenv(OPENMP_MODE_ENV, "auto").strip().lower()
    if raw_mode in OPENMP_DISABLED_MODES:
        return "off"
    if raw_mode in OPENMP_AUTO_MODES:
        return "auto"
    if raw_mode in OPENMP_REQUIRED_MODES:
        return "required"
    raise SystemExit(f"ungültiger OpenMP-Modus {raw_mode!r}. {OPENMP_MODE_HELP}")


def _openmp_prefixes() -> tuple[Path, ...]:
    custom_prefix = os.getenv(OPENMP_PREFIX_ENV, "").strip()
    if custom_prefix:
        return (Path(custom_prefix),)
    return OPENMP_DEFAULT_PREFIXES


def _openmp_flags(
    prefixes: tuple[Path, ...] | None = None,
    *,
    platform: str | None = None,
) -> tuple[list[str], list[str]]:
    mode = _openmp_mode()
    if mode == "off":
        return [], []

    platform_name = platform or sys.platform
    if platform_name not in OPENMP_SUPPORTED_PLATFORMS:
        if mode == "required":
            raise SystemExit(
                "OpenMP angefordert, aber diese Release-Konfiguration aktiviert "
                f"OpenMP nur auf macOS/Homebrew ({platform_name}). {OPENMP_MODE_HELP}"
            )
        return [], []

    for prefix in prefixes or _openmp_prefixes():
        include_dir = prefix / "include"
        lib_dir = prefix / "lib"
        if include_dir.exists() and lib_dir.exists():
            return (
                ["-Xpreprocessor", "-fopenmp", f"-I{include_dir}"],
                [f"-L{lib_dir}", "-lomp"],
            )

    if mode == "required":
        checked = ", ".join(str(prefix) for prefix in prefixes or _openmp_prefixes())
        raise SystemExit(f"OpenMP angefordert, aber libomp wurde nicht gefunden ({checked}). {OPENMP_MODE_HELP}")
    return [], []


def _release_link_args(*, platform: str | None = None) -> list[str]:
    """Strip macOS debug symbol metadata that exposes local build paths."""
    if (platform or sys.platform) == "darwin":
        return ["-Wl,-S"]
    return []


def generated_c_sources() -> dict[str, Path]:
    return {spec.name: spec.source.with_suffix(".c") for spec in NATIVE_EXTENSION_SPECS}


def generated_c_sources_with_local_absolute_paths(
    sources: dict[str, Path] | None = None,
    *,
    markers: tuple[str, ...] = LOCAL_ABSOLUTE_PATH_MARKERS,
) -> dict[str, tuple[str, ...]]:
    """Return generated C sources that embed local absolute build paths.

    Cython can stamp the build host's include and source paths into generated C
    headers. The release sdist regenerates C from .pyx instead of shipping these
    files blindly.
    """
    unsafe: dict[str, tuple[str, ...]] = {}
    for name, source in (sources or generated_c_sources()).items():
        if not source.exists():
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        matches = tuple(marker for marker in markers if marker and marker in text)
        if matches:
            unsafe[name] = matches
    return unsafe


def native_extensions() -> list[Extension]:
    include_dirs = [_numpy_include()]
    openmp_compile_args, openmp_link_args = _openmp_flags()
    release_link_args = _release_link_args()
    extensions: list[Extension] = []
    for spec in NATIVE_EXTENSION_SPECS:
        compile_args = ["-O3"]
        link_args = list(release_link_args)
        if spec.openmp:
            compile_args.extend(openmp_compile_args)
            link_args.extend(openmp_link_args)
        source = spec.source.relative_to(ROOT)
        extensions.append(
            Extension(
                spec.name,
                [str(source)],
                include_dirs=include_dirs,
                extra_compile_args=compile_args,
                extra_link_args=link_args,
            )
        )
    return extensions


def build_extensions() -> list[Extension]:
    try:
        from Cython.Build import cythonize
    except Exception as exc:  # pragma: no cover - setup failure path
        raise SystemExit("Cython ist erforderlich für build_ext") from exc
    return cythonize(
        native_extensions(),
        build_dir=str(CYTHON_BUILD_DIR),
        compiler_directives={"language_level": "3"},
    )


def main() -> None:
    setup(
        name="candyconc-native",
        package_dir={"": "src"},
        ext_modules=build_extensions(),
    )


if __name__ == "__main__":
    main()
