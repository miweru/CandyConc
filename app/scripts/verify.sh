
#!/bin/bash
set -euo pipefail

# Install dependencies if needed
if ! command -v ruff >/dev/null || ! command -v pytest >/dev/null; then
    pip install -r requirements.txt
fi

python scripts/check_stubs.py

ruff check --fix .

pytest

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(dirname "$0")/.."
REQ_FILE="$ROOT/requirements.txt"

# Install dependencies if they are missing
if ! python -m pip check >/dev/null 2>&1; then
    echo "Installing dependencies..."
    pip install -r "$REQ_FILE"
fi

pytest "$@"

scripts/check_stubs.py

ruff check --fix .
pytest


#!/bin/bash
set -e
poetry run mypy src/
poetry run ruff check .
poetry run pytest -q


