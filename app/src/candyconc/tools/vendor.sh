#!/usr/bin/env bash
#
# vendor.sh - Download a Python wheel for bundling with the project.
#
# Usage: ./vendor.sh "package==version"
# Example: ./vendor.sh fastapi==0.111.0
#
# The script runs `pip download --no-binary :all:` to fetch the matching wheel,
# moves it into the repository's `vendor/` directory and prints its SHA256
# checksum. Use the printed hash when updating `requirements.txt` and
# `embedding_packages.json`.

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 '<package==version>'" >&2
    exit 1
fi

PKG_SPEC="$1"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="$REPO_ROOT/vendor"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

pip download --no-binary :all: --dest "$TMP_DIR" "$PKG_SPEC"
WHEEL_PATH="$(find "$TMP_DIR" -name '*.whl' -print -quit)"

mkdir -p "$DEST_DIR"
TARGET="$DEST_DIR/$(basename "$WHEEL_PATH")"
mv "$WHEEL_PATH" "$TARGET"

SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"

echo "Vendored wheel: $TARGET"
echo "SHA256: $SHA256"
