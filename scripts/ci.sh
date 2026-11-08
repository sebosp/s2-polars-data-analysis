#!/usr/bin/env bash
# The checks of the repository on a snapshot: the tests of snapshot.py, every SQL query of the
# levels against its polars twin, and every notebook executed from top to bottom (the outputs and
# figures of the repository are not touched). The CI runs it on the test snapshot of the release
# `test-snapshot-5.1.0`, see .github/workflows/ci.yml.
#
#     S2_IPC_DIR=~/SC2Replays/ipcs scripts/ci.sh
set -euo pipefail
: "${S2_IPC_DIR:?the snapshot to check, i.e. ~/SC2Replays/ipcs}"
export S2_IPC_DIR S2_NO_FIGURE_FILES=1
cd "$(dirname "$0")/.."

echo "=== tests"
uv run --with pytest pytest -q tests

echo "=== SQL against polars"
uv run python scripts/check_duckdb_sql.py

echo "=== notebooks"
out=$(mktemp -d)
failed=0
for notebook in jupyter_notebooks/*.ipynb; do
  if uv run jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=1800 \
    --output-dir "$out" "$notebook" > "$out/$(basename "$notebook").log" 2>&1; then
    echo "ok   $notebook"
  else
    echo "FAIL $notebook"
    grep -E "Error|Exception" "$out/$(basename "$notebook").log" | tail -5
    failed=1
  fi
done
exit $failed
