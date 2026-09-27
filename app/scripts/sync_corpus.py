from __future__ import annotations

import argparse
from pathlib import Path

from candyconc.tools import replicate


def sync_corpus(corpus_a: Path, corpus_b: Path) -> list[str]:
    """Synchronise ``corpus_a`` and ``corpus_b`` using incremental rsync."""
    return replicate.replicate(corpus_a, corpus_b)


def main() -> None:  # pragma: no cover - CLI helper
    parser = argparse.ArgumentParser(description="Synchronise corpora across nodes")
    parser.add_argument("corpus_a", help="path to corpus on node A")
    parser.add_argument("corpus_b", help="path to corpus on node B")
    args = parser.parse_args()

    conflicts = sync_corpus(Path(args.corpus_a), Path(args.corpus_b))
    if conflicts:
        print("Conflicts detected. Manual merge required:")
        for f in conflicts:
            print(f" - {f}")
        parser.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
