"""Opens the snapshot in the DuckDB UI, with the examples of `sql/` as views.

    S2_IPC_DIR=~/SC2Replays/ipcs uv run python scripts/duckdb_ui.py

It copies the snapshot in `$S2_IPC_DIR` into `data/snapshot.duckdb` and opens the UI on
http://localhost:4213. In a UI notebook cell: `FROM examples`, `FROM level_2.balance`. On another
machine use `--no-browser` and `ssh -L 4213:localhost:4213 <machine>`.

Why a copy, when `s2.duck()` reads the files directly: the UI has its own connections, which do
not see the pyarrow datasets of Python, and the `read_arrow` of DuckDB, up to 2.0.0, does not read
the `string_view` columns of s2protocol-rs 5.1.0. When `read_arrow` can read them, plain views over
the files replace `copy_snapshot()`.

The copy is refreshed when this runs and the `created_at` of the snapshot changed, `--refresh`
forces it. The tables and views you add to the database stay. It holds native tables, so it also
opens without this script: `duckdb data/snapshot.duckdb -ui`.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jupyter_notebooks"))

import duckdb  # noqa: E402

import snapshot as s2  # noqa: E402

SQL_DIR = ROOT / "sql"
DEFAULT_DB = ROOT / "data" / "snapshot.duckdb"
QUERY = re.compile(r"^-- @query (\w+)(.*)$", re.MULTILINE)


def parse(path: Path) -> list[dict]:
    """The queries of a level file: name, title (the first comment), sql and the attributes."""
    parts = QUERY.split(path.read_text())
    queries = []
    for name, attributes, body in zip(parts[1::3], parts[2::3], parts[3::3]):
        sql = body.strip().rstrip(";")
        title = sql.splitlines()[0].removeprefix("-- ")
        queries.append({"name": name, "title": title, "sql": sql, **dict(item.split("=") for item in attributes.split())})
    return queries


def level_files() -> list[Path]:
    return sorted(SQL_DIR.glob("level_*.sql"))


def snapshot_id(ipc_dir: str) -> str:
    """Identifies a version of the snapshot: its directory and when it was written."""
    metadata = json.loads((Path(ipc_dir).expanduser() / "metadata.json").read_text())
    return f"{Path(ipc_dir).expanduser()} {metadata['created_at']}"


def copy_snapshot(con: duckdb.DuckDBPyConnection, ipc_dir: str) -> None:
    """Copies the files of the snapshot into native tables, and the player tables from them."""
    objects = con.execute(
        "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    for name, kind in objects:
        if name in ["players", "games_1v1", "games", "casts"]:
            con.execute(f"DROP {'VIEW' if kind == 'VIEW' else 'TABLE'} {name}")
    for name in s2.FILES:
        source = s2.dataset(ipc_dir, name)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS FROM source")
    s2.create_views(con)
    s2.materialize_players(con)


def build(ipc_dir: str, db: Path, memory_limit: str = "12GB", refresh: bool = False) -> duckdb.DuckDBPyConnection:
    """Creates the database, or refreshes it when the snapshot changed, and writes the examples."""
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    s2.configure(con, memory_limit)
    # A database built before the list of examples became a view.
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'main' AND table_name = 'examples'").fetchone()[0]:
        con.execute("DROP TABLE examples")
    con.execute("CREATE TABLE IF NOT EXISTS snapshot_info (id VARCHAR)")
    current = snapshot_id(ipc_dir)
    if refresh or con.execute("SELECT count(*) FROM snapshot_info WHERE id = ?", [current]).fetchone()[0] == 0:
        # One transaction: an interrupted copy leaves the database as it was.
        con.begin()
        copy_snapshot(con, ipc_dir)
        con.execute("DELETE FROM snapshot_info")
        con.execute("INSERT INTO snapshot_info VALUES (?)", [current])
        con.commit()
    con.execute((SQL_DIR / "00_settings.sql").read_text())
    for path in level_files():
        level = path.stem
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {level}")
        for query in parse(path):
            con.execute(f"CREATE OR REPLACE VIEW {level}.{query['name']} AS {query['sql']}")
            title = query["title"].replace("'", "''")
            con.execute(f"COMMENT ON VIEW {level}.{query['name']} IS '{title}'")
    # The list of the examples is DuckDB's own catalog of the views above.
    con.execute("""
        CREATE OR REPLACE VIEW examples AS
        SELECT schema_name AS level, view_name AS name, 'FROM ' || schema_name || '.' || view_name AS query, comment AS title, sql
        FROM duckdb_views()
        WHERE schema_name LIKE 'level\\_%' ESCAPE '\\'
        ORDER BY level, name
    """)
    return con


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", default=s2.ipc_dir(), help="the ipcs directory, default $S2_IPC_DIR or ~/SC2Replays/ipcs")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"the database to build, default {DEFAULT_DB}")
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--refresh", action="store_true", help="copy the snapshot again even if it did not change")
    parser.add_argument("--no-browser", action="store_true", help="start the server only")
    parser.add_argument("--build-only", action="store_true", help="build the database and exit")
    args = parser.parse_args()

    started = time.time()
    con = build(args.snapshot, args.db, args.memory_limit, args.refresh)
    games = con.execute("SELECT count(*) FROM games").fetchone()[0]
    examples = con.execute("SELECT count(*) FROM examples").fetchone()[0]
    print(f"{args.db}: {examples} examples, {games} 1v1 games from {args.snapshot}, built in {time.time() - started:.0f} s")
    if args.build_only:
        return
    con.execute("INSTALL ui; LOAD ui;")
    print(con.execute(f"CALL {'start_ui_server' if args.no_browser else 'start_ui'}()").fetchone()[0])
    print("Try `FROM examples` or `FROM level_2.balance` in a notebook cell. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
