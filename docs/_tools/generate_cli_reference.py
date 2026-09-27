#!/usr/bin/env python3
"""Write the command line reference from the argument parsers of ``candy``.

``candyconc/entrypoints/cli.py`` builds one ``argparse`` parser per command
(server, ``import``, ``pipeline``, ``migrate-project``). This script builds
each parser exactly as ``candy`` does, without running the command, and
renders its options as Markdown into ``docs/reference/_generated/cli.md``,
which ``docs/reference/cli.md`` includes. Run it with the Python environment
of CandyConc whenever an option changes::

    python docs/_tools/generate_cli_reference.py
    python docs/_tools/generate_cli_reference.py --check   # exit 1 if the file is out of date

The documentation build itself does not import CandyConc.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
OUT = DOCS / "reference" / "_generated" / "cli.md"

#: (command as typed, function in cli.py that builds and parses its options)
COMMANDS = (
    ("candy", "_serve"),
    ("candy import", "_run_import"),
    ("candy pipeline", "_run_pipeline"),
    ("candy migrate-project", "_migrate_project"),
)


class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__(parser.prog)
        self.parser = parser


def _find_source() -> None:
    # Prefer the source tree next to the documentation, so that the page
    # describes this checkout and not another installed version.
    for candidate in (DOCS.parent / "app" / "src", DOCS.parent.parent / "app" / "src"):
        if (candidate / "candyconc" / "entrypoints" / "cli.py").is_file():
            sys.path.insert(0, str(candidate))
            return
    try:
        import candyconc.entrypoints.cli  # noqa: F401
    except ImportError:
        raise SystemExit("candyconc not found: run from a source checkout or install CandyConc") from None


def _parsers() -> list[tuple[str, argparse.ArgumentParser]]:
    """Build every parser of ``candy`` without executing a command."""
    # Paths in help texts must not name the machine that renders the page.
    os.environ["CANDYCONC_HOME"] = "~/.candyconc"
    _find_source()
    from candyconc import paths
    from candyconc.entrypoints import cli

    paths.data_dir = lambda: Path("~/.candyconc")  # type: ignore[assignment]

    original = argparse.ArgumentParser.parse_args

    def capture(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise _Captured(self)

    captured: list[tuple[str, argparse.ArgumentParser]] = []
    argparse.ArgumentParser.parse_args = capture  # type: ignore[method-assign]
    try:
        for command, function in COMMANDS:
            try:
                getattr(cli, function)([])
            except _Captured as exc:
                captured.append((command, exc.parser))
            else:
                raise SystemExit(f"{function} did not build a parser")
    finally:
        argparse.ArgumentParser.parse_args = original  # type: ignore[method-assign]
    return captured


_OPTION_IN_TEXT = re.compile(r"(?<![\\w`-])(--[a-z][a-z0-9-]*)")


def _text(value: object) -> str:
    """One Markdown table cell: escape pipes and angle brackets, one line.

    Option names in help texts become code, so that ``--name`` reads as an
    option and not as a dash.
    """
    text = " ".join(str(value).split())
    text = text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "\\<").replace(">", "\\>")
    return _OPTION_IN_TEXT.sub(r"`\1`", text)


def _term(action: argparse.Action) -> str:
    """The option as typed: all its names and, if it takes a value, the metavar."""
    if not action.option_strings:
        return f"`{action.metavar or action.dest}`"
    if action.nargs == 0:
        value = ""
    elif action.choices:
        value = " " + (action.metavar or action.dest.upper())
    elif action.nargs == "*":
        value = f" {action.metavar or action.dest.upper()} ..."
    else:
        value = " " + (action.metavar or action.dest.upper())
    return ", ".join(f"`{name}{value}`" for name in action.option_strings)


def _details(action: argparse.Action) -> str:
    parts = []
    help_text = _text(action.help or "")
    if help_text:
        parts.append(help_text[0].upper() + help_text[1:] + ("" if help_text.endswith(".") else "."))
    if action.choices and action.nargs != 0:
        parts.append("Values: " + ", ".join(f"`{choice}`" for choice in action.choices) + ".")
    if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):  # noqa: SLF001
        return " ".join(parts)
    if action.required:
        parts.append("Required.")
    elif "default" not in (action.help or "").lower():
        if action.nargs == 0:
            parts.append("Off unless given." if not action.default else "On unless given.")
        elif action.default not in (None, ""):
            parts.append(f"Default: `{action.default}`.")
    return " ".join(parts)


def _render_parser(command: str, parser: argparse.ArgumentParser) -> list[str]:
    lines = [f"### `{command}`", ""]
    if parser.description:
        lines += [_text(parser.description), ""]
    usage = parser.format_usage().strip()
    lines += ["```text", usage, "```", ""]
    for action in parser._actions:  # noqa: SLF001
        lines += [_term(action), f": {_details(action)}", ""]
    return lines


def render() -> str:
    lines = [
        "<!-- Generated by docs/_tools/generate_cli_reference.py from candyconc/entrypoints/cli.py. Do not edit. -->",
        "",
    ]
    for command, parser in _parsers():
        lines += _render_parser(command, parser)
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the generated file is out of date")
    args = ap.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print(f"{OUT} is out of date. Run: python docs/_tools/generate_cli_reference.py")
            return 1
        print(f"{OUT} is current.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
