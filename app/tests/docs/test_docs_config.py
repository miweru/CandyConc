"""The documentation shows the version of the package and the labels of the interface."""

from __future__ import annotations

import re
import runpy
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2]
CANDIDATES = (APP.parent / "docs", APP.parent / "repo_root" / "docs")
DOCS = next((path for path in CANDIDATES if (path / "conf.py").is_file()), None)
#: candyconc-web lies next to app/ in the published repository and at the root
#: of the development tree, three levels above app/.
WEB = next(
    (path for path in (APP.parent / "candyconc-web", APP.parents[2] / "candyconc-web") if path.is_dir()),
    APP.parent / "candyconc-web",
)


def _package_version() -> str:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        import tomli as tomllib
    return tomllib.loads((APP / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


@pytest.mark.skipif(DOCS is None, reason="documentation sources not found next to app/")
def test_footer_version_is_the_package_version(monkeypatch):
    """The footer read the version from setup.py, which no longer has one."""
    monkeypatch.delenv("CANDYCONC_DOCS_VERSION", raising=False)
    namespace = runpy.run_path(str(DOCS / "conf.py"))
    assert namespace["release"] == _package_version()


@pytest.mark.skipif(not (WEB / "src" / "locales" / "en" / "settings.ts").is_file(), reason="web interface not found")
def test_messages_name_the_settings_tab_of_the_english_interface():
    """The start banner and the 424 message point to the tab as the interface labels it."""
    catalog = (WEB / "src" / "locales" / "en" / "settings.ts").read_text(encoding="utf-8")
    label = re.search(r"tabModelRoute:\s*'([^']+)'", catalog).group(1)
    from candyconc.services.llm_client import COPILOT_NOT_CONFIGURED_MESSAGE

    cli = (APP / "src" / "candyconc" / "entrypoints" / "cli.py").read_text(encoding="utf-8")
    assert f"Settings > {label}" in COPILOT_NOT_CONFIGURED_MESSAGE
    assert f"Settings > {label}" in cli
