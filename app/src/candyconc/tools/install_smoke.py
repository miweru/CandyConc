"""Check an installation end to end: ``python -m candyconc.tools.install_smoke``.

Runs in a throw-away data directory and leaves the user's data alone:

1. the native extensions import,
2. the built web interface and its license notices ship with the package,
3. ``candy import`` builds an index from four synthetic English sentences
   (``blank:en``, so no pipeline download),
4. ``candy`` starts on a free loopback port without a model endpoint, serves
   the web interface, finds the corpus, answers a search and exports it as CSV.

Used by the release workflow after installing each wheel and by the bundle
checks. Exit code 0 means every step passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SAMPLE_CSV = """doc_id,text,genre
d1,"The river rose after three days of rain. People in the old town moved their boats to higher ground.",news
d2,"She opened the letter slowly. The river had flooded the garden, and the roses were gone.",fiction
d3,"Rain is expected again on Friday. The council has opened two shelters near the river.",news
d4,"He walked along the river every morning and counted the herons standing in the shallow water.",fiction
"""
EXPECTED_RIVER_HITS = 4


def _step(ok: bool, text: str) -> bool:
    print(f"{'ok  ' if ok else 'FAIL'} {text}", flush=True)
    return ok


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(url: str, *, token: str | None = None, data: bytes | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status, response.read()


def _environment(work: Path, home: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("CANDYCONC_INDEX_PATH", "INDEX_DIR", "index_dir", "LM_STUDIO_BASE_URL"):
        env.pop(key, None)
    if env.get("PYTHONPATH"):
        # The server runs in another working directory.
        env["PYTHONPATH"] = os.pathsep.join(
            str(Path(entry).resolve()) for entry in env["PYTHONPATH"].split(os.pathsep) if entry
        )
    # CandyConc refuses indexes below the system temp directory. The check
    # lives in a temp directory, so the children get their own temp dir.
    (work / "tmp").mkdir(exist_ok=True)
    env["TMPDIR"] = env["TEMP"] = env["TMP"] = str(work / "tmp")
    env["CANDYCONC_HOME"] = str(home)
    env["CANDYCONC_CONFIG_FILE"] = str(home / "no-config.toml")
    env["COPILOT_ENDPOINT"] = "http://127.0.0.1:9/v1/responses"
    env["CANDYCONC_GEMMA_EMB_ENDPOINT"] = "http://127.0.0.1:9/v1/embeddings"
    # The import reserves free disk space for large corpora. This one is tiny.
    env["CANDYCONC_BUILD_ALLOW_LOW_DISK"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run(require_web: bool, keep: bool) -> int:
    work = Path(tempfile.mkdtemp(prefix="candyconc-smoke-"))
    home = work / "home"
    home.mkdir()
    env = _environment(work, home)
    ok = True
    server: subprocess.Popen[bytes] | None = None
    try:
        from candyconc.core.native_extensions import require_native_extensions
        from candyconc.version import package_version

        print(f"CandyConc {package_version()}, Python {sys.version.split()[0]}, {sys.platform}")
        try:
            require_native_extensions()
            ok &= _step(True, "native extensions import")
        except Exception as exc:
            ok &= _step(False, f"native extensions: {exc}")

        from candyconc.services.backend.frontend_static import packaged_dist_dir

        web = packaged_dist_dir()
        has_web = (web / "index.html").is_file()
        has_notices = (web / "THIRD_PARTY_LICENSES.txt").is_file()
        if require_web:
            ok &= _step(has_web and has_notices, f"web interface and license notices in {web}")
        else:
            _step(True, f"web interface in the package: {'yes' if has_web else 'no'}")

        sample = work / "synthetic_en.csv"
        sample.write_text(SAMPLE_CSV, encoding="utf-8")
        output = home / "corpora" / "smoke"
        imported = subprocess.run(
            [
                sys.executable, "-m", "candyconc.entrypoints.cli", "import",
                "--input", str(sample), "--input-format", "csv", "--meta-columns", "genre",
                "--spacy-model", "blank:en", "--output", str(output),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        ok &= _step(imported.returncode == 0, f"candy import (blank:en) into {output}")
        if imported.returncode != 0:
            print(imported.stdout[-2000:], imported.stderr[-4000:], sep="\n")
            return 1

        port = _free_port()
        log = (work / "server.log").open("wb")
        server = subprocess.Popen(
            [sys.executable, "-m", "candyconc.entrypoints.cli", "--port", str(port)],
            env=env,
            cwd=str(work),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(240):
            if server.poll() is not None:
                break
            try:
                if _get(f"{base}/api/v1/health")[0] == 200:
                    break
            except Exception:
                time.sleep(0.5)
        alive = server.poll() is None
        ok &= _step(alive, f"candy serves on {base} without a model endpoint")
        if not alive:
            print((work / "server.log").read_text(errors="replace")[-4000:])
            return 1

        if has_web:
            status, body = _get(f"{base}/")
            ok &= _step(status == 200 and b'<div id="app">' in body, "GET / returns the web interface")

        status, body = _get(f"{base}/api/v1/corpora")
        names = [item.get("name") for item in json.loads(body).get("corpora", [])]
        ok &= _step("smoke" in names, f"catalog lists the imported corpus ({names})")

        status, body = _get(f"{base}/api/v1/query?term=river&corpus=smoke")
        hits = json.loads(body)
        ok &= _step(len(hits) == EXPECTED_RIVER_HITS, f"search 'river' finds {len(hits)} of {EXPECTED_RIVER_HITS} lines")

        token = json.loads(_get(f"{base}/api/v1/auth/dev-token")[1])["token"]
        payload = json.dumps({"query": "river", "corpus": "smoke", "format": "csv"}).encode()
        status, body = _get(f"{base}/api/v1/export/concordance", token=token, data=payload)
        rows = [line for line in body.decode("utf-8", errors="replace").splitlines() if "river" in line.lower()]
        ok &= _step(status == 200 and len(rows) >= EXPECTED_RIVER_HITS, "CSV export of the concordance")
        return 0 if ok else 1
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
        if keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require-web", action="store_true", help="fail when the package ships no web interface")
    parser.add_argument("--keep", action="store_true", help="keep the temporary data directory")
    args = parser.parse_args(argv)
    return run(require_web=args.require_web, keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
