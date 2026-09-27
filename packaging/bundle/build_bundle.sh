#!/bin/sh
# Build the CandyConc application bundle for the current platform.
#
#   packaging/bundle/build_bundle.sh --wheels DIR_OR_WHEEL --out DIR [--python 3.12] [--sample DIR] [--examples DIR]
#
# The bundle is a folder with a relocatable CPython (python-build-standalone,
# installed with uv), the CandyConc wheel and its dependencies, the launcher
# ./candyconc, the sample corpora (examples/, sample/) and license notices. Result:
#   <out>/CandyConc-<version>-<platform>.tar.gz and .tar.gz.sha256
# Building needs uv and network access (CPython and the dependency wheels).
# Running the bundle needs neither uv, nor a compiler, nor Node.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
PACKAGING=$(dirname "$HERE")
WHEELS=""
OUT=""
PYV="3.12"
SAMPLE="$PACKAGING/sample"
EXAMPLES="$(dirname "$PACKAGING")/examples"

while [ $# -gt 0 ]; do
  case "$1" in
    --wheels) WHEELS=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --python) PYV=$2; shift 2 ;;
    --sample) SAMPLE=$2; shift 2 ;;
    --examples) EXAMPLES=$2; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$WHEELS" ] && [ -n "$OUT" ] || { echo "Usage: $0 --wheels DIR_OR_WHEEL --out DIR [--python 3.12] [--sample DIR] [--examples DIR]" >&2; exit 2; }
command -v uv >/dev/null 2>&1 || { echo "uv is needed to build the bundle: https://docs.astral.sh/uv/" >&2; exit 2; }

case "$(uname -s)" in
  Darwin) OS=macos ;;
  Linux) OS=linux ;;
  *) echo "Unsupported system: $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) ARCH=$([ "$OS" = macos ] && echo arm64 || echo aarch64) ;;
  x86_64|amd64) ARCH=x86_64 ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 2 ;;
esac
PLATFORM="${CANDYCONC_BUNDLE_PLATFORM:-$OS-$ARCH}"

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
STAGE="$OUT/bundle.tmp"
rm -rf "$STAGE" "$OUT/pyinst"
mkdir -p "$STAGE" "$OUT/pyinst"

# 1. Relocatable CPython, without links in ~/.local/bin
uv python install "$PYV" --install-dir "$OUT/pyinst" --no-bin
PYDIR=$(find "$OUT/pyinst" -maxdepth 1 -type d -name "cpython-$PYV*" | head -1)
[ -n "$PYDIR" ] || { echo "uv did not install CPython $PYV" >&2; exit 1; }
mv "$PYDIR" "$STAGE/python"
rm -rf "$OUT/pyinst"
PY="$STAGE/python/bin/python3"

# 2. CandyConc wheel and its runtime dependencies into that interpreter.
#    From a folder, take the wheel for this Python and platform by file name,
#    so that no package index can substitute another "candyconc".
if [ -d "$WHEELS" ]; then
  CP="cp$(echo "$PYV" | tr -d .)"
  case "$OS-$ARCH" in
    macos-arm64) PATTERN="candyconc-*-$CP-$CP-macosx_*_arm64.whl" ;;
    macos-x86_64) PATTERN="candyconc-*-$CP-$CP-macosx_*_x86_64.whl" ;;
    linux-x86_64) PATTERN="candyconc-*-$CP-$CP-*linux*_x86_64.whl" ;;
    linux-aarch64) PATTERN="candyconc-*-$CP-$CP-*linux*_aarch64.whl" ;;
  esac
  WHEEL=$(find "$WHEELS" -maxdepth 1 -name "$PATTERN" | sort | tail -1)
  [ -n "$WHEEL" ] || { echo "No wheel $PATTERN in $WHEELS" >&2; exit 1; }
else
  WHEEL=$WHEELS
fi
if [ "$OS" = macos ]; then
  # Resolve binary dependencies for the bundle's minimum OS, not the build host.
  case "$ARCH" in
    arm64) PYTHON_PLATFORM=aarch64-apple-darwin ;;
    x86_64) PYTHON_PLATFORM=x86_64-apple-darwin ;;
  esac
  MACOSX_DEPLOYMENT_TARGET=13.0 uv pip install --python "$PY" --break-system-packages \
    --python-platform "$PYTHON_PLATFORM" --only-binary :all: "$WHEEL"
else
  uv pip install --python "$PY" --break-system-packages "$WHEEL"
fi
VERSION=$("$PY" -c "import importlib.metadata as m; print(m.version('candyconc'))")

# 3. The interpreter is private to the bundle. uv marks it as externally
#    managed (PEP 668), which would stop "candyconc pipeline" from installing.
find "$STAGE/python/lib" -maxdepth 2 -name EXTERNALLY-MANAGED -delete

# 4. Byte-code ahead of time, so the first start does not write into the bundle.
"$PY" -m compileall -q "$STAGE/python/lib" >/dev/null || true

# 5. Launcher, sample corpora with their notices, license notices.
cp "$HERE/candyconc" "$STAGE/candyconc"
chmod +x "$STAGE/candyconc"
cp "$HERE/README.txt" "$STAGE/README.txt"
"$PY" "$HERE/stage_data.py" "$STAGE" --sample "$SAMPLE" --examples "$EXAMPLES"
"$PY" "$HERE/collect_licenses.py" "$STAGE"

# 6. Check the bundle before packing it.
"$PY" -m candyconc.tools.install_smoke --require-web

# 7. Archive and checksum.
NAME="CandyConc-$VERSION-$PLATFORM"
rm -rf "${OUT:?}/$NAME"
mv "$STAGE" "$OUT/$NAME"
(
  cd "$OUT"
  COPYFILE_DISABLE=1 tar -czf "$NAME.tar.gz" "$NAME"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256"
  else
    shasum -a 256 "$NAME.tar.gz" > "$NAME.tar.gz.sha256"
  fi
)
echo "$OUT/$NAME.tar.gz"
