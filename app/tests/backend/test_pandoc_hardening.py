"""B10f fix: pandoc export hardening in the export route converter.

Before the fix, pandoc was invoked as ``pandoc src -o out`` with the input
format inferred from ``.md``. Pandoc's default markdown enables the
``raw_tex`` extension, so a crafted document could smuggle
``\\input{/etc/passwd}`` into the LaTeX run during PDF export (local file
disclosure), and the subprocess had no timeout.

After the fix the command line is hardened:

* ``-f markdown-raw_tex`` for ``.md`` sources (raw TeX disabled),
* ``--sandbox`` when the installed pandoc supports it (>= 2.15),
* ``timeout=60`` on the subprocess call; ``TimeoutExpired`` maps to the
  established ``RuntimeError`` error shape.
"""

import asyncio
import shutil
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from candyconc.services.backend import server
from candyconc.services.backend.routes import exports as export_routes


def _convert(text: str, ext: str):
    return asyncio.run(export_routes._pandoc_convert(text, ext))


def test_download_file_rejects_paths_outside_export_dir(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}_outside.md"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(server, "_EXPORT_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(export_routes.download_file(f"../{outside.name}"))

    assert exc.value.status_code == 404


class TestPandocCommandHardening(unittest.TestCase):
    """Inspect the subprocess invocation via a mock (no pandoc required)."""

    def _run_and_capture(self, sandbox_supported: bool):
        run_mock = MagicMock(return_value=None)
        with patch.object(export_routes.subprocess, "run", run_mock), patch.object(
            server, "DRY_RUN", False
        ), patch.object(
            export_routes, "_pandoc_supports_sandbox", lambda: sandbox_supported
        ):
            _convert("# hi", ".pdf")
        self.assertEqual(run_mock.call_count, 1)
        args, kwargs = run_mock.call_args
        return [str(a) for a in args[0]], kwargs

    def test_md_source_disables_raw_tex_and_sets_timeout(self):
        cmd, kwargs = self._run_and_capture(sandbox_supported=False)
        self.assertEqual(cmd[0], "pandoc")
        fmt_idx = cmd.index("-f")
        self.assertEqual(cmd[fmt_idx + 1], "markdown-raw_tex")
        self.assertIn("-o", cmd)
        self.assertEqual(kwargs.get("timeout"), server._PANDOC_TIMEOUT_SEC)
        self.assertEqual(server._PANDOC_TIMEOUT_SEC, 60)
        self.assertTrue(kwargs.get("check"))
        self.assertNotIn("--sandbox", cmd)

    def test_sandbox_flag_added_when_supported(self):
        cmd, _ = self._run_and_capture(sandbox_supported=True)
        self.assertIn("--sandbox", cmd)

    def test_timeout_maps_to_established_error_shape(self):
        run_mock = MagicMock(
            side_effect=subprocess.TimeoutExpired(cmd="pandoc", timeout=60)
        )
        with patch.object(export_routes.subprocess, "run", run_mock), patch.object(
            server, "DRY_RUN", False
        ), patch.object(export_routes, "_pandoc_supports_sandbox", lambda: False):
            with self.assertRaisesRegex(
                RuntimeError, "Pandoc fehlt oder hat Fehler geliefert"
            ):
                _convert("# hi", ".pdf")


@unittest.skipUnless(shutil.which("pandoc"), "pandoc not installed")
class TestPandocRawTexNeutralized(unittest.TestCase):
    """End-to-end with the real pandoc binary (LaTeX writer, no engine needed)."""

    def test_input_directive_does_not_survive_to_latex(self):
        text = "# Doc\n\n\\input{/etc/passwd}\n\nNormal text.\n"
        with patch.object(server, "DRY_RUN", False):
            out_path = _convert(text, ".tex")
        content = out_path.read_text(encoding="utf-8")
        # Raw TeX disabled: the directive is escaped literal text, never a
        # live \input command that the PDF engine would execute.
        self.assertNotIn("\\input{/etc/passwd}", content)
        self.assertNotIn("\\input{", content)

    def test_sandbox_probe_matches_installed_pandoc(self):
        out = subprocess.run(
            ["pandoc", "--version"], capture_output=True, text=True, timeout=10
        ).stdout
        version = tuple(
            int(p) for p in out.splitlines()[0].split()[1].split(".")[:2]
        )
        self.assertEqual(export_routes._pandoc_supports_sandbox(), version >= (2, 15))


if __name__ == "__main__":
    unittest.main()
