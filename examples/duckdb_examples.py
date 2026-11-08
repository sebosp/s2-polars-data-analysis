"""What DuckDB adds to the snapshot, beyond the SQL equivalents of the Level notebooks.

    S2_IPC_DIR=~/SC2Replays/ipcs uv run python examples/duckdb_examples.py          # all of them
    uv run python examples/duckdb_examples.py --list
    uv run python examples/duckdb_examples.py asof_join fights
    uv run python examples/duckdb_examples.py --sql fights                          # only print the SQL

The SQL also runs in the DuckDB UI, see scripts/duckdb_ui.py, except the examples marked Python.
This file is not called duckdb.py: run from this directory, that name would hide the real package
from `import duckdb`.
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jupyter_notebooks"))

import duckdb  # noqa: E402
import polars as pl  # noqa: E402

import snapshot as s2  # noqa: E402

pl.Config.set_tbl_rows(15)
pl.Config.set_tbl_width_chars(170)
pl.Config.set_fmt_str_lengths(70)
pl.Config.set_tbl_hide_dataframe_shape(True)

# The most recent games, the windows over every event of a large snapshot would take minutes.
RECENT_GAMES = "(SELECT ext_fs_id FROM games ORDER BY ext_datetime DESC LIMIT 300)"

SQL_EXAMPLES = {
    "patch_adaptation": (
        "The usage tables per month: how the uses of an ability follow the patches, without the events",
        """
        WITH games AS (
            SELECT period, sum(games) AS games
            FROM player_usage_month u JOIN races r ON r.race = u.player_race
            WHERE r.letter = 'Z'
            GROUP BY ALL
        ),
        uses AS (
            SELECT period, sum(uses) AS uses, min(ext_protocol_version) AS first_version
            FROM ability_usage_month u JOIN races r ON r.race = u.player_race
            WHERE r.letter = 'Z' AND ability = 'SpawnLarva.Execute'
            GROUP BY ALL
        )
        SELECT period, games, round(uses / games, 1) AS injects_per_game, first_version
        FROM games JOIN uses USING (period)
        WHERE games >= 50
        ORDER BY period DESC
        LIMIT 15
        """,
    ),
    "unit_effectiveness": (
        "The usage tables per year: which units kill the most for what they cost, in a second",
        """
        SELECT unit, sum(born) AS made, sum(kills) AS kills, round(sum(kills) / sum(born), 2) AS kills_per_unit,
               round(100.0 * sum(wins) / sum(games), 1) AS win_rate
        FROM unit_usage_year
        WHERE unit IN ('Marine', 'Marauder', 'SiegeTank', 'Zergling', 'Roach', 'Hydralisk', 'Zealot', 'Stalker', 'Colossus')
        GROUP BY ALL
        ORDER BY kills_per_unit DESC
        """,
    ),
    "columns_regex": (
        "COLUMNS() applies one expression to every column matching a regex",
        """
        SELECT race, median(COLUMNS('^(minerals|vespene)_lost_(army|economy|technology)$'))
        FROM (
            SELECT p.race, s.*
            FROM stats s
            JOIN players p USING (ext_fs_id, player_id)
            WHERE p.race <> '?'
            QUALIFY s.ext_replay_loop = max(s.ext_replay_loop) OVER (PARTITION BY s.ext_fs_id, s.player_id)
        )
        GROUP BY race
        ORDER BY race
        """,
    ),
    "asof_join": (
        "ASOF JOIN: the economy at the moment of an event, from the latest stats sample before it",
        """
        SELECT
            u.name AS upgrade,
            p.player_result AS result,
            count(*) AS games,
            round(median(game_seconds(u.ext_replay_loop))) AS median_seconds,
            median(s.workers_active_count) AS workers_then,
            median(s.minerals_used_current_army + s.vespene_used_current_army) AS army_then
        FROM upgrades u
        JOIN players p USING (ext_fs_id, player_id)
        ASOF JOIN stats s
            ON u.ext_fs_id = s.ext_fs_id AND u.player_id = s.player_id AND u.ext_replay_loop >= s.ext_replay_loop
        WHERE u.name IN ('Stimpack', 'WarpGateResearch', 'zerglingmovementspeed') AND p.player_result IN ('Win', 'Loss')
        GROUP BY ALL
        ORDER BY upgrade, result
        """,
    ),
    "fights": (
        "Gaps and islands: a fight is a run of kills less than 15 seconds apart",
        f"""
        WITH kills AS (
            SELECT ext_fs_id, x, y, game_seconds(ext_replay_loop) AS seconds
            FROM unit_died
            WHERE killer_player_id IS NOT NULL AND unit_killer_name <> '' AND ext_fs_id IN {RECENT_GAMES}
              AND unit_died_name NOT IN ('InvisibleTargetDummy', 'Larva', 'Egg', 'Broodling', 'BroodlingEscort', 'AdeptPhaseShift')
        ),
        gaps AS (
            SELECT *, seconds - lag(seconds) OVER (PARTITION BY ext_fs_id ORDER BY seconds) AS gap
            FROM kills
        ),
        numbered AS (
            SELECT *, sum((gap IS NULL OR gap > 15)::INTEGER) OVER (PARTITION BY ext_fs_id ORDER BY seconds) AS fight
            FROM gaps
        )
        SELECT
            g.title, g.winner, g.loser,
            round(min(n.seconds) / 60, 1) AS start_minute,
            round(max(n.seconds) - min(n.seconds)) AS seconds,
            count(*) AS units_died,
            round(avg(n.x)) AS x,
            round(avg(n.y)) AS y
        FROM numbered n
        JOIN games g USING (ext_fs_id)
        GROUP BY g.title, g.winner, g.loser, n.ext_fs_id, n.fight
        ORDER BY units_died DESC
        LIMIT 10
        """,
    ),
    "build_order_lists": (
        "Lists: the build order of a game as one value, compared with list slices",
        f"""
        WITH builds AS (
            SELECT
                b.ext_fs_id, b.control_player_id,
                list(b.unit_type_name ORDER BY b.ext_replay_loop, b.unit_tag_index) AS structures
            FROM unit_born b
            WHERE b.ext_replay_loop > 0 AND b.unit_type_name IN (SELECT name FROM structures)
              AND b.ext_fs_id IN {RECENT_GAMES}
            GROUP BY ALL
        )
        SELECT
            p.race,
            list_slice(b.structures, 1, 4) AS first_four,
            count(*) AS players,
            round(avg((p.player_result = 'Win')::INTEGER), 2) AS win_rate
        FROM builds b
        JOIN players p ON p.ext_fs_id = b.ext_fs_id AND p.player_id = b.control_player_id
        WHERE p.race <> '?'
        GROUP BY p.race, first_four
        HAVING count(*) >= 5
        QUALIFY row_number() OVER (PARTITION BY p.race ORDER BY count(*) DESC) <= 3
        ORDER BY p.race, players DESC
        """,
    ),
    "macros": (
        "Macros: a Wilson interval and a table macro, reusable in every query and in the UI",
        """
        CREATE OR REPLACE TEMP MACRO wilson_low(wins, n) AS
            (wins / n + 1.92 / n - 1.96 * sqrt(wins / n * (1 - wins / n) / n + 0.96 / (n * n))) / (1 + 3.84 / n);
        CREATE OR REPLACE TEMP MACRO wilson_high(wins, n) AS
            (wins / n + 1.92 / n + 1.96 * sqrt(wins / n * (1 - wins / n) / n + 0.96 / (n * n))) / (1 + 3.84 / n);
        CREATE OR REPLACE TEMP MACRO player_vs_race(name) AS TABLE
            SELECT opponent_race, count(*) AS games, count(*) FILTER (WHERE player_result = 'Win') AS wins
            FROM games_1v1 WHERE player = name AND opponent_race <> '?' GROUP BY ALL;
        SELECT
            opponent_race, games,
            round(wins / games, 3) AS win_rate,
            round(wilson_low(wins, games), 3) AS low_95,
            round(wilson_high(wins, games), 3) AS high_95
        FROM player_vs_race((SELECT player FROM games_1v1 GROUP BY player ORDER BY count(*) DESC, player LIMIT 1))
        ORDER BY opponent_race
        """,
    ),
    "grouping_sets": (
        "GROUPING SETS: per matchup, per year and the total in one query",
        """
        SELECT
            coalesce(matchup, 'all') AS matchup,
            year(ext_datetime) AS year,
            count(*) AS games,
            round(median(minutes), 1) AS median_minutes
        FROM games
        GROUP BY GROUPING SETS ((matchup), (year(ext_datetime)), ())
        ORDER BY year NULLS FIRST, matchup
        """,
    ),
    "pivot": (
        "PIVOT: the columns come from the data, no list of matchups to maintain",
        """
        PIVOT (SELECT year(ext_datetime) AS year, matchup, minutes FROM games)
        ON matchup
        USING round(median(minutes), 1)
        GROUP BY year
        ORDER BY year
        """,
    ),
    "same_person": (
        "Identity: the names one account has used, to merge before a ranking",
        """
        WITH accounts AS (
            SELECT
                player_toon_region AS region, player_toon_id AS toon,
                list(DISTINCT list_extract(string_split(player_name, '<sp/>'), -1)) AS names,
                count(DISTINCT ext_fs_id) AS games
            FROM details
            WHERE player_toon_id <> 0 AND player_observe = 0
            GROUP BY ALL
        )
        SELECT region, toon, games, len(names) AS different_names, names[1:6] AS some_names
        FROM accounts
        WHERE len(names) > 1
        ORDER BY games DESC
        LIMIT 10
        """,
    ),
    "similar_names": (
        "Fuzzy matching: the names that look like the same player",
        """
        WITH names AS (SELECT player, count(*) AS games FROM games_1v1 GROUP BY player HAVING count(*) >= 20)
        SELECT
            a.player, a.games, b.player AS similar_to, b.games AS their_games,
            round(jaro_winkler_similarity(lower(a.player), lower(b.player)), 3) AS similarity
        FROM names a
        JOIN names b ON a.player < b.player
        WHERE jaro_winkler_similarity(lower(a.player), lower(b.player)) >= 0.85
           OR contains(lower(a.player), lower(b.player))
           OR contains(lower(b.player), lower(a.player))
        ORDER BY similarity DESC
        LIMIT 12
        """,
    ),
    "where_do_i_stand": (
        "percent_rank: where the most played player stands against the field at 8:00",
        """
        -- 0.75 is ahead of 75% of the players of that race at 8:00. Every game with a tracker id
        -- counts, also team games and games against the computer: filter on games_1v1 to compare 1v1s.
        WITH at_8 AS (
            SELECT
                s.ext_fs_id, s.player_id,
                arg_min(s.workers_active_count, s.ext_replay_loop) AS workers,
                arg_min(s.minerals_collection_rate + s.vespene_collection_rate, s.ext_replay_loop) AS income,
                arg_min(s.minerals_used_current_army + s.vespene_used_current_army, s.ext_replay_loop) AS army
            FROM stats s
            WHERE floor(game_seconds(s.ext_replay_loop) / 60)::INTEGER = 8
            GROUP BY ALL
        ),
        ranked AS (
            SELECT
                p.player, p.race,
                percent_rank() OVER (PARTITION BY p.race ORDER BY a.workers) AS workers,
                percent_rank() OVER (PARTITION BY p.race ORDER BY a.income) AS income,
                percent_rank() OVER (PARTITION BY p.race ORDER BY a.army) AS army
            FROM at_8 a
            JOIN players p USING (ext_fs_id, player_id)
        )
        SELECT player, race, count(*) AS games, round(median(COLUMNS(* EXCLUDE (player, race))), 2)
        FROM ranked
        WHERE player = (SELECT player FROM players GROUP BY player ORDER BY count(*) DESC, player LIMIT 1)
        GROUP BY player, race
        ORDER BY games DESC
        """,
    ),
    "text_histogram": (
        "bar(): a chart inside the result, for a terminal or a UI cell",
        """
        WITH lengths AS (SELECT floor(minutes / 5)::INTEGER * 5 AS from_minute, count(*) AS games FROM games GROUP BY ALL)
        SELECT from_minute, games, bar(games, 0, max(games) OVER (), 50) AS chart
        FROM lengths
        WHERE from_minute < 45
        ORDER BY from_minute
        """,
    ),
    "sample": (
        "USING SAMPLE: an approximate answer from a fraction of a large table, against the exact one",
        """
        WITH sampled AS (
            SELECT median(workers_active_count) AS workers, median(minerals_collection_rate) AS minerals_rate, count(*) AS samples
            FROM stats USING SAMPLE 1 PERCENT (system, 42)
        ),
        exact AS (
            SELECT median(workers_active_count) AS workers, median(minerals_collection_rate) AS minerals_rate, count(*) AS samples
            FROM stats
        )
        SELECT 'one percent' AS source, * FROM sampled UNION ALL SELECT 'all the rows', * FROM exact
        """,
    ),
    "regular_series": (
        "generate_series and IGNORE NULLS: a regular monthly series for functime, gaps made explicit",
        """
        WITH monthly AS (
            SELECT date_trunc('month', ext_datetime)::TIMESTAMP AS month, count(*) AS games, median(minutes) AS minutes
            FROM games
            GROUP BY ALL
        ),
        months AS (
            SELECT unnest(generate_series(min(month), max(month), INTERVAL 1 MONTH)) AS month FROM monthly
        )
        SELECT
            m.month,
            coalesce(g.games, 0) AS games,
            g.minutes IS NULL AS was_missing,
            round(last_value(g.minutes IGNORE NULLS) OVER (ORDER BY m.month), 1) AS minutes
        FROM months m
        LEFT JOIN monthly g USING (month)
        ORDER BY m.month DESC
        LIMIT 12
        """,
    ),
}


def polars_round_trip(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """SQL on a polars frame by its variable name, then polars on the result."""
    # polars computes something, DuckDB sees the frame by its name.
    durations = s2.games(IPC_DIR).select("title", "matchup", "minutes").collect()  # noqa: F841
    relation = con.sql(
        """
        SELECT title, matchup, count(*) AS games, median(minutes) AS median_minutes
        FROM durations
        GROUP BY ALL
        HAVING count(*) >= 20
        """
    )
    # `.pl()` returns to polars, for a window or a function functime or polars-ds provide.
    return (
        relation.pl()
        .lazy()
        .with_columns((pl.col("median_minutes") - pl.col("median_minutes").mean().over("matchup")).round(1).alias("vs_matchup_average"))
        .sort("vs_matchup_average", descending=True)
        .head(8)
        .collect()
    )


def export_parquet(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """COPY: share part of a snapshot as Parquet, partitioned by year, and query it back."""
    with tempfile.TemporaryDirectory() as tmp:
        con.execute(
            f"""
            COPY (SELECT *, year(ext_datetime) AS year FROM details)
            TO '{tmp}/details' (FORMAT parquet, PARTITION_BY (year), COMPRESSION zstd)
            """
        )
        parquet_bytes = sum(path.stat().st_size for path in Path(tmp).rglob("*.parquet"))
        files = len(list(Path(tmp).rglob("*.parquet")))
        # hive_partitioning turns year=2026 into a column, the other years are not read.
        rows = con.sql(f"SELECT year, count(*) AS rows FROM read_parquet('{tmp}/details/*/*.parquet', hive_partitioning = true) GROUP BY year ORDER BY year").pl()
    arrow_bytes = sum(path.stat().st_size for path in Path(IPC_DIR).expanduser().rglob("details.arrow"))
    print(f"details: {arrow_bytes / 2**20:.1f} MiB of Arrow, {parquet_bytes / 2**20:.1f} MiB of Parquet in {files} files")
    return rows


PYTHON_EXAMPLES = {
    "polars_round_trip": ("Python: SQL on a polars frame by its name, then polars on the result", polars_round_trip),
    "export_parquet": ("Python: COPY part of the snapshot to partitioned Parquet and read it back", export_parquet),
}


def run_sql(con: duckdb.DuckDBPyConnection, sql: str) -> pl.DataFrame:
    """Runs the statements of an example, the last one returns the rows."""
    statements = con.extract_statements(sql)
    for statement in statements[:-1]:
        con.execute(statement)
    return con.execute(statements[-1]).pl()


def main() -> None:
    global IPC_DIR
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="the examples to run, default all")
    parser.add_argument("--list", action="store_true", help="list the examples")
    parser.add_argument("--sql", action="store_true", help="print the SQL without running it")
    parser.add_argument("--snapshot", default=s2.ipc_dir(), help="the ipcs directory, default $S2_IPC_DIR or ~/SC2Replays/ipcs")
    args = parser.parse_args()
    IPC_DIR = args.snapshot
    every = {**SQL_EXAMPLES, **PYTHON_EXAMPLES}
    if args.list:
        for name, example in every.items():
            print(f"{name:20} {example[0]}")
        return
    unknown = set(args.names) - set(every)
    if unknown:
        parser.error(f"unknown examples: {', '.join(sorted(unknown))}, see --list")
    names = args.names or list(every)
    if args.sql:
        for name in names:
            if name in SQL_EXAMPLES:
                print(f"-- {name}: {SQL_EXAMPLES[name][0]}\n{SQL_EXAMPLES[name][1]};\n")
        return
    con = s2.duck(IPC_DIR, materialize=True)
    for name in names:
        title, body = every[name]
        started = time.time()
        result = body(con) if callable(body) else run_sql(con, body)
        print(f"\n=== {name}: {title} ({time.time() - started:.1f} s)")
        print(result)


if __name__ == "__main__":
    main()
