"""Adds the counter score of the alive armies to the features: from -1 (every unit of player 1
is countered by every unit of player 2) to 1, weighted by the supply of both, as swarmy's
score_unit_choice does with the strengths and weaknesses of the balance data."""
import json, sys
from pathlib import Path
import polars as pl

root, balance_dir, features, out = sys.argv[1:5]
flat = not any(Path(root).glob("year=*"))
glob = (lambda f: f"{root}/{f}") if flat else (lambda f: f"{root}/year=*/month=*/day=*/{f}")
scan = lambda f: pl.scan_ipc(glob(f), hive_partitioning=False)

WORKERS = {"SCV", "Probe", "Drone", "MULE"}
units, pairs = {}, set()
for path in Path(balance_dir).glob("*.json"):
    data = json.loads(path.read_text())
    cost = data.get("cost") or {}
    supply = cost.get("@supply") or 0
    if supply <= 0 or data["@id"] in WORKERS:
        continue
    units[data["@id"]] = supply
    for kind, sign in (("strengths", 1), ("weaknesses", -1)):
        for other in ((data.get(kind) or {}).get("unit") or []):
            pairs.add((data["@id"], other["@id"], sign))
# advantage(a, b): a strong vs b or b weak vs a is +1, a weak vs b or b strong vs a is -1.
adv = {}
for a, b, sign in pairs:
    adv.setdefault((a, b), set()).add(sign)
    adv.setdefault((b, a), set()).add(-sign)
advantage = pl.DataFrame(
    [(a, b, (1 in s) - (-1 in s)) for (a, b), s in adv.items()],
    schema=["unit_1", "unit_2", "advantage"], orient="row",
).filter(pl.col("advantage") != 0)
supply = pl.DataFrame({"unit": list(units), "supply": list(units.values())})

renames = {"SiegeTankSieged": "SiegeTank", "VikingAssault": "VikingFighter", "LiberatorAG": "Liberator",
           "ThorAP": "Thor", "WarpPrismPhasing": "WarpPrism"}
base = pl.col("unit_type_name").str.strip_suffix("Burrowed").replace(renames)
born = scan("unit_born.arrow").select(
    "ext_fs_id", "unit_tag_index", "unit_tag_recycle", player_id="control_player_id",
    unit=base, born=pl.col("ext_replay_loop"),
)
died = scan("unit_died.arrow").select("ext_fs_id", "unit_tag_index", "unit_tag_recycle", died=pl.col("ext_replay_loop"))
feat = pl.read_parquet(features)
samples = pl.LazyFrame(feat.select("ext_fs_id", "sample").unique())
alive = (
    born.filter(pl.col("player_id").is_in([1, 2]))
    .join(supply.lazy(), on="unit")
    .join(died, on=["ext_fs_id", "unit_tag_index", "unit_tag_recycle"], how="left")
    .join(samples, on="ext_fs_id")
    .with_columns(at=pl.col("sample") * 30 * 22.4)
    .filter(pl.col("born") <= pl.col("at"), pl.col("died").is_null() | (pl.col("died") > pl.col("at")))
    .group_by("ext_fs_id", "sample", "player_id", "unit")
    .agg(supply=pl.col("supply").sum())
)
p1 = alive.filter(pl.col("player_id") == 1).select("ext_fs_id", "sample", unit_1="unit", supply_1="supply")
p2 = alive.filter(pl.col("player_id") == 2).select("ext_fs_id", "sample", unit_2="unit", supply_2="supply")
counter = (
    p1.join(p2, on=["ext_fs_id", "sample"])
    .join(advantage.lazy(), on=["unit_1", "unit_2"], how="left")
    .group_by("ext_fs_id", "sample")
    .agg(
        counter=(pl.col("advantage").fill_null(0) * pl.col("supply_1") * pl.col("supply_2")).sum()
        / (pl.col("supply_1") * pl.col("supply_2")).sum()
    )
)
result = feat.join(counter.collect(engine="streaming"), on=["ext_fs_id", "sample"], how="left").with_columns(
    pl.col("counter").fill_null(0)
)
result.write_parquet(out)
print(result.select(pl.col("counter").describe() if False else pl.col("counter").mean().alias("mean"),
                    (pl.col("counter") != 0).mean().alias("nonzero"), pl.corr("counter", "army")))
