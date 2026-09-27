#!/usr/bin/env python3
"""Write THIRD_PARTY_LICENSES.txt for an application bundle.

Run with the bundle's own interpreter: ``python collect_licenses.py <bundle dir>``.
The file lists every installed Python distribution with its declared license
and the full license texts it ships, then the license of CPython itself, the
notices of the npm packages in the web interface and the source and license
notices of the sample corpora in ``examples/`` (staged before this step).
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
import sysconfig
from pathlib import Path

NOTICE = re.compile(r"(^|/)(licen[cs]e|copying|notice|authors)([.-][^/]*)?$", re.IGNORECASE)
RULE = "=" * 78


def _declared_license(meta) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return ", ".join(classifiers)
    text = (meta.get("License") or "").strip()
    return text.splitlines()[0] if text else "not declared"


def _license_texts(dist) -> list[tuple[str, str]]:
    texts = []
    for file in dist.files or []:
        name = str(file)
        if ".dist-info/" not in name and not name.startswith("licenses/"):
            continue
        if not NOTICE.search(name):
            continue
        try:
            texts.append((name, Path(dist.locate_file(file)).read_text(encoding="utf-8", errors="replace").strip()))
        except OSError:
            continue
    return texts


def main(bundle: Path) -> int:
    sections = []
    for dist in sorted(md.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        meta = dist.metadata
        head = [RULE, f"{meta['Name']} {dist.version}", f"License: {_declared_license(meta)}"]
        url = meta.get("Home-page") or next(
            (value.split(",", 1)[1].strip() for value in meta.get_all("Project-URL") or [] if "," in value), ""
        )
        if url:
            head.append(f"Source: {url}")
        texts = _license_texts(dist)
        body = "\n\n".join(f"--- {name}\n{text}" for name, text in texts) or "The distribution ships no license file."
        sections.append("\n".join(head) + "\n\n" + body)

    python_license = Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"
    if python_license.is_file():
        sections.append(f"{RULE}\nCPython {sys.version.split()[0]} (python-build-standalone)\n\n{python_license.read_text(errors='replace').strip()}")

    import candyconc

    web_notices = Path(candyconc.__file__).resolve().parent / "web_dist" / "THIRD_PARTY_LICENSES.txt"
    if web_notices.is_file():
        sections.append(f"{RULE}\n{web_notices.read_text(encoding='utf-8').strip()}")

    attribution = bundle / "examples" / "ATTRIBUTION.txt"
    if attribution.is_file():
        sections.append(
            f"{RULE}\nSample corpora in examples/ (data, not software)\n\n"
            f"{attribution.read_text(encoding='utf-8').strip()}\n\n"
            "The full text of CC BY-SA 4.0 is in examples/LICENSE-CC-BY-SA-4.0.txt."
        )

    header = (
        "Third-party software in this CandyConc bundle\n\n"
        "CandyConc itself is MIT licensed (see the LICENSE file of the candyconc entry below).\n"
        "The bundle contains the following Python distributions, the CPython interpreter,\n"
        "the npm packages of the web interface and the sample corpora in examples/.\n"
    )
    out = bundle / "THIRD_PARTY_LICENSES.txt"
    out.write_text(header + "\n" + "\n\n".join(sections) + "\n", encoding="utf-8")
    print(f"{out}: {len(sections)} sections")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
