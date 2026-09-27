#!/usr/bin/env python3
"""Command-line helper to build the FAISS index."""

from pathlib import Path
import argparse

from candyconc.services.semantic.index_utils import build_faiss_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FAISS index")
    parser.add_argument("corpus")
    parser.add_argument("--out", default="runtime")
    args = parser.parse_args()
    build_faiss_index(Path(args.corpus), Path(args.out))


if __name__ == "__main__":  # pragma: no cover - CLI
    main()
