"""Check a Fast Index for known build defects: ``python -m candyconc.tools.check_index DIR``.

Builds before builder revision 1 (see ``core.index_format.BUILDER_REVISION``)
stored the morph value of every token empty whose spaCy morph hash is 2**63
or larger, about half of all feature sets, ``Number=Sing`` among them. Such a
token keeps its part of speech but has no morph value at all, not even the
part of speech that a correct build stores for a token without features. The
check counts these tokens. It reads the index and changes nothing.

Exit code 0: no defect found. 1: the index is affected, import the corpus
again. 2: the directory is not a readable index.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

from candyconc.core.index_format import COUNT_HEADER_SIZE, COUNT_HEADER_STRUCT, IndexManifest

_CHUNK = 1 << 22


def _count_prefixed(path: Path) -> np.ndarray:
    with open(path, "rb") as fh:
        header = fh.read(COUNT_HEADER_SIZE)
    if len(header) != COUNT_HEADER_SIZE:
        raise ValueError(f"{path.name}: header missing")
    count = int(struct.unpack(COUNT_HEADER_STRUCT, header)[0])
    if count == 0:
        return np.zeros(0, dtype=np.uint32)
    return np.memmap(path, dtype=np.uint32, mode="r", offset=COUNT_HEADER_SIZE, shape=(count,))


def morph_gaps(index_dir: Path) -> dict:
    """Tokens with a part of speech but without a morph value."""
    index_dir = Path(index_dir)
    pos = _count_prefixed(index_dir / "pos_ids.bin")
    morph = _count_prefixed(index_dir / "morph_ids.bin")
    if pos.shape != morph.shape:
        raise ValueError("pos_ids.bin and morph_ids.bin differ in length")
    with_pos = 0
    gaps = 0
    for start in range(0, int(pos.shape[0]), _CHUNK):
        p = np.asarray(pos[start : start + _CHUNK])
        m = np.asarray(morph[start : start + _CHUNK])
        has_pos = p != 0
        with_pos += int(np.count_nonzero(has_pos))
        gaps += int(np.count_nonzero(has_pos & (m == 0)))
    return {"tokens": int(pos.shape[0]), "tokens_with_pos": with_pos, "tokens_without_morph": gaps}


def check_index(index_dir: Path) -> dict:
    index_dir = Path(index_dir)
    manifest = IndexManifest.load(index_dir)
    report = {
        "index": str(index_dir),
        "builder_revision": int(manifest.builder_revision),
        "annotation_pipeline": manifest.annotation_pipeline or None,
        "language": manifest.language or None,
    }
    report.update(morph_gaps(index_dir))
    report["morph_values_incomplete"] = report["tokens_without_morph"] > 0
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m candyconc.tools.check_index",
        description="Check a Fast Index for known build defects (read only).",
    )
    parser.add_argument("index", type=Path, help="index directory, e.g. ~/.candyconc/corpora/<name>")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    try:
        report = check_index(args.index.expanduser())
    except (OSError, ValueError) as exc:
        print(f"Not a readable index: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"index             {report['index']}")
        print(f"builder revision  {report['builder_revision']}")
        print(f"pipeline          {report['annotation_pipeline'] or 'not recorded'}")
        print(
            f"morph values      {report['tokens_without_morph']} of {report['tokens_with_pos']} "
            "tokens with a part of speech have no morph value"
        )
        if report["morph_values_incomplete"]:
            print("The morph attribute of this index is incomplete. Import the corpus again.")
        else:
            print("No known defect found.")
    return 1 if report["morph_values_incomplete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
