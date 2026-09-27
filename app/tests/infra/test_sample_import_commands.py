"""The documented import commands for the sample file name its columns.

``packaging/sample/synthetic_en.csv`` has the columns ``doc_id``, ``text``
and ``genre``. The commands in the sample README, the bundle README, the
release workflow and ``make demo-index`` gave no ``--id-column``, so the
default ``id`` found no column and the documents were numbered ``doc-0`` to
``doc-3`` instead of ``d1`` to ``d4``. Every option that names a column must
name a column of the file.
"""

from __future__ import annotations

import csv
import re
import shlex
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
#: Defaults of ``candy import`` (entrypoints/cli.py).
DEFAULT_COLUMNS = {"--text-column": "text", "--id-column": "id"}


def _root() -> Path:
    # Exported repository: packaging/ next to app/. Monorepo: repo_root/ next to app/.
    for root in (APP_ROOT.parent, APP_ROOT.parent / "repo_root"):
        if (root / "packaging" / "sample" / "synthetic_en.csv").is_file():
            return root
    raise AssertionError("packaging/sample/synthetic_en.csv not found next to app/")


def _sample_commands(text: str) -> list[list[str]]:
    joined = re.sub(r"\\\n\s*", " ", text)
    commands = []
    for line in joined.splitlines():
        if " import " in line and "--input-format csv" in line:
            words = shlex.split(line.replace("$(", "").replace(")", ""))
            commands.append(words[words.index("import") + 1:])
    return commands


def _columns(words: list[str]) -> dict[str, list[str]]:
    named = {option: [value] for option, value in DEFAULT_COLUMNS.items()}
    for i, word in enumerate(words):
        if word in DEFAULT_COLUMNS:
            named[word] = [words[i + 1]]
        elif word == "--meta-columns":
            values = []
            for value in words[i + 1:]:
                if value.startswith("--"):
                    break
                values.append(value)
            named[word] = values
    return named


def test_every_sample_command_names_columns_of_the_sample_file():
    root = _root()
    with (root / "packaging" / "sample" / "synthetic_en.csv").open(encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    sources = [
        root / "packaging" / "sample" / "README.md",
        root / "packaging" / "bundle" / "README.txt",
        root / ".github" / "workflows" / "release.yml",
        APP_ROOT / "Makefile",
    ]
    checked = 0
    for source in sources:
        commands = _sample_commands(source.read_text(encoding="utf-8"))
        assert commands, f"no sample import command found in {source}"
        for words in commands:
            for option, values in _columns(words).items():
                missing = [value for value in values if value not in header]
                assert not missing, f"{source.name}: {option} {missing} is not a column of {header}"
            checked += 1
    assert checked >= len(sources)
