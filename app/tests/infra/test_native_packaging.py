from __future__ import annotations

import importlib.util
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11 test environments
    import tomli as tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS_DEV = ROOT / "requirements-dev.txt"
MANIFEST = ROOT / "MANIFEST.in"
GITIGNORE = ROOT / ".gitignore"
SETUP_NATIVE = ROOT / "setup_native.py"
SETUP_PY = ROOT / "setup.py"

EXPECTED_NATIVE_EXTENSIONS = {
    "candyconc.core._fast_count": ROOT / "src" / "candyconc" / "core" / "_fast_count.pyx",
    "candyconc.core._fast_index": ROOT / "src" / "candyconc" / "core" / "_fast_index.pyx",
    "cqlhpc.cython._lexicon": ROOT / "src" / "cqlhpc" / "cython" / "_lexicon.pyx",
    "cqlhpc.cython._nfa": ROOT / "src" / "cqlhpc" / "cython" / "_nfa.pyx",
    "cqlhpc.cython._planner": ROOT / "src" / "cqlhpc" / "cython" / "_planner.pyx",
    "cqlhpc.cython._postings": ROOT / "src" / "cqlhpc" / "cython" / "_postings.pyx",
}

REQUIREMENTS = ROOT / "requirements.txt"

#: Every package here is imported by a core code path (server start, import,
#: statistics, export). scipy backs core/significance.py, psutil the memory
#: preflight of the import.
REQUIRED_RUNTIME_DEPENDENCIES = {
    "anytree",
    "fastapi",
    "google-re2",
    "httpx",
    "jsonschema",
    "networkx",
    "numpy",
    "openpyxl",
    "orjson",
    "pandas",
    "platformdirs",
    "polars",
    "psutil",
    "pydantic",
    "pydantic-settings",
    "pyarrow",
    "rapidfuzz",
    "scipy",
    "spacy",
    "uvicorn",
    "websockets",
}

#: No module under src/ imports these. torch and sentence-transformers made the
#: wheel pull CUDA packages on Linux and blocked macOS x86_64, annoy needed a
#: C++ compiler. faiss is the optional extra "semantic". tiktoken downloaded an
#: encoding file on first use and is not used any more.
NOT_CORE_DEPENDENCIES = {
    "annoy",
    "bert-score",
    "cython",
    "faiss-cpu",
    "sentence-transformers",
    "setuptools",
    "tiktoken",
    "torch",
    "transformers",
}


def _requirement_name(requirement: str) -> str:
    for marker in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";"):
        if marker in requirement:
            requirement = requirement.split(marker, 1)[0]
    return requirement.strip().replace("_", "-").lower()


def _normalize_package_name(name: str) -> str:
    return name.replace("_", "-").lower()


def _load_setup_native_module():
    spec = importlib.util.spec_from_file_location("setup_native_for_test", SETUP_NATIVE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_setup_kwargs(monkeypatch) -> dict:
    import setuptools
    from Cython import Build

    captured: dict = {}
    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(Build, "cythonize", lambda extensions, **_kwargs: extensions)
    spec = importlib.util.spec_from_file_location("setup_for_test", SETUP_PY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return captured


def test_runtime_native_gate_covers_all_required_extensions(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    from candyconc.core import native_extensions

    seen: list[str] = []

    def fake_importer(module_name: str):
        seen.append(module_name)
        return object()

    native_extensions.require_native_extensions(importer=fake_importer)

    assert tuple(seen) == native_extensions.REQUIRED_NATIVE_EXTENSIONS
    assert set(native_extensions.REQUIRED_NATIVE_EXTENSIONS) == set(EXPECTED_NATIVE_EXTENSIONS)


def test_runtime_native_gate_reports_missing_extensions(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    from candyconc.core import native_extensions

    def fake_importer(module_name: str):
        if module_name == "cqlhpc.cython._postings":
            raise ImportError("boom")
        return object()

    with pytest.raises(RuntimeError, match="cqlhpc.cython._postings"):
        native_extensions.require_native_extensions(importer=fake_importer)


def test_cqlhpc_native_wrapper_catalog_is_explicit(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    from cqlhpc.cython import CQLHPC_NATIVE_EXTENSIONS, require_cqlhpc_native_extensions

    seen: list[str] = []

    def fake_importer(module_name: str):
        seen.append(module_name)
        return object()

    require_cqlhpc_native_extensions(importer=fake_importer)

    assert tuple(seen) == CQLHPC_NATIVE_EXTENSIONS
    assert set(CQLHPC_NATIVE_EXTENSIONS) == {
        "cqlhpc.cython._lexicon",
        "cqlhpc.cython._nfa",
        "cqlhpc.cython._planner",
        "cqlhpc.cython._postings",
    }


def test_setup_native_declares_all_required_extensions():
    module = _load_setup_native_module()
    specs = {spec.name: spec.source for spec in module.NATIVE_EXTENSION_SPECS}

    assert specs == EXPECTED_NATIVE_EXTENSIONS
    for source in specs.values():
        assert source.exists(), f"native extension source missing: {source}"


def test_setup_native_extension_objects_are_import_safe(monkeypatch):
    monkeypatch.setenv("CANDYCONC_ENABLE_OPENMP", "off")
    module = _load_setup_native_module()
    extensions = {extension.name: extension for extension in module.native_extensions()}

    assert set(extensions) == set(EXPECTED_NATIVE_EXTENSIONS)
    for name, source in EXPECTED_NATIVE_EXTENSIONS.items():
        assert extensions[name].sources == [str(source.relative_to(ROOT))]


def test_setup_native_generates_c_only_in_the_ignored_build_directory(monkeypatch):
    from Cython import Build

    module = _load_setup_native_module()
    captured: dict = {}
    monkeypatch.setattr(
        Build,
        "cythonize",
        lambda extensions, **kwargs: captured.update(kwargs) or extensions,
    )

    module.build_extensions()

    # Relative to the project directory, the working directory of every build
    # (the extension sources are relative to it as well).
    assert captured["build_dir"] == str(Path("build") / "cython")


def test_generated_c_paths_are_relative_to_the_project(monkeypatch, tmp_path):
    """The C sources that cythonize returns end up in SOURCES.txt of the sdist.

    With an absolute build directory they carried the path of the build
    machine, user name included (RC0 report, B2).
    """
    pytest.importorskip("Cython")
    module = _load_setup_native_module()
    pyx = tmp_path / "src" / "pkg" / "_probe.pyx"
    pyx.parent.mkdir(parents=True)
    pyx.write_text("def one():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "NATIVE_EXTENSION_SPECS", (module.NativeExtensionSpec("pkg._probe", pyx),))
    monkeypatch.setenv("CANDYCONC_ENABLE_OPENMP", "off")
    monkeypatch.chdir(tmp_path)

    (extension,) = module.build_extensions()

    (source,) = extension.sources
    assert not Path(source).is_absolute()
    assert Path(source).parts[:2] == ("build", "cython")
    assert (tmp_path / source).is_file()


def test_setup_native_openmp_modes_are_explicit(monkeypatch, tmp_path):
    module = _load_setup_native_module()
    missing_prefix = tmp_path / "missing-libomp"

    monkeypatch.setenv(module.OPENMP_MODE_ENV, "off")
    assert module._openmp_flags(prefixes=(missing_prefix,), platform="darwin") == ([], [])

    monkeypatch.setenv(module.OPENMP_MODE_ENV, "auto")
    assert module._openmp_flags(prefixes=(missing_prefix,), platform="darwin") == ([], [])

    libomp_prefix = tmp_path / "libomp"
    (libomp_prefix / "include").mkdir(parents=True)
    (libomp_prefix / "lib").mkdir()
    monkeypatch.setenv(module.OPENMP_MODE_ENV, "on")
    compile_args, link_args = module._openmp_flags(prefixes=(libomp_prefix,), platform="darwin")
    assert "-fopenmp" in compile_args
    assert f"-I{libomp_prefix / 'include'}" in compile_args
    assert f"-L{libomp_prefix / 'lib'}" in link_args
    assert "-lomp" in link_args

    monkeypatch.setenv(module.OPENMP_PREFIX_ENV, str(libomp_prefix))
    compile_args, link_args = module._openmp_flags(platform="darwin")
    assert f"-I{libomp_prefix / 'include'}" in compile_args
    assert f"-L{libomp_prefix / 'lib'}" in link_args

    monkeypatch.setenv(module.OPENMP_MODE_ENV, "required")
    with pytest.raises(SystemExit, match="OpenMP angefordert"):
        module._openmp_flags(prefixes=(missing_prefix,), platform="darwin")

    monkeypatch.setenv(module.OPENMP_MODE_ENV, "maybe")
    with pytest.raises(SystemExit, match="ungültiger OpenMP-Modus"):
        module._openmp_flags(prefixes=(missing_prefix,), platform="darwin")


def test_setup_native_openmp_is_platform_gated(monkeypatch, tmp_path):
    module = _load_setup_native_module()
    libomp_prefix = tmp_path / "libomp"
    (libomp_prefix / "include").mkdir(parents=True)
    (libomp_prefix / "lib").mkdir()

    monkeypatch.setenv(module.OPENMP_MODE_ENV, "auto")
    assert module._openmp_flags(prefixes=(libomp_prefix,), platform="linux") == ([], [])

    monkeypatch.setenv(module.OPENMP_MODE_ENV, "required")
    with pytest.raises(SystemExit, match="macOS/Homebrew"):
        module._openmp_flags(prefixes=(libomp_prefix,), platform="linux")


def test_setup_native_strips_macos_debug_symbols_from_release_binaries():
    module = _load_setup_native_module()

    assert module._release_link_args(platform="darwin") == ["-Wl,-S"]
    assert module._release_link_args(platform="linux") == []


def test_generated_c_policy_tracks_native_siblings():
    module = _load_setup_native_module()
    generated_sources = module.generated_c_sources()

    assert set(generated_sources) == set(EXPECTED_NATIVE_EXTENSIONS)
    for name, pyx_source in EXPECTED_NATIVE_EXTENSIONS.items():
        c_source = pyx_source.with_suffix(".c")
        assert generated_sources[name] == c_source
        # The generated C next to the .pyx is a build artifact: builds
        # regenerate it under build/cython, the sdist excludes it, and the
        # exported repository leaves it out because Cython stamps the build
        # host's absolute paths into it. Where it exists, the path check
        # (generated_c_sources_with_local_absolute_paths) applies.


def test_generated_c_policy_detects_local_absolute_paths(tmp_path):
    module = _load_setup_native_module()
    c_source = tmp_path / "module.c"
    c_source.write_text('/* "/Users/release-builder/project/src/module.pyx" */\n', encoding="utf-8")

    unsafe = module.generated_c_sources_with_local_absolute_paths(
        {"example.module": c_source},
        markers=("/Users/release-builder",),
    )

    assert unsafe == {"example.module": ("/Users/release-builder",)}


def test_makefile_has_native_build_target():
    text = MAKEFILE.read_text()

    assert "PYTHON ?= python3" in text
    assert "native:" in text
    assert "\t$(PYTHON) setup_native.py build_ext --inplace" in text
    assert "wheel:" in text
    assert "\t$(PYTHON) -m build --wheel" in text
    assert "sdist:" in text
    assert "\t$(PYTHON) -m build --sdist" in text


def test_pyproject_declares_core_runtime_dependencies():
    data = tomllib.loads(PYPROJECT.read_text())
    declared = {_requirement_name(item) for item in data["project"]["dependencies"]}

    assert not REQUIRED_RUNTIME_DEPENDENCIES - declared
    assert not NOT_CORE_DEPENDENCIES & declared


def test_requirements_txt_mirrors_pyproject_dependencies():
    data = tomllib.loads(PYPROJECT.read_text())
    lines = [
        line.split("#", 1)[0].strip()
        for line in REQUIREMENTS.read_text().splitlines()
    ]
    assert [line for line in lines if line] == data["project"]["dependencies"]


def test_optional_extras_carry_the_optional_packages():
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    names = {extra: {_requirement_name(item) for item in items} for extra, items in extras.items()}

    assert names["semantic"] == {"faiss-cpu"}
    assert names["hf"] == {"datasets"}
    assert names["metrics"] == {"prometheus-client"}
    assert names["cluster"] == {"hdbscan"}
    assert names["all"] == names["semantic"] | names["hf"] | names["metrics"] | names["cluster"]


def test_project_metadata_is_complete():
    project = tomllib.loads(PYPROJECT.read_text())["project"]

    assert project["name"] == "candyconc"
    assert project["requires-python"] == ">=3.11"
    assert project["license"] == "MIT"
    assert project["scripts"] == {"candy": "candyconc.entrypoints.cli:main"}
    assert "Source" in project["urls"]
    assert not any("@example.com" in author.get("email", "") for author in project["authors"])
    assert "tool" not in tomllib.loads(PYPROJECT.read_text()) or "poetry" not in tomllib.loads(
        PYPROJECT.read_text()
    )["tool"]


def test_pyproject_uses_setuptools_native_build_backend():
    data = tomllib.loads(PYPROJECT.read_text())
    build_system = data["build-system"]
    requires = {_normalize_package_name(requirement.split(">", 1)[0].split("<", 1)[0]) for requirement in build_system["requires"]}

    assert build_system["build-backend"] == "setuptools.build_meta"
    assert {"setuptools", "wheel", "cython", "numpy"} <= requires


def test_setup_py_delegates_to_native_extension_catalog(monkeypatch):
    kwargs = _load_setup_kwargs(monkeypatch)

    assert kwargs["package_dir"] == {"": "src"}
    assert {extension.name for extension in kwargs["ext_modules"]} == set(EXPECTED_NATIVE_EXTENSIONS)
    assert kwargs["include_package_data"] is True
    assert kwargs["exclude_package_data"] == {"": ["*.c", "*.pyx"]}
    # Metadata and dependencies come from pyproject.toml alone.
    for key in ("name", "version", "install_requires", "extras_require", "python_requires", "entry_points"):
        assert key not in kwargs, key


def test_setup_py_ships_the_built_interface(monkeypatch, tmp_path):
    kwargs = _load_setup_kwargs(monkeypatch)
    web_dist = ROOT / "src" / "candyconc" / "web_dist"
    if (web_dist / "index.html").is_file():
        assert "candyconc.web_dist" in kwargs["packages"]
        assert "index.html" in kwargs["package_data"]["candyconc.web_dist"]
        assert "THIRD_PARTY_LICENSES.txt" in kwargs["package_data"]["candyconc.web_dist"]
        if (web_dist / "assets").is_dir():
            assert kwargs["package_data"]["candyconc.web_dist.assets"]
    else:
        assert not any(key.startswith("candyconc.web_dist") for key in kwargs["package_data"])
    # The optional HTML manual (packaging/build_web.py with Sphinx) is package
    # data of candyconc when it was built, and absent otherwise.
    docs_html = ROOT / "src" / "candyconc" / "docs_html"
    if (docs_html / "index.html").is_file():
        assert kwargs["package_data"]["candyconc"] == ["docs_html/**/*"]
    else:
        assert "candyconc" not in kwargs["package_data"]


def test_dev_requirements_include_pep517_builder():
    text = REQUIREMENTS_DEV.read_text()

    assert "build>=1.2,<2" in text


def test_sdist_manifest_includes_native_build_inputs():
    text = MANIFEST.read_text()

    for entry in ("requirements.txt", "setup.py", "setup_native.py"):
        assert f"include {entry}" in text
    assert "recursive-include src *.pyx" in text
    assert "recursive-include src/candyconc/web_dist *" in text
    assert "recursive-include src/candyconc/docs_html *" in text
    assert "recursive-include src *.c" not in text
    assert "Generated C can embed local absolute build paths" in text
    assert "prune build" in text
    assert "recursive-exclude src *.c" in text
    for pattern in ("*.so", "*.pyd", "*.dylib", "*.pyc"):
        assert f"global-exclude {pattern}" in text
    assert "recursive-exclude * __pycache__" in text


def test_native_binary_and_build_outputs_are_ignored():
    text = GITIGNORE.read_text()

    for pattern in ("*.so", "*.pyd", "*.dylib", "build/", "src/build/", "src/**/build/"):
        assert pattern in text
