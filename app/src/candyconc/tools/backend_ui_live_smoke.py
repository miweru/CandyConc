from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen


def _backend_src(root: Path) -> Path:
    for app in (root / "app", root / "app"):
        if (app / "src" / "candyconc").is_dir():
            return app / "src"
    raise RuntimeError(f"CandyConc app/src not found under {root}")


def _repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in (here, *here.parents):
        if (parent / "candyconc-web" / "package.json").is_file():
            _backend_src(parent)
            return parent
    raise RuntimeError("Repository with candyconc-web and app/src not found")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http(url: str, *, timeout: float, expected_status: int = 200) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == expected_status:
                    return
        except Exception as exc:  # pragma: no cover - depends on process timing
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(
        f"HTTP endpoint nicht rechtzeitig bereit: {url} "
        f"(expected {expected_status}, last error: {last_error})"
    )


def _tail(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def _pythonpath(root: Path, env: dict[str, str]) -> str:
    parts = [
        str(_backend_src(root)),
        str(root),
    ]
    existing = env.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


def build_smoke_index(root: Path, work_dir: Path) -> Path:
    """Build a tiny CandyConc-only index outside tempfile.

    The backend deliberately rejects `tempfile.gettempdir()` indices, because a
    release server must not silently bind to throwaway paths. The live smoke
    therefore uses the repo-local ignored `.tmp` tree and isolated application
    state for the registry and projects.
    """

    index_path = work_dir / "index"
    if index_path.exists():
        shutil.rmtree(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(root))
    sys.path.insert(0, str(_backend_src(root)))

    import numpy as np
    import spacy
    from spacy.attrs import DEP, HEAD
    from spacy.language import Language
    from candyconc.ingest import build_fast_index_from_parquet as build_mod

    component_name = "backend_ui_live_smoke_fake_annot"
    if component_name not in Language.factories:

        @Language.component(component_name)
        def _fake_annot(doc):  # type: ignore[no-untyped-def]
            for tok in doc:
                tok.lemma_ = tok.lower_
                tok.pos_ = "X"
            words = [tok.text for tok in doc]
            root_idx = next(
                (idx for idx, word in enumerate(words) if word in {"springt", "läuft", "sieht", "mag"}),
                0,
            )
            dep_labels = ["ROOT"] * len(doc)
            head_offsets = [0] * len(doc)

            def _attach(index: int, head: int, dep: str) -> None:
                dep_labels[index] = dep
                head_offsets[index] = int(head) - int(index)

            for idx, word in enumerate(words):
                if word in {"Der", "Ein", "den", "zweiter"}:
                    target = next((j for j in range(idx + 1, len(words)) if words[j] in {"Hase", "Hund"}), root_idx)
                    _attach(idx, target, "nk")
                elif word == "Hase":
                    if "sieht" in words and idx > words.index("sieht"):
                        _attach(idx, root_idx, "oa")
                    else:
                        _attach(idx, root_idx, "sb")
                elif word == "Hund":
                    _attach(idx, root_idx, "sb")
                elif word == "Karotte":
                    _attach(idx, root_idx, "oa")
                elif word in {"schnell", "langsam"}:
                    _attach(idx, root_idx, "mo")
                elif word == ".":
                    _attach(idx, root_idx, "punct")
                elif idx == root_idx:
                    _attach(idx, idx, "ROOT")

            dep_ids = [doc.vocab.strings.add(dep) for dep in dep_labels]
            attrs = np.zeros((len(doc), 2), dtype="uint64")
            attrs[:, 0] = np.asarray(head_offsets, dtype="int64").astype("uint64")
            attrs[:, 1] = np.asarray(dep_ids, dtype="uint64")
            doc.from_array([HEAD, DEP], attrs)
            return doc

    def _blank_load(_name: str, disable: object = None, **_kw: object):  # type: ignore[no-untyped-def]
        nlp = spacy.blank("de")
        nlp.add_pipe(component_name, name="parser")
        return nlp

    real_load = spacy.load
    spacy.load = _blank_load
    try:
        build_mod.build_fast_index_from_rows(
            [
                {"id": "d1", "text": "Der Hase springt schnell .", "register": "smoke"},
                {"id": "d2", "text": "Ein zweiter Hase läuft langsam .", "register": "smoke"},
                {"id": "d3", "text": "Der Hund sieht den Hase .", "register": "smoke"},
                {"id": "d4", "text": "Der Hase mag Karotte .", "register": "smoke"},
                {"id": "d5", "text": "Der Hase mag Karotte .", "register": "smoke"},
                {"id": "d6", "text": "Der Hase mag Karotte .", "register": "smoke"},
                {"id": "d7", "text": "Der Hase mag Karotte .", "register": "smoke"},
                {"id": "d8", "text": "Der Hase mag Karotte .", "register": "smoke"},
            ],
            index_path,
            spacy_model="de_blank",
            text_column="text",
            id_column="id",
            meta_columns=["register"],
            batch_size=1,
            n_process=1,
            disable_deps=False,
            build_info={"import_mode": "backend-ui-live-smoke"},
        )
    finally:
        spacy.load = real_load
    return index_path


def build_import_smoke_fixture(work_dir: Path) -> Path:
    """Create a tiny server-side prealigned CSV fixture for the live UI smoke."""

    import_dir = work_dir / "imports"
    import_dir.mkdir(parents=True, exist_ok=True)
    path = import_dir / "paired_smoke.csv"
    path.write_text(
        "\n".join(
            [
                "id,pair_id,pair_role,text,register",
                "s1,p1,source,Der Hase springt schnell.,smoke",
                "t1,p1,target,The rabbit jumps quickly.,smoke",
                "s2,p2,source,Ein Hund läuft langsam.,smoke",
                "t2,p2,target,A dog walks slowly.,smoke",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def build_import_preflight_matrix_fixtures(work_dir: Path) -> list[dict[str, Any]]:
    """Create tiny method-specific inputs for non-mutating import preflights."""

    import_dir = work_dir / "imports" / "preflight_matrix"
    import_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = import_dir / "generic.parquet"
    _write_parquet(
        parquet_path,
        [
            {"id": "d1", "input_text": "Der Hase springt.", "register": "smoke"},
            {"id": "d2", "input_text": "Ein Hund läuft.", "register": "smoke"},
        ],
    )

    vrt_path = import_dir / "sample.vrt"
    vrt_path.write_text(
        "<text id=\"v1\" source=\"smoke\">\n"
        "Der\tder\tDET\n"
        "Hase\thase\tNOUN\n"
        "</text>\n",
        encoding="utf-8",
    )

    prealigned_parquet_path = import_dir / "paired.parquet"
    _write_parquet(
        prealigned_parquet_path,
        [
            {"id": "s1", "text": "Der Hase springt.", "pair_id": "p1", "pair_role": "source"},
            {"id": "t1", "text": "The rabbit jumps.", "pair_id": "p1", "pair_role": "target"},
        ],
    )

    prealigned_csv_path = build_import_smoke_fixture(work_dir)

    jsonl_path = import_dir / "paired.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"doc": {"text": "Der Hase springt."}, "pair": {"id": "p1", "role": "source"}}, ensure_ascii=False),
                json.dumps({"doc": {"text": "The rabbit jumps."}, "pair": {"id": "p1", "role": "target"}}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return [
        {
            "method": "parquet",
            "input_path": str(parquet_path),
            "options": {"text_column": "input_text"},
            "expect_columns": ["input_text"],
        },
        {
            "method": "vrt",
            "input_path": str(vrt_path),
            "options": {"token_columns": ["word", "lemma", "pos"], "token_separator": "tab"},
            "expect_evidence": ["vrt"],
        },
        {
            "method": "prealigned_parquet",
            "input_path": str(prealigned_parquet_path),
            "options": {"reject_policy": "fail_fast", "pair_order": "grouped"},
            "expect_columns": ["text", "pair_id", "pair_role"],
        },
        {
            "method": "prealigned_csv",
            "input_path": str(prealigned_csv_path),
            "options": {"reject_policy": "fail_fast", "pair_order": "grouped"},
            "expect_columns": ["text", "pair_id", "pair_role"],
        },
        {
            "method": "prealigned_jsonl",
            "input_path": str(jsonl_path),
            "options": {
                "text_column": "doc.text",
                "pair_key_column": "pair.id",
                "pair_role_column": "pair.role",
                "reject_policy": "fail_fast",
                "pair_order": "grouped",
            },
            "expect_columns": ["doc.text", "pair.id", "pair.role"],
        },
    ]


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run_import_preflight_matrix(base_url: str, work_dir: Path) -> dict[str, Any]:
    """Exercise every backend-declared import method through the real route."""

    cases = build_import_preflight_matrix_fixtures(work_dir)
    results: list[dict[str, Any]] = []
    for case in cases:
        method = str(case["method"])
        payload = {
            "method": method,
            "input_path": case["input_path"],
            "target_name": f"preflight-{method.replace('_', '-')}",
            "spacy_model": "blank:de",
            **dict(case.get("options") or {}),
        }
        try:
            response = _post_json(f"{base_url}/corpora/import-preflight", payload)
            columns = set(response.get("evidence", {}).get("columns") or [])
            missing_columns = [
                column for column in case.get("expect_columns", []) if column not in columns
            ]
            missing_evidence = [
                key for key in case.get("expect_evidence", []) if key not in response.get("evidence", {})
            ]
            ok = (
                response.get("ok") is True
                and response.get("blocking") is not True
                and not missing_columns
                and not missing_evidence
            )
            results.append(
                {
                    "method": method,
                    "status": "passed" if ok else "failed",
                    "ok": response.get("ok"),
                    "blocking": response.get("blocking"),
                    "summary": response.get("summary"),
                    "input_path": case["input_path"],
                    "missing_columns": missing_columns,
                    "missing_evidence": missing_evidence,
                    "columns": sorted(columns),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "method": method,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "input_path": case["input_path"],
                }
            )
    failed = [item for item in results if item.get("status") != "passed"]
    return {
        "name": "import_preflight_matrix",
        "status": "passed" if not failed else "failed",
        "methods": results,
        "method_count": len(results),
        "failed_methods": [str(item.get("method")) for item in failed],
    }


def _collocation_evidence(rows: Any, *, source: str) -> dict[str, float | int | str]:
    if not isinstance(rows, list):
        raise RuntimeError(f"{source}: Kollokationszeilen fehlen")
    row = next((item for item in rows if isinstance(item, dict) and item.get("word") == "mag"), None)
    if row is None:
        raise RuntimeError(f"{source}: Referenzkollokat 'mag' fehlt")
    try:
        observed = int(row["observed"])
        frequency = int(row["f"])
        expected = float(row["expected"])
        chi2_cell = float(row["chi2_cell"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{source}: vollständige χ²-Zell-Evidenz fehlt: {row!r}") from exc
    if observed != frequency:
        raise RuntimeError(f"{source}: observed={observed} stimmt nicht mit f={frequency} überein")
    return {
        "word": "mag",
        "observed": observed,
        "expected": expected,
        "chi2_cell": chi2_cell,
    }


def _same_collocation_evidence(
    reference: dict[str, float | int | str],
    candidate: dict[str, float | int | str],
    *,
    source: str,
) -> None:
    if candidate["word"] != reference["word"] or candidate["observed"] != reference["observed"]:
        raise RuntimeError(f"{source}: Kollokationszeile weicht von der Engine ab: {candidate!r}")
    for field in ("expected", "chi2_cell"):
        if abs(float(candidate[field]) - float(reference[field])) > 1e-9:
            raise RuntimeError(
                f"{source}: {field}={candidate[field]} weicht von Engine={reference[field]} ab"
            )


def _assert_collocation_scope(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    method = payload.get("method")
    if not isinstance(method, dict):
        raise RuntimeError(f"{source}: Methodenscope fehlt")
    expected_scope = {"target_total": 42, "window": 5, "within_sentence": True}
    for field, expected in expected_scope.items():
        if method.get(field) != expected:
            raise RuntimeError(f"{source}: Methodenscope {field}={method.get(field)!r}, erwartet {expected!r}")
    return expected_scope


def run_collocation_stat_parity(index_path: Path, base_url: str) -> dict[str, Any]:
    """Verify one real χ²-cell row through engine, API, job, and Copilot tool.

    The Playwright smoke verifies the visible table and CSV export separately.
    This helper keeps the numerical cross-layer check independent of a model
    request: it calls the deterministic tool wrapper directly.
    """

    try:
        from candyconc.core import query_runtime
        from candyconc.core.corpus_index import CorpusIndex
        from candyconc.tools.collocate_stats import collocate_stats
        from candyconc.candyconc_copilot.tool_wrappers import collocate_stats_tool

        index = CorpusIndex(index_path, read_only=True)
        previous = query_runtime._CORPUS_INDEX
        query_runtime.set_corpus(index)
        try:
            direct_df = collocate_stats(
                "Hase",
                window=5,
                within_sentence=True,
                sort_by="chi2_cell",
                corpus=index,
                min_count=5,
            )
            engine = _collocation_evidence(direct_df.to_dict("records"), source="Engine")
            tool_result = collocate_stats_tool(
                "Hase",
                window=5,
                within_sentence=True,
                sort_by="chi2_cell",
            )
            tool = _collocation_evidence(tool_result.get("rows"), source="Copilot-Tool")
        finally:
            query_runtime.set_corpus(previous)
            index.close()

        sync_payload = _get_json(
            f"{base_url}/analysis/collocates?" + urlencode(
                {
                    "term": "Hase",
                    "corpus": "default",
                    "window": 5,
                    "within_sentence": "true",
                    "min_freq": 5,
                    "sort_by": "chi2_cell",
                    "limit": 50,
                }
            )
        )
        sync = _collocation_evidence(sync_payload.get("rows"), source="REST")
        scope = _assert_collocation_scope(sync_payload, source="REST")

        dev_token = str(_get_json(f"{base_url}/auth/dev-token").get("token") or "")
        if not dev_token:
            raise RuntimeError("Live-Smoke konnte keinen lokalen Dev-Token beziehen")
        auth_headers = {"Authorization": f"Bearer {dev_token}"}
        launched = _post_json(
            f"{base_url}/analysis/collocates/job",
            {
                "term": "Hase",
                "corpus": "default",
                "window": 5,
                "within_sentence": True,
                "min_freq": 5,
                "sort_by": "chi2_cell",
                "limit": 50,
            },
            headers=auth_headers,
        )
        job_id = str(launched.get("job_id") or "")
        if not job_id:
            raise RuntimeError(f"Analysejob lieferte keine job_id: {launched!r}")
        deadline = time.monotonic() + 30
        job_rows: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            snapshot = _get_json(f"{base_url}/analysis/jobs/{job_id}", headers=auth_headers)
            status = str(snapshot.get("status") or "")
            if status == "done":
                job_rows = _get_json(
                    f"{base_url}/analysis/jobs/{job_id}/rows?offset=0&limit=50",
                    headers=auth_headers,
                )
                break
            if status in {"error", "cancelled"}:
                raise RuntimeError(f"Kollokationsjob endete mit {status}: {snapshot.get('error')}")
            time.sleep(0.1)
        if job_rows is None:
            raise RuntimeError("Kollokationsjob wurde nicht rechtzeitig fertig")
        job = _collocation_evidence(job_rows.get("rows"), source="Analysejob")
        _assert_collocation_scope(job_rows, source="Analysejob")

        for source, candidate in (("Copilot-Tool", tool), ("REST", sync), ("Analysejob", job)):
            _same_collocation_evidence(engine, candidate, source=source)
        return {
            "name": "collocation_stat_parity",
            "status": "passed",
            "scope": scope,
            "engine": engine,
            "copilot_tool": tool,
            "rest": sync,
            "job": job,
        }
    except Exception as exc:
        return {
            "name": "collocation_stat_parity",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_backend_ui_live_smoke(
    root: Path,
    *,
    timeout: int = 240,
    frontend_port: int | None = None,
    backend_port: int | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    web_root = root / "candyconc-web"
    if not (web_root / "package.json").is_file():
        return {"name": "backend_ui_live_smoke", "status": "failed", "error": "candyconc-web/package.json fehlt"}

    base_dir = root / ".tmp" / "candyconc_backend_ui_live_smoke"
    work_dir = base_dir / f"run_{os.getpid()}_{int(time.time() * 1000)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    state_dir = work_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_file = work_dir / "config.toml"
    config_file.write_text("", encoding="utf-8")
    (work_dir / "projects").mkdir(parents=True, exist_ok=True)
    (work_dir / "spill").mkdir(parents=True, exist_ok=True)
    backend_log = work_dir / "backend.log"
    playwright_log = work_dir / "playwright.log"

    index_path = work_dir / "index"
    import_fixture_path = build_import_smoke_fixture(work_dir)
    backend_port = backend_port or _free_port()
    frontend_port = frontend_port or _free_port()

    host_env = os.environ.copy()
    env = {
        key: value
        for key, value in host_env.items()
        if not (
            key.startswith("CANDYCONC_")
            or key.startswith("COPILOT_")
            or key.startswith("LM_STUDIO_")
            or key in {"ENABLE_FAISS", "FAISS_DIR"}
        )
    }
    env.update(
        {
            "PYTHONPATH": _pythonpath(root, env),
            "CANDYCONC_HOME": str(state_dir),
            "CANDYCONC_CONFIG_FILE": str(config_file),
            "CANDYCONC_INDEX_PATH": str(index_path),
            "CANDYCONC_PREFS_PATH": str(work_dir / "prefs.json"),
            "CANDYCONC_PROJECTS_DIR": str(work_dir / "projects"),
            "CANDYCONC_PROJECT_FILE": str(work_dir / "project.ccproj"),
            "CANDYCONC_USER_FILE": str(work_dir / "users.json"),
            "CANDYCONC_QUERY_SPILL_DIR": str(work_dir / "spill"),
            "CANDYCONC_BACKEND_PORT": str(backend_port),
            "CANDYCONC_FRONTEND_PORT": str(frontend_port),
            "CANDYCONC_BACKEND_URL": f"http://127.0.0.1:{backend_port}/api/v1",
            "CANDYCONC_IMPORT_SMOKE_INPUT": str(import_fixture_path),
            "CANDYCONC_IMPORT_SMOKE_METHOD": "prealigned_csv",
            "CANDYCONC_IMPORT_SMOKE_TARGET": f"ui-import-smoke-{os.getpid()}",
            "CANDYCONC_IMPORT_SMOKE_SPACY_MODEL": "blank:de",
            # Keep the release smoke deterministic and safe: pyproject.toml may
            # define a local LM Studio endpoint, but this smoke verifies the
            # product's explicit "Copilot unavailable" gate against a closed
            # dummy endpoint instead of touching a loaded model.
            "COPILOT_ENDPOINT": "http://127.0.0.1:9/v1/responses",
            "CANDYCONC_GEMMA_EMB_ENDPOINT": "http://127.0.0.1:9/v1/embeddings",
            "COPILOT_MODEL": "candyconc-live-smoke-unavailable",
            "LM_STUDIO_BASE_URL": "",
            "CANDYCONC_LM_STUDIO_MODEL_PREFLIGHT_TIMEOUT_SEC": "0.2",
            "CANDYCONC_SECURITY_MODE": "local_dev_unsafe",
            "CANDYCONC_ENABLE_RBAC": "0",
            "CANDYCONC_LOG_LEVEL": "WARNING",
            "CANDYCONC_LIVE_BACKEND_SMOKE": "1",
        }
    )
    env.pop("CI", None)

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "candyconc.services.backend.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(backend_port),
    ]
    playwright_cmd = [
        "npm",
        "run",
        "test:e2e:backend-ui",
        "--",
        "--reporter=line",
    ]

    backend_proc: subprocess.Popen[str] | None = None
    start = time.monotonic()
    try:
        os.environ.clear()
        os.environ.update(env)
        index_path = build_smoke_index(root, work_dir)
        with backend_log.open("w", encoding="utf-8") as log_fh:
            backend_proc = subprocess.Popen(
                backend_cmd,
                cwd=root,
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _wait_for_http(f"http://127.0.0.1:{backend_port}/api/v1/health", timeout=60)
            preflight_matrix = run_import_preflight_matrix(
                f"http://127.0.0.1:{backend_port}/api/v1",
                work_dir,
            )
            collocation_stat_parity = run_collocation_stat_parity(
                index_path,
                f"http://127.0.0.1:{backend_port}/api/v1",
            )
            with playwright_log.open("w", encoding="utf-8") as playwright_fh:
                proc = subprocess.run(
                    playwright_cmd,
                    cwd=web_root,
                    env=env,
                    text=True,
                    stdout=playwright_fh,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
        elapsed_ms = round((time.monotonic() - start) * 1000)
        passed = (
            proc.returncode == 0
            and preflight_matrix.get("status") == "passed"
            and collocation_stat_parity.get("status") == "passed"
        )
        return {
            "name": "backend_ui_live_smoke",
            "status": "passed" if passed else "failed",
            "returncode": proc.returncode,
            "work_dir": str(work_dir),
            "index_path": str(index_path),
            "import_fixture_path": str(import_fixture_path),
            "import_preflight_matrix": preflight_matrix,
            "collocation_stat_parity": collocation_stat_parity,
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "elapsed_ms": elapsed_ms,
            "playwright_tail": _tail(playwright_log),
            "backend_tail": _tail(backend_log),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": "backend_ui_live_smoke",
            "status": "failed",
            "error": f"timeout after {timeout}s",
            "work_dir": str(work_dir),
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
            "playwright_tail": _tail(playwright_log),
            "backend_tail": _tail(backend_log),
        }
    except Exception as exc:
        return {
            "name": "backend_ui_live_smoke",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "work_dir": str(work_dir),
            "playwright_tail": _tail(playwright_log),
            "backend_tail": _tail(backend_log),
        }
    finally:
        os.environ.clear()
        os.environ.update(host_env)
        if backend_proc is not None and backend_proc.poll() is None:
            backend_proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                backend_proc.wait(timeout=10)
            if backend_proc.poll() is None:  # pragma: no cover - defensive cleanup
                backend_proc.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run CandyConc Backend-UI live smoke.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--backend-port", type=int, default=None)
    parser.add_argument("--frontend-port", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = args.repo_root.resolve() if args.repo_root else _repo_root()
    result = run_backend_ui_live_smoke(
        root, timeout=args.timeout, backend_port=args.backend_port, frontend_port=args.frontend_port,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{result['name']}: {result['status']}")
        if result.get("error"):
            print(result["error"])
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
