#!/usr/bin/env python3
"""Copy the sample data into an application bundle.

    python stage_data.py <bundle dir> --sample DIR --examples DIR

``sample/`` holds four synthetic sentences for a quick check. ``examples/``
holds the two sample corpora of the documentation (State of the Union
addresses, Deutsches Textarchiv) with their README, attribution and the
CC BY-SA 4.0 license text, which the DTA file requires next to it. The step
stops when one of these files is missing, so that no bundle ships the data
without its notices.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REQUIRED_EXAMPLE_FILES = ("README.md", "ATTRIBUTION.txt", "LICENSE-CC-BY-SA-4.0.txt")


def stage(bundle: Path, sample: Path | None, examples: Path) -> list[Path]:
    if not examples.is_dir():
        raise SystemExit(f"examples folder not found: {examples} (pass --examples DIR)")
    missing = [name for name in REQUIRED_EXAMPLE_FILES if not (examples / name).is_file()]
    corpora = sorted(examples.glob("*.jsonl"))
    if missing:
        raise SystemExit(f"{examples} lacks {', '.join(missing)}")
    if not corpora:
        raise SystemExit(f"{examples} holds no sample corpus (*.jsonl)")
    copied = []
    target = bundle / "examples"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(examples, target, ignore=shutil.ignore_patterns("__pycache__", ".*"))
    copied.append(target)
    if sample is not None and sample.is_dir():
        sample_target = bundle / "sample"
        if sample_target.exists():
            shutil.rmtree(sample_target)
        shutil.copytree(sample, sample_target, ignore=shutil.ignore_patterns("__pycache__", ".*"))
        copied.append(sample_target)
    for folder in copied:
        files = [path for path in folder.rglob("*") if path.is_file()]
        size = sum(path.stat().st_size for path in files)
        print(f"{folder}: {len(files)} files, {size / 1e6:.1f} MB")
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--sample", type=Path, default=None)
    parser.add_argument("--examples", type=Path, required=True)
    args = parser.parse_args(argv)
    stage(args.bundle, args.sample, args.examples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
