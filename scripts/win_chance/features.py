"""Features of each 1v1 game every 30 seconds, player 1 vs player 2, and whether player 1 won."""
import sys
import polars as pl

root = sys.argv[1]
flat = not any(True for _ in __import__("pathlib").Path(root).glob("year=*"))
glob = (lambda f: f"{root}/{f}") if flat else (lambda f: f"{root}/year=*/month=*/day=*/{f}")
scan = lambda f: pl.scan_ipc(glob(f), hive_partitioning=False)

details = (
    scan("details.arrow")
    .filter(pl.col("player_observe") == 0)
    .with_columns(player_id=(pl.int_range(pl.len()).over("ext_fs_id") + 1).cast(pl.UInt8))
)
games = (
    details.group_by("ext_fs_id")
    .agg(
        players=pl.len(),
        results=pl.col("player_result").sort_by("player_id"),
        races=pl.col("player_race").sort_by("player_id").str.join(""),
        version=pl.col("ext_protocol_version").first(),
    )
    .filter(pl.col("players") == 2, pl.col("results").list.contains("Win"))
    .select("ext_fs_id", "races", "version", p1_won=pl.col("results").list.get(0) == "Win")
)
killed = sum(pl.col(f"{r}_killed_{k}") for r in ("minerals", "vespene") for k in ("army", "economy", "technology"))
stats = (
    scan("stats.arrow")
    .join(games.select("ext_fs_id"), on="ext_fs_id", how="semi")
    .filter(pl.col("player_id").is_in([1, 2]))
    .with_columns(
        # The loops, the seconds of older snapshots were not at Faster speed.
        sample=(pl.col("ext_replay_loop") / 22.4 / 30).floor().cast(pl.Int32),
        army=pl.col("minerals_used_current_army") + pl.col("vespene_used_current_army"),
        income=pl.col("minerals_collection_rate") + pl.col("vespene_collection_rate"),
        workers=pl.col("workers_active_count"),
        killed=killed,
    )
    .group_by("ext_fs_id", "sample", "player_id")
    .agg(pl.col("army", "income", "workers", "killed").last())
)
wide = (
    stats.collect()
    .pivot("player_id", index=["ext_fs_id", "sample"], values=["army", "income", "workers", "killed"])
    .drop_nulls()
    .join(games.collect(), on="ext_fs_id")
    .with_columns(
        minute=pl.col("sample") / 2,
        army=((pl.col("army_1").clip(0) + 200) / (pl.col("army_2").clip(0) + 200)).log(),
        income=((pl.col("income_1").clip(0) + 100) / (pl.col("income_2").clip(0) + 100)).log(),
        workers=((pl.col("workers_1").clip(0) + 5) / (pl.col("workers_2").clip(0) + 5)).log(),
        trade=(pl.col("killed_1") - pl.col("killed_2")) / (pl.col("killed_1") + pl.col("killed_2") + 1000),
    )
    .filter(pl.col("sample") >= 4)
)
wide.write_parquet(sys.argv[2])
print(wide.select(pl.len(), pl.col("ext_fs_id").n_unique()), wide.group_by("races").len().sort("len"))
