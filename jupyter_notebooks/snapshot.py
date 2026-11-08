"""Reads the snapshot written by s2protocol-rs `write-arrow-ipc` (and swarmy's Optimize).

Since s2protocol-rs 3.6.0 the snapshot is partitioned by the day the games were
played, one directory per day with all the files:

    ipcs/
      metadata.json
      year=2026/month=05/day=28/details.arrow
      year=2026/month=05/day=28/stats.arrow
      ...

The replays are identified by `ext_fs_id`, unique in the snapshot. Older snapshots have the files
at the root of `ipcs/`, `scan()` reads both layouts.

Since s2protocol-rs 5.1.0 the snapshot also has its aggregations, computed once by the writer: a
row per game in each day (`GAME_TABLES`) and the same usage tables per day, month and year
(`USAGE_TABLES`). They answer most questions without the hundreds of millions of event rows.

Usage from a notebook in this directory:

    import snapshot as s2
    IPC_DIR = s2.ipc_dir()                      # $S2_IPC_DIR, or ~/SC2Replays/ipcs
    details = s2.scan(IPC_DIR, "details")       # polars, lazy
    con = s2.duck(IPC_DIR)                      # DuckDB, one table per file: con.sql("FROM details")
"""

import glob
import os
from pathlib import Path

import duckdb
import polars as pl
from polars.testing import assert_frame_equal

# A snapshot can be larger than the memory, a query over unit_born with the in-memory engine takes
# 15 GB and more on 36,000 replays. The streaming engine processes the files in batches.
pl.Config.set_engine_affinity("streaming")

# The files of the snapshot, see the s2protocol-rs README.
FILES = [
    "details",
    "stats",
    "upgrades",
    "unit_born",
    "unit_died",
    "cmd_target_point",
    "cmd_target_unit",
]

# The aggregations of s2protocol-rs 5.1.0: a row per game, in the directory of each day.
GAME_TABLES = ["game_abilities", "game_units", "game_players", "game_minutes"]
# A row per period, protocol version, race, player and ability or unit, in each day, month and year.
USAGE_TABLES = ["ability_usage", "unit_usage", "player_usage"]
USAGE_GLOBS = {"day": "year=*/month=*/day=*", "month": "year=*/month=*", "year": "year=*"}

# The game loops per second at "Faster" speed, the speed of the ladder and the tournaments.
GAME_LOOPS_PER_SECOND = 22.4
# The PlayerStats tracker events (the stats file) are written every 160 game loops, about 7 s.
STATS_SAMPLE_LOOPS = 160
STATS_SAMPLE_SECONDS = STATS_SAMPLE_LOOPS / GAME_LOOPS_PER_SECOND

# The races of the details are localized, i.e. "Terraner", "테란", "神族". The other races are the
# ones of the arcade maps, "Primal Zerg", "Night Elf"...
RACES = {
    race: letter
    for letter, races in {
        "T": ["Terran", "테란", "人类", "人類", "Терраны", "Terraner", "Terranie", "Terrano"],
        "Z": ["Zerg", "저그", "异虫", "蟲族", "Зерги", "Zergi"],
        "P": ["Protoss", "프로토스", "星灵", "神族", "Протоссы", "Protosi"],
    }.items()
    for race in races
}


def ipc_dir(default: str = "~/SC2Replays/ipcs") -> str:
    """The snapshot directory: `$S2_IPC_DIR` when set, else `default`.

    swarmy's Optimize writes the snapshot to `ipcs` in the replay directory, so the default is
    the `ipcs` of `~/SC2Replays`. Set the variable to use another one without editing the
    notebooks, i.e. `S2_IPC_DIR=~/SCReplaysOnNVMe/ipcs uv run jupyter lab`.
    """
    return os.environ.get("S2_IPC_DIR", default)


def arrow_files(ipc_dir: str, name: str) -> str:
    """The file(s) of the snapshot as a path or a glob, the one `scan()` reads."""
    root = Path(ipc_dir).expanduser()
    flat = root / f"{name}.arrow"
    return str(flat) if flat.exists() else str(root / f"year=*/month=*/day=*/{name}.arrow")


def scan(ipc_dir: str, name: str) -> pl.LazyFrame:
    """The file of every day of the snapshot as one LazyFrame, i.e. `scan(ipc_dir, "details")`."""
    root = Path(ipc_dir).expanduser()
    flat = root / f"{name}.arrow"
    if flat.exists():
        return pl.scan_ipc(flat)
    # The year, month and day are not added as columns, `ext_datetime` of the details has the date.
    return pl.scan_ipc(root / f"year=*/month=*/day=*/{name}.arrow", hive_partitioning=False)


def usage(ipc_dir: str, name: str, grain: str = "month") -> pl.LazyFrame:
    """A usage table per `day`, `month` or `year`, i.e. `usage(ipc_dir, "ability_usage", "year")`.

    `period` is `2026-10-15`, `2026-10` or `2026`. All the columns add up, a year is its months.
    """
    root = Path(ipc_dir).expanduser()
    return pl.scan_ipc(root / f"{USAGE_GLOBS[grain]}/{name}.arrow", hive_partitioning=False)


def has_aggregations(ipc_dir: str) -> bool:
    """Whether the snapshot was written by s2protocol-rs 5.1.0 or later."""
    return bool(glob.glob(str(Path(ipc_dir).expanduser() / "year=*/month=*/day=*/game_players.arrow")))


def peek(lf: pl.LazyFrame, n: int = 5) -> pl.DataFrame:
    """The first `n` rows of a LazyFrame of the snapshot, `s2.peek(details.select("title"))`.

    `lf.head(n).collect()` fails on some projections of the partitioned snapshot with polars
    1.40 ("RecordBatch requires all its arrays to have an equal number of rows") when the slice
    is pushed into the IPC scan of many files; this falls back to a collect without the slice
    pushdown, which reads the files whole.
    """
    try:
        return lf.head(n).collect()
    except pl.exceptions.ComputeError:
        return lf.head(n).collect(optimizations=pl.QueryOptFlags(slice_pushdown=False))


def game_seconds(loop_col: str = "ext_replay_loop") -> pl.Expr:
    """The game time in seconds at Faster speed.

    The `ext_replay_seconds` column of the snapshots written by s2protocol-rs 4.0.0 and older is
    computed with 68.58 ms per loop, about 14.6 loops per second instead of 22.4, this one is
    right for every snapshot.
    """
    return (pl.col(loop_col) / GAME_LOOPS_PER_SECOND).alias("game_seconds")


def name_without_clan(col: str = "player_name") -> pl.Expr:
    """The player name without the clan tag, i.e. `&lt;TAG&gt;<sp/>Serral` is `Serral`."""
    return pl.col(col).str.split("<sp/>").list.last()


# The prefixes of the sprays, rewards, etc. They are upgrades in the tracker events but not part
# of the build orders.
COSMETIC_UPGRADE_PREFIXES = ["Spray", "Reward", "GameHeart"]


def is_cosmetic_upgrade(col: str = "name") -> pl.Expr:
    """Whether the upgrade is a spray, a reward, etc, i.e. `upgrades.filter(~is_cosmetic_upgrade())`."""
    return pl.any_horizontal(pl.col(col).str.starts_with(prefix) for prefix in COSMETIC_UPGRADE_PREFIXES)


# The structures a player starts, by race. The morphs (Lair, OrbitalCommand, WarpGate...) are
# not in it, they are born from a structure, i.e. with a `creator_unit_type_name`.
STRUCTURES = {
    "P": ["Nexus", "Pylon", "Gateway", "Assimilator", "CyberneticsCore", "Forge", "PhotonCannon", "ShieldBattery",
          "TwilightCouncil", "TemplarArchive", "DarkShrine", "RoboticsFacility", "RoboticsBay", "Stargate", "FleetBeacon"],
    "T": ["CommandCenter", "SupplyDepot", "Barracks", "Refinery", "EngineeringBay", "Bunker", "MissileTurret", "SensorTower",
          "Factory", "Starport", "GhostAcademy", "Armory", "FusionCore", "BarracksTechLab", "BarracksReactor",
          "FactoryTechLab", "FactoryReactor", "StarportTechLab", "StarportReactor"],
    "Z": ["Hatchery", "SpawningPool", "Extractor", "EvolutionChamber", "RoachWarren", "BanelingNest", "SpineCrawler",
          "SporeCrawler", "HydraliskDen", "LurkerDenMP", "InfestationPit", "Spire", "NydusNetwork", "NydusCanal",
          "UltraliskCavern"],
}
ALL_STRUCTURES = [name for names in STRUCTURES.values() for name in names]
TOWNHALLS = ["Nexus", "CommandCenter", "Hatchery"]
WORKERS = ["Probe", "SCV", "Drone"]


def is_structure(col: str = "unit_type_name") -> pl.Expr:
    """Whether the unit born is a structure started by the player, see `STRUCTURES`."""
    return pl.col(col).is_in(ALL_STRUCTURES)


def sql_list(values) -> str:
    """The values as a SQL list, i.e. `name IN ({s2.sql_list(s2.TOWNHALLS)})`."""
    return ", ".join("'" + str(value).replace("'", "''") + "'" for value in values)


def race_letter(col: str = "player_race") -> pl.Expr:
    """T, Z or P, `?` for Random or an unknown localization."""
    return pl.col(col).replace_strict(RACES, default="?")


def players(ipc_dir: str) -> pl.LazyFrame:
    """One row per player of every game, with its tracker `player_id`.

    The tracker events (stats, upgrades, unit_born, unit_died) identify the player by `player_id`
    (`control_player_id`, `killer_player_id`), the details by name. The `game_players`
    aggregation maps one to the other; the snapshots before 5.1.0 scan the unit_born events, which
    have both.
    """
    if has_aggregations(ipc_dir):
        ids = scan(ipc_dir, "game_players").select("ext_fs_id", "player_id", "player_name")
    else:
        ids = (
            scan(ipc_dir, "unit_born")
            .filter(pl.col("player_name").is_not_null())
            .select("ext_fs_id", pl.col("control_player_id").alias("player_id"), "player_name")
            .unique()
        )
    details = scan(ipc_dir, "details").filter(pl.col("player_observe") == 0)
    return details.join(ids, on=["ext_fs_id", "player_name"], how="inner").select(
        "ext_fs_id",
        "player_id",
        "player_name",
        name_without_clan().alias("player"),
        race_letter().alias("race"),
        "player_result",
        "player_team_id",
        "title",
        "ext_datetime",
        "ext_protocol_version",
    )


def one_vs_one(ipc_dir: str) -> pl.LazyFrame:
    """The players of the 1v1 games with their opponent race and matchup, i.e. `PvT`.

    The games are the ones with exactly two players on different teams in the details. The
    computer players have no name in unit_born, so the games against the A.I. are not included,
    nor a 2v2 against the A.I., where only the two humans would be found.
    """
    games = (
        scan(ipc_dir, "details")
        .filter(pl.col("player_observe") == 0)
        .group_by("ext_fs_id")
        .agg(pl.len().alias("players"), pl.col("player_team_id").n_unique().alias("teams"))
        .filter((pl.col("players") == 2) & (pl.col("teams") == 2))
        .select("ext_fs_id")
    )
    players_lf = (
        players(ipc_dir)
        .join(games, on="ext_fs_id", how="semi")
        .filter(pl.len().over("ext_fs_id") == 2)
    )
    opponents = players_lf.select(
        "ext_fs_id",
        pl.col("player_id").alias("opponent_id"),
        pl.col("player").alias("opponent"),
        pl.col("race").alias("opponent_race"),
    )
    return (
        players_lf.join(opponents, on="ext_fs_id")
        .filter(pl.col("player_id") != pl.col("opponent_id"))
        .with_columns(pl.concat_str("race", pl.lit("v"), "opponent_race").alias("matchup"))
    )


def games(ipc_dir: str) -> pl.LazyFrame:
    """One row per 1v1 game: the date, the map, the matchup with the races sorted (`PvT`, never
    `TvP`), the winner and the loser with their races, and the length in minutes (the last stats
    sample, at Faster speed)."""
    durations = scan(ipc_dir, "stats").group_by("ext_fs_id").agg(pl.col("ext_replay_loop").max().alias("last_loop"))
    winners = one_vs_one(ipc_dir).filter(pl.col("player_result") == "Win")
    return winners.join(durations, on="ext_fs_id").select(
        "ext_fs_id",
        "ext_datetime",
        "title",
        pl.when(pl.col("race") <= pl.col("opponent_race"))
        .then(pl.col("matchup"))
        .otherwise(pl.concat_str("opponent_race", pl.lit("v"), "race"))
        .alias("matchup"),
        pl.col("player").alias("winner"),
        pl.col("race").alias("winner_race"),
        pl.col("opponent").alias("loser"),
        pl.col("opponent_race").alias("loser_race"),
        (game_seconds("last_loop") / 60).alias("minutes"),
    )


def casts(ipc_dir: str) -> pl.LazyFrame:
    """One row per ability command of both cmd files, i.e. a Psionic Storm or an Inject.

    Since s2protocol-rs 5.1.0 a row of the cmd files is a command, `selection_size` has the units
    selected. Before it was a row per unit selected, a Storm commanded with four High Templar was
    four rows: the `sequence` numbers the commands of each player, it counts them once in both.
    The commands are not always cast, a Storm can be cancelled before the High Templar is in range.
    To count the commands per game, `scan(ipc_dir, "game_abilities")` has them already.
    """
    columns = ["ext_fs_id", "user_id", "player_name", "ability", "ext_replay_loop", "sequence"]
    return (
        pl.concat(
            [scan(ipc_dir, "cmd_target_point").select(columns), scan(ipc_dir, "cmd_target_unit").select(columns)]
        )
        .filter(pl.col("ability") != "")
        .unique(["ext_fs_id", "user_id", "sequence", "ext_replay_loop"])
        .with_columns(pl.col("ability").str.split(".").list.first().alias("ability_name"))
    )


# ---------------------------------------------------------------------------------------------
# DuckDB: the same snapshot as SQL views, for the SQL twin of every polars query.
# ---------------------------------------------------------------------------------------------

# The tracker id of each player, see `s2.players()`.
PLAYER_IDS_SQL = "SELECT ext_fs_id, player_id, player_name FROM game_players"
PLAYER_IDS_BORN_SQL = """
    SELECT DISTINCT ext_fs_id, control_player_id AS player_id, player_name
    FROM unit_born
    WHERE player_name IS NOT NULL
"""

# `s2.players()` and `s2.one_vs_one()` as SQL, the same rows.
PLAYERS_SQL = """
    SELECT
        d.ext_fs_id,
        ids.player_id,
        d.player_name,
        -- the name without the clan tag, i.e. '<TAG><sp/>Serral' is 'Serral'
        list_extract(string_split(d.player_name, '<sp/>'), -1) AS player,
        coalesce(r.letter, '?') AS race,
        d.player_result,
        d.player_team_id,
        d.title,
        d.ext_datetime,
        d.ext_protocol_version
    FROM details d
    JOIN player_ids ids USING (ext_fs_id, player_name)
    LEFT JOIN races r ON r.race = d.player_race
    WHERE d.player_observe = 0
"""

GAMES_1V1_SQL = """
    WITH games AS (
        SELECT ext_fs_id
        FROM details
        WHERE player_observe = 0
        GROUP BY ext_fs_id
        HAVING count(*) = 2 AND count(DISTINCT player_team_id) = 2
    ),
    two AS (
        SELECT p.*
        FROM players p
        WHERE ext_fs_id IN (FROM games)
        QUALIFY count(*) OVER (PARTITION BY ext_fs_id) = 2
    )
    SELECT
        me.*,
        them.player_id AS opponent_id,
        them.player AS opponent,
        them.race AS opponent_race,
        me.race || 'v' || them.race AS matchup
    FROM two me
    JOIN two them ON me.ext_fs_id = them.ext_fs_id AND me.player_id <> them.player_id
"""


# `s2.games()` as SQL: one row per 1v1 game.
GAMES_SQL = """
    SELECT
        g.ext_fs_id,
        g.ext_datetime,
        g.title,
        least(g.race, g.opponent_race) || 'v' || greatest(g.race, g.opponent_race) AS matchup,
        g.player AS winner,
        g.race AS winner_race,
        g.opponent AS loser,
        g.opponent_race AS loser_race,
        game_seconds(d.last_loop) / 60 AS minutes
    FROM games_1v1 g
    JOIN (SELECT ext_fs_id, max(ext_replay_loop) AS last_loop FROM stats GROUP BY ext_fs_id) d USING (ext_fs_id)
    WHERE g.player_result = 'Win'
"""

# `s2.casts()` as SQL: one row per ability command of both cmd files.
CASTS_SQL = """
    SELECT ext_fs_id, user_id, player_name, ability, ext_replay_loop, sequence,
           string_split(ability, '.')[1] AS ability_name
    FROM (
        SELECT ext_fs_id, user_id, player_name, ability, ext_replay_loop, sequence FROM cmd_target_point
        UNION ALL
        SELECT ext_fs_id, user_id, player_name, ability, ext_replay_loop, sequence FROM cmd_target_unit
    )
    WHERE ability <> ''
    GROUP BY ALL
"""


def duck(ipc_dir: str, memory_limit: str = "12GB", materialize: bool = False) -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with one view per file of the snapshot, plus the views `races`,
    `structures`, `players`, `games_1v1`, `games` and `casts`, and the macro `game_seconds`:
    `con.sql("SELECT title, count(*) FROM details GROUP BY ALL")`. The usage tables are per grain,
    `ability_usage_month`, `unit_usage_year`...

    The views read the files with `read_arrow`, the `arrow` community extension, with the filters
    and the columns pushed down. The connection also sees the polars frames of the notebook by
    their variable names (`con.sql("FROM my_frame")`).

    DuckDB spills to disk above `memory_limit`, its default of 80% of the memory is too much next
    to polars in the same process. `materialize` keeps the player tables in memory, for many
    queries on a large snapshot.
    """
    con = duckdb.connect()
    configure(con, memory_limit)
    link_files(con, ipc_dir)
    create_views(con)
    if materialize:
        materialize_players(con)
    return con


def load_arrow(con: duckdb.DuckDBPyConnection) -> None:
    """Loads `read_arrow`, the extension is downloaded the first time."""
    con.execute("INSTALL arrow FROM community; LOAD arrow;")


def read_arrow_sql(ipc_dir: str, name: str, grain: str = "day") -> str:
    """The file of every period as SQL, i.e. `read_arrow('.../year=*/month=*/day=*/stats.arrow')`."""
    root = Path(ipc_dir).expanduser()
    files = root / f"{name}.arrow" if (root / f"{name}.arrow").exists() else root / f"{USAGE_GLOBS[grain]}/{name}.arrow"
    return f"read_arrow('{files}')"


def snapshot_tables(ipc_dir: str) -> dict[str, str]:
    """The tables of the snapshot by their name in DuckDB, with the SQL that reads each one."""
    tables = {name: read_arrow_sql(ipc_dir, name) for name in FILES}
    if has_aggregations(ipc_dir):
        tables |= {name: read_arrow_sql(ipc_dir, name) for name in GAME_TABLES}
        tables |= {
            f"{name}_{grain}": read_arrow_sql(ipc_dir, name, grain) for name in USAGE_TABLES for grain in USAGE_GLOBS
        }
    return tables


def link_files(con: duckdb.DuckDBPyConnection, ipc_dir: str) -> None:
    """Creates a view over the files of each table of the snapshot."""
    load_arrow(con)
    for name, source in snapshot_tables(ipc_dir).items():
        con.execute(f"CREATE OR REPLACE VIEW {name} AS FROM {source}")


def configure(con: duckdb.DuckDBPyConnection, memory_limit: str = "12GB") -> None:
    """The settings for queries over a whole snapshot."""
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute("SET preserve_insertion_order = false")


def create_views(con: duckdb.DuckDBPyConnection) -> None:
    """The views over the snapshot files, which must already be tables or views."""
    races = ", ".join(f"('{race}', '{letter}')" for race, letter in RACES.items())
    con.execute(f"CREATE OR REPLACE VIEW races AS SELECT * FROM (VALUES {races}) AS t(race, letter)")
    structures = ", ".join(f"('{name}', '{race}')" for race, names in STRUCTURES.items() for name in names)
    con.execute(f"CREATE OR REPLACE VIEW structures AS SELECT * FROM (VALUES {structures}) AS t(name, race)")
    con.execute(f"CREATE OR REPLACE MACRO game_seconds(loop) AS loop / {GAME_LOOPS_PER_SECOND}")
    names = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    con.execute(f"CREATE OR REPLACE VIEW player_ids AS {PLAYER_IDS_SQL if 'game_players' in names else PLAYER_IDS_BORN_SQL}")
    con.execute(f"CREATE OR REPLACE VIEW players AS {PLAYERS_SQL}")
    con.execute(f"CREATE OR REPLACE VIEW games_1v1 AS {GAMES_1V1_SQL}")
    con.execute(f"CREATE OR REPLACE VIEW casts AS {CASTS_SQL}")
    con.execute(f"CREATE OR REPLACE VIEW games AS {GAMES_SQL}")


def materialize_players(con: duckdb.DuckDBPyConnection) -> None:
    """Turns `players`, `games_1v1` and `games` into tables, they scan all of unit_born as views."""
    for name in ["players", "games_1v1", "games"]:
        con.execute(f"CREATE TABLE {name}_table AS FROM {name}")
    for name in ["games", "games_1v1", "players"]:
        con.execute(f"DROP VIEW {name}")
    for name in ["players", "games_1v1", "games"]:
        con.execute(f"ALTER TABLE {name}_table RENAME TO {name}")


def same(polars_result: pl.DataFrame, sql_result, *, rel_tol: float = 1e-6) -> str:
    """Checks that a polars result and a DuckDB result have the same rows, in any order.

    The types are allowed to differ (polars counts are u32, DuckDB's are i64) and the floats
    are compared with a tolerance. Returns a short message, raises AssertionError otherwise.
    """
    sql_df = sql_result.pl() if isinstance(sql_result, duckdb.DuckDBPyRelation) else sql_result
    by = polars_result.columns
    # The same types as the polars result where the cast is exact (i64 to u32, µs to ns), the
    # floats keep their type and are compared with the tolerance.
    sql_df = sql_df.select(by).cast(
        {name: dtype for name, dtype in polars_result.schema.items() if not dtype.is_float()}, strict=False
    )
    assert_frame_equal(
        polars_result.sort(by),
        sql_df.sort(by),
        check_dtypes=False,
        check_column_order=False,
        rel_tol=rel_tol,
    )
    return f"same {polars_result.height} rows, {len(by)} columns"
