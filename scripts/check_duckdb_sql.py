"""Checks that every query of `sql/level_*.sql` returns the same rows as its polars frame.

    S2_IPC_DIR=~/SC2Replays/ipcs uv run python scripts/check_duckdb_sql.py [level_2 ...]

Runs the code cells of each Level notebook, without writing figures, and compares each query with
the frame named by its `frame=` attribute. The queries without one are only executed.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["S2_NO_FIGURE_FILES"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import plotly.basedatatypes  # noqa: E402

from duckdb_ui import ROOT, build, level_files, parse, s2  # noqa: E402

plotly.basedatatypes.BaseFigure.show = lambda self, *args, **kwargs: None


def notebook_namespace(level: str) -> dict:
    """The variables of the notebook of a level after running its code cells."""
    os.chdir(ROOT / "jupyter_notebooks")
    path = next(Path(".").glob(f"Level_{level.removeprefix('level_')}_*.ipynb"))
    namespace = {"__name__": "__main__"}
    for cell in json.loads(path.read_text())["cells"]:
        if cell["cell_type"] == "code":
            exec(compile("".join(cell["source"]), str(path), "exec"), namespace)
    return namespace


def main() -> int:
    selected = sys.argv[1:]
    failures = compared = executed = 0
    with tempfile.TemporaryDirectory() as tmp:
        con = build(s2.ipc_dir(), Path(tmp) / "check.duckdb")
        for path in level_files():
            level = path.stem
            if selected and level not in selected:
                continue
            frames = notebook_namespace(level)
            for query in parse(path):
                result = con.sql(f"FROM {level}.{query['name']}")
                label = f"{level}.{query['name']}"
                if "frame" not in query:
                    print(f"ran  {label}: {len(result.fetchall())} rows")
                    executed += 1
                    continue
                frame = frames[query["frame"]]
                frame = frame.collect() if hasattr(frame, "collect") else frame
                if "cols" in query:
                    frame = frame.select(query["cols"].split(","))
                try:
                    print(f"ok   {label}: {s2.same(frame, result)}")
                    compared += 1
                except Exception as error:  # the assertion, or a column missing in the SQL
                    print(f"FAIL {label}: {str(error)[:400]}")
                    failures += 1
    print(f"{compared} compared, {executed} executed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
