"""Where CandyConc keeps user data and where it reads its configuration file.

Data directory (corpora, catalog, project file, preferences, logs,
temporary files): ``CANDYCONC_HOME`` if set, otherwise ``~/.candyconc`` on
every platform. Installations before this module kept their data in the same
place, so existing corpora and projects stay where they are.

Configuration file: ``CANDYCONC_CONFIG_FILE`` if set, otherwise ``config.toml``
in the platform configuration directory (macOS
``~/Library/Application Support/candyconc``, Linux ``$XDG_CONFIG_HOME/candyconc``
or ``~/.config/candyconc``).
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_ENV = "CANDYCONC_HOME"
CONFIG_FILE_ENV = "CANDYCONC_CONFIG_FILE"
APP_NAME = "candyconc"


def data_dir() -> Path:
    """The user data directory (not created here)."""
    raw = os.environ.get(DATA_DIR_ENV, "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".candyconc"


def config_file() -> Path:
    """The user configuration file (may not exist)."""
    raw = os.environ.get(CONFIG_FILE_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    from platformdirs import user_config_path

    return user_config_path(APP_NAME, appauthor=False) / "config.toml"


def corpora_dir() -> Path:
    return data_dir() / "corpora"


def logs_dir() -> Path:
    return data_dir() / "logs"


def tmp_dir() -> Path:
    return data_dir() / "tmp"


def pipelines_dir() -> Path:
    """Target of ``candy pipeline --user-dir``: spaCy pipelines kept with the user data."""
    return data_dir() / "pipelines"


def project_file(configured: str | None) -> Path:
    """The project file (subcorpora, annotations, coding schemes).

    An explicit ``CANDYCONC_PROJECT_FILE`` wins, relative paths resolve
    against the working directory as before. Without it, a ``proj.ccproj`` in
    the working directory keeps being used (the earlier default), otherwise the
    file lives in the data directory.
    """
    if configured:
        return Path(configured).expanduser()
    legacy = Path("proj.ccproj")
    if legacy.is_file():
        return legacy
    return data_dir() / "proj.ccproj"


def projects_dir(configured: str | None) -> Path:
    """Project configuration (analysis presets, clusters, members).

    Same rule as :func:`project_file`: explicit value, then an existing
    ``config/projects`` in the working directory, then the data directory.
    """
    if configured:
        return Path(configured).expanduser()
    legacy = Path("config") / "projects"
    if legacy.is_dir():
        return legacy
    return data_dir() / "projects"


def describe() -> dict[str, str]:
    """All locations, for ``candy paths`` and ``/api/v1/system/info``."""
    from candyconc.config import APP_CONFIG

    return {
        "data_dir": str(data_dir()),
        "config_file": str(config_file()),
        "corpora_dir": str(corpora_dir()),
        "corpus_catalog": str(data_dir() / "corpora.json"),
        "project_file": str(project_file(APP_CONFIG.CANDYCONC_PROJECT_FILE).resolve()),
        "projects_dir": str(projects_dir(APP_CONFIG.CANDYCONC_PROJECTS_DIR).resolve()),
        "logs_dir": str(logs_dir()),
        "pipelines_dir": str(pipelines_dir()),
    }
