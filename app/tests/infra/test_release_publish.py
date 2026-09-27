"""Deployment and release automation contracts.

The Docker image and the systemd unit start CandyConc from an installed wheel
with the CLI (candy), keep release security and RBAC on, and keep user data in
CANDYCONC_HOME. Before, both started uvicorn directly without a web interface,
without COPILOT_ENDPOINT (which then stopped the start) and without users, and
set CANDYCONC_BACKEND_PORT, which the backend never read.
"""

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = APP_ROOT / "deploy" / "Dockerfile"
SYSTEMD_SERVICE = APP_ROOT / "deploy" / "candyconc.service"


def _workflow(name: str) -> Path | None:
    # Exported repository: .github at the root next to app/. In the monorepo
    # the future root files live in repo_root next to app/.
    for root in (APP_ROOT.parent, APP_ROOT.parent / "repo_root"):
        candidate = root / ".github" / "workflows" / name
        if candidate.is_file():
            return candidate
    return None


def test_release_workflow_builds_sdist_wheels_bundles_and_only_a_draft():
    workflow = _workflow("release.yml")
    assert workflow is not None, "release workflow missing at the repository root"
    text = workflow.read_text()
    assert "uv build --sdist" in text
    assert "cibuildwheel" in text and "sdist/*.tar.gz" in text
    assert "install_smoke --require-web" in text
    assert "build_bundle.sh" in text
    assert "--draft" in text
    assert "SHA256SUMS" in text
    assert 'CANDYCONC_ENABLE_OPENMP: "off"' in text


def test_release_workflow_takes_its_notes_from_the_documentation_and_attaches_the_manual():
    """The workflow read RELEASE_NOTES.md at the root, which the repository does
    not have, and attached no documentation (RC0 report, B4). The footer of the
    documentation named no commit in a tree without Git (B5)."""
    text = _workflow("release.yml").read_text()
    assert "python packaging/release_notes.py" in text
    assert "--notes-file notes/RELEASE_NOTES.md" in text
    assert "--generate-notes" not in text
    assert "--require-docs" in text and "--docs-zip docs-zip" in text
    assert "CANDYCONC_DOCS_COMMIT=" in text
    assert "python packaging/check_sdist.py dist/*.tar.gz" in text

    release_job = text.split("\n  release:\n", 1)[1]
    downloads = release_job.split("- uses: actions/download-artifact")[1:]
    assert downloads
    # Every download names its artifacts: without name or pattern the job
    # also took web-dist, whose index.html and assets/ are no release files.
    for step in downloads:
        block = step.split("\n      - ", 1)[0]
        assert "name:" in block or "pattern:" in block, block
    fetched = {line.split(":", 1)[1].strip() for line in release_job.splitlines()
               if line.strip().startswith(("name:", "pattern:"))}
    assert {"sdist", "wheels-*", "bundle-*", "docs-html", "release-notes"} <= fetched
    assert "web-dist" not in fetched


def test_setup_uv_is_pinned_to_a_published_tag():
    """astral-sh/setup-uv has no floating major tag since v8. "@v10" did not
    resolve, and every job that installs uv would stop at that step."""
    for name in ("release.yml", "test.yml"):
        refs = re.findall(r"uses: astral-sh/setup-uv@(\S+)", _workflow(name).read_text())
        assert refs, name
        for ref in refs:
            assert re.fullmatch(r"v\d+\.\d+\.\d+", ref), (name, ref)


def test_test_workflow_builds_the_documentation():
    text = _workflow("test.yml").read_text()
    assert "python -m sphinx -W --keep-going -n -b html docs docs/_build/html" in text
    assert "python packaging/release_notes.py" in text


def test_test_workflow_checks_backend_frontend_and_an_installed_wheel():
    workflow = _workflow("test.yml")
    assert workflow is not None, "test workflow missing at the repository root"
    text = workflow.read_text()
    assert "make lint" in text
    assert "npx vitest run" in text
    assert "install_smoke --require-web" in text


def test_dockerfile_builds_and_runs_the_packaged_application():
    text = DOCKERFILE.read_text()

    assert "FROM python:3.11-slim" in text
    assert "CANDYCONC_SECURITY_MODE=${CANDYCONC_SECURITY_MODE}" in text
    assert "CANDYCONC_ENABLE_RBAC=${CANDYCONC_ENABLE_RBAC}" in text
    assert "CANDYCONC_ENABLE_OPENMP=off" in text
    assert "CANDYCONC_REQUIRE_WEB_DIST=1" in text
    assert "build-essential" in text
    assert "CANDYCONC_HOME=/data" in text
    assert "USER candyconc" in text
    assert "EXPOSE 8010" in text
    assert "HEALTHCHECK" in text
    assert 'CMD ["candy", "--host", "0.0.0.0", "--port", "8010"]' in text
    assert "CANDYCONC_BACKEND_PORT" not in text
    assert "PYTHONPATH=/opt/candyconc/src" not in text


def test_systemd_service_runs_the_installed_cli():
    text = SYSTEMD_SERVICE.read_text()

    assert 'Environment="CANDYCONC_HOME=/var/lib/candyconc"' in text
    assert "CANDYCONC_USER_FILE=/etc/candyconc/users.json" in text
    assert "CANDYCONC_ENABLE_RBAC=1" in text
    assert "CANDYCONC_SECURITY_MODE=release" in text
    assert "ExecStart=/opt/candyconc/.venv/bin/candy --host 127.0.0.1 --port 8010" in text
    assert "CANDYCONC_BACKEND_PORT" not in text
    assert "PYTHONPATH" not in text
