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

Usage from a notebook in this directory:

    import snapshot as s2
    details = s2.scan(IPC_DIR, "details")
"""

from pathlib import Path

import polars as pl

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

# The game loops per second at "Faster" speed, the speed of the ladder and the tournaments.
GAME_LOOPS_PER_SECOND = 22.4

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


def scan(ipc_dir: str, name: str) -> pl.LazyFrame:
    """The file of every day of the snapshot as one LazyFrame, i.e. `scan(ipc_dir, "details")`."""
    root = Path(ipc_dir).expanduser()
    flat = root / f"{name}.arrow"
    if flat.exists():
        return pl.scan_ipc(flat)
    # The year, month and day are not added as columns, `ext_datetime` of the details has the date.
    return pl.scan_ipc(root / f"year=*/month=*/day=*/{name}.arrow", hive_partitioning=False)


def game_seconds(loop_col: str = "ext_replay_loop") -> pl.Expr:
    """The game time in seconds at Faster speed.

    The `ext_replay_seconds` column is computed by s2protocol-rs with 68.58 ms per loop, about
    14.6 loops per second instead of 22.4, use this one instead.
    """
    return (pl.col(loop_col) / GAME_LOOPS_PER_SECOND).alias("game_seconds")


def name_without_clan(col: str = "player_name") -> pl.Expr:
    """The player name without the clan tag, i.e. `&lt;TAG&gt;<sp/>Serral` is `Serral`."""
    return pl.col(col).str.split("<sp/>").list.last()


def race_letter(col: str = "player_race") -> pl.Expr:
    """T, Z or P, `?` for Random or an unknown localization."""
    return pl.col(col).replace_strict(RACES, default="?")


def players(ipc_dir: str) -> pl.LazyFrame:
    """One row per player of every game, with its tracker `player_id`.

    The tracker events (stats, upgrades, unit_born, unit_died) identify the player by `player_id`
    (`control_player_id`, `killer_player_id`), the details by name. The unit_born events have
    both, so they map one to the other.
    """
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
