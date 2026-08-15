#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}

"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" -m compileall -q scripts tests
git diff --check
